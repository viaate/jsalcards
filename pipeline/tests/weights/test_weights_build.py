"""The whole build, run offline on the real fixture slices, and its command.

The fixture server holds every slice at its real URL (``conftest.py``); the build
reads three school years (2018-19, 2021-22, 2024-25), five correlation releases,
twelve county records, ten day files, eleven schools and nineteen station records.
"""

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from snowlight.weights import build, cli, count, notes, outlines, registered
from snowlight.weights.codes import CODES

if TYPE_CHECKING:
    from weights.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"


def _paths(kit: "Kit", out: Path) -> build.Paths:
    return build.Paths(
        cache_dir=kit.cache_dir,
        out_dir=out,
        directory=kit.path("schools.parquet"),
        coverage=kit.path("coverage.json"),
        research=kit.path("research"),
        registry=None,
        siblings=(),
    )


def _scope(kit: "Kit", *, windows: bool = True) -> build.Scope:
    return build.Scope(
        years=(2018, 2021, 2024),
        releases=kit.releases,
        county_release=kit.county_release(),
        day_windows=((date(2025, 2, 6), date(2025, 2, 7)),) if windows else (),
        dma_sha256=hashlib.sha256(kit.bytes("usa-tvdma-county.csv")).hexdigest(),
    )


def _run(kit: "Kit", out: Path, *, windows: bool = True) -> build.Result:
    return build.build(
        _paths(kit, out), scope=_scope(kit, windows=windows), clock=kit.clock, cache=kit.http()
    )


