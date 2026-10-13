"""Building a SYNTHETIC day: the real matcher, the place guard, expansion, zones, the reader."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

import polars as pl
import pytest

from replays.world import (
    CHICAGO,
    DAY,
    DENVER,
    FakeEntry,
    FakeParsed,
    StubZones,
    World,
    disk_counties,
    ids,
    raw_row,
    school,
    station,
    stub_parse,
    utc,
    write_disk_world,
)
from snowlight.listed.evidence import load_rows
from snowlight.listed.located import Gazetteer
from snowlight.listed.matching import MatcherSpec
from snowlight.replays.build import (
    DISPUTED_VOTE,
    OPEN_VOTE,
    BuildError,
    DayInputs,
    Directory,
    Lit,
    _check_invariants,
    match_archive,
    part_vote,
    settle_day,
)
from snowlight.replays.gates import Drop, capture_window
from snowlight.replays.rows import row_extras, widest_window
from snowlight.schemas.vocab import Status
from snowlight.sources.stations.registry import load_registry

MORN = utc("2024-01-16 05:26")
ON = "on=2024-01-16"


@pytest.fixture(scope="module")
def disk(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SYNTHETIC world on disk with a district, a guarded listing and a church."""
    root = tmp_path_factory.mktemp("replay-world")
    rows = [
        raw_row("hearst-a", MORN, "Quillfeather R-7", f"closed;{ON}", "Jackson, Quillfeather, MO"),
        raw_row(
            "hearst-a", MORN, "Marrowbrook Elementary", f"closed;{ON}", "Johnson, Tansyridge, KS"
        ),
        raw_row("hearst-a", MORN, "First Baptist Church of Quillfeather", f"closed;{ON}"),
        raw_row("hearst-a", MORN, "Marrowbrook Middle", f"closed;{ON}", "Jackson, Marrowbrook, MO"),
        raw_row("hearst-b", MORN, "Tansyridge USD 900", f"delayed;{ON}", "Johnson, Tansyridge, KS"),
        raw_row("hearst-b", MORN, "Quillfeather R-7", f"closed;{ON}"),
    ]
    write_disk_world(root, per_district=3, rows=rows)
    return root


def _inputs(root: Path, *, public_year: int | None = None) -> DayInputs:
    loaded = load_rows(root / "archive" / "reads.jsonl", root / "archive" / "rows.jsonl")
    registry = load_registry(root / "sources")
    spec = MatcherSpec(root / "directory", root / "aliases.yaml")
    schools = pl.read_parquet(root / "directory" / "schools.parquet")
    gazetteer = Gazetteer.build(
        schools, pl.read_parquet(root / "directory" / "districts.parquet"), disk_counties()
    )
    book = match_archive(loaded, registry, spec.build(), gazetteer=gazetteer, spec=spec)
    directory = Directory.from_frame(schools)
    if public_year is not None:
        directory = Directory(schools=directory.schools, public_year=public_year)
    return DayInputs(
        loaded=loaded,
        registry=registry,
        book=book,
        directory=directory,
        lookup=StubZones(),
        parse=stub_parse,
        extras=row_extras(root / "archive" / "rows.jsonl"),
    )


def test_a_district_listing_lights_its_schools_through_the_real_matcher(disk: Path) -> None:
    settled = settle_day(_inputs(disk), DAY)
    quill = {sid for sid in settled.lit if sid.startswith("9900001")}
    assert quill == {f"9900001{n:05d}" for n in range(3)}
    assert all(settled.lit[sid].status is Status.CLOSED for sid in quill)
    assert {r.level for sid in quill for r in settled.lit[sid].evidence} == {"district"}
    tansy = {sid for sid in settled.lit if sid.startswith("9900003")}
    assert len(tansy) == 3
    assert all(settled.lit[sid].status is Status.DELAYED for sid in tansy)


def test_the_place_guard_and_unmatched_rows_drop(disk: Path) -> None:
    settled = settle_day(_inputs(disk), DAY)
    assert "990000200001" not in settled.lit
    assert settled.row_drops[Drop.PLACE_GUARD.value] == 1
    # the church, and hearst-b's "Quillfeather R-7": a MO district is not in its KS context
    assert settled.row_drops[Drop.NOT_MATCHED.value] == 2


