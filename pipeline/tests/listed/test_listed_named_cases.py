"""The owner's named cases, on real rows of the Kansas City lists, against the real directory.

The rows are real (``fixtures/kc``, sliced from the stations' rows files with the
reads they came in); each is matched with the committed matcher in its station's
registry context (``fixtures/kc/contexts.json``), as the build matches it. These
tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed) and are skipped where it is not built.
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from snowlight.listed.build import GUARD_REASON, guard
from snowlight.listed.evidence import ListRow
from snowlight.listed.located import Gazetteer, Verdict
from snowlight.listed.matching import Outcome, Query, match_all, match_one
from snowlight.listed.measure import aggregate, school_table
from snowlight.listed.scope import Context
from snowlight.match import Matcher, load_directory

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"
BUILT = Path(__file__).resolve().parents[2] / "out" / "internal" / "listed" / "schools.parquet"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

PEMBROKE_HILL = "A1902690"
SHAWNEE_MISSION = "2011640"
SHAWNEE_MISSION_SCHOOLS = 45
SHAWNEE_MISSION_CHRISTIAN = "A0501678"
KCPS, KCK = "2916400", "2007950"
"""Kansas City Public Schools (``"KANSAS CITY 33"``, MO) and Kansas City Kansas (USD 500)."""

type Pick = Callable[[str, str], list[ListRow]]


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    return Matcher(load_directory(DIRECTORY))


def _outcome(matcher: Matcher, contexts: dict[str, Context], row: ListRow) -> Outcome:
    return match_one(matcher, Query(contexts[row.source_id], row.name, row.section))


def _pairs(
    matcher: Matcher, contexts: dict[str, Context], rows: list[ListRow]
) -> list[tuple[ListRow, Outcome]]:
    return [(row, _outcome(matcher, contexts, row)) for row in rows]


def test_pembroke_hill_is_seen_on_three_lists(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick
) -> None:
    rows = [
        *rows_named("hearst-kmbc", "Pembroke Hill School"),
        *rows_named("scripps-kshb", "Pembroke Hill School"),
        *rows_named("nexstar-wdaf", "Pembroke Hill"),
    ]
    pairs = _pairs(matcher, contexts, rows)
    for row, outcome in pairs:
        assert outcome.accepted, row
        assert outcome.targets == (PEMBROKE_HILL,)
        assert outcome.direct == (PEMBROKE_HILL,)
    evidence = aggregate(pairs, [])
    school = evidence[PEMBROKE_HILL]
    assert school.basis == "school"
    assert school.sources == {"hearst-kmbc", "scripps-kshb", "nexstar-wdaf"}
    assert school.rows_seen == len(rows) == 9
    assert school.first_seen == min(row.fetched_at for row in rows) == "2018-11-26T14:30:08Z"
    assert school.last_seen == max(row.fetched_at for row in rows) == "2025-02-18T14:18:21Z"
    table = school_table([(PEMBROKE_HILL, "MO")], evidence)
    assert table.row(0, named=True)["seen"] is True


def test_pembroke_hill_school_in_new_hampshire_is_another_school(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick
) -> None:
    for row in rows_named("hearst-wmur", "Pembroke Hill School"):
        outcome = _outcome(matcher, contexts, row)
        assert outcome.accepted
        assert outcome.targets != (PEMBROKE_HILL,)
        assert matcher.directory[outcome.targets[0]].state == "NH"


def test_the_built_measure_dates_pembroke_hill_by_its_captures() -> None:
    if not BUILT.exists():
        pytest.skip("the listed build has not run here")
    row = pl.read_parquet(BUILT).filter(pl.col("id") == PEMBROKE_HILL).row(0, named=True)
    assert row["seen"] is True
    assert row["basis"] == "school"
    assert row["first_seen"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2018-11-26T14:30:08Z"
    assert row["last_seen"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2025-02-18T14:18:21Z"
    assert set(row["source_ids"]) >= {"hearst-kmbc", "scripps-kshb", "nexstar-wdaf"}


def test_shawnee_mission_usd_512_reaches_all_45_schools(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick
) -> None:
    rows = rows_named("hearst-kmbc", "Shawnee Mission USD512")
    pairs = _pairs(matcher, contexts, rows)
    [(_row, outcome)] = pairs
    assert outcome.targets == (SHAWNEE_MISSION,)
    assert outcome.direct == ()
    assert len(outcome.via_district) == SHAWNEE_MISSION_SCHOOLS
    evidence = aggregate(pairs, [])
    names = {matcher.directory[school].name for school in evidence}
    assert {"Prairie Elem", "Rising Star Elem", "Shawnee Mission East High"} <= names
    assert {item.basis for item in evidence.values()} == {"district"}
    for other in ("Shawnee Mission USD 512",):
        [(_r, again)] = _pairs(matcher, contexts, rows_named("scripps-kshb", other)[:1])
        assert again.targets == (SHAWNEE_MISSION,)
    [(_r, wdaf)] = _pairs(
        matcher, contexts, rows_named("nexstar-wdaf", "Shawnee Mission Schools #512")
    )
    assert wdaf.targets == (SHAWNEE_MISSION,)


def test_shawnee_mission_christian_school_is_not_the_district(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick
) -> None:
    rows = [
        *rows_named("hearst-kmbc", "Shawnee Mission Christian School"),
        *rows_named("nexstar-wdaf", "Shawnee Mission Christian School"),
    ]
    for _row, outcome in _pairs(matcher, contexts, rows):
        assert SHAWNEE_MISSION not in outcome.targets
        assert outcome.targets == (SHAWNEE_MISSION_CHRISTIAN,)
        assert outcome.via_district == ()


NOT_SCHOOLS = [
    ("hearst-kmbc", "Bannister Road Baptist Church"),
    ("hearst-kmbc", "Christ United Methodist"),
    ("hearst-kmbc", "Belton Senior Center"),
    ("hearst-kmbc", "Guadalupe Center Meals on Wheels"),
    ("hearst-kmbc", "Kansas City Public Library"),
    ("hearst-kmbc", "Country Club Christian Church Preschool"),
    ("scripps-kshb", "Shawnee Mission Meals On Wheels"),
    ("scripps-kshb", "Mt. Carmel Missionary Baptist Church of Kansas City"),
    ("nexstar-wdaf", "Shawnee Mission Meals on Wheels"),
    ("nexstar-wdaf", "JOCO Meals on Wheels"),
    ("nexstar-wdaf", "Behavioral Health Kansas City Early Intervention C"),
    ("nexstar-wdaf", "Reformed Baptist Church Of Kansas City"),
    ("nexstar-wdaf", "Nodaway County Senior Center"),
    ("nexstar-wdaf", "Mercury Gymnastics KC North"),
    ("gray-kctv", "Johnson County KS Meals on Wheels"),
]
"""Churches, senior centers, businesses, Meals on Wheels and daycares on the lists."""


@pytest.mark.parametrize(("station", "name"), NOT_SCHOOLS)
def test_churches_senior_centers_businesses_and_daycares_match_no_school(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick, station: str, name: str
) -> None:
    for row in rows_named(station, name):
        outcome = _outcome(matcher, contexts, row)
        assert not outcome.accepted, (row, outcome.targets)
        assert outcome.direct == outcome.via_district == ()


@pytest.mark.parametrize(
    "case",
    [
        ("hearst-kmbc", "Kansas City MO Public Schools", KCPS),
        ("scripps-kshb", "Kansas City, MO Public Schools", KCPS),
        ("gray-kctv", "Kansas City MO Public Schools", KCPS),
        ("hearst-kmbc", "Kansas City KS USD500", KCK),
        ("scripps-kshb", "Kansas City, KS Public Schools", KCK),
        ("gray-kctv", "Kansas City KS Public Schools-USD 500", KCK),
    ],
)
def test_kansas_city_public_schools_by_state(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick, case: tuple[str, str, str]
) -> None:
    station, name, district = case
    for row in rows_named(station, name):
        assert _outcome(matcher, contexts, row).targets == (district,)


def test_bare_kansas_city_public_schools_is_never_kansas_city_kansas(
    matcher: Matcher, contexts: dict[str, Context]
) -> None:
    """No list wrote the bare name; on a Missouri and Kansas list the matcher queues it."""
    for station in ("hearst-kmbc", "scripps-kshb", "nexstar-wdaf", "gray-kctv"):
        outcome = match_one(
            matcher, Query(contexts[station], "Kansas City Public Schools", "Schools")
        )
        assert KCK not in outcome.targets
        assert not outcome.accepted or outcome.targets == (KCPS,)


def test_parallel_matching_gives_the_same_answers(
    matcher: Matcher, contexts: dict[str, Context], kc_rows: list[ListRow]
) -> None:
    queries = [Query(contexts[row.source_id], row.name, row.section) for row in kc_rows]
    assert match_all(matcher, queries, workers=1) == {q: match_one(matcher, q) for q in queries}


def test_the_place_guard_on_real_rows(
    matcher: Matcher, contexts: dict[str, Context], rows_named: Pick
) -> None:
    gazetteer = Gazetteer.build(
        pl.read_parquet(DIRECTORY / "schools.parquet"),
        pl.read_parquet(DIRECTORY / "districts.parquet"),
        None,
    )
    cases = {
        ("nbc-owned-wbts", "Canton Public Schools"): Verdict.CONFLICT,
        ("ecc-chicago", "DIST #81"): Verdict.CONFLICT,
        ("ecc-chicago", "YORK COMMUNITY HIGH SCHOOL"): Verdict.AGREES,
        ("hearst-kmbc", "Pembroke Hill School"): Verdict.AGREES,
    }
    for (station, name), expected in cases.items():
        rows = rows_named(station, name)
        outcome = _outcome(matcher, contexts, rows[0])
        assert outcome.accepted, (station, name)
        verdicts = {
            gazetteer.verdict(row.places, outcome.targets, contexts[station].states) for row in rows
        }
        assert expected in verdicts, (station, name, verdicts)
    rows = rows_named("ecc-chicago", "DIST #81")
    query = Query(contexts["ecc-chicago"], rows[0].name, rows[0].section)
    changed = guard(
        gazetteer, [(query, row.places) for row in rows], {query: match_one(matcher, query)}
    )
    assert changed[query].reason == GUARD_REASON
    assert not changed[query].accepted
    assert changed[query].direct == changed[query].via_district == ()
