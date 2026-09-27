"""The method note (``method.md``) and the station priority note (``station-priority.md``).

Both are generated from the build's results so that every number in them is the
one the JSON files hold. They are internal and never published.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from snowlight.output import JSONValue
from snowlight.sources.nws.iem import WATCHWARN_URL
from snowlight.weights import archive, crosscheck, zones
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
        "| Partial-county share |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        subsets = _dict(row["subsets_days_per_year"])
        lines.append(
            f"| {row['rank']} | {row['state']} | {row['schools']} | {_f(row['weight'])} "
            f"| {_f(row['days_per_year'])} | {_f(subsets.get('winter'))} "
            f"| {_f(subsets.get('listed_winter'))} | {_f(row['any_days_per_year'])} "
            f"| {_pct(row['share_of_weighted_closure_days'])} | {_pct(row['partial_day_share'])} |"
        )
    return lines


def _flag_lines(flags: Sequence[Mapping[str, JSONValue]]) -> list[str]:
    lines: list[str] = []
    for flag in flags:
        lines.append(f"- **{flag['state']}** {flag['finding']}. {flag['reason']}")
        for county in _list(flag["counties"]):
            item = _dict(county)
            zones_text = "; ".join(
                f"{_dict(z)['ugc']} {_dict(z)['name']} ({_dict(z)['days']} days, "
                f"{_dict(z)['only']} as the only zone)"
                for z in _list(item.get("top_zones"))
            )
            lines.append(
                f"  - {item['name']} ({item['fips']}, {item['schools']} schools, "
                f"{item['years_counted']} school years counted): "
                f"{_f(item['days_per_year'])} weighted days/yr, "
                f"{_f(item['whole_county_days_per_year'])} on whole-county days; {zones_text}"
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
        (record for record in result.counties.values() if record["school_years_left_out"]),
        key=lambda record: (-int(str(record["schools"])), str(record["fips"])),
    )
    schools = sum(int(str(record["schools"])) for record in counties)
    county_years = sum(len(_dict(record["school_years_left_out"])) for record in counties)
    lines = [
        "#### School years left out of a county's average",
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


def method_note(result: "Result", counted: "Counted", stamp: str) -> str:
    """Return the method note."""
    checks = result.checks
    mapping = _dict(checks["zone_mapping"])
    rows_by = _dict(mapping["rows_by_resolution"])
    total_rows = sum(int(str(v)) for v in rows_by.values())
    unmapped = _dict(mapping["unmapped_ugcs"])
    years = counted.files
    sanity = result.sanity
    lines: list[str] = [
        "# Closure weights: method note",
        "",
        f"Generated {stamp} by `python -m snowlight.weights build`. Internal; never published.",
        "",
        "## What is measured",
        "",
        "For every county of the contiguous states and DC (the 5-digit FIPS codes of the NWS "
        f"county list, {len(counted.counties.counties)} counties): the average number of "
        "distinct school days per school year on which the county was under at least one "
        "closure-type NWS event, each day weighted by the heaviest code in effect, over the "
        f"school years {years[0].label} to {years[-1].label} ({len(years)} years), less any "
        "school year for which zone rows covering the county could not be counted (the "
        "county is then averaged over its other years, `years_counted`; see the section on "
        "school years left out below). `weight` is that average divided by its mean over the "
        f"{result.schools} directory schools (each school takes its county's value), so the "
        f"school-weighted national mean weight is 1. That mean is {result.mean_days:.4f} "
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
        f"A day counts for a code when a row of that code covering the county was in effect at "
        f"{DECISION_TIME:%H:%M} local time, or its product had been issued by then for a start "
        f"after {DECISION_TIME:%H:%M} and before {SCHOOL_DAY_END:%H:%M} that day and had not "
        f"been withdrawn by {DECISION_TIME:%H:%M}. A county split by a time zone line counts "
        "the day if the rule holds in either zone. Spans are those IEM finally recorded "
        "(cancellations and upgrades end them; a begin time a later product moved is read "
        "where it ended up). A row withdrawn (cancelled or upgraded) before it began is kept: "
        "IEM records it ending at the withdrawal, before its begin time, and it counts for its "
        "day when it was still standing at 6 AM; the table below gives how many such rows each "
        "school year has.",
        "",
        "## Sources",
        "",
        "- NWS VTEC events: the Iowa Environmental Mesonet archive, one CSV per school year "
        f"from `{WATCHWARN_URL}` (`accept=csv`, the closure-type codes, the contiguous "
        "states and DC, rows beginning 1 August to 17 June). URLs, retrieval times and SHA-256 "
        "sums are in `manifest.json`.",
        "- Zone to county: the NWS zone-county correlation files "
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
        "## Zone to county",
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
    lines += ["", "### Against IEM's archived zone outlines", ""]
    lines.extend(_outline_lines(_dict(checks.get("zone_outlines")), result))
    tropical = [
        (label, _dict(entry))
        for label, entry in _dict(_dict(checks["rows"])["school_years"]).items()
    ]
    ended = [_dict(row) for _, entry in tropical for row in _list(entry.get("tropical_rows_ended"))]
    lines += [
        "",
        "## Rows",
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
    lines += ["", "### Codes replaced during the period", ""]
    lines.extend(_change_lines(_dict(checks.get("code_changes"))))
    placed = _dict(_dict(checks["schools"])["placed_by"])
    lines += [
        "",
        "## Schools",
        "",
        "Each school takes its directory county when the NWS uses that code, else the NWS "
        "county its coordinates fall in (Connecticut's planning regions), else the nearest "
        f"county of its state within {0.05} degrees: "
        + ", ".join(f"{k} {v}" for k, v in placed.items())
        + f"; unplaced {len(_list(_dict(checks['schools'])['unplaced']))}; schools whose "
        f"directory county differs from the county their point falls in: "
        f"{_dict(checks['schools'])['fips_point_disagreements']}.",
        "",
        *_address_lines(_list(_dict(checks["schools"]).get("address_state_elsewhere"))),
        "",
        "## Results",
        "",
        f"Top {min(10, len(result.states))} states by weight:",
        "",
    ]
    lines.extend(_state_table(result.states[:10]))
    lines += ["", "Bottom 10 states:", ""]
    lines.extend(_state_table(result.states[-10:]))
    whole_rows = sorted(
        result.states, key=lambda row: (-float(str(row["whole_county_weight"])), str(row["state"]))
    )
    lines += [
        "",
        "`Partial-county share`: the part of the state's school-weighted closure-days that "
        "came from days when the covering zones were only some of the county's zones.",
        "",
        "Schools in counties averaged over fewer school years (incomplete years left out; "
        "see the section on them), by state: "
        + (
            ", ".join(
                f"{row['state']} {row['schools_in_counties_with_school_years_left_out']} of "
                f"{row['schools']}"
                for row in sorted(
                    result.states,
                    key=lambda r: -int(str(r["schools_in_counties_with_school_years_left_out"])),
                )
                if row["schools_in_counties_with_school_years_left_out"]
            )
            or "none"
        )
        + ".",
        "",
        "### Diagnostic: whole-county days only",
        "",
        "Counting only the days an event covered every zone of a county (or the county "
        "itself), normalized the same way (school-weighted mean "
        f"{result.whole_mean_days:.4f} days). This is not the metric; it shows how much of "
        "the ranking the correlation rule's partial-county days carry. Top 10 and bottom 10:",
        "",
        "| State | Whole-county weight | Weight (metric) | Rank (metric) |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['state']} | {_f(row['whole_county_weight'])} | {_f(row['weight'])} "
        f"| {row['rank']} |"
        for row in [*whole_rows[:10], *whole_rows[-10:]]
    )
    lines += [
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
    lines += ["", "## Cross-checks", "", "Against the existing day-file client (`IemArchive`):", ""]
    lines.extend(_day_file_lines(checks) or ["- not run"])
    lines += [
        "",
        f"Counties compared: {', '.join(crosscheck.CHECK_COUNTIES)}.",
        "",
        "## Limits",
        "",
        "- A zone that touches a county counts for all of it, as the correlation rule "
        "requires; where a county holds mountains and valleys, warnings for the mountains "
        "count for the valley schools too (see the partial-county share and the flags).",
        "- Zones before 2 April 2019 are read in the first served release; the name check "
        "and IEM's archived outlines test whether they changed. Rows of zones in no served "
        "release (reconfigured before it) are left out, and so are the school years they "
        "leave incomplete in the counties their outlines covered: those counties are "
        "averaged over fewer years (as few as "
        f"{min((int(str(r['years_counted'])) for r in result.counties.values()), default=0)} "
        f"of {len(years)}), so a single mild or severe year weighs more in them.",
        "- The correlation files have quirks of their own, kept as published: some zones "
        "named for a county list only the independent cities inside it (see the outline "
        "check), and a record can name one county with another's FIPS code (see Zone to "
        "county).",
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
        "`Weighted` schools are schools times their county's closure weight (national mean "
        "1 per school). Members whose own page said it was last updated before "
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