def test_a_school_outside_its_stations_states_is_dropped_in_expansion() -> None:
    a, b = ids("0007", 2)
    world = World(stations=[station("gray-a", states=("MO",))])
    world.add_schools(school(a), school(b, state="KS", fips="20091"))
    world.row("gray-a", MORN, f"closed;{ON}", district=[a, b])
    world.row("gray-a", MORN, f"closed;{ON}", name="only ks", direct=[b])
    settled = settle_day(world.inputs(), DAY)
    assert set(settled.lit) == {a}
    assert settled.target_drops == {Drop.OUT_OF_STATE.value: 2}
    assert settled.row_drops == {Drop.OUT_OF_STATE.value: 1}


def test_the_school_year_guard(disk: Path) -> None:
    """Marrowbrook Middle is New in the 2024-2025 directory; a 2024-01 storm is before it."""
    settled = settle_day(_inputs(disk), DAY)
    assert "990000200002" not in settled.lit
    assert settled.target_drops[Drop.SCHOOL_YEAR.value] == 1
    later = settle_day(_inputs(disk, public_year=2023), DAY)
    assert later.lit["990000200002"].status is Status.CLOSED


def test_the_book_measures_each_read_and_station(disk: Path) -> None:
    one = _inputs(disk).book
    assert one.medians == {"hearst-a": None, "hearst-b": None}
    assert one.shares[("hearst-a", MORN)] == 0.5


# --- zones, the reader and the invariants on stub answers ---------------------------------------


def test_a_row_whose_schools_span_zones_and_disagree_drops() -> None:
    a, b = ids("0003", 2)
    world = World(stations=[station("gray-a", states=("CO", "MO"))])
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", utc("2024-01-16 04:30"), "closed", district=[a, b])  # 03:30 in Denver
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.ZONE_SPLIT.value: 1}


def test_a_row_whose_schools_span_zones_and_agree_lights_both() -> None:
    a, b = ids("0003", 2)
    world = World(stations=[station("gray-a", states=("CO", "MO"))])
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", utc("2024-01-16 06:30"), "closed", district=[a, b])
    assert set(settle_day(world.inputs(), DAY).lit) == {a, b}


def test_a_school_with_no_zone_drops_the_row() -> None:
    a, b = ids("0004", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a), school(b, fips="29999"))
    world.row("gray-a", MORN, f"closed;{ON}", district=[a, b])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.ZONE_UNKNOWN.value: 1}


def test_the_reader_is_injected_and_called_with_the_capture_and_zone() -> None:
    (a,) = ids("0005", 1)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a))
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a])
    calls: list[tuple[str, datetime, str]] = []

    def reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        calls.append((text, posted_at, tz))
        return stub_parse(text, posted_at=posted_at, tz=tz)

    settled = settle_day(world.inputs(parse=reader), DAY)
    assert a in settled.lit
    assert {(text, tz) for text, _at, tz in calls} == {(f"closed;{ON}", CHICAGO)}
    assert {at.isoformat() for _text, at, _tz in calls} == {"2024-01-16T11:26:00+00:00"}
    assert DENVER not in {tz for _text, _at, tz in calls}


def test_the_directory_must_hold_every_matched_school() -> None:
    world = World(stations=[station("gray-a")])
    world.row("gray-a", MORN, f"closed;{ON}", direct=["990009999999"])
    with pytest.raises(BuildError, match="does not hold"):
        settle_day(world.inputs(), DAY)


def test_the_state_and_platform_invariants_raise() -> None:
    (a,) = ids("0006", 1)
    world = World(stations=[station("gray-a", states=("KS",)), station("apptegy-x")])
    world.add_schools(school(a))
    inputs = world.inputs()
    lit = Lit(school=a, status=Status.CLOSED, reason=None, stations=("gray-a",), evidence=())
    with pytest.raises(BuildError, match=r"\(MO\) is lit from gray-a"):
        _check_invariants({a: lit}, inputs)
    off = Lit(school=a, status=Status.CLOSED, reason=None, stations=("apptegy-x",), evidence=())
    with pytest.raises(BuildError, match="excluded source"):
        _check_invariants({a: off}, inputs)


def test_the_directory_reads_its_public_year() -> None:
    frame = pl.DataFrame(
        {
            "id": ["990000100001", "A9900001"],
            "kind": ["public", "private"],
            "state": ["MO", "MO"],
            "status": ["Open", None],
            "county_fips": ["29095", None],
            "lat": [39.0, None],
            "lon": [-94.4, None],
            "school_year": ["2024-2025", "2023-2024"],
        }
    )
    directory = Directory.from_frame(frame)
    assert directory.public_year == 2024
    assert directory.schools["A9900001"].public is False
    assert directory.schools["A9900001"].lat is None


# --- the row's whole status: comments and posted times ------------------------------------------


