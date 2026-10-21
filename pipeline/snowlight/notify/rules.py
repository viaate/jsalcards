"""Which notifications are due: pure rules over accounts, the published files and the log.

Three kinds, for each school an account saves (docs/notify.md):

* **Status** (:func:`status_pushes`): the published closings file shows the school closed,
  delayed, remote or dismissing early on its local today or tomorrow, a status it was not
  sent for that day (new or changed); or, for a status it was sent, the opens file says the
  school is open that day. A status that only leaves the closings file is never said to be
  lifted: a school with no row has no status on file, which is not the same as open (a
  source whose read failed, a blanked file and a list that dropped a row all leave
  statuses that still stand). At most :data:`STATUS_CAP` a school-day, so a status that
  flips between passes cannot keep pushing. Never held by quiet hours: closings come out
  at 5 to 6:30 AM.
* **Chance** (:func:`chance_pushes`): tomorrow's chance of no school first reaches the
  account's threshold (30, 50 or 70%); at most once per school and day, plus once more only
  if it then rises 20 points or more. Held during quiet hours. The push service keeps it
  for :data:`CHANCE_TTL` only, so a phone that comes online later never shows an old chance.
* **Night before**: at the account's chosen time (default 8 PM), tomorrow's chance when it
  is at least 10%. Off by default, held during quiet hours, and sent only in the 3 hours
  after that time, so a late pass never sends it at night.

Every time is the school's own: its today and tomorrow, its quiet hours and its evening are
taken in its time zone. A school-day that already shows a status gets no chance push. The
log (``notify_sent``) keeps what each account was sent for each school and day, so a pass
sends only what changed; it is written only once a browser took the push.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from snowlight.schemas.vocab import Status

type Kind = Literal["status", "chance", "chance_rise", "night"]
type Urgency = Literal["normal", "high"]

THRESHOLDS: Final = (30, 50, 70)
RISE_POINTS: Final = 20
"""A second chance push needs the chance this many points above the first one's."""
NIGHT_FLOOR: Final = 10
"""The night-before push names a chance of at least this much."""
NIGHT_WINDOW: Final = timedelta(hours=3)
LIFTED: Final = "none"
"""The log's value for a status an open statement lifted."""
STATUS_CAP: Final = 4
"""Status pushes a school-day can have for an account (new, changed and lifted together)."""
COUNT: Final = "#"
"""The log's status value ends in this and how many status pushes the school-day had."""
CHANCE_TTL: Final = 45 * 60
"""Seconds a push service keeps a chance push for an offline phone: about one predictions
pass, after which the chance may have moved and nothing would replace it."""
NIGHT_TTL: Final = 45 * 60
MIN_TTL: Final = 60

STATUS_WORD: Final[Mapping[Status, str]] = {
    Status.CLOSED: "closed",
    Status.DELAYED: "delayed",
    Status.REMOTE: "remote",
    Status.EARLY_DISMISSAL: "early_dismissal",
}
"""The status as the payload names it (``web/src/pwa/push.ts`` reads these)."""


@dataclass(frozen=True, slots=True)
class Settings:
    """An account's choices (``notify_settings``; no row: these defaults)."""

    status: bool = True
    chance: bool = True
    threshold: int = 50
    night_before: bool = False
    night_time: time = time(20, 0)
    quiet_from: time = time(22, 0)
    quiet_to: time = time(5, 0)

    def quiet_at(self, local: time) -> bool:
        """Whether a school-local time is in the quiet hours (none when from equals to)."""
        start, end = self.quiet_from, self.quiet_to
        if start == end:
            return False
        if start < end:
            return start <= local < end
        return local >= start or local < end


@dataclass(frozen=True, slots=True)
class School:
    """A saved school: its id and the name the account saved it with."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Subscription:
    """One browser of an account."""

    endpoint: str
    p256dh: str
    auth: str
    failures: int = 0
    """Its push service's refusals in a row so far."""


@dataclass(frozen=True, slots=True)
class Account:
    """An account with at least one browser, as the sender reads it."""

    user_id: str
    schools: tuple[School, ...]
    settings: Settings
    subscriptions: tuple[Subscription, ...]


