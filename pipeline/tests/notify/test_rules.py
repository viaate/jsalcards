"""The notification rules: status change detection (new, changed, lifted only by an open
statement, never by leaving the file), the status cap a school-day, chance thresholds and the
20-point rise, short chance TTLs, de-duplication through the log, quiet hours in each school's
own time zone, and the night-before push. Every account and school here is SYNTHETIC."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from snowlight.notify.rules import (
    CHANCE_TTL,
    NIGHT_TTL,
    STATUS_CAP,
    Account,
    Outlook,
    Push,
    School,
    SentKey,
    Settings,
    Shown,
    Subscription,
    chance_pushes,
    status_pushes,
)
from snowlight.schemas.vocab import Status

NY = "America/New_York"
LA = "America/Los_Angeles"
LINCOLN = School("360000000001", "Lincoln High")
PINE = School("060000000002", "Pine Elementary")
SUB = Subscription("https://fcm.googleapis.com/fcm/send/a", "B" * 87, "A" * 22)
ZONES = {LINCOLN.id: NY, PINE.id: LA}
# 06:10 in New York, 03:10 in Los Angeles, on Tue Jan 12 2027.
MORNING = datetime(2027, 1, 12, 11, 10, tzinfo=UTC)
TODAY = date(2027, 1, 12)
TOMORROW = date(2027, 1, 13)


def account(settings: Settings | None = None, *schools: School) -> Account:
    return Account(
        user_id="u1",
        schools=schools or (LINCOLN,),
        settings=settings or Settings(),
        subscriptions=(SUB,),
    )


def status_run(
    shown: dict[str, dict[date, Shown]],
    sent: dict[SentKey, str] | None = None,
    now: datetime = MORNING,
    opens: frozenset[tuple[str, date]] = frozenset(),
    who: Account | None = None,
) -> list[Push]:
    return status_pushes([who or account()], shown, opens, ZONES, sent or {}, now)


def key(kind: str = "status", day: date = TODAY, school: School = LINCOLN) -> SentKey:
    return SentKey("u1", school.id, kind, day)  # type: ignore[arg-type]


class TestStatus:
    def test_a_new_closing_is_pushed_once(self) -> None:
        [push] = status_run({LINCOLN.id: {TODAY: Shown(Status.CLOSED)}})
        assert push.kind == "status"
        assert push.value == "closed#1"
        assert push.day == TODAY
        assert push.urgency == "high"
        assert push.payload == {
            "v": 1,
            "school": LINCOLN.id,
            "name": "Lincoln High",
            "day": "2027-01-12",
            "zone": NY,
            "kind": "status",
            "status": "closed",
            "shift": None,
            "clock": None,
        }
        # The push service keeps it until the end of the school's day, no longer.
        end = datetime(2027, 1, 13, 5, 0, tzinfo=UTC)
        assert push.ttl == int((end - MORNING).total_seconds())
        again = status_run({LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}, {key(): "closed#1"})
        assert again == []

    def test_a_change_is_pushed_and_the_same_status_is_not(self) -> None:
        delayed = Shown(Status.DELAYED, shift=120, clock=600)
        [push] = status_run({LINCOLN.id: {TODAY: delayed}}, {key(): "closed#1"})
        assert push.value == "delayed:120:600#2"
        assert push.payload["status"] == "delayed"
        assert push.payload["shift"] == 120
        assert status_run({LINCOLN.id: {TODAY: delayed}}, {key(): "delayed:120:600#2"}) == []
        later = Shown(Status.DELAYED, shift=180, clock=660)
        [push] = status_run({LINCOLN.id: {TODAY: later}}, {key(): "delayed:120:600#2"})
        assert push.value == "delayed:180:660#3"

    def test_tomorrow_is_its_own_day(self) -> None:
        shown = {LINCOLN.id: {TODAY: Shown(Status.CLOSED), TOMORROW: Shown(Status.CLOSED)}}
        pushes = status_run(shown, {key(): "closed#1"})
        assert [(p.day, p.value) for p in pushes] == [(TOMORROW, "closed#1")]

    def test_days_are_the_schools_own(self) -> None:
        # 03:30 UTC on Jan 13 is still Jan 12 in Los Angeles but Jan 12 22:30 in New York:
        # both schools' today is the 12th; at 05:30 UTC New York's today is the 13th.
        late = datetime(2027, 1, 13, 5, 30, tzinfo=UTC)
        shown = {
            LINCOLN.id: {TODAY: Shown(Status.CLOSED)},
            PINE.id: {TODAY: Shown(Status.CLOSED)},
        }
        pushes = status_run(shown, now=late, who=account(None, LINCOLN, PINE))
        assert [p.school for p in pushes] == [PINE], "New York's Jan 12 is over"

    def test_a_status_that_leaves_the_file_is_never_lifted(self) -> None:
        # Its source held back for 30 minutes of passes (a read that failed), the file
        # blanked under the same stamp, or a list that dropped the row: the status may well
        # still stand, so nothing is said, and nothing again when the row comes back.
        sent = {key(): "closed#1"}
        for minutes in range(0, 35, 5):
            at = MORNING + timedelta(minutes=minutes)
            assert status_run({}, sent, now=at) == []
            assert status_run({LINCOLN.id: {}}, sent, now=at) == []
        back = {LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}
        assert status_run(back, sent, now=MORNING + timedelta(minutes=40)) == []

    def test_a_dropped_delay_that_returns_changed_is_a_change(self) -> None:
        sent = {key(): "delayed:120:-#1"}
        assert status_run({}, sent) == []
        [push] = status_run({LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}, sent)
        assert push.value == "closed#2"

    def test_an_open_statement_lifts(self) -> None:
        opens = frozenset({(LINCOLN.id, TODAY)})
        [push] = status_run({}, {key(): "closed#1"}, opens=opens)
        assert push.value == "none#2"
        assert push.payload["kind"] == "lifted"
        assert push.payload["open"] is True
        assert push.payload["was"] == "closed"
        assert status_run({}, {key(): "none#2"}, opens=opens) == []
        # An open statement for a school-day never sent a status says nothing.
        assert status_run({}, {}, opens=opens) == []

    def test_a_lifted_status_that_comes_back_is_pushed(self) -> None:
        [push] = status_run({LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}, {key(): "none#2"})
        assert push.value == "closed#3"

    def test_a_flapping_status_stops_at_the_cap(self) -> None:
        # Two sources that disagree on a delay's clock, swapping every pass.
        a = {LINCOLN.id: {TODAY: Shown(Status.DELAYED, shift=120, clock=600)}}
        b = {LINCOLN.id: {TODAY: Shown(Status.DELAYED, shift=120, clock=630)}}
        sent: dict[SentKey, str] = {}
        sends = 0
        for n in range(24):  # two hours of 5-minute passes
            pushes = status_run(
                a if n % 2 == 0 else b, sent, now=MORNING + timedelta(minutes=5 * n)
            )
            for push in pushes:
                sends += 1
                sent[key()] = push.value
        assert sends == STATUS_CAP
        assert sent[key()] == "delayed:120:630#4"

    def test_a_log_value_without_a_count_counts_one(self) -> None:
        [push] = status_run({LINCOLN.id: {TODAY: Shown(Status.REMOTE)}}, {key(): "closed"})
        assert push.value == "remote#2"
        assert status_run({LINCOLN.id: {TODAY: Shown(Status.REMOTE)}}, {key(): "x#y"}) == []

    def test_never_held_by_quiet_hours(self) -> None:
        # 05:30 in New York, inside the default quiet hours.
        early = datetime(2027, 1, 12, 10, 30, tzinfo=UTC)
        assert Settings().quiet_at(time(5, 30)) is False
        night = datetime(2027, 1, 12, 4, 0, tzinfo=UTC)  # 23:00 on Jan 11 in New York
        assert Settings().quiet_at(time(23, 0))
        assert len(status_run({LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}, now=early)) == 1
        shown = {LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}
        assert len(status_run(shown, now=night)) == 1

    def test_off_and_unknown_schools_send_nothing(self) -> None:
        shown = {LINCOLN.id: {TODAY: Shown(Status.CLOSED)}}
        assert status_run(shown, who=account(Settings(status=False))) == []
        stranger = School("999999999999", "Nowhere")
        assert (
            status_run({stranger.id: {TODAY: Shown(Status.CLOSED)}}, who=account(None, stranger))
            == []
        )


def outlook(today: int | None, tomorrow: int | None, zone: str = NY) -> Outlook:
    return Outlook(zone=zone, percent={TODAY: today, TOMORROW: tomorrow})


# 17:00 in New York on Jan 12: tomorrow is the 13th, outside quiet hours.
EVENING = datetime(2027, 1, 12, 22, 0, tzinfo=UTC)


def chance_run(  # noqa: PLR0913, PLR0917 - every input a test may swap
    percent: int | None,
    sent: dict[SentKey, str] | None = None,
    settings: Settings | None = None,
    now: datetime = EVENING,
    with_status: frozenset[tuple[str, date]] = frozenset(),
    zone: str = NY,
) -> list[Push]:
    return chance_pushes(
        [account(settings)],
        {LINCOLN.id: outlook(5, percent, zone)},
        with_status,
        sent or {},
        now,
    )


class TestChance:
    @pytest.mark.parametrize(
        ("threshold", "percent", "sent"),
        [
            (30, 30, True),
            (30, 29, False),
            (50, 50, True),
            (50, 49, False),
            (70, 70, True),
            (70, 69, False),
        ],
    )
    def test_threshold(self, threshold: int, percent: int, sent: bool) -> None:
        pushes = chance_run(percent, settings=Settings(threshold=threshold))
        assert bool(pushes) is sent
        if sent:
            [push] = pushes
            assert push.kind == "chance"
            assert push.day == TOMORROW
            assert push.value == str(percent)
            assert push.payload["percent"] == percent
            assert push.payload["rise"] is False
            assert push.urgency == "normal"

    def test_once_per_school_and_day_then_once_more_after_a_20_point_rise(self) -> None:
        sent = {key("chance", TOMORROW): "55"}
        assert chance_run(60, sent) == []
        assert chance_run(74, sent) == []
        [rise] = chance_run(75, sent)
        assert rise.kind == "chance_rise"
        assert rise.payload["rise"] is True
        sent[key("chance_rise", TOMORROW)] = "75"
        assert chance_run(95, sent) == []

    def test_a_drop_and_a_new_climb_does_not_send_again(self) -> None:
        sent = {key("chance", TOMORROW): "62"}
        assert chance_run(20, sent) == []
        assert chance_run(64, sent) == []

    def test_held_in_quiet_hours_by_the_schools_zone(self) -> None:
        late = datetime(2027, 1, 13, 3, 30, tzinfo=UTC)  # 22:30 in New York, 19:30 in LA
        assert chance_run(80, now=late) == []
        [push] = chance_run(80, now=late, zone=LA)
        assert push.day == TOMORROW
        custom = Settings(quiet_from=time(19, 0), quiet_to=time(6, 0))
        assert chance_run(80, now=late, zone=LA, settings=custom) == []
        no_quiet = Settings(quiet_from=time(0, 0), quiet_to=time(0, 0))
        assert len(chance_run(80, now=late, settings=no_quiet)) == 1

    def test_no_chance_push_for_a_day_that_shows_a_status_or_is_no_school_day(self) -> None:
        assert chance_run(80, with_status=frozenset({(LINCOLN.id, TOMORROW)})) == []
        assert chance_run(None) == []

    def test_off(self) -> None:
        assert chance_run(80, settings=Settings(chance=False)) == []


class TestNightBefore:
    AT_8 = datetime(2027, 1, 13, 1, 7, tzinfo=UTC)  # 20:07 in New York

    def test_off_by_default(self) -> None:
        assert chance_run(35, now=self.AT_8) == []

    def test_at_the_chosen_time_when_tomorrow_is_10_percent_or_more(self) -> None:
        on = Settings(night_before=True, chance=False)
        [push] = chance_run(35, settings=on, now=self.AT_8)
        assert push.kind == "night"
        assert push.payload["kind"] == "night"
        assert push.payload["percent"] == 35
        assert chance_run(9, settings=on, now=self.AT_8) == []
        assert chance_run(35, {key("night", TOMORROW): "35"}, on, self.AT_8) == []
        before = self.AT_8 - timedelta(minutes=10)
        assert chance_run(35, settings=on, now=before) == []
        too_late = datetime(2027, 1, 13, 4, 1, tzinfo=UTC)  # 23:01: past the 3-hour window
        late_quiet = Settings(night_before=True, chance=False, quiet_from=time(0), quiet_to=time(0))
        assert chance_run(35, settings=late_quiet, now=too_late) == []
        at_9 = Settings(night_before=True, chance=False, night_time=time(21, 30))
        [push] = chance_run(35, settings=at_9, now=datetime(2027, 1, 13, 2, 37, tzinfo=UTC))
        assert push.kind == "night"

    def test_one_push_stands_for_a_chance_push_due_with_it(self) -> None:
        on = Settings(night_before=True)
        [push] = chance_run(62, settings=on, now=self.AT_8)
        assert push.kind == "night"
        assert push.also == (("chance", "62"),)

    def test_held_when_the_time_is_in_quiet_hours(self) -> None:
        on = Settings(
            night_before=True, chance=False, night_time=time(21, 0), quiet_from=time(21, 0)
        )
        assert chance_run(35, settings=on, now=datetime(2027, 1, 13, 2, 7, tzinfo=UTC)) == []


def test_quiet_hours_span_midnight_or_not() -> None:
    over = Settings(quiet_from=time(22), quiet_to=time(5))
    assert [over.quiet_at(time(h)) for h in (21, 22, 23, 0, 4, 5, 12)] == [
        False,
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    day = Settings(quiet_from=time(9), quiet_to=time(15))
    assert [day.quiet_at(time(h)) for h in (8, 9, 14, 15)] == [False, True, True, False]


def test_chance_pushes_expire_within_about_one_predictions_pass() -> None:
    # An offline phone never shows a chance that later passes may have moved: the push
    # service drops it after about one pass (passes run every 20 to 30 minutes).
    assert CHANCE_TTL <= 3600
    assert NIGHT_TTL <= 3600
    shown = {LINCOLN.id: Outlook(zone=NY, percent={TOMORROW: 80})}
    [push] = chance_pushes([account()], shown, frozenset(), {}, MORNING)
    assert push.ttl == CHANCE_TTL