def test_comments_and_posted_times_reach_the_reader_from_the_archive(tmp_path: Path) -> None:
    """Read from rows.jsonl beside load_rows: a comment changes the reading; an old post drops."""
    rows = [
        raw_row(
            "hearst-a",
            MORN,
            "Quillfeather R-7",
            f"closed;{ON}",
            "Jackson, Quillfeather, MO",
            comment="Remote learning day",
        ),
        raw_row(
            "hearst-b",
            MORN,
            "Tansyridge USD 900",
            "closed",
            "Johnson, Tansyridge, KS",
            updated="1/14/2024 4:39 PM",
        ),
    ]
    write_disk_world(tmp_path, per_district=2, rows=rows)
    settled = settle_day(_inputs(tmp_path), DAY)
    quill = {sid: item for sid, item in settled.lit.items() if sid.startswith("9900001")}
    assert {item.status for item in quill.values()} == {Status.REMOTE}
    assert not any(sid.startswith("9900003") for sid in settled.lit)
    assert settled.row_drops == {Drop.STALE_POST.value: 1}


def _tomorrow_reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
    """A SYNTHETIC reader that reads "closed tomorrow" as the day after ``posted_at``, dated."""
    if text != "closed tomorrow":
        return stub_parse(text, posted_at=posted_at, tz=tz)
    after = posted_at.astimezone(ZoneInfo(tz)).date() + timedelta(days=1)
    return FakeParsed(kind="closed", schedule=(FakeEntry("closed", (after,)),), reason=None)


@pytest.mark.parametrize(("scope", "lit"), [(None, True), ("page", False)])
def test_only_a_rows_own_stamp_dates_a_tomorrow_from_the_morning_before(
    tmp_path: Path, scope: str | None, lit: bool
) -> None:
    """ "Closed tomorrow" at 08:00 the day before: the row's own stamp that morning says it is
    that day's word; a page's stamp that morning says only that something on the page changed."""
    rows = [
        raw_row(
            "hearst-a",
            utc("2024-01-15 08:00"),
            "Quillfeather R-7",
            "closed tomorrow",
            "Jackson, Quillfeather, MO",
            updated="1/15/2024 7:30 AM",
            scope=scope,
        )
    ]
    write_disk_world(tmp_path, per_district=2, rows=rows)
    inputs = replace(_inputs(tmp_path), parse=_tomorrow_reader)
    settled = settle_day(inputs, DAY)
    assert bool(settled.lit) is lit
    assert settled.row_drops == ({} if lit else {Drop.OUTSIDE_WINDOW.value: 1})


def _one(*, public: bool = True, fips: str = "29095", state: str = "MO") -> tuple[World, str]:
    (a,) = ids("0020", 1)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a, public=public, fips=fips, state=state))
    return world, a


def test_a_comment_that_says_learning_lights_remote() -> None:
    world, a = _one()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a], comment="Remote learning day")
    assert settle_day(world.inputs(), DAY).lit[a].status is Status.REMOTE


def test_a_comment_the_reader_misses_still_holds_the_row() -> None:
    """The stub does not know "AMI": the learning-word gate still keeps the row dark."""
    world, a = _one()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a], comment="AMI Day #2")
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.DETAIL_MODE.value: 1}


@pytest.mark.parametrize(
    ("posted", "lit"),
    [
        ("1/14/2024 4:39 PM", False),  # read then, a bare "closed" is Monday's
        ("1/15/2024 4:39 PM", True),  # read then, it is Tuesday's
        ("UPDATED MONDAY, JAN 15 AT 4:39 PM", True),
        ("Updated a while ago", True),  # no time to read it at
        ("1/16/2024 9:00 AM", True),  # after the capture: not believed
        ("2024-01-15", False),  # a date only, before the day: a bare row may be Monday's
        ("2024-01-16", True),
    ],
)
def test_a_row_must_say_the_same_at_its_posted_time(posted: str, lit: bool) -> None:
    world, a = _one()
    world.row("gray-a", MORN, "closed", direct=[a], posted=posted)
    settled = settle_day(world.inputs(), DAY)
    assert (a in settled.lit) is lit
    assert (settled.row_drops == {Drop.STALE_POST.value: 1}) is not lit


