"""The method note (``method.md``) and the station priority note (``station-priority.md``).

Both are generated from the build's results so that every number in them is the
one the JSON files hold. They are internal and never published.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from snowlight.output import JSONValue
from snowlight.sources.nws.iem import WATCHWARN_URL
from snowlight.weights import archive, crosscheck, schoolzones, zonepolys, zones
from snowlight.weights.codes import ADDED_CODES, CODES
from snowlight.weights.count import DECISION_TIME, SCHOOL_DAY_END
from snowlight.weights.priority import STALE_BEFORE

if TYPE_CHECKING:
    from snowlight.weights.build import Counted, Result


def _f(value: JSONValue, places: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(str(value)):.{places}f}"


def _pct(value: JSONValue) -> str:
    if value is None:
        return "n/a"
    return f"{float(str(value)):.1%}"


def _dict(value: JSONValue) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


def _list(value: JSONValue) -> list[JSONValue]:
    return value if isinstance(value, list) else []


def _state_table(rows: Sequence[Mapping[str, JSONValue]]) -> list[str]:
    lines = [
        "| Rank | State | Schools | Weight | Weighted days/yr | Winter days/yr "
        "| Listed winter days/yr | Any-code days/yr | Share of national closure-days "
        "| County-rule weight (rank) | County-rule days/yr |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        subsets = _dict(row["subsets_days_per_year"])
        lines.append(
            f"| {row['rank']} | {row['state']} | {row['schools']} | {_f(row['weight'])} "
            f"| {_f(row['days_per_year'])} | {_f(subsets.get('winter'))} "
            f"| {_f(subsets.get('listed_winter'))} | {_f(row['any_days_per_year'])} "
            f"| {_pct(row['share_of_weighted_closure_days'])} "
            f"| {_f(row['county_rule_weight'])} ({row['county_rule_rank']}) "
            f"| {_f(row['county_rule_days_per_year'])} |"
        )
    return lines


def _flag_lines(flags: Sequence[Mapping[str, JSONValue]]) -> list[str]:
    lines: list[str] = []
    for flag in flags:
        lines.append(f"- **{flag['state']}** {flag['finding']}. {flag['reason']}")
        for county in _list(flag["counties"]):
            item = _dict(county)
            zones_text = ", ".join(f"{k} {v}" for k, v in _dict(item.get("zones")).items())
            lines.append(
                f"  - {item['name']} ({item['fips']}, {item['schools']} schools): weight "
                f"{_f(item['weight'])} ({_f(item['days_per_year'])} weighted days/yr), county "
                f"rule {_f(item['county_rule_weight'])}; schools by zone: {zones_text}"
            )
    return lines


def _day_file_lines(checks: Mapping[str, JSONValue]) -> list[str]:
    lines: list[str] = []
    for window in _list(checks.get("day_files")):
        item = _dict(window)
        lines.append(
            f"- {item['first_day']} to {item['last_day']} ({item['day_files']} day files): "
            f"{item['rows_matched']} of {item['rows_csv']} school-year rows and of "
            f"{item['rows_day_files']} day-file rows match on event, UGC, begin and end; "
            f"{len(_list(item['rows_only_csv']))} only in the school-year file, "
            f"{len(_list(item['rows_only_day_files']))} only in day files. County days: "
            f"{item['county_days_agree']} of {item['county_days']} agree "
            f"({item['county_days_with_events']} with an event) across "
            f"{len(_dict(item['counties']))} counties."
        )
        lines.extend(f"  - differs: {text}" for text in _list(item["disagreements"])[:10])
        lines.extend(f"  - only in school-year file: {t}" for t in _list(item["rows_only_csv"])[:5])
        lines.extend(f"  - only in day files: {t}" for t in _list(item["rows_only_day_files"])[:5])
    return lines


def _name_lines(checks: Mapping[str, JSONValue]) -> list[str]:
    lines: list[str] = []
    for entry in _list(checks.get("zone_names_before_first_release")):
        item = _dict(entry)
        agreeing = _list(item["different_but_agreeing"])
        left_out = _list(item["left_out"])
        missing = _list(item["missing_in_iem"])
        lines.append(
            f"- {archive.school_year_label(int(str(item['school_year_start'])))} "
            f"(IEM at {item['iem_valid']}): {item['same_name']} of {item['zones']} zones have "
            f"the same name; {len(agreeing)} differ but agree; "
            f"{len(left_out) + len(_list(item.get('kept_by_outline')))} disagree, of which "
            f"{len(left_out)} are left out for the year; {len(missing)} not in IEM's list."
        )
        kept = _list(item.get("kept_by_outline"))
        if kept:
            lines.append(
                f"  - {len(kept)} of the disagreeing zones kept: IEM's outline of the zone then "
                "covered the counties the release lists (see the outline check below)"
            )
        lines.extend(f"  - kept (outline agrees): {text}" for text in kept)
        lines.extend(f"  - left out: {text}" for text in left_out)
        lines.extend(f"  - agree: {text}" for text in agreeing[:40])
        if missing:
            lines.append(f"  - not in IEM's list: {', '.join(str(m) for m in missing[:20])}")
    return lines


def _outline_lines(report: Mapping[str, JSONValue], result: "Result") -> list[str]:
    if not report:
        return ["- not run"]
    compared = _dict(report["zones_compared"])
    agreeing = _dict(report["zones_agreeing"])
    disagreements = [_dict(item) for item in _list(report["disagreements"])]
    standing = report.get("standing_school_year")
    lines = [
        "IEM's archive of the NWS UGC database (`ugcs.geojson?valid=`, 15 January of each "
        "school year concerned; simplified outlines; retrieval in `manifest.json`) gives each "
        "zone's outline at the time. A release's counties for a zone agree with the outline "
        f"when every county holding at least {_f(report['major_share'], 3)} of the outline is "
        f"listed and every listed county holds at least {_f(report['touch_share'], 3)} of it.",
        "",
        "Zones read in a release for products issued before it took effect, by school year "
        "(zones agreeing of zones compared): "
        + ", ".join(f"{label} {agreeing.get(label, 0)} of {n}" for label, n in compared.items())
        + f". Each zone that disagrees is compared with its outline in {standing}, the first "
        "school year wholly under the served releases. When that outline shows the same "
        "disagreement, the listing is the release's standing reading of the zone (most are "
        "the release's own quirks, repeated in every later release, such as a zone named for "
        "a county that its records leave out), applied alike before and after 2019, and "
        "nothing is changed. When it does not (the zone was redrawn), the counties it "
        "disagreed on then have that school year left out of their average (below). The "
        "disagreeing zones, with the rows read that way:",
        "",
    ]
    seen: dict[str, list[dict[str, JSONValue]]] = {}
    for item in disagreements:
        seen.setdefault(str(item["ugc"]), []).append(item)
    for ugc, items in sorted(seen.items(), key=lambda kv: -sum(int(str(i["rows"])) for i in kv[1])):
        first = items[0]
        shares = ", ".join(f"{k} {_f(v, 3)}" for k, v in _dict(first["outline_shares"]).items())
        later = first.get("standing_outline_shares")
        later_text = (
            "no outline"
            if later is None
            else ", ".join(f"{k} {_f(v, 3)}" for k, v in _dict(later).items())
        )
        years = ", ".join(str(i["school_year"]) for i in items)
        rows = sum(int(str(i["rows"])) for i in items)
        listed = ", ".join(str(c) for c in _list(first["listed"]))
        left = sorted({str(c) for i in items for c in _list(i["counties_left_out_for_the_year"])})
        verdict = (
            "the same disagreement then: standing"
            if all(i["same_in_standing_school_year"] for i in items)
            else f"not the same: {', '.join(left) or 'nothing'} left out for {years}"
        )
        lines.append(
            f"- {ugc} ({first['iem_name']}): listed {listed}; outline {shares}; "
            f"{rows} rows in {years}; outline in {standing} {later_text}, {verdict}."
        )
    lines += ["", *_left_out_lines(report, result)]
    if report["zones_without_outline"]:
        missing = ", ".join(str(z) for z in _list(report["zones_without_outline"]))
        lines += ["", f"Zones read in a release with no outline in IEM's archive: {missing}."]
    return lines


def _period_lines(effects: JSONValue) -> list[str]:
    groups = [_dict(item) for item in _list(effects)]
    if not groups:
        return ["Every county keeps every school year."]
    lines = [
        "The years a county keeps are not the whole period, and a set of years can be "
        "stormier or milder than the whole. For each state and set of years kept: among the "
        "counties that keep every year, nationally and in the same state, the school-weighted "
        "mean over the years kept divided by the mean over all years (nothing is adjusted; a "
        "ratio above 1 means the counties averaged over those years are lifted by about as "
        "much, below 1 lowered):",
        "",
        "| State | School years counted | Counties | Schools | National ratio | State ratio |",
        "|---|---|---|---|---|---|",
    ]
    for item in sorted(groups, key=lambda i: (-int(str(i["schools"])), str(i["state"]))):
        kept = _list(item["school_years_counted"])
        left = ", ".join(str(label) for label in _list(item["school_years_left_out"]))
        lines.append(
            f"| {item['state']} | {len(kept)}: all but {left} | {len(_list(item['counties']))} "
            f"| {item['schools']} | {_f(item['national_ratio'], 3)} "
            f"| {_f(item['state_ratio'], 3)} |"
        )
    return lines


def _touching_lines(report: Mapping[str, JSONValue]) -> list[str]:
    below = _dict(report.get("below_major_share_kept"))
    largest = [_dict(item) for item in _list(below.get("largest"))]
    if not largest:
        return [
            f"No county holding less than {_f(report['major_share'], 3)} of a left-out zone's "
            "outline keeps a school year the zone's rows would have touched."
        ]
    top = largest[0]
    return [
        f"A county holding at least {_f(report['touch_share'], 3)} but less than "
        f"{_f(report['major_share'], 3)} of a left-out zone's outline keeps the year: "
        f"{below['county_school_years']} county-years. The largest such share is "
        f"{_pct(top['share'])} ({top['ugc']} in {top['fips']}, {top['school_year']}); these "
        "are the slivers the simplified outlines leave along county lines. Largest: "
        + "; ".join(
            f"{item['ugc']} in {item['fips']} {item['school_year']} {_pct(item['share'])}"
            for item in largest
        )
        + "."
    ]


def _left_out_lines(report: Mapping[str, JSONValue], result: "Result") -> list[str]:
    left_out = [_dict(item) for item in _list(report["left_out_zones"])]
    total_rows = sum(int(str(item["rows"])) for item in left_out)
    counties = sorted(
        (
            record
            for record in result.county_rule_records.values()
            if record["school_years_left_out"]
        ),
        key=lambda record: (-int(str(record["schools"])), str(record["fips"])),
    )
    schools = sum(int(str(record["schools"])) for record in counties)
    county_years = sum(len(_dict(record["school_years_left_out"])) for record in counties)
    lines = [
        "##### School years left out of a county's average",
        "",
        "Zone rows left out (in no served release, left out by the name check, or given a "
        f"county code the county list lacks): {total_rows} rows of "
        f"{len({str(i['ugc']) for i in left_out})} zones. Every county holding at least "
        f"{_f(report['major_share'], 3)} of such a zone's outline that school year, and not "
        "reached by the rows, misses them, "
        "so its count for the year is incomplete, not zero. Each such county-year (and each "
        "one a redrawn zone read in a release makes wrong, above) is left out of the county's "
        "average: the county is averaged over its other school years (`years_counted`, and "
        "`null` in `by_year`), and every per-year figure of it uses those years only. Nothing "
        f"is filled in. {len(counties)} counties ({schools} schools) lose {county_years} "
        "county-years in all. `Left-out rows would add` is the diagnostic "
        "`left_out_zone_days`: the weighted days the left-out rows would give the county if "
        "counted by the outline (never in the metric).",
        "",
        *_touching_lines(report),
    ]
    lines += ["", *_period_lines(result.checks.get("years_counted")), "", "By schools:", ""]
    lines += [
        "| County | Schools | Years counted | Weighted days/yr (metric) | Weight "
        "| School years left out (zones) | Left-out rows would add |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in counties:
        left = _dict(record["school_years_left_out"])
        years = "; ".join(
            f"{label} ({', '.join(str(z) for z in _list(ugcs))})" for label, ugcs in left.items()
        )
        gains = ", ".join(f"{k} {_f(v)}" for k, v in _dict(record["left_out_zone_days"]).items())
        lines.append(
            f"| {record['name']} {record['state']} ({record['fips']}) | {record['schools']} "
            f"| {record['years_counted']} | {_f(record['days_per_year'])} "
            f"| {_f(record['weight'])} | {years} | {gains or 'none'} |"
        )
    return lines


def _change_lines(changes: Mapping[str, JSONValue]) -> list[str]:
    if not changes:
        return ["- not checked"]
    rows = _dict(changes["rows_by_school_year"])
    last = _dict(changes["last_school_year_with_rows"])
    named = _dict(changes["named_in_todays_event_list"])
    lines = [
        "Rows per school year of the replaced codes and of the codes that replaced them, "
        "and whether today's NWS event list (`https://api.weather.gov/alerts/types`, "
        "retrieval in `manifest.json`) still names each event:",
        "",
    ]
    for code, per_year in rows.items():
        counts = ", ".join(f"{label} {n}" for label, n in _dict(per_year).items())
        lines.append(f"- {code}: last rows in {last.get(code) or 'none'}; {counts}.")
    lines.append(
        "- Named in today's event list: "
        + ", ".join(f"{name} {'yes' if value else 'no'}" for name, value in named.items())
        + "."
    )
    for code, entry in _dict(changes["replaced"]).items():
        item = _dict(entry)
        lines.append(
            f"- {code} ({item['event']}) is counted with its replacement, "
            f"{item['replaced_by']}, at the same weight."
        )
    return lines


def _address_lines(elsewhere: Sequence[JSONValue]) -> list[str]:
    """Say which state a school counts in, and name those whose address is elsewhere."""
    text = (
        "A school counts in the state of the county it is placed in (where it is, by its "
        "county code and coordinates), not the state of its directory address"
    )
    if not elsewhere:
        return [text + "; for every school they are the same."]
    names = ", ".join(
        f"{item['school']} ({item['address_state']} address, in {item['state']})"
        for item in map(_dict, elsewhere)
    )
    return [f"{text}. The two differ for {len(elsewhere)} schools: {names}."]


NAMED_COUNTIES: tuple[tuple[str, str], ...] = (
    ("49035", "Salt Lake City (Salt Lake County)"),
    ("49049", "Provo and Orem (Utah County)"),
    ("49011", "Davis County, UT"),
    ("49057", "Ogden (Weber County)"),
    ("08031", "Denver (Denver County)"),
    ("08059", "Jefferson County, CO (Denver's west)"),
    ("08005", "Arapahoe County, CO (Denver's south)"),
    ("08001", "Adams County, CO (Denver's north)"),
    ("08013", "Boulder County, CO"),
    ("08035", "Douglas County, CO"),
    ("16001", "Boise (Ada County)"),
    ("16027", "Nampa and Caldwell (Canyon County)"),
    ("53033", "Seattle (King County)"),
    ("32003", "Las Vegas (Clark County)"),
    ("06037", "Los Angeles County"),
    ("44007", "Providence County, RI"),
    ("25025", "Boston (Suffolk County)"),
    ("36061", "Manhattan (New York County)"),
    ("36029", "Buffalo (Erie County)"),
    ("26163", "Detroit (Wayne County)"),
    ("27053", "Minneapolis (Hennepin County)"),
    ("42101", "Philadelphia"),
    ("42003", "Pittsburgh (Allegheny County)"),
    ("28049", "Jackson (Hinds County), MS"),
    ("22071", "New Orleans (Orleans Parish)"),
    ("12086", "Miami-Dade County"),
)
"""Counties shown side by side under both rules (the places the owner's request names, their
neighbours, and one or two big school counties of each snowy and mild example state)."""
MOVERS_MIN_SCHOOLS = 20
UNCHANGED = 0.01


def _short(key: str) -> str:
    """``iem/NCZ051/531.0424`` to ``531.0424``, ``z_18mr25/NCZ051`` to ``z_18mr25``."""
    return key.rsplit("/", 1)[-1] if key.startswith("iem/") else key.split("/", 1)[0]


ALTERNATION_NOTES: dict[str, str] = {
    "NCZ051": "NCZ051's 531 km² outline leaves out 869 km² of the 1,400 km² zone (Swain "
    "County, NC); Cherokee's schools lie 0.73 km outside it and take its rows by the "
    "school-year rule below.",
    "VAZ099": "VAZ099's 998 km² outline is Accomack County's mainland alone; its 1,178 km² "
    "outline adds the county's islands (180 km² in 363 parts, Chincoteague and Tangier "
    "among them), and MDZ024's 1,278 km² outline holds exactly those islands: the Accomack "
    "schools on them lay in MDZ024 in the school years whose rows use those outlines, and "
    "take MDZ024's rows then.",
}
"""What the build found in the outlines of zones whose rows alternate between outlines that
differ materially (checked when the notes were written, 2026-09-27; shown only while the
zone is still listed)."""


def _alternating_lines(zp: dict[str, JSONValue], log: dict[str, JSONValue]) -> list[str]:
    """The zones whose rows go back and forth between outlines."""
    found = [_dict(item) for item in _list(zp.get("alternating_outlines", []))]
    material = [
        item for item in found if float(str(item["largest_area_difference"])) > zonepolys.MATERIAL
    ]
    logged: dict[str, set[str]] = {}
    for entry in _list(log.get("logged", [])):
        item = _dict(entry)
        logged.setdefault(str(item["zone"]), set()).add(str(item["school"]))
    elsewhere = _dict(log.get("school_years_in_another_zone_by_own_zone", {}))
    lines = [
        f"- Outlines a zone's rows return to: the rows of {len(found)} zones, in time order, "
        "go back to an outline after rows joined to another. IEM held two outlines of such a "
        "zone at once: its archived UGC outlines of 15 January 2018 (read for the zone-name "
        "check) list two each for NCZ051, NCZ052, MDZ024 and VAZ099. Each row is still read "
        "against its own outline. The outline returned to and those in between differ by at "
        f"most {zonepolys.MATERIAL:.0%} in area for {len(found) - len(material)} of them "
        f"(redrawn edges), and more for {len(material)}" + (":" if material else "."),
    ]
    for item in material:
        ugc = str(item["ugc"])
        areas = _dict(item["outlines_km2"])
        runs = [_dict(run) for run in _list(item["runs"])]
        sequence = ", ".join(
            f"{_short(str(run['version']))} {str(run['first'])[:7]} to {str(run['last'])[:7]}"
            for run in runs
        )
        outlines = ", ".join(f"{_short(key)} ({_f(area, 1)} km²)" for key, area in areas.items())
        lines.append(
            f"  - {ugc}: outlines {outlines}; its rows in order: {sequence}. Schools with a "
            f"school year logged for it below: {len(logged.get(ugc, set()))}; school years its "
            f"schools lay in another zone's outline: {elsewhere.get(ugc, 0)}."
            + (f" {ALTERNATION_NOTES[ugc]}" if ugc in ALTERNATION_NOTES else "")
        )
    return lines


def _zone_polygon_lines(result: "Result") -> list[str]:
    zp = _dict(result.checks.get("zone_polygons"))
    counting = _dict(result.checks.get("school_counting"))
    if not zp:
        return ["## Each school in its own forecast zone", "", "- not run"]
    by_source = _dict(zp["versions_by_source"])
    rows_by_source = _dict(zp["rows_by_source"])
    worst = _dict(zp["largest_area_difference_by_source"])
    served = list(_dict(zp["served_releases"]))
    lines = [
        "## Each school in its own forecast zone",
        "",
        "### Zone polygons",
        "",
        "A zone code names an area the NWS redraws now and then (Salt Lake City's valley and "
        "mountain zones were UTZ003 and UTZ008 until the SLC reconfiguration of 30 March 2021, "
        "then UTZ105 and UTZ111), so each zone row is read against the polygon of its zone as "
        "it stood when its product was issued. Every row of IEM's school-year files carries "
        "`area2d`: the area, in km² in the US National Atlas Equal Area projection "
        "(EPSG:2163), of the zone outline IEM joined to it: the outline IEM held for the zone "
        "then, from the NWS zone release it had loaded (for a few zones it held two at once; "
        "below). A zone *version* is one zone code with one such "
        f"area; the rows hold {zp['versions']} versions.",
        "",
        f"- The NWS serves two zone releases, {' and '.join(served)} "
        f"({zonepolys.PUBLIC_ZONES_PAGE}). "
        "Of the 155 file names its zone change log gives "
        f"({zonepolys.ZONE_CHANGE_LOG}; public and fire zones, 2005 to 2026), only z_18mr25 "
        "answers at `https://www.weather.gov/source/gis/Shapefiles/WSOM/`; the others, and a "
        "`z_DDmmYY.zip` for every release date of the correlation files the county rule reads "
        "(bp02ap19 to bp10se24), answer 404 (HEAD requests, 2026-09-27).",
        f"- A version whose area equals the equal-area size of its zone's polygon in a served "
        f"release, to within {zp['area_tolerance']} of it, is that polygon: "
        + ", ".join(
            f"{by_source.get(name, 0)} versions ({rows_by_source.get(name, 0)} rows) from {name}, "
            f"largest difference {worst.get(name, 'n/a')}"
            for name in served
        )
        + ".",
        f"- The other {by_source.get('iem', 0)} versions ({rows_by_source.get('iem', 0)} rows) are "
        "IEM's full-resolution copies of the NWS polygon of the time (`watchwarn.py` with "
        f"`simple=0`: {len(_list(zp['iem_requests']))} requests of one office, one code and one "
        "minute of begin times, chosen to hold a row of every such version). Each copy's own "
        "equal-area size agrees with its rows' `area2d` (largest difference "
        f"{worst.get('iem', 'n/a')}). They are the zones redrawn before March 2025, and the "
        "zones as they stood before October 2019: the NWS reduced every zone's points to a "
        "0.0001° tolerance with z_10oc19 (zone change log), which moved their areas by 1e-5 "
        "and more, so no version of before then is read in a later release.",
        f"- Versions with no polygon: {len(_list(zp['unresolved'])) or 'none'} (the build "
        "stops when there is one).",
        *_alternating_lines(
            zp, _dict(_dict(result.checks.get("school_zones")).get("by_school_year", {}))
        ),
        "",
        "Zone rows by where their polygon came from, per school year:",
        "",
        f"| School year | {' | '.join(served)} | IEM copy |",
        f"|---|{'---|' * len(served)}---|",
    ]
    per_year = _dict(counting.get("zone_rows_by_school_year_and_polygon_source"))
    for label, found in per_year.items():
        item = _dict(found)
        cells = " | ".join(str(item.get(name, 0)) for name in served)
        lines.append(f"| {label} | {cells} | {item.get('iem', 0)} |")
    return lines


def _year_run(years: list[int]) -> str:
    """``2015-16 to 2022-23`` for consecutive school years, else a list."""
    labels = [f"{year}-{(year + 1) % 100:02d}" for year in years]
    if len(years) > 2 and years == list(range(years[0], years[-1] + 1)):  # noqa: PLR2004
        return f"{labels[0]} to {labels[-1]}"
    return ", ".join(labels)


def _by_year_lines(log: dict[str, JSONValue]) -> list[str]:
    """The school-year rule and every school year it logged, grouped by school."""
    if not log:
        return []
    by_method = _dict(log["school_years_by_method"])
    lines = [
        "School year by school year, each school placed `inside` or `nearest` is checked "
        "against the zone versions with rows that school year. When a version of its own "
        "zone misses it and a version of another zone covers it, it lay in that zone that year "
        "(its zone was redrawn since, or its outline changed within the year) and takes the "
        "rows of the versions covering it: "
        f"{log['school_years_in_another_zone']} school years of "
        f"{log['schools_with_school_years_in_another_zone']} schools ("
        + ", ".join(
            f"{zone} {n}"
            for zone, n in list(_dict(log["school_years_in_another_zone_by_own_zone"]).items())[:8]
        )
        + "). Otherwise, each version of its own zone (the zone it is in under the reference "
        "release) with rows that school year that does not cover the school is a miss: when "
        "no version of its own zone covers it that year, it takes the missed versions' rows "
        f"of that year if each lies within {log['nearest_km']} km (`nearest`), and falls back "
        "to its county for that school year beyond that (`county`, the county rule's counts "
        "of that year); when another version of its own zone covers it that year (the outline "
        "changed within the school year), it takes each missed version within "
        f"{log['nearest_km']} km and not one beyond (`not_taken`). A school placed `nearest` "
        "reaches its zone's rows this way. Logged: "
        f"{sum(int(str(v)) for v in by_method.values())} school years of {log['schools']} "
        "schools ("
        + (", ".join(f"{k} {v}" for k, v in by_method.items()) or "none")
        + f"); {log['schools_with_county_years']} schools fell back to their county for a "
        "school year."
        + (
            " Every one (also in `manifest.json`, `school_zones.by_school_year`):"
            if _list(log["logged"])
            else ""
        ),
    ]
    if not _list(log["logged"]):
        return lines
    lines += [
        "",
        "| School | County | Own zone | School years | Versions missed (km) | Rows taken "
        "| Placed |",
        "|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, str, str, str, str], tuple[list[int], list[int]]] = {}
    for entry in _list(log["logged"]):
        item = _dict(entry)
        versions = [_dict(v) for v in _list(item["versions"])]
        missed = "; ".join(
            f"{v['version']} ({_f(v['distance_km'], 3)})" + ("" if v["taken"] else ", not taken")
            for v in versions
        )
        kind = str(item["placed"])
        if item["inside_another_version_of_its_zone"]:
            kind += ", inside another version that year"
        key = (str(item["school"]), str(item["fips"]), str(item["zone"]), missed, kind)
        years, rows = groups.setdefault(key, ([], []))
        years.append(int(str(item["school_year"])[:4]))
        rows.append(sum(int(str(v["rows"])) for v in versions if v["taken"]))
    for (school, fips, zone, missed, kind), (years, rows) in groups.items():
        lines.append(
            f"| {school} | {fips} | {zone} | {_year_run(years)} | {missed} | {sum(rows)} | {kind} |"
        )
    return lines


def _placement_lines(result: "Result") -> list[str]:
    zoned = _dict(result.checks.get("school_zones"))
    if not zoned:
        return []
    placed = _dict(zoned["placed_by"])
    nearest = [_dict(item) for item in _list(zoned["nearest"])]
    county = [_dict(item) for item in _list(zoned["county"])]
    lines = [
        "### Where each school is",
        "",
        f"Each school's point is placed in {zoned['reference_release']}: inside a zone polygon "
        f"(boundary included) {placed.get('inside', 0)} schools; outside every zone polygon but "
        f"within {zoned['nearest_km']} km of one, the nearest zone {placed.get('nearest', 0)} "
        f"(listed below); farther than that, its county {placed.get('county', 0)} (it then "
        "takes the county rule for zone-coded products). Distances are on a local "
        "equirectangular plane (sphere of 6,371.0088 km), within 1% at 2 km. "
        f"{zoned['on_shared_boundary']} points lie on a boundary two zones share (both zones' "
        "rows reach them).",
        "",
        "A zone row reaches every school inside the polygon of the version it was issued for, "
        "whatever zone the school is in under the reference release: a school whose zone was "
        "redrawn takes, in each period, the zone it was in then.",
        "",
        *_by_year_lines(_dict(zoned["by_school_year"])),
        "",
        f"Time zones: of the schools in counties a time zone line crosses, "
        f"{zoned['time_zone_from_zone']} are in a zone that lies in one time zone and take "
        f"it; {zoned['time_zone_split_kept']} are in a zone the line crosses too and keep "
        "both.",
        "",
        "Schools placed in the nearest zone:",
        "",
    ]
    lines.extend(
        f"- {item['school']} (county {item['fips']}): {item['zone']}, "
        f"{_f(item['distance_km'], 3)} km"
        for item in nearest
    )
    if not nearest:
        lines.append("- none")
    lines += ["", "Schools that fell back to their county:", ""]
    lines.extend(
        f"- {item['school']} (county {item['fips']}): nearest zone {item['nearest_zone']} at "
        f"{_f(item['distance_km'], 3)} km"
        for item in county
    )
    if not county:
        lines.append(f"- none (every school is within {schoolzones.NEAREST_KM} km of a zone)")
    return lines


def _storm_lines(result: "Result") -> list[str]:
    counting = _dict(result.checks.get("school_counting"))
    storms = _dict(result.checks.get("storm_polygons"))
    if not counting:
        return []
    without = _dict(counting["polygon_code_events_without_polygons"])
    lines = [
        "### County-coded products and storm-based polygons",
        "",
        f"County-coded rows (UGC `XXCnnn`) reach every school placed in the county: "
        f"{counting['county_rows']} rows (other than the Flash Flood Warning's), "
        f"{counting['county_rows_reaching_schools']} reaching schools. Zone rows: "
        f"{counting['zone_rows']}, {counting['zone_rows_reaching_schools']} reaching schools.",
        "",
        "The Flash Flood Warning is the only storm-based code counted: it reaches the schools "
        "inside its polygon, one version at a time (a follow-up statement that narrows the "
        "warning issues a new polygon; each version counts over its own span under the 6 AM "
        "rule). Its county rows are then not used "
        f"({counting['polygon_code_county_rows_replaced_by_polygons']} rows). Events with county "
        f"rows and no polygon in the polygon file ({len(without)}) keep their county rows: "
        + (", ".join(f"{k} ({v} rows)" for k, v in without.items()) or "none")
        + f". Polygon versions read: {counting['polygon_rows']}, "
        f"{counting['polygon_rows_reaching_schools']} reaching a school.",
        "",
        "| School year | Polygon versions | Events | Events with polygon rows in the "
        "school-year file | In both | Only in the school-year file | Only in the polygon file "
        "| Blank event times |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, entry in storms.items():
        item = _dict(entry)
        lines.append(
            f"| {label} | {item['polygon_rows']} | {item['events']} "
            f"| {item['school_year_file_polygon_events']} | {item['events_in_both']} "
            f"| {len(_list(item['only_in_school_year_file']))} "
            f"| {len(_list(item['only_in_polygon_file']))} | {item['without_event_times']} |"
        )
    return lines


def _change(new: float, old: float) -> str:
    return "n/a" if old <= 0 else f"{new / old - 1:+.0%}"


def _zones_listed(counted: "Counted") -> dict[str, int]:
    """County FIPS to the zones the latest correlation release lists for it."""
    found: dict[str, int] = {}
    for fips_codes in counted.releases[-1].counties.values():
        for fips in fips_codes:
            found[fips] = found.get(fips, 0) + 1
    return found


def _named_lines(result: "Result", counted: "Counted") -> list[str]:
    ratio = result.mean_days / result.county_rule_mean if result.county_rule_mean > 0 else 0.0
    listed = _zones_listed(counted)
    latest = counted.releases[-1].name
    lines = [
        "### The places named, under both rules",
        "",
        "Weighted days per school year are absolute; weights are relative to each rule's "
        f"national mean, which fell from {result.county_rule_mean:.3f} (county rule) to "
        f"{result.mean_days:.3f} ({ratio - 1:+.0%}): mountain-zone days no longer count for "
        "valley schools anywhere, so a county whose schools lost no days gains weight.",
        "",
        f"| County | Schools | Zones the correlation lists for it ({latest}) "
        "| Days/yr, county rule | Days/yr, per school | Change "
        "| Weight, county rule | Weight, per school | Schools by zone |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    unchanged: list[str] = []
    for fips, label in NAMED_COUNTIES:
        record = result.counties.get(fips)
        if record is None:
            continue
        rule = _dict(record["county_rule"])
        old = float(str(rule["days_per_year"]))
        new = float(str(record["days_per_year"]))
        zones_text = ", ".join(f"{k} {v}" for k, v in list(_dict(record["zones"]).items())[:4])
        lines.append(
            f"| {label} ({fips}) | {record['schools']} | {listed.get(fips, 0)} | {_f(old)} "
            f"| {_f(new)} | {_change(new, old)} | {_f(rule['weight'])} "
            f"| {_f(record['weight'])} | {zones_text} |"
        )
        if old > 0 and abs(new / old - 1) < UNCHANGED and listed.get(fips, 0) == 1:
            unchanged.append(label)
    if unchanged:
        lines += [
            "",
            f"Unchanged in days (within {UNCHANGED:.0%}): {', '.join(unchanged)}. The "
            "correlation lists a single zone for each of these counties, the zone (nearly) "
            "all their schools are in (see the last column), so the county rule gave them "
            "only that zone's warnings and there was nothing for the per-school rule to "
            "remove; their weight rises only because the national mean fell.",
        ]
    return lines


def _mover_lines(result: "Result") -> list[str]:
    changes = []
    for record in result.counties.values():
        if int(str(record["schools"])) < MOVERS_MIN_SCHOOLS:
            continue
        rule = _dict(record["county_rule"])
        old = float(str(rule["days_per_year"]))
        new = float(str(record["days_per_year"]))
        changes.append((new - old, record, old, new))
    changes.sort(key=lambda item: (item[0], str(item[1]["fips"])))
    header = [
        "| County | Schools | Days/yr, county rule (years counted) | Days/yr, per school "
        "| Change | Top zones of the county rule |",
        "|---|---|---|---|---|---|",
    ]

    def row(item: tuple[float, Mapping[str, JSONValue], float, float]) -> str:
        _, record, old, new = item
        rule = _dict(record["county_rule"])
        tops = "; ".join(
            f"{_dict(z)['ugc']} {_dict(z)['name']} ({_dict(z)['days']} days)"
            for z in _list(rule.get("top_zones"))[:2]
        )
        return (
            f"| {record['name']} {record['state']} ({record['fips']}) | {record['schools']} "
            f"| {_f(old)} ({rule['years_counted']}) | {_f(new)} | {_change(new, old)} | {tops} |"
        )

    return [
        f"### Largest changes (counties with at least {MOVERS_MIN_SCHOOLS} schools)",
        "",
        "Fifteen largest falls in weighted days per school year:",
        "",
        *header,
        *(row(item) for item in changes[:15]),
        "",
        "Fifteen largest rises (a per-school count can exceed the county rule's where the "
        "county rule left a school year out, where a row's own zone version reaches a school "
        "the correlation release did not list, or where a school's own time zone differs):",
        "",
        *header,
        *(row(item) for item in reversed(changes[-15:])),
    ]


def _results_lines(result: "Result", counted: "Counted") -> list[str]:
    sanity = result.sanity
    lines = [
        "## Results",
        "",
        f"Top {min(10, len(result.states))} states by weight (the mean of their schools' "
        "weights), with the county rule beside it:",
        "",
        *_state_table(result.states[:10]),
        "",
        "Bottom 10 states:",
        "",
        *_state_table(result.states[-10:]),
        "",
        "Every state:",
        "",
        *_state_table(result.states),
        "",
        *_named_lines(result, counted),
        "",
        *_mover_lines(result),
        "",
        "### The owner's check",
        "",
        f"Bar: {sanity['bar']}.",
        "",
    ]
    for key in ("listed_winter", "winter"):
        item = _dict(sanity[key])
        lines.append(
            f"- {key.replace('_', ' ')} days per year: snowy "
            + ", ".join(f"{k} {_f(v)}" for k, v in _dict(item["snowy_days_per_year"]).items())
            + "; mild "
            + ", ".join(f"{k} {_f(v)}" for k, v in _dict(item["mild_days_per_year"]).items())
            + f"; lowest snowy over highest mild {item['lowest_snowy_over_highest_mild']}: "
            + ("passes" if item["passes"] else "FAILS")
            + "."
        )
    lines.append(
        "- weights: " + ", ".join(f"{k} {_f(v)}" for k, v in _dict(sanity["weights"]).items())
    )
    lines += ["", "### Flags (surprises, with the data behind them; nothing was adjusted)", ""]
    lines.extend(_flag_lines(result.flags) or ["- none"])
    return lines


def _station_lines() -> list[str]:
    return [
        "## For the station builders: reading per-school weights",
        "",
        "`pipeline/snowlight/sources/stations/coverage.py` reads `counties[].fips` and "
        "`counties[].weight` from `closure-weights.json` and gives every school its NWS "
        "county's weight (`Weights.placed`). That keeps working unchanged: each county's "
        "`weight` is now the mean of its schools' own weights, so a county's schools sum to "
        "the same total as their own weights wherever the directory county is the NWS county "
        "(everywhere but Connecticut). Counties with no school are no longer listed (they "
        "have no weight to give); `load_weights` accepts that. The exact change that makes "
        "coverage count each school's own weight (not made here: that module is the station "
        "builders'):",
        "",
        "1. `Weights` gains a field `by_school: Mapping[str, float] | None = None` (NCES id "
        "to weight).",
        '2. `load_weights` also reads `data["schools"]`, a dict keyed by NCES id whose '
        "values each hold a numeric `weight` (at least 0), and passes it as `by_school`; it "
        "raises `CoverageError` for a value that is not a dict with such a weight, as it does "
        "for a county.",
        "3. In `Weights.placed`, the weight of a school becomes "
        "`self.by_school.get(school.school_id) if self.by_school is not None else None`, and "
        "when that is `None`, `self.by_county.get(school.nws_fips)` as now. Nothing else "
        "changes: the sums stay per (directory county, state), and `placed` passes "
        "`by_school` on to the `Weights` it returns.",
        "4. `snowlight/sources/stations/storms.py` reads `count_weather(...).tally`, the county "
        "rule's day counts per county; that function and its tally are unchanged.",
    ]


def method_note(result: "Result", counted: "Counted", stamp: str) -> str:
    """Return the method note."""
    checks = result.checks
    mapping = _dict(checks["zone_mapping"])
    rows_by = _dict(mapping["rows_by_resolution"])
    total_rows = sum(int(str(v)) for v in rows_by.values())
    unmapped = _dict(mapping["unmapped_ugcs"])
    years = counted.files
    fewest = min(
        (int(str(r["years_counted"])) for r in result.county_rule_records.values()), default=0
    )
    lines: list[str] = [
        "# Closure weights: method note",
        "",
        f"Generated {stamp} by `python -m snowlight.weights build`. Internal; never published.",
        "",
        "## What is measured",
        "",
        f"For every school of the directory ({result.schools} schools of the contiguous states "
        "and DC, each at its NCES latitude and longitude): the average number of distinct "
        "school days per school year on which the school was under at least one closure-type "
        "NWS event, each day weighted by the heaviest code in effect, over the school years "
        f"{years[0].label} to {years[-1].label} ({len(years)} years). A zone-coded event counts "
        "for the schools inside the polygon of the public forecast zone it was issued for, as "
        "that zone stood when the product was issued; a county-coded event for every school "
        "of the county; a storm-based warning (the Flash Flood Warning) for the schools inside "
        "its polygon. `weight` is a school's average divided by the mean over every school, so "
        f"the school-weighted national mean weight is 1. That mean is {result.mean_days:.4f} "
        "weighted days per school year.",
        "",
        "Each county's record in `closure-weights.json` is the mean of its schools (so a "
        "county's `weight` times its schools is the sum of its schools' weights); each "
        "school's own record is under `schools`, keyed by NCES id. Counties with no school "
        f"({len(result.counties_without_schools)}: "
        f"{', '.join(result.counties_without_schools) or 'none'}) have no summary and are "
        "listed in `counties_without_schools`.",
        "",
        "The earlier rule, which gave every county the warnings of every zone the NWS "
        "zone-county correlation lists for it, is still computed (`county_rule` in each county "
        "record, and the state table): it is the comparison below and the base of the "
        f"whole-county diagnostic. Its school-weighted mean was {result.county_rule_mean:.4f} "
        "weighted days per school year.",
        "",
        "## Codes and weights",
        "",
        "| Code | Event | Group | Weight | Note |",
        "|---|---|---|---|---|",
    ]
    lines.extend(f"| {c.code} | {c.name} | {c.group} | {c.weight:g} | {c.note} |" for c in CODES)
    lines += [
        "",
        "The weights are the project's judgment, set to follow the owner's instruction "
        "(2026-09-26) to weigh the places whose weather closes schools far above those "
        "where it rarely does; no official source gives a closure rate per warning. 1.0: "
        "the warnings that most often close schools across an area (winter storm, blizzard, "
        "ice storm, lake-effect snow, hurricane). 0.5: warnings that close schools in some "
        "districts only (extreme cold and wind chill, tropical storm). 0.25: the Winter "
        "Weather Advisory, more often a delay. 0.1: the Flash Flood Warning, short and "
        "partial-county. A day counts once, at its heaviest code.",
        "",
        f"Codes counted beyond the instructions' list: {', '.join(sorted(ADDED_CODES))}. The "
        "NWS issues the Lake Effect Snow Warning instead of a Winter Storm Warning for "
        "lake-effect snow, and folded the Freezing Rain and Lake Effect Snow Advisories into "
        "the Winter Weather Advisory during the period. The state table gives the winter days "
        "with and without them (`winter` and `listed winter`).",
        "",
        "## School days and the 6 AM rule",
        "",
        "School days are the weekdays from 15 August to 15 June (holidays are not removed). "
        f"A day counts for a code when a row of that code reaching the school was in effect at "
        f"{DECISION_TIME:%H:%M} local time, or its product had been issued by then for a start "
        f"after {DECISION_TIME:%H:%M} and before {SCHOOL_DAY_END:%H:%M} that day and had not "
        f"been withdrawn by {DECISION_TIME:%H:%M}. Local time is the school's own: its "
        "zone's time zone in z_18mr25; where the NWS marks the zone as crossed by a time zone "
        "line (a two-letter code; it does not draw the line), the county's zones, and the day "
        "counts if the rule holds in either. Spans are those IEM finally recorded "
        "(cancellations and upgrades end them; a begin time a later product moved is read "
        "where it ended up). A row withdrawn (cancelled or upgraded) before it began is kept: "
        "IEM records it ending at the withdrawal, before its begin time, and it counts for its "
        "day when it was still standing at 6 AM; the table below gives how many such rows each "
        "school year has.",
        "",
        *_zone_polygon_lines(result),
        "",
        *_placement_lines(result),
        "",
        *_storm_lines(result),
        "",
        "## Sources",
        "",
        "- NWS VTEC events: the Iowa Environmental Mesonet archive, one CSV per school year "
        f"from `{WATCHWARN_URL}` (`accept=csv`, the closure-type codes, the contiguous "
        "states and DC, rows beginning 1 August to 17 June). URLs, retrieval times and SHA-256 "
        "sums of every file are in `manifest.json`.",
        "- Zone polygons: the NWS public zone releases still served "
        f"({', '.join(f'`{r.url}`' for r in zonepolys.ZONE_RELEASES)}, MD5 as "
        f"{zonepolys.PUBLIC_ZONES_PAGE} lists it), and IEM's full-resolution copies of the "
        f"zones no served release holds (`{WATCHWARN_URL}` with `simple=0`).",
        "- Storm-based polygons: IEM, one shapefile per school year (`accept=shapefile`, FF.W, "
        "`addsvs=1`).",
        "- Zone to county (the county rule): the NWS zone-county correlation files "
        f"(`{zones.RELEASE_BASE}bpDDmmYY.dbx`, page {zones.ZONE_COUNTY_PAGE}). The page links "
        "only the two newest; every older release still served was found by requesting "
        "`bpDDmmYY.dbx` for every date from 2013-01-01 to 2026-09-26 (HEAD, 2026-09-26): "
        + ", ".join(
            f"{r.name} ({r.valid_from.isoformat()}, {len(r.counties)} zones)"
            for r in counted.releases
        )
        + ". None is served for a date before 2019-04-02.",
        f"- Counties, states and time zones: the NWS county file `{zones.COUNTY_RELEASE.url}`.",
        "- Schools: the school directory (`pipeline/out/internal/directory/schools.parquet`).",
        "",
        *_results_lines(result, counted),
        "",
        *_station_lines(),
        "",
        "## The county rule (kept for comparison and the whole-county diagnostic)",
        "",
        "Everything in this part describes the earlier rule, which the per-school metric "
        "replaced; its numbers are `county_rule` in the county records and the county-rule "
        "columns of the state table.",
        "",
        "### Zone to county",
        "",
        "A zone row counts for every county the correlation release in effect on its "
        "product's issue date lists for it; a county row names its county directly. Rows by "
        f"how they were mapped (of {total_rows} county/zone rows):",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(rows_by.items()))
    lines += [
        "",
        "`before_first`: products issued before the first release served (2 April 2019), read "
        "in that release; `nearest`: a zone missing from the release in effect, read in the "
        "nearest release that has it; `left_out_renamed`: a zone read in the first release "
        "before it took effect whose name then disagreed with its name there, left out for "
        "that school year; `unmapped`: a zone in no release served, left out. "
        f"Unmapped zones ({len(unmapped)}): "
        + ", ".join(f"{k} ({v} rows)" for k, v in list(unmapped.items())[:30])
        + ". County FIPS codes a release lists that the county file does not have (the rows "
        "never reach a county; the county-years they leave incomplete are left out, below): "
        + (
            ", ".join(
                f"{k} ({v} rows)" for k, v in _dict(mapping["counties_not_in_county_list"]).items()
            )
            or "none"
        )
        + ". Records whose county name contradicts their FIPS code (kept as published; the "
        "FIPS code decides): "
        + (
            "; ".join(
                f"{_dict(c)['ugc']} names {_dict(c)['county_as_written']} with "
                f"{_dict(c)['fips']} ({_dict(c)['county_of_fips']}) in "
                f"{len(_list(_dict(c)['releases']))} releases, "
                f"{_list(_dict(c)['releases'])[0]} to {_list(_dict(c)['releases'])[-1]}"
                for c in _list(mapping.get("county_name_conflicts"))
            )
            or "none"
        )
        + ". Records whose STATE_ZONE disagrees with STATE and ZONE (kept under STATE and ZONE): "
        + (
            "; ".join(
                f"{k}: {', '.join(str(z) for z in _list(v))}"
                for k, v in _dict(mapping["state_zone_mismatches"]).items()
            )
            or "none"
        )
        + ".",
        "",
        "Zone names of the rows read in the first release, against IEM's UGC database for "
        "the school year:",
        "",
    ]
    lines.extend(_name_lines(checks))
    lines += ["", "#### Against IEM's archived zone outlines", ""]
    lines.extend(_outline_lines(_dict(checks.get("zone_outlines")), result))
    tropical = [
        (label, _dict(entry))
        for label, entry in _dict(_dict(checks["rows"])["school_years"]).items()
    ]
    ended = [_dict(row) for _, entry in tropical for row in _list(entry.get("tropical_rows_ended"))]
    lines += [
        "",
        "### Rows",
        "",
        "Tropical Storm and Hurricane Warnings are issued until further notice; IEM stores "
        "a placeholder expiry for such a row. Rows no product ended were ended when the last "
        f"explicitly ended row of their event ended ({len(ended)} rows):",
        "",
    ]
    lines.extend(
        f"- {row['event']} {row['ugc']} ({row['status']}): recorded until "
        f"{row['recorded_end']}, ended {row['end'] or 'as recorded (no ended row)'}"
        for row in ended
    )
    lines += [
        "",
        "Rows: every row of the school-year file; kept: the county and zone rows of the "
        "contiguous states and DC (polygon rows and other areas are skipped); withdrawn "
        "before start: kept rows cancelled or upgraded before they began.",
        "",
        "| School year | Rows | Kept | Withdrawn before start | Longest row (days) | By code |",
        "|---|---|---|---|---|---|",
    ]
    for label, entry in tropical:
        codes = ", ".join(f"{k} {v}" for k, v in _dict(entry["by_code"]).items())
        lines.append(
            f"| {label} | {entry['rows']} | {entry['kept']} | {entry['ended_before_start']} "
            f"| {entry['longest_row_days']} | {codes} |"
        )
    lines += ["", "#### Codes replaced during the period", ""]
    lines.extend(_change_lines(_dict(checks.get("code_changes"))))
    placed = _dict(_dict(checks["schools"])["placed_by"])
    lines += [
        "",
        "### Schools in counties",
        "",
        "Each school takes its directory county when the NWS uses that code, else the NWS "
        "county its coordinates fall in (Connecticut's planning regions), else the nearest "
        f"county of its state within {0.05} degrees: "
        + ", ".join(f"{k} {v}" for k, v in placed.items())
        + f"; unplaced {len(_list(_dict(checks['schools'])['unplaced']))}; schools whose "
        f"directory county differs from the county their point falls in: "
        f"{_dict(checks['schools'])['fips_point_disagreements']}. County-coded products "
        "reach a school through this county.",
        "",
        *_address_lines(_list(_dict(checks["schools"]).get("address_state_elsewhere"))),
    ]
    whole_rows = sorted(
        result.states, key=lambda row: (-float(str(row["whole_county_weight"])), str(row["state"]))
    )
    lines += [
        "",
        "### Diagnostic: whole-county days only",
        "",
        "Counting only the days an event covered every zone of a county (or the county "
        "itself), normalized the same way (school-weighted mean "
        f"{result.whole_mean_days:.4f} days). It shows how much of the county rule's ranking "
        "its partial-county days carried. Top 10 and bottom 10:",
        "",
        "| State | Whole-county weight | Weight (metric) | Rank (metric) "
        "| County-rule weight | Partial-county share of county-rule days |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['state']} | {_f(row['whole_county_weight'])} | {_f(row['weight'])} "
        f"| {row['rank']} | {_f(row['county_rule_weight'])} | {_pct(row['partial_day_share'])} |"
        for row in [*whole_rows[:10], *whole_rows[-10:]]
    )
    recount = _dict(checks.get("school_recount"))
    lines += [
        "",
        "## Cross-checks",
        "",
        f"Per school: {recount.get('agree', 0)} of {recount.get('schools', 0)} schools (the "
        "first school of each state by NCES id, every school placed in its nearest zone, and "
        f"the {recount.get('school_year_rule_schools', 0)} schools with a school year logged "
        "above) recounted directly, row by row, without the cells the count groups schools "
        "into, re-applying the school-year rule from the rows of each school's own zone: the "
        "same weighted days to within 1e-9, and the same versions taken in the same school "
        "years. The recounts are in `manifest.json` (`school_recount`).",
        "",
        "Against the existing day-file client (`IemArchive`), county days under the county rule:",
        "",
    ]
    lines.extend(_day_file_lines(checks) or ["- not run"])
    lines += [
        "",
        f"Counties compared: {', '.join(crosscheck.CHECK_COUNTIES)}.",
        "",
        "## Limits",
        "",
        "- A school's zone is decided by its NCES point; a point that is off (a district "
        "office's address, a rounded coordinate) puts the school in the zone of that point.",
        "- The zone polygons of versions no served NWS release holds are IEM's copies of the "
        "NWS polygons (checked against the rows' own areas, not against an NWS file). A "
        "served polygon stands for a version when their areas agree to within 1e-6; a redraw "
        "that kept a zone's area to that precision would go unseen.",
        "- Whether a school is inside a zone, near one or neither is decided in z_18mr25; a "
        "shoreline an older release drew differently can leave a shore school outside an "
        "older version's polygon.",
        "- A school in a zone the NWS marks as crossed by a time zone line counts a day when "
        "the 6 AM rule holds in either zone.",
        "- School years before 2 April 2019 are read with the zone polygon each row was issued "
        "for, which the county rule could not do; the name and outline checks in the county "
        "rule's part apply to the county rule only.",
        "- Under the county rule, counties with school years left out are averaged over fewer "
        f"years (as few as {fewest} of {len(years)}); a school that falls back to its county "
        "(see where each school is) inherits that.",
        "- Holidays are not removed from school days; a district's own calendar is unknown.",
        "- The weights are judgment, not a measured closure rate.",
        "",
    ]
    return "\n".join(lines)


def _every_lines(baseline: Mapping[str, JSONValue]) -> list[str]:
    groups = _dict(baseline.get("working_stations_by_group"))
    every = _dict(baseline.get("every_working_source"))
    if not every:
        return []
    others = {k: v for k, v in groups.items() if k not in {"gray", "hearst"}}
    return [
        "Working stations in the coverage file, by group: "
        + (", ".join(f"{k} {v}" for k, v in groups.items()) or "none")
        + ". "
        + (
            "Groups beyond Gray and Hearst already have working scrapers ("
            + ", ".join(sorted(others))
            + "); the ranking still measures each family beyond Gray and Hearst, as asked, "
            if others
            else "Only Gray and Hearst have working scrapers; "
        )
        + f"and every working source together covers {every['schools']} schools "
        f"({_pct(every['share'])}), {every['weighted_schools']} weighted "
        f"({_pct(every['weighted_share'])}), in {every['counties']} counties. `Rank: beyond "
        "every working source` orders the families by what they add beyond all of them.",
        "",
    ]


def _cautions(families: Sequence[Mapping[str, JSONValue]]) -> list[str]:
    lines = []
    for family in families:
        alone = float(str(_dict(family["standalone"])["new_weighted_schools"]))
        fresh = _dict(family["standalone_without_stale_members"])
        stale = int(str(fresh["stale_members"]))
        kept = float(str(fresh["new_weighted_schools"]))
        if stale and alone > 0:
            lines.append(
                f"- {family['name']} (rank {family['rank']}): {stale} of its lists say they were "
                f"last updated before {STALE_BEFORE}; without them it adds {kept:.1f} weighted "
                f"schools alone instead of {alone:.1f}, and ranks "
                f"{family['rank_without_stale_members']}."
            )
    return lines


def priority_note(document: Mapping[str, JSONValue]) -> str:
    """Return the station priority note."""
    baseline = _dict(document["baseline"])
    lines = [
        "# Station priority: which scraper family next",
        "",
        f"Generated {document['generated_at']}. Internal; never published.",
        "",
        "Every first-hand record with a closings list counts, including lists whose file "
        "robots.txt disallows (the owner decided on 2026-09-26 to read those too) and lists "
        "that are known (by address, frame or lead) but were not read because robots.txt "
        "disallows them, could not be read, or the host could not be reached; each member "
        "says why it counts (`counted_because` in the JSON). A record's "
        "counties are its market's counties in the DMA crosswalk the station registry uses; "
        "every figure is an upper bound, since a station rarely lists its whole market. "
        "`Weighted` schools are the sum of the schools' own closure weights (each school in "
        "its own forecast zone; national mean 1 per school). Members whose own page said it "
        "was last updated before "
        f"{STALE_BEFORE} are marked: they count, as the rule says, but have not listed a "
        "closing since.",
        "",
        f"Already covered by working Gray and Hearst sources: {baseline['schools']} schools "
        f"({_pct(baseline['share'])}), {baseline['weighted_schools']} weighted "
        f"({_pct(baseline['weighted_share'])}), in {baseline['counties']} counties. Of "
        f"{document['schools']} schools, {document['weighted_schools']} weighted.",
        "",
        *_every_lines(baseline),
        "",
        "Order: each step takes the family adding the most weighted schools not yet covered "
        "by Gray, Hearst or the families before it. `Alone` is the family's gain over Gray and "
        "Hearst by itself. The rank columns give the family's place in the same greedy "
        "order without the stale lists, under the whole-county diagnostic weights (see the "
        "method note), with every school counted as 1, and beyond every working source in "
        "the coverage file (not only Gray and Hearst); the last column is the family's "
        "weighted gain alone beyond every working source.",
        "",
        "| Rank | Family | Sources (robots-blocked) | New weighted schools | New schools "
        "| Alone: weighted | Alone: schools | Alone without stale lists: weighted "
        "| Cumulative share (weighted) | Rank: without stale lists "
        "| Rank: whole-county weights | Rank: unweighted "
        "| Rank: beyond every working source | Alone beyond every working source: weighted |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    families = [_dict(item) for item in _list(document["families"])]
    cautions = _cautions(families)
    for family in families:
        order, alone = _dict(family["in_order"]), _dict(family["standalone"])
        fresh = _dict(family["standalone_without_stale_members"])
        lines.append(
            f"| {family['rank']} | {family['name']} | {family['sources']} "
            f"({family['sources_robots_blocked']}) | {order['new_weighted_schools']} "
            f"| {order['new_schools']} | {alone['new_weighted_schools']} "
            f"| {alone['new_schools']} | {fresh['new_weighted_schools']} "
            f"({fresh['stale_members']} stale) | {_pct(order['cumulative_share'])} "
            f"({_pct(order['cumulative_weighted_share'])}) "
            f"| {family['rank_without_stale_members']} "
            f"| {family['rank_with_whole_county_weights']} "
            f"| {family['rank_by_schools_unweighted']} "
            f"| {family['rank_beyond_every_working_source']} "
            f"| {_dict(family['standalone_beyond_every_working_source'])['new_weighted_schools']} |"
        )
    lines += ["", "## Read with the ranking", ""]
    lines.extend(cautions)
    lines += [
        "- The weights count a whole county whenever any of its zones is under a warning, as "
        "the correlation rule requires, which lifts counties whose mountains get warnings their "
        "valley schools do not (much of the West, California included). The whole-county "
        "column shows the order without those partial-county days (method.md explains it).",
        "- Market counties are an upper bound: two stations of one market count as covering "
        "the same counties, so a family whose markets are already taken adds nothing here even "
        "when its lists name other schools.",
    ]
    lines += ["", "## Members", ""]
    for family in families:
        lines.append(f"### {family['rank']}. {family['name']}")
        lines.append("")
        for member in _list(family["members"]):
            item = _dict(member)
            blocked = ", robots-blocked" if item["robots_blocked"] else ""
            if item.get("stale_since"):
                blocked += f", page last updated {item['stale_since']}"
            markets = "; ".join(str(m) for m in _list(item["markets"]))
            lines.append(
                f"- {item['name']} ({item['group']}, `{item['variant']}`{blocked}): "
                f"{markets} [{item['basis']}, {item['found_by']}], {item['counties']} counties"
            )
        lines.append("")
    records = _dict(document["records"])
    lines += [
        "## Records left out",
        "",
        f"{records['counted']} records counted, {records['left_out']} left out:",
        "",
    ]
    for reason, names in _dict(records["left_out_by_reason"]).items():
        members = _list(names)
        lines.append(f"- {reason} ({len(members)}): {', '.join(str(n) for n in members)}")
    gray = records.get("left_out_as_gray_checked_in_registry")
    lines += ["", "Records left out as Gray's, checked against the station registry:", ""]
    if isinstance(gray, list):
        for entry in gray:
            item = _dict(entry)
            if item["registry_station"] is None:
                lines.append(f"- {item['name']}: not in the registry ({item['reason']})")
            else:
                platform = item.get("registry_platform")
                elsewhere = "" if platform == "gray" else f", filed under {platform}"
                lines.append(
                    f"- {item['name']}: {item['registry_station']} ({item['registry_status']}, "
                    f"{item['registry_counties']} counties{elsewhere}), found by "
                    f"{item['found_by']}"
                )
        lines += _gray_gap_lines(gray)
    else:
        lines.append(f"- {gray}")
    lines += ["", *_market_check_lines(document.get("market_counties_checked_in_registry")), ""]
    return "\n".join(lines)


def _gray_gap_lines(gray: Sequence[JSONValue]) -> list[str]:
    """Name the records left out as Gray's that no active Gray registry entry reads."""
    gaps = [
        str(item["name"])
        for item in map(_dict, gray)
        if item["registry_platform"] != "gray" or item["registry_status"] != "active"
    ]
    if not gaps:
        return []
    return [
        "",
        f"{len(gaps)} of these {len(gray)} have no active Gray entry in the registry "
        f"({', '.join(gaps)}): no adapter reads their lists yet, and they are in no family "
        "above, so their markets count as covered only where a working source in the "
        "coverage file already lists them. They are the Gray adapter's to add.",
    ]


def _market_check_lines(check: JSONValue) -> list[str]:
    """Describe the check of the registry's DMA-based county lists against the crosswalk."""
    lines = ["Market counties checked against the station registry:", ""]
    if not isinstance(check, dict):
        return [*lines, f"- {check}"]
    differing = _list(check["differing"])
    lines.append(
        f"- {check['agreeing']} of {check['stations_with_dma_county_lists']} DMA-based county "
        "lists in the registry hold exactly the market's counties as read here."
    )
    for entry in differing:
        item = _dict(entry)
        where = "" if item["in_crosswalk"] else " (market not in the crosswalk read here)"
        lines.append(
            f"- {item['station']}: {item['dma']}{where}: {item['registry_counties']} listed, "
            f"{item['market_counties']} in the market; only in the registry: "
            f"{', '.join(str(c) for c in _list(item['only_in_registry'])) or 'none'}; only in "
            f"the market: {', '.join(str(c) for c in _list(item['only_in_market'])) or 'none'}"
        )
    return lines