@dataclass(frozen=True, slots=True)
class SentKey:
    user_id: str
    school_id: str
    kind: Kind
    day: date


type Sent = Mapping[SentKey, str]
"""The log: what each account was last sent for a school, kind and day."""


@dataclass(frozen=True, slots=True)
class Shown:
    """A school's status on one day, as the public closings file shows it."""

    status: Status
    shift: int | None = None
    clock: int | None = None

    def value(self) -> str:
        """The log's value: the status with its stated delay and time."""
        word = STATUS_WORD[self.status]
        if self.status in {Status.DELAYED, Status.EARLY_DISMISSAL}:
            return f"{word}:{_or_dash(self.shift)}:{_or_dash(self.clock)}"
        return word


def _or_dash(value: int | None) -> str:
    return "-" if value is None else str(value)


@dataclass(frozen=True, slots=True)
class Push:
    """One notification for one account (sent to each of its browsers)."""

    user_id: str
    school: School
    kind: Kind
    day: date
    value: str
    """What the log records once it is sent."""
    payload: Mapping[str, object]
    ttl: int
    urgency: Urgency
    topic: str
    also: tuple[tuple[Kind, str], ...] = ()
    """Other log rows this push stands for (a night-before push that also said the chance)."""


@dataclass(frozen=True, slots=True)
class Outlook:
    """A school's chances as the published predictions file gives them."""

    zone: str
    percent: Mapping[date, int | None] = field(default_factory=dict)
    """Each forecast day's chance of no school in whole percent (``None``: not a school day)."""


def _local(now: datetime, zone: str) -> datetime:
    return now.astimezone(ZoneInfo(zone))


def _ttl_to_end_of(day: date, zone: str, now: datetime) -> int:
    """Seconds from ``now`` to the end of ``day`` in ``zone`` (at least a minute)."""
    end = datetime.combine(day + timedelta(days=1), time(0), ZoneInfo(zone))
    return max(MIN_TTL, int((end - now).total_seconds()))


def _topic(prefix: str, school: str, day: date) -> str:
    """A push topic (at most 32 base64url characters): the kind, the school and the day."""
    return f"{prefix}-{school}-{day:%m%d}"


def _base(school: School, day: date, zone: str) -> dict[str, object]:
    return {"v": 1, "school": school.id, "name": school.name, "day": day.isoformat(), "zone": zone}


@dataclass(frozen=True, slots=True)
class Record:
    """A log row: what a push that a browser took stands for."""

    key: SentKey
    value: str


def status_pushes(  # noqa: PLR0913, PLR0917 - the accounts, the files and the log
    accounts: Iterable[Account],
    shown: Mapping[str, Mapping[date, Shown]],
    opens: frozenset[tuple[str, date]],
    zones: Mapping[str, str],
    sent: Sent,
    now: datetime,
) -> list[Push]:
    """The status pushes due now (new and changed statuses, and statuses an open statement
    lifted, on each saved school's local today and tomorrow). ``shown``, ``opens`` and
    ``zones`` are by school id; a school the directory does not place (no zone) gets
    none."""
    pushes: list[Push] = []
    for account in accounts:
        if not account.settings.status:
            continue
        for school in account.schools:
            zone = zones.get(school.id)
            if zone is None:
                continue
            today = _local(now, zone).date()
            for day in (today, today + timedelta(days=1)):
                key = SentKey(account.user_id, school.id, "status", day)
                found = _status_on(
                    key, school, zone, shown.get(school.id, {}).get(day), sent.get(key), opens, now
                )
                if found is not None:
                    pushes.append(found)
    return pushes