@pytest.mark.parametrize(
    ("section", "public", "lit"),
    [
        ("Private Schools", True, False),
        ("Private", True, False),
        ("Catholic Schools", True, False),
        ("Public Schools", False, False),
        ("Public Schools", True, True),
        ("Private Schools", False, True),
        ("Schools", True, True),
        (None, True, True),
        ("CHRISTIAN SCHOOLS", True, False),
        ("Montessori", True, False),
        ("Independent Schools", True, False),
        ("Non-Public", True, False),
        ("Non-Public Schools", False, True),
        ("Nonpublic", True, False),
    ],
)
def test_a_section_that_names_the_other_kind_of_school_never_lights_it(
    section: str | None, public: bool, lit: bool
) -> None:
    """A private "Kestrel Hill School" filed under Private never lights a public namesake."""
    world, a = _one(public=public)
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a], section=section)
    settled = settle_day(world.inputs(), DAY)
    assert (a in settled.lit) is lit
    assert (settled.target_drops == {Drop.SECTION.value: 1}) is not lit


@pytest.mark.parametrize(
    ("virtual", "name", "drop"),
    [
        ("FACEVIRTUAL", "SYNTHETIC school", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Virtual Academy", Drop.VIRTUAL),  # the name says so
        ("MISSING", "Kestrel E-School", Drop.VIRTUAL),
        ("SUPPVIRTUAL", "Kestrel Online Academy", Drop.VIRTUAL),
        (None, "Kestrel Cyber Charter", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Juvenile Detention Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Children's Hospital", Drop.FACILITY),
        ("NOTVIRTUAL", "Homebound Elementary", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Residential Treatment Center", Drop.FACILITY),
        # how the directory names detention, jail, hospital and treatment programs
        ("NOTVIRTUAL", "Kestrel Youth Development Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Youth Services Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel County Youth Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Youth Development Campus", Drop.FACILITY),
        ("NOTVIRTUAL", "ADJUDICATED YOUTH FACILITY", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL COUNTY SHERIFFS OFFICE", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL CHILDREN'S MEDICAL CTR", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL YOUTH RECOVERY", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Behavioral Health Systems", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Children's Home", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Crisis Stabilization Unit", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL PSYCHIATRIC CENTER", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL SECURE CENTER", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel County Court", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel-Paige Camp", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL CO JJAEP", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel State Prison", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Group Home School", Drop.FACILITY),
        ("NOTVIRTUAL", "AmiKiDs Caddo", Drop.FACILITY),  # a court-referred day treatment program
        ("NOTVIRTUAL", "AMIKIDS KESTREL COUNTY", Drop.FACILITY),
        ("NOTVIRTUAL", "Youth Villages at Inner Harbour", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL BEHAVIOR HEALTH CENTER", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL BEHAVIORAL SERVICES", Drop.FACILITY),
        ("NOTVIRTUAL", "Home & Hosp/Transition Support", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Youth Educational Support School", Drop.FACILITY),
        ("NOTVIRTUAL", "THE ACADEMY AT YOUTH CARE LANE", Drop.FACILITY),
        ("NOTVIRTUAL", "Pine Hills Youth Corr Facil HS", Drop.FACILITY),
        ("NOTVIRTUAL", "EAST RECEP/DIAG CORR CENT/ACAD", Drop.FACILITY),
        ("NOTVIRTUAL", "MCLENNAN COUNTY CHALLENGE ACADEMY", Drop.FACILITY),
        ("NOTVIRTUAL", "HIS HOUSE", Drop.FACILITY),
        ("NOTVIRTUAL", "Boys Republic High", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Girls School", Drop.FACILITY),
        ("NOTVIRTUAL", "Kemmerer Village School", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Cty Jvnl Det Ctr 9-12", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel RYDC", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel HOSP EL", Drop.FACILITY),
        ("NOTVIRTUAL", "Boys Town Kestrel", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Job Corps", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Juve Hall", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Det Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Inner Harbour Kestrel", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Prairie Care", Drop.FACILITY),
        # facility programs the directory types Regular, and misspelled
        ("NOTVIRTUAL", "Devereux Kestrel Academy", Drop.FACILITY),
        ("NOTVIRTUAL", "KESTREL STATE SCHOOL", Drop.FACILITY),
        ("NOTVIRTUAL", "JUVENILLE JUSTICE ALTERNATIVE PROGRAM", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Regional Inst for Children & Adol", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Children's Services", Drop.FACILITY),
        ("NOTVIRTUAL", "GREATER KESTREL HEALTH CENTER", Drop.FACILITY),
        ("NOTVIRTUAL", "M Health Kestrel C&T", Drop.FACILITY),
        # plural and variant names, and contract, placement and tuition rosters (round 6: a
        # treatment campus and a placement roster typed Regular lit through their districts)
        ("NOTVIRTUAL", "Whaley Children Centers", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Children Center", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Childrens Homes", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Youth Development Centers", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Group Homes", Drop.FACILITY),
        ("NOTVIRTUAL", "CONTRACT", Drop.FACILITY),
        ("NOTVIRTUAL", "Contract - 02", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Contracted Programs", Drop.FACILITY),
        ("NOTVIRTUAL", "Exceptional Children Special Placements", Drop.FACILITY),
        ("NOTVIRTUAL", "VO. TECH. TUITION", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Out-of-District Placement", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Out of State School", Drop.FACILITY),
        ("NOTVIRTUAL", "Kestrel Middle Advanced Placement Magnet School", None),
        ("NOTVIRTUAL", "Kestrel Health Sciences Academy", None),  # a magnet school
        ("NOTVIRTUAL", "Kestrel Regional School", None),  # a regional district's school
        ("NOTVIRTUAL", "Kestrel Independent Study", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Home School Academy", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Flex Academy", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Digital Learning Center", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Kestrel Hybrid School", Drop.VIRTUAL),
        ("NOTVIRTUAL", "Shelter Rock Elementary", None),
        ("NOTVIRTUAL", "Camp Creek Elementary", None),
        ("NOTVIRTUAL", "Kestrel Medical Magnet High", None),
        ("SUPPVIRTUAL", "Kestrel Elementary", None),  # a building that also teaches online
    ],
)
def test_an_online_school_or_a_facility_is_reached_only_by_its_own_row(
    virtual: str | None, name: str, drop: Drop | None
) -> None:
    a, b = ids("0025", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a), school(b, virtual=virtual, name=name))
    world.row("gray-a", MORN, f"closed;{ON}", name="host district", district=[a, b])
    settled = settle_day(world.inputs(), DAY)
    assert (b in settled.lit) is (drop is None)
    assert settled.target_drops == ({} if drop is None else {drop.value: 1})
    world.row("gray-a", MORN, f"closed;{ON}", name="the school itself", direct=[b])
    assert settle_day(world.inputs(), DAY).lit[b].status is Status.CLOSED


@pytest.mark.parametrize(
    ("school_type", "name", "drop"),
    [
        ("Alternative School", "Summit View Youth J-SHS", Drop.FACILITY),  # youth corrections
        ("Alternative School", "CHALLENGE ACADEMY", Drop.FACILITY),
        ("Special Education School", "Kestrel House", Drop.FACILITY),
        ("Alternative School", "Kestrel Therapeutic Day School", Drop.FACILITY),
        ("Alternative School", "Kestrel Harbor High School", Drop.FACILITY),  # the cost
        ("Alternative School", "KCDC Educational Center", Drop.FACILITY),  # a detention center's
        ("Alternative School", "Dolan Ctr Kestrel Farm Campus", Drop.FACILITY),
        # a plain name: the type alone holds it (the cost: alternative high schools)
        ("Alternative School", "Kestrel Alternative High", Drop.FACILITY),
        ("Special Education School", "Kestrel Learning Center", Drop.FACILITY),
        # facility programs lit through their districts on candidate days in round 4
        ("Alternative School", "Breathitt Regional School", Drop.FACILITY),
        ("Alternative School", "Dessie Scott School", Drop.FACILITY),
        ("Alternative School", "Gateway Children's Services", Drop.FACILITY),
        (
            "Special Education School",
            "John L Gildner Regional Inst for Children & Adol",
            Drop.FACILITY,
        ),
        ("Alternative School", "Peace Academy", Drop.FACILITY),
        ("Alternative School", "RTC SCHOOL", Drop.FACILITY),
        ("Career and Technical School", "Kestrel Career Center", None),
        ("Regular School", "Summit View Youth J-SHS", None),
        ("Regular School", "Kestrel Village Elementary", None),
    ],
)
def test_an_alternative_or_special_school_is_reached_only_by_its_own_row(
    school_type: str, name: str, drop: Drop | None
) -> None:
    a, b = ids("0026", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a), school(b, name=name, school_type=school_type))
    world.row("gray-a", MORN, f"closed;{ON}", name="host district", district=[a, b])
    settled = settle_day(world.inputs(), DAY)
    assert (b in settled.lit) is (drop is None)
    assert settled.target_drops == ({} if drop is None else {drop.value: 1})
    world.row("gray-a", MORN, f"closed;{ON}", name="the school itself", direct=[b])
    assert settle_day(world.inputs(), DAY).lit[b].status is Status.CLOSED


@pytest.mark.parametrize(
    ("school_type", "enrollment", "grades", "drop"),
    [
        ("Regular School", 0, ("KG", "12"), Drop.FACILITY),  # a roster, not a building
        ("Regular School", 0, ("PK", "12"), Drop.FACILITY),
        ("Regular School", 32, ("PK", "12"), None),  # students enrolled
        ("Regular School", None, ("KG", "12"), None),  # no count reported
        ("Regular School", 0, ("09", "12"), None),  # a new or career school
        ("Regular School", 0, ("KG", "08"), None),
        ("Career and Technical School", 0, ("KG", "12"), None),
    ],
)
def test_a_roster_of_every_grade_with_no_students_is_reached_only_by_its_own_row(
    school_type: str, enrollment: int | None, grades: tuple[str, str], drop: Drop | None
) -> None:
    """A K-12 Regular school with no students enrolled is a roster or program (a placement
    roster, a treatment campus, a shared-time program), not a building its district closes."""
    a, b = ids("0027", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(
        school(a),
        school(
            b,
            name="SYNTHETIC Kestrel Center",
            school_type=school_type,
            enrollment=enrollment,
            grades=grades,
        ),
    )
    world.row("gray-a", MORN, f"closed;{ON}", name="host district", district=[a, b])
    settled = settle_day(world.inputs(), DAY)
    assert (b in settled.lit) is (drop is None)
    assert settled.target_drops == ({} if drop is None else {drop.value: 1})
    world.row("gray-a", MORN, f"closed;{ON}", name="the program itself", direct=[b])
    assert settle_day(world.inputs(), DAY).lit[b].status is Status.CLOSED


def test_a_fully_virtual_school_is_reached_only_by_its_own_row() -> None:
    a, b = ids("0021", 2)
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC market two")])
    world.add_schools(school(a), school(b, virtual="FULLVIRTUAL"))
    world.row("gray-a", MORN, f"closed;{ON}", name="host district", district=[a, b])
    world.row("gray-b", MORN, f"remote;{ON}", name="the academy", direct=[b])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit[a].status is Status.CLOSED
    assert settled.lit[b].status is Status.REMOTE
    assert settled.lit[b].stations == ("gray-b",)
    assert settled.target_drops == {Drop.VIRTUAL.value: 1}


def test_a_moved_school_is_reached_only_by_its_own_row_before_the_directory_year() -> None:
    a, b = ids("0022", 2)
    world = World(stations=[station("gray-a")], public_year=2024)
    world.add_schools(school(a), school(b, status="Changed Boundary/Agency"))
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[a, b])
    settled = settle_day(world.inputs(), DAY)
    assert set(settled.lit) == {a}
    assert settled.target_drops == {Drop.SCHOOL_YEAR.value: 1}
    world.row("gray-a", MORN, f"closed;{ON}", name="the school", direct=[b])
    assert settle_day(world.inputs(), DAY).lit[b].status is Status.CLOSED
    world.public_year = 2023
    assert b in settle_day(world.inputs(), DAY).lit


def test_a_district_row_that_names_a_campus_lights_none_of_its_schools() -> None:
    """It narrows the district's status to one campus, which it does not say is which: it
    stands against every claim for its schools, even the campus's own row."""
    a, b = ids("0023", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a), school(b))
    world.row(
        "gray-a", MORN, f"closed;{ON}", name="district", district=[a, b], comment="Ashby campus"
    )
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.target_drops == {Drop.PART_OF_DISTRICT.value: 2}
    assert settled.row_drops == {Drop.PART_OF_DISTRICT.value: 1}
    world.row("gray-a", MORN, f"closed;{ON}", name="a building", direct=[a], comment="Ashby campus")
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


def test_a_run_without_extras_reads_the_status_alone() -> None:
    world, a = _one()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a], comment="Remote learning day")
    inputs = replace(world.inputs(), extras={})
    assert settle_day(inputs, DAY).lit[a].status is Status.CLOSED


@pytest.mark.parametrize(
    ("comment", "lit"),
    [
        ("Ashby campus only", False),
        ("Closure impacts the Ashby building", False),
        ("All campuses closed", True),
        ("All buildings are closed", True),
        ("Every building closed", True),
        ("Snow day", True),
        ("Closed at Lincoln Elementary", False),
        ("2 hour delay for Central High School", False),
        ("Washington Middle School only", False),
        ("Delayed 2 hours - Northside site", False),
        ("East location", False),
        ("Closed at the Smith Center", False),
        ("South Annex", False),
        ("Early Childhood Center", False),
        ("Preschool and Pre-K", False),
        ("All schools except the north side", False),
        ("Kestrel Academy", False),
        ("All elementary schools and every middle school", True),
        ("Buses on pavement only", True),
        ("Lincoln Elem only", False),
        ("Upper School closed", False),
        ("Lower School 2 hour delay", False),
        ("2 hr delay - JHS", False),
        ("Kestrel MS remote", False),
        ("Kestrel Jr/Sr High", False),
        ("K-8 closed", False),
        ("Closed today for PK-5", False),
        ("Closed at Lincoln School", False),
        ("Closed for all schools", True),
        ("Closed 1/16", True),
    ],
)
def test_only_a_single_campus_or_building_holds_back_a_district_row(
    comment: str, lit: bool
) -> None:
    a, b = ids("0024", 2)
    world = World(stations=[station("gray-a")])
    world.add_schools(school(a), school(b))
    world.row("gray-a", MORN, f"closed;{ON}", district=[a, b], comment=comment)
    assert bool(settle_day(world.inputs(), DAY).lit) is lit


def test_extras_must_match_the_reads_rows() -> None:
    world, a = _one()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a])
    world.extras[("gray-a", MORN)].append(world.extras[("gray-a", MORN)][0])
    with pytest.raises(BuildError, match="2 extras for 1 rows"):
        settle_day(world.inputs(), DAY)


def test_the_directory_reads_the_virtual_column() -> None:
    frame = pl.DataFrame(
        {
            "id": ["990000100001", "990000100002"],
            "kind": ["public", "public"],
            "state": ["MO", "MO"],
            "status": ["Open", "Open"],
            "county_fips": ["29095", "29095"],
            "lat": [39.0, 39.0],
            "lon": [-94.4, -94.4],
            "school_year": ["2024-2025", "2024-2025"],
            "virtual": ["FULLVIRTUAL", None],
            "school_type": ["Alternative School", None],
            "enrollment": [0, None],
            "grade_low": ["KG", None],
            "grade_high": ["12", None],
        }
    )
    schools = Directory.from_frame(frame).schools
    assert schools["990000100001"].virtual == "FULLVIRTUAL"
    assert schools["990000100002"].virtual is None
    assert schools["990000100001"].school_type == "Alternative School"
    assert schools["990000100002"].school_type is None
    assert schools["990000100001"].enrollment == 0
    assert schools["990000100002"].enrollment is None
    assert (schools["990000100001"].grade_low, schools["990000100001"].grade_high) == ("KG", "12")
    assert schools["990000100002"].grade_low is None
    assert schools["990000100002"].grade_high is None


# --- the widest window holds every US zone's window ---------------------------------------------

US = [
    *(
        zone
        for zone in sorted(available_timezones())
        if zone.startswith("US/") and zone not in {"US/Samoa"}
    ),
    "America/New_York",
    "America/Detroit",
    "America/Indiana/Indianapolis",
    "America/Kentucky/Louisville",
    "America/Chicago",
    "America/Menominee",
    "America/North_Dakota/Center",
    "America/Denver",
    "America/Boise",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "America/Juneau",
    "America/Sitka",
    "America/Metlakatla",
    "America/Yakutat",
    "America/Nome",
    "America/Adak",
    "Pacific/Honolulu",
    "America/Puerto_Rico",
    "America/St_Thomas",
]


@pytest.mark.parametrize("day", [date(2024, 1, 16), date(2024, 10, 15), date(2025, 3, 12)])
@pytest.mark.parametrize("zone", US)
def test_the_widest_window_holds_each_us_zones_window(day: date, zone: str) -> None:
    low, high = widest_window(day)
    for dated in (True, False):
        start, end = capture_window(day, zone, dated=dated)
        assert low <= start
        assert end <= high


def test_a_school_in_a_zone_past_the_widest_window_raises() -> None:
    world, a = _one(fips="60050", state="AS")
    world.stations[0]["states"] = ["AS"]
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a])
    with pytest.raises(BuildError, match="outside the widest window"):
        settle_day(world.inputs(), DAY)


