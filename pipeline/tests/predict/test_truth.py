"""Every base sentence is true of the recorded days of the place it names (addendum d, 4).

The website says a base of ``points`` percent as "almost never", "3 in 4", "more than 3 in
5" or "almost always" (``shareOf``, kept identical to :func:`share_of` by the golden file in
``test_share.py``). Here that sentence is checked, with exact fractions, against the closed
or remote days ``y`` of ``n`` recorded days of the level the base names: in the chain, over
every cell of the committed model, and over every cell a serving pass publishes.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from math import floor

import numpy as np
import numpy.typing as npt
import pytest

from predict import world
from snowlight.predict.alerts_live import UgcIndex, live_events
from snowlight.predict.artifact import SITUATION_KEYS, Learned, LiveCounts, ModelArtifact, load
from snowlight.predict.geography import REGION_OF
from snowlight.predict.pool import (
    SCOPES,
    Chain,
    LevelCounts,
    Strengths,
    chain,
    level_counts,
    make_places,
    named_counts,
)
from snowlight.predict.serve import (
    ServeModel,
    build_model,
    district_classes,
    forecast_file,
    whole_weather,
)
from snowlight.predict.share import share_of
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass, Window
from snowlight.predict.why import base_for, sayable
from snowlight.schemas.predictions import Forecast, PooledBase, SimilarDaysBase
from snowlight.sources.nws.alerts import parse_active

ALMOST: Fraction = Fraction(1, 20)


def told_true(points: int, y: float, n: float) -> bool:
    """The sentence for ``points``, judged by hand against ``y`` of ``n`` days."""
    if n <= 0:
        return False
    share = Fraction(round(y), round(n))
    if points <= 1:
        return share < ALMOST
    if points >= 99:
        return share > 1 - ALMOST
    told = share_of(points)
    if told.more:
        return share > Fraction(told.some, told.of)
    return floor(share * 100 + Fraction(1, 2)) == points


def cells(
    p: npt.NDArray[np.float64], y: npt.NDArray[np.float64], n: npt.NDArray[np.float64]
) -> Iterator[tuple[int, float, float]]:
    """(points, y, n) per cell, each distinct one once."""
    points = np.round(np.clip(np.round(p, 2), 0.01, 0.99) * 100).astype(np.int64)
    seen = {
        (int(a), float(b), float(c))
        for a, b, c in zip(points.ravel(), y.ravel(), n.ravel(), strict=True)
    }
    yield from sorted(seen)


def committed_chain(artifact: ModelArtifact, *, private: bool = False) -> tuple[LevelCounts, Chain]:
    """The chain over the committed model's districts (``private``: its private schools,
    counted over private schools only), nearby being the same county's (up to twelve), as a
    pass would build it with its own neighbors."""
    entry = artifact.private if private else artifact.districts
    leaids = sorted(entry)
    states = [entry[d].state for d in leaids]
    counties = [entry[d].county for d in leaids]
    by_county: dict[str, list[str]] = {}
    for leaid, county in zip(leaids, counties, strict=True):
        if county is not None:
            by_county.setdefault(county, []).append(leaid)
    near = {
        d: [e for e in by_county.get(c or "", []) if e != d][:12]
        for d, c in zip(leaids, counties, strict=True)
    }
    places = make_places(
        leaids,
        region=[None if s is None else REGION_OF.get(s) for s in states],
        state=states,
        county=counties,
        neighbors=near,
    )
    shape = (len(leaids), len(SITUATION_KEYS))
    y, n = np.zeros(shape), np.zeros(shape)
    for i, leaid in enumerate(leaids):
        found = entry[leaid]
        if found.y is not None and found.n is not None:
            y[i], n[i] = found.y, found.n
    counts = level_counts(places, y, n)
    fitted = artifact.private_strengths if private else artifact.strengths
    strengths = Strengths(fitted["no_school"])  # type: ignore[arg-type]
    return counts, chain(counts, strengths, rules=artifact.settings.rules(private=private))


def test_every_cell_of_the_committed_model_says_a_true_sentence() -> None:
    artifact = load()
    counts, found = committed_chain(artifact)
    y, n = named_counts(counts, found)
    rules = artifact.settings.rules()
    p = rules.published(found.p)
    false = [cell for cell in cells(p, y, n) if not told_true(*cell)]
    assert false == []
    # Every pooled scope is named somewhere, so the check reaches each level's counts.
    named = {SCOPES[int(k)] for k in np.unique(found.scope[~found.own])}
    assert named == set(SCOPES)


def test_every_cell_of_the_committed_private_chain_says_a_true_sentence() -> None:
    artifact = load()
    assert artifact.private
    counts, found = committed_chain(artifact, private=True)
    y, n = named_counts(counts, found)
    rules = artifact.settings.rules(private=True)
    p = rules.published(found.p)
    false = [cell for cell in cells(p, y, n) if not told_true(*cell)]
    assert false == []
    # A private level below the nation is named only with its many labeled days.
    level = rules.level_min_days
    assert level == 30
    pooled = ~found.own & (found.scope != SCOPES.index("nation"))
    assert (n[pooled] >= level).all()


def test_every_served_cell_says_a_true_sentence() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    false = [cell for cell in cells(built.p, built.named_y, built.named_n) if not told_true(*cell)]
    assert false == []
    assert built.named_n.shape == built.p.shape
    assert (built.named_n > 0).all()
    private = built.private
    assert private is not None
    false = [
        cell for cell in cells(private.p, private.named_y, private.named_n) if not told_true(*cell)
    ]
    assert false == []
    assert (private.named_n > 0).all()


def _one(y_own: int, n_own: int, y_rest: int, n_rest: int, strength: float) -> Chain:
    """Two districts in one county: the first with ``y_own`` of ``n_own`` snow warning days,
    the second with the rest (and plenty of plain days, so every situation is modeled)."""
    places = make_places(
        ["0100001", "0100002"],
        region=["south", "south"],
        state=["AL", "AL"],
        county=["01001", "01001"],
        neighbors={"0100001": ["0100002"], "0100002": ["0100001"]},
    )
    snow = SITUATION_KEYS.index("snow_warning")
    y = np.zeros((2, len(SITUATION_KEYS)))
    n = np.zeros((2, len(SITUATION_KEYS)))
    n[:, :] = 40.0
    y[0, snow], n[0, snow] = y_own, n_own
    y[1, snow], n[1, snow] = y_rest, n_rest
    strengths = Strengths.uniform(strength)
    rules = world.SETTINGS.rules()
    return chain(level_counts(places, y, n), strengths, rules=rules)


@pytest.mark.parametrize(
    ("y_own", "n_own", "y_rest", "n_rest"),
    [
        (4, 4, 30, 40),  # the critic's "49 in 50" over 4 of 4
        (3, 4, 30, 40),  # "more than 3 in 4" over exactly 3 of 4
        (15, 17, 40, 40),  # "more than 9 in 10" over 15 of 17
        (77, 82, 36, 40),  # "9 in 10" over 77 of 82
    ],
)
def test_the_chain_never_names_a_record_its_sentence_misstates(
    y_own: int, n_own: int, y_rest: int, n_rest: int
) -> None:
    for strength in (1.0, 4.0, 16.0):
        found = _one(y_own, n_own, y_rest, n_rest, strength)
        counts_y, counts_n = (
            np.array([[y_own], [y_rest]], dtype=float),
            np.array([[n_own], [n_rest]], dtype=float),
        )
        assert counts_y.shape == counts_n.shape
        snow = SITUATION_KEYS.index("snow_warning")
        p = world.SETTINGS.rules().published(found.p)[:, snow]
        for row in range(2):
            if found.own[row, snow]:
                y, n = (y_own, n_own) if row == 0 else (y_rest, n_rest)
            else:
                scope = SCOPES[int(found.scope[row, snow])]
                assert scope in {"nearby", "county", "state", "region", "nation"}
                y, n = (
                    (y_own + y_rest, n_own + n_rest) if scope != "nearby" else
                    ((y_rest, n_rest) if row == 0 else (y_own, n_own))
                )  # fmt: skip
            points = round(float(p[row]) * 100)
            assert told_true(points, y, n), (strength, row, points, y, n)


def test_a_borrowed_base_says_which_days_it_counts() -> None:
    snow = Situation(WeatherClass.SNOW_WARNING)
    ice = Situation(WeatherClass.ICE)
    plain = Situation(WeatherClass.NONE)
    after = Situation(WeatherClass.NONE, after=True)
    lent = base_for(snow, 0.9, own=False, scope="nation", day=ice)
    assert lent.kind == "pooled"
    assert lent.borrowed
    assert lent.alert == "winter_storm_warning"
    assert not base_for(snow, 0.9, own=False, scope="nation").borrowed  # type: ignore[union-attr]
    day = base_for(plain, 0.01, own=True, scope="nation", day=after)
    assert day.kind == "similar_days"
    assert day.borrowed
    # Days with no alert to name can stand only for the same weather without the day after.
    assert not sayable(Situation(WeatherClass.COLD), plain)
    with pytest.raises(ValueError, match="cannot be counted"):
        base_for(plain, 0.01, own=False, scope="nation", day=Situation(WeatherClass.COLD))


def test_every_fallback_the_settings_allow_can_be_said() -> None:
    fallback = world.CONFIG.model.fallback
    for item in SITUATIONS:
        seen = item
        while seen.key in fallback:
            seen = Situation.from_key(fallback[seen.key])
            assert sayable(item, seen), (item.key, seen.key)


def test_a_served_fallback_day_is_borrowed() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    ice = SITUATION_KEYS.index("ice")
    assert SITUATIONS[built.effective[ice]].key == "snow_warning"
    assert all(sayable(SITUATIONS[k], SITUATIONS[e]) for k, e in enumerate(built.effective))


ADVISORY = SITUATION_KEYS.index("advisory")
ADVISORY_AFTER = SITUATION_KEYS.index("advisory_after")
_COUNTY = ["0100001", "0100002", "0100003"]


def _advisory_world(
    plain: list[tuple[int, int]], after: list[tuple[int, int]]
) -> tuple[LevelCounts, Chain]:
    """Three districts of one county, each nearby the other two, with ``plain`` advisory
    days ``(y, n)`` and ``after`` advisory days after a snow day, and plenty of every other
    situation (so every situation is modeled)."""
    places = make_places(
        _COUNTY,
        region=["south"] * 3,
        state=["AL"] * 3,
        county=["01001"] * 3,
        neighbors={d: [e for e in _COUNTY if e != d] for d in _COUNTY},
    )
    y = np.zeros((3, len(SITUATION_KEYS)))
    n = np.full((3, len(SITUATION_KEYS)), 40.0)
    for row in range(3):
        y[row, ADVISORY], n[row, ADVISORY] = plain[row]
        y[row, ADVISORY_AFTER], n[row, ADVISORY_AFTER] = after[row]
    counts = level_counts(places, y, n)
    return counts, chain(counts, Strengths.uniform(4.0), rules=world.SETTINGS.rules())


def _weather_days(
    rows: list[int], plain: list[tuple[int, int]], after: list[tuple[int, int]]
) -> tuple[int, int]:
    """Every advisory day (with the days after a snow day) of the districts ``rows``."""
    return (
        sum(plain[r][0] + after[r][0] for r in rows),
        sum(plain[r][1] + after[r][1] for r in rows),
    )


@pytest.mark.parametrize(
    ("plain", "after"),
    [
        # No day after a snow day anywhere: every advisory base names its weather.
        ([(3, 4), (9, 12), (2, 10)], [(0, 0), (0, 0), (0, 0)]),
        # The critic's case: 3 of 4 plain days and 2 of 2 after: 5 in 6, never "3 in 4".
        ([(3, 4), (9, 12), (2, 10)], [(2, 2), (0, 0), (0, 0)]),
        # After days elsewhere only: the own record of the first may still name it.
        ([(6, 8), (9, 12), (2, 10)], [(0, 0), (4, 5), (1, 3)]),
        ([(30, 40), (10, 40), (20, 40)], [(9, 10), (1, 10), (5, 10)]),
    ],
)
def test_a_base_names_the_weather_only_where_true_of_all_its_days(
    plain: list[tuple[int, int]], after: list[tuple[int, int]]
) -> None:
    """A base that says "recorded winter advisory days" makes a claim about all of the
    place's advisory days, the days after a snow day too: its share must be true of them
    all (addendum e, E2; the critic's B1 and B2). Judged by hand over the union."""
    counts, found = _advisory_world(plain, after)
    whole = whole_weather(found, counts, None, np.zeros(len(SITUATION_KEYS), dtype=np.bool_))
    p = world.SETTINGS.rules().published(found.p)
    named = 0
    for row in range(3):
        for k in (ADVISORY, ADVISORY_AFTER):
            counted = SITUATIONS[int(found.situation[row, k])]
            own = bool(found.own[row, k])
            scope = SCOPES[int(found.scope[row, k])]
            base = base_for(
                counted, float(p[row, k]), own, scope, SITUATIONS[k], whole=bool(whole[row, k])
            )
            weather = getattr(base, "weather", None)
            borrowed = bool(getattr(base, "borrowed", False))
            if counted.after:
                assert weather is None
            if weather is None or borrowed:
                continue
            named += 1
            assert weather == "advisory"
            rows = (
                [row]
                if own
                else [r for r in range(3) if r != row]
                if scope == "nearby"
                else [0, 1, 2]
            )
            y, n = _weather_days(rows, plain, after)
            assert told_true(round(float(p[row, k]) * 100), y, n), (row, k, scope, y, n)
            # And it names the weather only where those are the counted days alone.
            assert sum(after[r][1] for r in rows) == 0
    if not any(item[1] for item in after):
        assert named == 3
    else:
        assert named < 3


def test_a_served_base_names_the_weather_only_where_no_day_after_is_counted_beside() -> None:
    """The serving pass: a district with advisory days after a snow day makes every level
    that counts it say "days like this" for the advisory class; a district whose own record
    holds none names its weather."""
    model = world.model()
    districts = dict(model.districts)
    for leaid, (y_plain, n_plain, y_after, n_after) in (
        ("2900001", (30, 40, 2, 2)),
        ("2900002", (30, 40, 0, 0)),
    ):
        entry = districts[leaid]
        assert entry.y is not None
        assert entry.n is not None
        assert entry.nd is not None
        y, n, nd = list(entry.y), list(entry.n), list(entry.nd)
        y[ADVISORY], n[ADVISORY], nd[ADVISORY] = y_plain, n_plain, n_plain - y_plain
        y[ADVISORY_AFTER], n[ADVISORY_AFTER] = y_after, n_after
        nd[ADVISORY_AFTER] = n_after - y_after
        districts[leaid] = entry.model_copy(update={"y": tuple(y), "n": tuple(n), "nd": tuple(nd)})
    built = build_model(
        world.directory(),
        model.model_copy(update={"districts": districts}),
        world.CONFIG,
        lambda _lon, _lat: None,
    )
    assert SITUATIONS[built.effective[ADVISORY]].key == "advisory"
    order = list(built.directory.district_ids)
    first, second = order.index("2900001"), order.index("2900002")
    assert built.own[first, ADVISORY]
    assert built.own[second, ADVISORY]
    assert not built.whole[first, ADVISORY]
    assert built.whole[second, ADVISORY]
    # A pooled base names it only where its level leaves the first's after days out: the
    # nation never does; the districts nearby do when the first is not among them.
    pooled = np.flatnonzero(~built.own[:, ADVISORY]).tolist()
    scopes = {SCOPES[int(built.scope[row, ADVISORY])] for row in pooled}
    assert scopes == {"nation", "nearby"}
    for row in pooled:
        scope = SCOPES[int(built.scope[row, ADVISORY])]
        holds = scope != "nearby" or first in built.neighbors[row]
        assert bool(built.whole[row, ADVISORY]) == (not holds), (order[row], scope)
    # The days after a snow day are too few to model here: they borrow the advisory days,
    # whose flag they carry (the sentence then says which days: "that did not follow").
    assert SITUATIONS[built.effective[ADVISORY_AFTER]].key == "advisory"
    assert (built.whole[:, ADVISORY_AFTER] == built.whole[:, ADVISORY]).all()
    assert built.private is not None
    assert built.private.whole.shape == built.private.p.shape


def test_live_days_are_judged_against_the_live_days_of_the_weather() -> None:
    """A base counted over the advisory days the live pipeline read names the weather only
    when no advisory day after a snow day was read live there; an archive base looks at the
    archive's."""
    plain = [(30, 40), (30, 40), (30, 40)]
    archive, found = _advisory_world(plain, [(0, 0)] * 3)
    live, _ = _advisory_world(plain, [(1, 1), (0, 0), (0, 0)])
    anchored = np.zeros(len(SITUATION_KEYS), dtype=np.bool_)
    assert whole_weather(found, archive, live, anchored)[:, ADVISORY].all()
    anchored[ADVISORY] = True
    reached = whole_weather(found, archive, live, anchored)[:, ADVISORY]
    for row in range(3):
        own = bool(found.own[row, ADVISORY])
        scope = SCOPES[int(found.scope[row, ADVISORY])]
        counts_first = (own and row == 0) or (not own and (scope != "nearby" or row != 0))
        assert bool(reached[row]) == (not counts_first), (row, own, scope)


LIVE_DAYS = 30
"""Live-read advisory days of each district that has any (SYNTHETIC)."""


def _anchored_advisory(
    after_first: tuple[int, int],
    archive_after: tuple[int, int],
    anchored: tuple[str, ...] = ("advisory",),
    after_second: tuple[int, int] = (0, 0),
) -> ServeModel:
    """SYNTHETIC: the served model with the advisory situation anchored on live days. The
    archive gives the first two Missouri districts 30 of 40 advisory days each and the first
    ``archive_after`` days after a snow day; live, the first two districts were read on 30
    advisory days each (the others pool), and on ``after_first`` and ``after_second`` after a
    snow day; ``anchored`` situations count the live days."""
    model = world.model()
    districts = dict(model.districts)
    for leaid in ("2900001", "2900002"):
        entry = districts[leaid]
        assert entry.y is not None
        assert entry.n is not None
        assert entry.nd is not None
        y, n, nd = list(entry.y), list(entry.n), list(entry.nd)
        y[ADVISORY], n[ADVISORY], nd[ADVISORY] = 30, 40, 10
        y[ADVISORY_AFTER], n[ADVISORY_AFTER] = archive_after if leaid == "2900001" else (0, 0)
        nd[ADVISORY_AFTER] = n[ADVISORY_AFTER] - y[ADVISORY_AFTER]
        districts[leaid] = entry.model_copy(update={"y": tuple(y), "n": tuple(n), "nd": tuple(nd)})
    live: dict[str, LiveCounts] = {}
    for leaid in ("2900001", "2900002"):
        y, n = [0] * len(SITUATION_KEYS), [0] * len(SITUATION_KEYS)
        y[ADVISORY], n[ADVISORY] = 20, LIVE_DAYS
        y[ADVISORY_AFTER], n[ADVISORY_AFTER] = after_first if leaid == "2900001" else after_second
        nd = [b - a for a, b in zip(y, n, strict=True)]
        live[leaid] = LiveCounts(y=tuple(y), n=tuple(n), yd=(0,) * len(y), nd=tuple(nd))
    through = date(2026, 1, 5)
    learned = Learned(
        schema_version=1,
        archive_sha256="c" * 64,
        through=through,
        labeled_days=2 * LIVE_DAYS,
        anchored=anchored,
        live=live,
        records={},
        check={},
        made_at=datetime(2026, 1, 6, 9, tzinfo=UTC),
        days=tuple(through - timedelta(days=d) for d in range(LIVE_DAYS, 0, -1)),
    )
    return build_model(
        world.directory(),
        model.model_copy(update={"districts": districts}),
        world.CONFIG,
        lambda _lon, _lat: None,
        learned,
    )


def _counts_first(built: ServeModel, row: int, first: int) -> bool:
    """Whether the level the advisory base of ``row`` names counts the district ``first``."""
    if built.own[row, ADVISORY]:
        return row == first
    scope = SCOPES[int(built.scope[row, ADVISORY])]
    assert scope in {"nation", "nearby"}, scope
    return scope == "nation" or first in built.neighbors[row]


def _advisory_bases(built: ServeModel) -> dict[str, SimilarDaysBase | PooledBase]:
    """Each Missouri district's base for an advisory day over its zone (SYNTHETIC alert)."""
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WW.Y.0004.260107T0600Z-260108T0000Z/",
                    ("MOZ028",),
                    sent="2026-01-06T20:00:00+00:00",
                    onset="2026-01-07T06:00:00+00:00",
                    ends="2026-01-08T00:00:00+00:00",
                    event="Winter Weather Advisory",
                )
            ],
            "2026-01-06T20:05:00+00:00",
        )
    )
    lon, lat = world.lon_lat()
    ugcs = UgcIndex.build(lon, lat, world.ugc_areas())
    window = Window(
        world.CONFIG.weather.window_from,
        world.CONFIG.weather.window_until,
        world.CONFIG.weather.snapshot_hour,
    )
    now = world.utc("2026-01-07T02:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    classes = district_classes(built, live_events(feed), ugcs, days, now, window, 0.5)
    made = forecast_file(built, classes, days, now, closed_on=lambda _day: None, last=None)
    found: dict[str, SimilarDaysBase | PooledBase] = {}
    order = built.directory.district_ids
    for entry in made.districts:
        day, leaid = entry.days[1], order[entry.district]
        if leaid.startswith("29") and isinstance(day, Forecast):
            assert isinstance(day.why.base, SimilarDaysBase | PooledBase), day.why.base
            found[leaid] = day.why.base
    assert sorted(found) == ["2900001", "2900002", "2900003"]
    return found


def test_an_anchored_base_names_the_weather_only_where_no_live_day_after_is_counted() -> None:
    """The anchored path end to end (r2 critic, S2): live advisory days after a snow day in
    one district turn the flag off at every level that counts it (its own record, the
    districts nearby, the nation), for the districts and the private schools pooled over
    them, and its advisory day's base says "days like this"; the archive's after days do not
    count against a base counted over the live days."""
    first = list(world.DISTRICTS).index("2900001")
    built = _anchored_advisory(after_first=(1, 1), archive_after=(0, 0))
    assert built.anchored[ADVISORY]
    assert SITUATIONS[built.effective[ADVISORY]].key == "advisory"
    assert built.own[first, ADVISORY]
    levels = set()
    for row in range(len(world.DISTRICTS)):
        counts = _counts_first(built, row, first)
        levels.add("own" if built.own[row, ADVISORY] else SCOPES[int(built.scope[row, ADVISORY])])
        assert bool(built.whole[row, ADVISORY]) == (not counts), (world.DISTRICTS[row], counts)
    assert levels == {"own", "nearby", "nation"}
    assert built.private is not None
    assert not built.private.whole[:, ADVISORY].any()  # pooled over the nation or nearby
    bases = _advisory_bases(built)
    assert bases["2900001"].weather is None
    assert bases["2900002"].weather == "advisory"
    assert bases["2900002"].live
    # The same live days with none after a snow day: every level names the weather, though
    # the archive holds after days (they are not the days counted).
    clean = _anchored_advisory(after_first=(0, 0), archive_after=(2, 2))
    assert clean.whole[:, ADVISORY].all()
    assert {base.weather for base in _advisory_bases(clean).values()} == {"advisory"}
    # A situation counted over the archive while its twin is anchored looks at the
    # archive's days, never the live ones.
    twin = _anchored_advisory(
        after_first=(0, 0), archive_after=(2, 2), anchored=("advisory_after",), after_second=(9, 9)
    )
    assert twin.anchored[ADVISORY_AFTER]
    assert not twin.anchored[ADVISORY]
    for row in range(len(world.DISTRICTS)):
        counts = _counts_first(twin, row, first)
        assert bool(twin.whole[row, ADVISORY]) == (not counts), (world.DISTRICTS[row], counts)