def _status_on(  # noqa: PLR0913, PLR0917 - one school-day's comparison
    key: SentKey,
    school: School,
    zone: str,
    current: Shown | None,
    before: str | None,
    opens: frozenset[tuple[str, date]],
    now: datetime,
) -> Push | None:
    """The push one school-day needs, if any."""
    day = key.day
    was, count = parse_status(before)

    def push(value: str, payload: dict[str, object]) -> Push | None:
        if count >= STATUS_CAP:
            return None
        return Push(
            user_id=key.user_id,
            school=school,
            kind="status",
            day=day,
            value=f"{value}{COUNT}{count + 1}",
            payload=_base(school, day, zone) | payload,
            ttl=_ttl_to_end_of(day, zone, now),
            urgency="high",
            topic=_topic("st", school.id, day),
        )

    if current is not None:
        value = current.value()
        if value == was:
            return None
        return push(
            value,
            {
                "kind": "status",
                "status": STATUS_WORD[current.status],
                "shift": current.shift,
                "clock": current.clock,
            },
        )
    # Gone from the file is not lifted: only an open statement says the school is open.
    if was is None or was == LIFTED or (school.id, day) not in opens:
        return None
    return push(LIFTED, {"kind": "lifted", "was": was.split(":", 1)[0], "open": True})


def parse_status(value: str | None) -> tuple[str | None, int]:
    """A status log value: the status it said last, and how many status pushes the
    school-day had (a value without a count had one)."""
    if value is None:
        return None, 0
    said, mark, count = value.rpartition(COUNT)
    if not mark:
        return value, 1
    try:
        return said, max(1, int(count))
    except ValueError:
        return said, STATUS_CAP


def chance_pushes(
    accounts: Iterable[Account],
    outlooks: Mapping[str, Outlook],
    with_status: frozenset[tuple[str, date]],
    sent: Sent,
    now: datetime,
) -> list[Push]:
    """The chance and night-before pushes due now, for tomorrow in each school's zone.
    ``outlooks`` is by school id (a school the file gives no chance gets none);
    ``with_status`` lists the school-days the closings file already shows a status for."""
    pushes: list[Push] = []
    for account in accounts:
        settings = account.settings
        if not (settings.chance or settings.night_before):
            continue
        for school in account.schools:
            outlook = outlooks.get(school.id)
            if outlook is None:
                continue
            local = _local(now, outlook.zone)
            tomorrow = local.date() + timedelta(days=1)
            percent = outlook.percent.get(tomorrow)
            if (
                percent is None
                or (school.id, tomorrow) in with_status
                or settings.quiet_at(local.time())
            ):
                continue
            pushes.extend(
                _chance_for(account, school, outlook.zone, tomorrow, percent, local, sent)
            )
    return pushes


def _chance_for(  # noqa: PLR0913, PLR0917 - one school's tomorrow
    account: Account,
    school: School,
    zone: str,
    tomorrow: date,
    percent: int,
    local: datetime,
    sent: Sent,
) -> list[Push]:
    settings = account.settings

    def key(kind: Kind) -> SentKey:
        return SentKey(account.user_id, school.id, kind, tomorrow)

    chance: tuple[Kind, str] | None = None
    if settings.chance:
        first = sent.get(key("chance"))
        if first is None:
            if percent >= settings.threshold:
                chance = ("chance", str(percent))
        elif sent.get(key("chance_rise")) is None and percent >= _int(first) + RISE_POINTS:
            chance = ("chance_rise", str(percent))
    night = False
    if settings.night_before and percent >= NIGHT_FLOOR and sent.get(key("night")) is None:
        start = datetime.combine(local.date(), settings.night_time, local.tzinfo)
        night = start <= local < start + NIGHT_WINDOW
    base = _base(school, tomorrow, zone)
    if night:
        # One push says it all: the night-before push stands for a chance push due with it.
        return [
            Push(
                user_id=account.user_id,
                school=school,
                kind="night",
                day=tomorrow,
                value=str(percent),
                payload=base | {"kind": "night", "percent": percent},
                ttl=NIGHT_TTL,
                urgency="normal",
                topic=_topic("nb", school.id, tomorrow),
                also=() if chance is None else (chance,),
            )
        ]
    if chance is None:
        return []
    kind, value = chance
    return [
        Push(
            user_id=account.user_id,
            school=school,
            kind=kind,
            day=tomorrow,
            value=value,
            payload=base | {"kind": "chance", "percent": percent, "rise": kind == "chance_rise"},
            ttl=CHANCE_TTL,
            urgency="normal",
            topic=_topic("ch", school.id, tomorrow),
        )
    ]


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 100