# --- each zone keeps its own reading; the read gate reads what the claim reads ------------------


def test_zones_that_drop_a_row_for_one_reason_with_other_kinds_split() -> None:
    a, b = ids("0026", 2)
    world = World(stations=[station("gray-a", states=("CO", "MO"))])
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", MORN, f"closed;{ON}", district=[a, b])

    def reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        del text
        kind = "delayed" if tz == DENVER else "closed"
        return stub_parse(f"{kind};{ON};note=hedged", posted_at=posted_at, tz=tz)

    settled = settle_day(world.inputs(parse=reader), DAY)
    assert settled.row_drops == {Drop.ZONE_SPLIT.value: 1}


def test_a_row_split_by_zones_disputes_another_stations_claim() -> None:
    """The zones read the row as different statuses: the row says nothing certain about the day."""
    a, b = ids("0027", 2)
    world = World(
        stations=[
            station("gray-a", states=("CO", "MO")),
            station("gray-b", states=("MO",), market="SYNTHETIC market two"),
        ]
    )
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", MORN, "zoned", name="district", district=[a, b])
    world.row("gray-b", MORN, f"closed;{ON}", name="the school", direct=[a])

    def reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        if text != "zoned":
            return stub_parse(text, posted_at=posted_at, tz=tz)
        kind = "delayed" if tz == DENVER else "closed"
        return stub_parse(f"{kind};{ON};note=hedged", posted_at=posted_at, tz=tz)

    settled = settle_day(world.inputs(parse=reader), DAY)
    assert settled.row_drops == {Drop.ZONE_SPLIT.value: 1}
    assert settled.lit == {}
    assert settled.conflicts == (a,)