def _read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_build_writes_every_output(kit: "Kit", tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _run(kit, out)
    assert sorted(path.name for path in out.iterdir()) == [
        "closure-weights.json",
        "closure-weights.png",
        "manifest.json",
        "method.md",
        "state-weights.json",
        "station-priority.json",
        "station-priority.md",
    ]
    assert (out / "closure-weights.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    closure = _read(out / "closure-weights.json")
    assert closure["schema"] == 2
    assert closure["school_years"] == ["2018-19", "2021-22", "2024-25"]
    counties = closure["counties"]
    assert isinstance(counties, list)
    assert len(counties) == 10
    by_fips = {county["fips"]: county for county in counties}
    providence = by_fips["44007"]
    assert providence["state"] == "RI"
    assert providence["schools"] == 3
    assert set(providence["codes"]) == {code.code for code in CODES}
    assert providence["codes"]["WS.W"]["days"] >= 1
    assert providence["weight"] > 0
    assert providence["years_counted"] == 3
    assert providence["school_years_left_out"] == {}
    assert None not in providence["by_year"].values()
    # Every per-year figure divides by the county's own school years counted.
    for county in counties:
        counted = [year for year in county["by_year"].values() if year is not None]
        assert len(counted) == county["years_counted"]
        assert set(county["school_years_left_out"]) == {
            label for label, year in county["by_year"].items() if year is None
        }
        total = sum(year["weighted"] for year in counted)
        assert county["days_per_year"] == pytest.approx(total / len(counted), abs=1e-3)
        for code in county["codes"].values():
            assert code["per_year"] == pytest.approx(code["days"] / len(counted), abs=1e-4)
    # The school-weighted mean weight is 1.
    placed = sum(county["schools"] for county in counties)
    assert placed == result.schools == 10
    mean = sum(county["schools"] * county["weight"] for county in counties) / placed
    assert mean == pytest.approx(1.0, abs=1e-3)
    normalizer = closure["normalizer"]
    assert isinstance(normalizer, dict)
    assert normalizer["school_weighted_mean_days_per_year"] == pytest.approx(result.mean_days)


def test_state_weights_and_sanity(kit: "Kit", tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run(kit, out, windows=False)
    states = _read(out / "state-weights.json")
    rows = states["states"]
    assert isinstance(rows, list)
    assert {row["state"] for row in rows} == {"RI", "FL", "MT", "CT"}
    assert sum(row["share_of_weighted_closure_days"] for row in rows) == pytest.approx(1, abs=1e-4)
    assert sum(row["schools"] for row in rows) == 10
    assert [row["rank"] for row in rows] == [1, 2, 3, 4]
    sanity = states["sanity"]
    assert isinstance(sanity, dict)
    # Only Rhode Island and Florida of the owner's examples are in the slice: the check
    # cannot pass, and says which states are missing.
    assert sanity["missing_states"] == ["MA", "NY", "MI", "MN", "PA", "MS", "LA"]
    assert sanity["winter"]["passes"] is False
    assert sanity["winter"]["snowy_days_per_year"]["RI"] > 0
    manifest = _read(out / "manifest.json")
    assert "day_files" not in manifest["checks"]


def test_manifest_records_provenance(kit: "Kit", tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _run(kit, out)
    manifest = _read(out / "manifest.json")
    sources = manifest["sources"]
    assert isinstance(sources, dict)
    year = sources["school_years"]["2024-25"]
    assert year["sha256"] == hashlib.sha256(kit.bytes("iem-2024-2025.csv")).hexdigest()
    assert year["url"].startswith("https://mesonet.agron.iastate.edu/cgi-bin/request/gis/")
    assert year["retrieved_at"] == "2026-09-26T12:00:00Z"
    assert set(sources["zone_county_releases"]) == set(kit.releases)
    assert sources["directory"]["path"] == "pipeline/tests/weights/fixtures/schools.parquet"
    references = sources["references"]
    assert references["coverage"]["generated_at"] == "2026-09-26T18:53:25Z"
    checks = manifest["checks"]
    (window,) = checks["day_files"]
    assert window["rows_matched"] == window["rows_csv"] == 9
    names = checks["zone_names_before_first_release"]
    assert [entry["school_year_start"] for entry in names] == [2018]
    # Both names disagree with IEM's in 2018-19. IDZ075's outline then lay in Blaine
    # County, the county the release lists: kept. MTZ043's release counties include
    # three the county slice lacks, so its outline cannot be shown to cover them:
    # left out.
    assert [entry.split(":")[0] for entry in names[0]["left_out"]] == ["MTZ043"]
    assert [entry.split(":")[0] for entry in names[0]["kept_by_outline"]] == ["IDZ075"]
    assert checks["zone_mapping"]["left_out_renamed"]["MTZ043"] > 0
    assert "IDZ075" not in checks["zone_mapping"]["left_out_renamed"]
    outline_checks = checks["zone_outlines"]
    assert set(outline_checks["outline_files"]) == {"2018-19", "2021-22"}
    left_out = {(item["ugc"], item["school_year"]) for item in outline_checks["left_out_zones"]}
    assert ("MTZ043", "2018-19") in left_out
    assert ("LAZ056", "2021-22") in left_out  # Ida's zones: no Louisiana line in the slices
    mtz043 = next(i for i in outline_checks["left_out_zones"] if i["ugc"] == "MTZ043")
    assert mtz043["why"] == "left_out_renamed"
    assert mtz043["outline_counties"] == {"30063": pytest.approx(0.633, abs=0.001)}
    assert checks["schools"]["unplaced"] == ["00230442"]
    ida = checks["rows"]["school_years"]["2021-22"]["tropical_rows_ended"]
    assert len(ida) == 5
    changes = checks["code_changes"]
    assert changes["named_in_todays_event_list"] == {
        "Extreme Cold Warning": True,
        "Freezing Rain Advisory": False,
        "Lake Effect Snow Advisory": False,
        "Wind Chill Warning": False,
        "Winter Weather Advisory": True,
    }
    assert changes["rows_by_school_year"]["EC.W"]["2024-25"] == 6  # Gulf and Franklin, FL
    assert changes["last_school_year_with_rows"]["WC.W"] == "2018-19"  # MTZ043
    assert references["alert_types"]["url"] == "https://api.weather.gov/alerts/types"
    assert result.checks is checks or result.checks == checks


def test_incomplete_school_years_are_left_out(kit: "Kit", tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run(kit, out, windows=False)
    closure = _read(out / "closure-weights.json")
    counties = closure["counties"]
    missoula = next(c for c in counties if c["fips"] == "30063")
    # MTZ043's 2018-19 rows are left out, and its outline lay in Missoula County: that
    # year's count there is incomplete, so Missoula is averaged over the other two.
    assert missoula["left_out_zone_days"]["2018-19"] > 0
    assert missoula["years_counted"] == 2
    assert missoula["school_years_left_out"] == {"2018-19": ["MTZ043"]}
    assert missoula["by_year"]["2018-19"] is None
    kept = [missoula["by_year"][label] for label in ("2021-22", "2024-25")]
    assert missoula["days_per_year"] == pytest.approx(
        sum(year["weighted"] for year in kept) / 2, abs=1e-4
    )
    assert "left_out_zone_days_per_year" not in missoula
    outline_checks = _read(out / "manifest.json")["checks"]["zone_outlines"]
    assert outline_checks["school_years_left_out"] == {"30063": {"2018-19": ["MTZ043"]}}
    assert outline_checks["standing_school_year"] == "2019-20"
    (period,) = _read(out / "manifest.json")["checks"]["years_counted"]
    assert period["state"] == "MT"
    assert period["school_years_counted"] == ["2021-22", "2024-25"]
    assert period["school_years_left_out"] == ["2018-19"]
    assert (period["counties"], period["schools"]) == (["30063"], 1)
    assert period["state_ratio"] is None  # Missoula is the slice's only Montana county
    national = [c for c in counties if c["years_counted"] == 3 and c["schools"]]
    schools_n = sum(c["schools"] for c in national)
    yearly = {
        label: sum(c["schools"] * c["by_year"][label]["weighted"] for c in national) / schools_n
        for label in ("2018-19", "2021-22", "2024-25")
    }
    kept = (yearly["2021-22"] + yearly["2024-25"]) / 2
    assert period["national_ratio"] == pytest.approx(kept / (sum(yearly.values()) / 3), abs=1e-3)
    states = _read(out / "state-weights.json")
    montana = next(row for row in states["states"] if row["state"] == "MT")
    assert montana["schools_in_counties_with_school_years_left_out"] == 1
    method = (out / "method.md").read_text(encoding="utf-8")
    assert "#### School years left out of a county's average" in method
    assert "| Missoula MT (30063) | 1 | 2 |" in method
    assert "| MT | 2: all but 2018-19 | 1 | 1 |" in method
    assert "by state: MT 1 of 1." in method


def test_station_priority(kit: "Kit", tmp_path: Path) -> None:
    out = tmp_path / "out"
    _run(kit, out, windows=False)
    document = _read(out / "station-priority.json")
    families = document["families"]
    assert isinstance(families, list)
    assert [family["rank"] for family in families] == list(range(1, len(families) + 1))
    by_id = {family["id"]: family for family in families}
    # Gray's working lists cover Gulf County and the Capitol region; Rhode Island is
    # uncovered, so the families that list it (Nexstar's WPRI, RIBA and WJAR) gain its
    # five placed schools; the Hartford market (WTNH) adds nothing.
    assert by_id["nexstar-wp"]["standalone"]["new_schools"] == 5
    assert by_id["state-systems"]["standalone"]["new_schools"] == 5
    assert by_id["nexstar-wp"]["in_order"]["new_schools"] in {0, 5}
    assert by_id["state-systems"]["sources_robots_blocked"] == 1  # WVEIS
    baseline = document["baseline"]
    assert isinstance(baseline, dict)
    assert baseline["counties"] == 2
    # The coverage slice lists only Gray sources: every working source is the baseline.
    assert baseline["working_stations_by_group"] == {}
    assert baseline["every_working_source"]["counties"] == 2
    for family in families:
        assert family["rank_beyond_every_working_source"] == family["rank"]
        beyond = family["standalone_beyond_every_working_source"]
        assert beyond["new_schools"] == family["standalone"]["new_schools"]
    records = document["records"]
    assert isinstance(records, dict)
    assert records["counted"] + records["left_out"] == 19
    assert records["left_out_as_gray_checked_in_registry"] == "not read"
    note = (out / "station-priority.md").read_text(encoding="utf-8")
    assert "| 1 |" in note
    assert "WVEIS" in note
    method = (out / "method.md").read_text(encoding="utf-8")
    assert "### The owner's check" in method
    assert "FAILS" in method
    assert "not the state of its directory address; for every school they are the same." in method
    manifest = _read(out / "manifest.json")
    assert manifest["checks"]["schools"]["address_state_elsewhere"] == []


def test_second_build_runs_from_the_cache(kit: "Kit", tmp_path: Path) -> None:
    _run(kit, tmp_path / "one")
    hits = sum(kit.server.hits.values())
    _run(kit, tmp_path / "two")
    assert sum(kit.server.hits.values()) == hits
    one = _read(tmp_path / "one" / "closure-weights.json")
    two = _read(tmp_path / "two" / "closure-weights.json")
    assert one["counties"] == two["counties"]


def test_unplaced_directory_is_an_error(kit: "Kit", tmp_path: Path) -> None:
    with pytest.raises(build.WeightsBuildError, match="no school"):
        build.school_mean({"44007": 1.0}, {})
    with pytest.raises(build.WeightsBuildError, match="closure-type day"):
        build.school_mean({"44007": 0.0}, {"44007": 3})
    paths = _paths(kit, tmp_path / "out")
    scope = _scope(kit, windows=False)
    wrong = build.Scope(
        years=scope.years,
        releases=scope.releases,
        county_release=scope.county_release,
        day_windows=(),
        dma_sha256="0" * 64,
    )
    with pytest.raises(build.WeightsBuildError, match="SHA-256"):
        build.build(paths, scope=wrong, clock=kit.clock, cache=kit.http())


def test_left_out_rows_need_the_outline_check(kit: "Kit") -> None:
    scope = replace(_scope(kit, windows=False), outline_check=False)
    counted = build.count_weather(kit.cache(), scope)
    # Without outlines the name check leaves MTZ043 and IDZ075 out, and Ida's Louisiana
    # zones are in no release of the slices: which county-years they leave incomplete
    # cannot be told, so the build stops.
    assert counted.summary == {}
    with pytest.raises(build.WeightsBuildError, match="outline check is off"):
        build.summarize_counties(counted)


def test_summary_failures_stop_the_build(kit: "Kit", monkeypatch: pytest.MonkeyPatch) -> None:
    counted = build.count_weather(kit.cache(), _scope(kit, windows=False))

    def no_outline(*_: object) -> None:
        raise outlines.OutlineError("MTZ043 2018-19: rows left out and no outline")

    def no_years(*_: object) -> None:
        raise count.CountError("county 30063: every school year is left out")

    monkeypatch.setattr(outlines, "check_outlines", no_outline)
    with pytest.raises(build.WeightsBuildError, match="MTZ043 2018-19"):
        build.summarize_counties(counted)
    monkeypatch.undo()
    monkeypatch.setattr(count, "summarize", no_years)
    with pytest.raises(build.WeightsBuildError, match="every school year is left out"):
        build.summarize_counties(counted)


def test_cli_parser() -> None:
    args = cli.parser().parse_args(["build", "--skip-day-files", "--out-dir", "x"])
    assert args.action == "build"
    assert args.skip_day_files
    assert args.out_dir == Path("x")
    with pytest.raises(SystemExit):
        cli.parser().parse_args([])


def test_cli_main_prints_the_summary(
    kit: "Kit", tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = _run(kit, tmp_path / "out", windows=False)
    seen: list[bool] = []

    def fake_build(paths: build.Paths, *, day_files: bool) -> build.Result:
        seen.append(day_files)
        assert paths.out_dir == tmp_path / "elsewhere"
        return result

    monkeypatch.setattr(cli, "build", fake_build)
    assert cli.main(["build", "--skip-day-files", "--out-dir", str(tmp_path / "elsewhere")]) == 0
    assert seen == [False]
    printed = capsys.readouterr().out
    assert "10 counties, 10 schools" in printed
    assert "(incomplete years left out): 1, holding 1 schools" in printed
    assert "sanity (winter): FAILS" in printed
    assert "closure_weights:" in printed


def test_cli_main_reports_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(paths: build.Paths, *, day_files: bool) -> build.Result:
        raise build.WeightsBuildError(f"nothing to do in {paths.out_dir.name} ({day_files})")

    monkeypatch.setattr(cli, "build", failing)
    assert cli.main(["build", "--out-dir", "somewhere"]) == 1
    assert "weights build failed: nothing to do in somewhere (True)" in capsys.readouterr().err


def test_unreadable_registry_is_reported(kit: "Kit", tmp_path: Path) -> None:
    paths = replace(_paths(kit, tmp_path / "out"), registry=tmp_path / "no-registry")
    build.build(paths, scope=_scope(kit, windows=False), clock=kit.clock, cache=kit.http())
    document = _read(tmp_path / "out" / "station-priority.json")
    check = document["records"]["left_out_as_gray_checked_in_registry"]
    assert check.startswith("the registry could not be read: no registry files")


def test_registry_checks(kit: "Kit", tmp_path: Path) -> None:
    """The real registry slice: the Gray check and the market check both run."""
    paths = replace(_paths(kit, tmp_path / "out"), registry=kit.path("registry"))
    build.build(paths, scope=_scope(kit, windows=False), clock=kit.clock, cache=kit.http())
    document = _read(tmp_path / "out" / "station-priority.json")
    # No record of the research slice is left out as Gray's.
    assert document["records"]["left_out_as_gray_checked_in_registry"] == []
    markets = document["market_counties_checked_in_registry"]
    assert markets["stations_with_dma_county_lists"] == 9
    assert markets["agreeing"] == 5
    assert {row["station"] for row in markets["differing"]} == {
        "gray-kktv",
        "gray-kold",
        "gray-wtva",
        "scripps-kktv",
    }
    note = (tmp_path / "out" / "station-priority.md").read_text(encoding="utf-8")
    assert "- 5 of 9 DMA-based county lists in the registry hold exactly" in note
    assert "gray-kold: Tucson (Nogales), AZ DMA (market not in the crosswalk" in note


def test_registry_not_read_is_said(kit: "Kit", tmp_path: Path) -> None:
    _run(kit, tmp_path / "out", windows=False)
    document = _read(tmp_path / "out" / "station-priority.json")
    assert document["market_counties_checked_in_registry"] == "not read"
    note = (tmp_path / "out" / "station-priority.md").read_text(encoding="utf-8")
    assert "Market counties checked against the station registry:\n\n- not read" in note


def test_cli_registry_options() -> None:
    args = cli.parser().parse_args(["build"])
    assert args.registry == registered.DEFAULT_REGISTRY_DIR
    assert not args.skip_registry
    args = cli.parser().parse_args(["build", "--registry", "r", "--skip-registry"])
    assert args.registry == Path("r")
    assert args.skip_registry


@pytest.mark.parametrize(("extra", "expected"), [([], True), (["--skip-registry"], False)])
def test_cli_passes_the_registry(
    monkeypatch: pytest.MonkeyPatch, extra: list[str], *, expected: bool
) -> None:
    seen: list[Path | None] = []

    def failing(paths: build.Paths, *, day_files: bool) -> build.Result:
        seen.append(paths.registry)
        raise build.WeightsBuildError(f"stop ({day_files})")

    monkeypatch.setattr(cli, "build", failing)
    assert cli.main(["build", "--registry", "somewhere", *extra]) == 1
    assert (seen == [Path("somewhere")]) is expected
    assert (seen == [None]) is not expected


def test_inputs_outside_the_repository(kit: "Kit", tmp_path: Path) -> None:
    """A local input outside the repository is recorded by its absolute path."""
    copy = tmp_path / "elsewhere" / "schools.parquet"
    copy.parent.mkdir()
    copy.write_bytes(kit.bytes("schools.parquet"))
    paths = replace(_paths(kit, tmp_path / "out"), directory=copy)
    build.build(paths, scope=_scope(kit, windows=False), clock=kit.clock, cache=kit.http())
    directory = _read(tmp_path / "out" / "manifest.json")["sources"]["directory"]
    assert directory["path"] == str(copy.resolve())
    assert directory["sha256"] == hashlib.sha256(kit.bytes("schools.parquet")).hexdigest()


def test_priority_note_lists_the_gray_check(kit: "Kit", tmp_path: Path) -> None:
    """The note's Gray lines, on a built document given a Gray check's entries (synthetic
    entries shaped as :func:`snowlight.weights.priority.gray_cover` writes them)."""
    _run(kit, tmp_path / "out", windows=False)
    document = _read(tmp_path / "out" / "station-priority.json")
    entry = {"variant": "moved-to-gray", "reason": "now Gray", "found_by": "call sign"}
    document["records"]["left_out_as_gray_checked_in_registry"] = [
        {
            **entry,
            "name": "WTVA",
            "registry_station": "gray-wtva",
            "registry_platform": "gray",
            "registry_status": "active",
            "registry_counties": 19,
        },
        {
            **entry,
            "name": "WJTV",
            "registry_station": "nexstar-wjtv",
            "registry_platform": "nexstar",
            "registry_status": "active",
            "registry_counties": 24,
        },
        {
            **entry,
            "name": "WFFT",
            "registry_station": None,
            "registry_platform": None,
            "registry_status": None,
            "registry_counties": None,
            "found_by": None,
        },
    ]
    note = notes.priority_note(document)
    assert "- WTVA: gray-wtva (active, 19 counties), found by call sign" in note
    assert "- WJTV: nexstar-wjtv (active, 24 counties, filed under nexstar), found by" in note
    assert "- WFFT: not in the registry (now Gray)" in note
    assert "2 of these 3 have no active Gray entry in the registry (WJTV, WFFT)" in note