def test_a_read_whose_statuses_are_all_in_comments_is_read_and_lights() -> None:
    """A list that keeps its status in a second field: an empty status, the words beside it."""
    a = ids("0028", 4)
    world = World(stations=[station("gray-a")])
    world.add_schools(*(school(sid) for sid in a))
    for n, sid in enumerate(a):
        world.row("gray-a", MORN, "", name=f"listing {n}", direct=[sid], comment=f"closed;{ON}")
    settled = settle_day(world.inputs(), DAY)
    assert set(settled.lit) == set(a)
    assert [check.drop for check in settled.reads] == [None]
    assert settled.reads[0].unread_share == 0.0


# --- what a district row that names part of the district says of each school ----------------


def test_a_part_rows_open_reading_votes_open() -> None:
    """ "Open; no AM preschool" says the school is open; "2 hr delay - JHS" disputes."""
    open_ = stub_parse("open", posted_at=datetime.fromisoformat(MORN), tz=CHICAGO)
    assert part_vote(open_, None, DAY, text="Open; no AM preschool", name="d") == OPEN_VOTE
    delayed = stub_parse(f"delayed;{ON}", posted_at=datetime.fromisoformat(MORN), tz=CHICAGO)
    vote = part_vote(delayed, delayed.on(DAY), DAY, text="2 hr delay - JHS", name="d")
    assert vote == DISPUTED_VOTE


def test_each_school_of_a_part_row_takes_its_own_zones_vote() -> None:
    """A part row over two zones: Chicago reads it "open", Denver reads it about Friday. The
    Denver school's own claim at another station still lights."""
    a, b = ids("0029", 2)
    world = World(
        stations=[
            station("gray-a", states=("CO", "MO")),
            station("gray-b", states=("CO", "MO"), market="SYNTHETIC market two"),
        ]
    )
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", MORN, "zoned", name="district", district=[a, b], comment="Lincoln Elem")
    world.row("gray-b", MORN, f"closed;{ON}", name="the school", direct=[b])

    def reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        if not text.startswith("zoned"):
            return stub_parse(text, posted_at=posted_at, tz=tz)
        said = "closed;on=2024-01-19" if tz == DENVER else "open"
        return stub_parse(said, posted_at=posted_at, tz=tz)

    settled = settle_day(world.inputs(parse=reader), DAY)
    assert set(settled.lit) == {b}
    assert settled.row_drops == {Drop.PART_OF_DISTRICT.value: 1}  # no zone reads the day


def test_a_part_row_whose_zones_read_the_day_differently_drops_as_split() -> None:
    a, b = ids("0031", 2)
    world = World(stations=[station("gray-a", states=("CO", "MO"))])
    world.add_schools(school(a), school(b, state="CO", fips="08001"))
    world.row("gray-a", MORN, "zoned", name="district", district=[a, b], comment="Lincoln Elem")

    def reader(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        del text
        kind = "delayed" if tz == DENVER else "closed"
        return stub_parse(f"{kind};{ON}", posted_at=posted_at, tz=tz)

    settled = settle_day(world.inputs(parse=reader), DAY)
    assert settled.row_drops == {Drop.ZONE_SPLIT.value: 1}
    assert settled.lit == {}


def test_a_part_school_with_no_zone_casts_no_vote_and_the_others_still_vote() -> None:
    a, b = ids("0030", 2)
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC market two")])
    world.add_schools(school(a), school(b, fips="99999"))
    world.row("gray-a", MORN, f"delayed;{ON}", name="district", district=[a, b], comment="JHS")
    world.row("gray-b", MORN, f"closed;{ON}", name="the school", direct=[a])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.conflicts == (a,)
    assert Drop.ZONE_UNKNOWN.value not in settled.row_drops
