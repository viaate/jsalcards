"""Regenerate ``tests/weather/fixtures/``: verbatim slices of real cached source files.

Run from ``pipeline/`` once the weather cache holds the sources (``snowlight
alerts live`` fills most of it; this script fetches the rest through the same
cache) and the NCES cache holds the directory sources (``snowlight directory
build``)::

    uv run python tests/weather/make_fixtures.py [--only PART ...] [ACTIVE_SNAPSHOT]

``ACTIVE_SNAPSHOT`` defaults to the cached ``/alerts/active`` response; the
alerts listed in :data:`ALERTS` must be in it. ``--only`` (repeatable) rewrites
only the named parts (``alerts``, ``types``, ``pages``, ``boundaries``,
``archive``, ``schools``) and keeps the other entries of ``provenance.json``.
What is written, and how:

* ``active.geojson``: the response's ``type``, ``title`` and ``updated`` with
  only the features listed below, each copied unchanged. Every feature can be
  re-read at ``https://api.weather.gov/alerts/<id>`` while the NWS keeps it.
* ``alert-types.json``: the ``/alerts/types`` response, unchanged.
* ``<page>.table.html``: the release table of each NWS boundary page, cut from
  ``<table`` to ``</table>`` unchanged.
* ``z_*.zip`` / ``c_*.zip``, ``iem-<date>.zip`` and ``iem-full-<date>.zip``:
  shapefiles holding only the records named below (``iem-no-rows.zip`` holds
  none). Each ``.shp`` record (header and content) and each ``.dbf`` record is
  copied byte for byte in the original order; only the file length in the
  ``.shp`` header and the record count in the ``.dbf`` header are rewritten to
  match. ``.prj`` and ``.cpg`` members are copied unchanged. ``iem-full-*``
  comes from the same IEM request as ``iem-*`` with ``simple=0`` (IEM's
  full-resolution boundaries instead of its simplified outlines), as evidence
  for the simplified-outline tolerance.
* ``iem-range-<office>-<code>-<first>_<end>.zip``: range files (one office and
  code over whole months), sliced the same way to the rows named below.
* ``iem-snapshot-<time>.json``: IEM ``events_status`` responses holding only
  the rows of the events named below, each row object unchanged (keys, order
  and values) and re-serialised compactly as the service writes it;
  ``iem-snapshot-no-events.json`` keeps the ``schema`` member and no rows.
* ``nces-schools.json``: the rows of the named schools from the NCES EDGE
  geocode files the school directory is built from: the public-school text
  line verbatim (named by the header of the workbook in the same zip), and the
  private-school workbook row as the cell texts Excel stored.

``provenance.json`` records, for every fixture, the source URL, the SHA-256 of
the source file, when it was retrieved, and exactly what was kept.
"""

import argparse
import json
import re
import struct
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from snowlight.sources.nces.readers import read_member
from snowlight.sources.nces.xlsx import iter_rows, read_header
from snowlight.sources.nws.boundaries import PAGES, BoundaryCatalog, BoundaryKind
from snowlight.sources.nws.http import CachedFile, HttpCache, make_client, sha256_file
from snowlight.sources.nws.iem import ArchiveRow, day_url, read_day_file, snapshot_url
from snowlight.sources.nws.shapefile import read_zip
from snowlight.weather.build import DEFAULT_CACHE_DIR, PIPELINE_ROOT, archive_codes, make_archive
from snowlight.weather.hazards import CONUS_STATES

OUT = Path(__file__).resolve().parent / "fixtures"
ACTIVE = DEFAULT_CACHE_DIR / "api.weather.gov" / "alerts" / "active.geojson"
TYPES_URL = "https://api.weather.gov/alerts/types"
NCES_CACHE = PIPELINE_ROOT / ".cache" / "nces" / "nces.ed.gov" / "programs" / "edge" / "data"

# Alert id suffixes (the full ids are recorded in provenance.json) and why each is here.
ALERTS = {
    "cdcc597e.001.1": "kept: Flash Flood Warning with its own polygon and two county zones",
    "3f83cf451.001.1": "kept: Flood Warning polygon with no end time (until further notice)",
    "dcf4fb.002.1": "kept: Coastal Flood Warning on one forecast zone",
    "b6ecb8.005.1": "kept: Coastal Flood Watch that begins after the feed time",
    "076716.006.1": "kept: Coastal Flood Advisory for the District of Columbia",
    "ac297d.001.1": "kept: High Wind Watch on three forecast zones",
    "6c22f7.001.1": "kept: Flood Watch across Oklahoma and Texas zones",
    "fdfd15f47.001.1": "dropped: Air Quality Alert is not on the allowlist",
    "8c715cca.003.2": "dropped: Red Flag Warning (fire weather zones) is not on the allowlist",
    "d26fe4b5.001.1": "dropped: Special Weather Statement is not on the allowlist",
    "65f9328cf.017.1": "dropped: Tropical Storm Watch for Hawaii is outside the contiguous states",
    "c0766c.001.1": "dropped: Flood Watch for Alaska is outside the contiguous states",
}

# Boundary records to keep, by UGC, and why.
ZONES_16AP26 = {
    "NCZ204": "Coastal Flood Warning zone",
    "NYZ074": "Coastal Flood Watch zone",
    "DCZ001": "District of Columbia",
    "MTZ302": "High Wind Watch zone",
    "MTZ303": "High Wind Watch zone",
    "MTZ308": "High Wind Watch zone",
    "OKZ001": "Flood Watch zone",
    "OKZ002": "Flood Watch zone",
    "TXZ001": "Flood Watch zone",
    "TXZ002": "Flood Watch zone",
    "TXZ006": "Flood Watch zone",
    "AZZ010": "time zone M (Navajo Nation) inside a county coded Mm",
    "AZZ014": "time zone Mm",
    "CTZ002": "Connecticut zone for a place whose county code is a planning region",
    "FLZ014": "one UGC stored as two records",
}
# The Flood Warning's counties (FLC017, FLC075, FLC083) are left out on purpose:
# their coastlines take 400 KB, and the tests use that alert's own polygon.
COUNTIES_16AP26 = {
    "NMC009": "Flash Flood Warning county",
    "NMC041": "Flash Flood Warning county",
    "AZC001": "time zone Mm (Apache County)",
    "CTC003": "Connecticut county (NWS keeps the pre-2022 counties)",
    "FLC045": "time zone CE, stored as two records",
}
ZONES_18MR25 = {
    "MEZ008": "Winter Storm Warning zone, 2026-01-26",
    "MEZ009": "Winter Storm Warning zone, 2026-01-26",
    "MEZ013": "Winter Storm Warning zone, 2026-01-26",
    "MEZ002": "Winter Storm Watch zone upgraded before it began, 2026-01-26",
    "LAZ077": "Orleans zone, 2025-01-21 (before this release: only a hint then)",
    "LAZ078": "zone east of Orleans, 2025-01-21 (hint)",
    "TXZ313": "Baytown's zone, 2025-01-21 (hint)",
    "TXZ231": "zone whose simplified 2025-01-21 outline dropped a sliver (hint)",
    "VTZ006": "Lamoille zone of the Winter Storm Warning numbered in 2024, 2025-01-01 (hint)",
}
COUNTIES_18MR25 = {
    "ALC063": "river Flood Warning county whose polygon does not cover the whole county",
    "ALC107": "river Flood Warning county",
    "ALC119": "river Flood Warning county",
    "KYC013": "Flood Advisory county",
    "FLC019": "county of a river flood warning cancelled before it began, 2025-01-21",
    "IAC001": "county of the 2024-05-21 Tornado Warning",
    "IAC029": "county of the 2024-05-21 Tornado Warning",
    "IAC089": "Howard County: Tornado Watch county of 2024-05-21 (Riceville's schools)",
    "IAC065": "Fayette County: Tornado Watch county of 2024-05-21",
    "IAC019": "Buchanan County: not in that watch segment (Fairbank Elementary's county)",
    "TXC071": "Chambers County, TX: time zone of the round 3 point (HGX river Flood Warning 52)",
    "TXC245": "Jefferson County, TX: time zone of the Beaumont schools (LCH Flood Warning 55)",
    "TXC351": "Newton County, TX: time zone of Deweyville (LCH Flood Warning 35)",
    "ILC013": "Calhoun County, IL: time zone of Hardin (LSX Flood Warning 47)",
    "VTC015": "Lamoille County, VT: time zone of Hyde Park (BTV Winter Storm Warning 10)",
}

# IEM day files: the events kept from each, the UGCs kept (None: every row), and why.
type EventSlice = dict[str, tuple[frozenset[str] | None, str]]
IEM_DAYS: dict[date, EventSlice] = {
    date(2025, 1, 21): {
        "LIX.CW.Y.0005.2025": (None, "Cold Weather Advisory for Orleans, before any NWS release"),
        "LIX.WS.A.0001.2025": (None, "Winter Storm Watch upgraded before it began"),
        "JAX.FL.W.0001.2025": (None, "river Flood Warning cancelled before its begin time"),
        "LIX.WS.W.0001.2025": (
            frozenset({"LAZ077", "LAZ078"}),
            "Winter Storm Warning: Orleans and the zone east of it (a shared edge)",
        ),
        "HGX.WS.W.0001.2025": (frozenset({"TXZ313"}), "Winter Storm Warning, Baytown's zone"),
        "HGX.CW.Y.0004.2025": (frozenset({"TXZ313"}), "Cold Weather Advisory, Baytown's zone"),
        "CRP.WS.W.0001.2025": (
            frozenset({"TXZ231"}),
            "Winter Storm Warning on a zone whose simplified outline dropped a sliver",
        ),
    },
    date(2025, 1, 22): {
        "LIX.EC.W.0001.2025": (
            frozenset({"LAZ077", "LAZ078"}),
            "Extreme Cold Warning, Orleans and the zone east of it",
        ),
        "HGX.EC.W.0001.2025": (frozenset({"TXZ313"}), "Extreme Cold Warning, Baytown's zone"),
    },
    date(2026, 1, 26): {
        "GYX.WS.W.0001.2026": (None, "zone-based Winter Storm Warning"),
        "CAR.WS.A.0002.2026": (None, "Winter Storm Watch upgraded before it began"),
        "BMX.FL.W.0001.2026": (None, "river Flood Warning: polygon versions and county rows"),
        "JKL.FA.Y.0001.2026": (None, "areal Flood Advisory polygon"),
    },
    date(2024, 5, 21): {
        "DMX.TO.W.0034.2024": (None, "Tornado Warning with four polygon versions"),
        "ARX.TO.A.0277.2024": (
            frozenset({"IAC089", "IAC065"}),
            "county-based Tornado Watch: Howard and Fayette counties",
        ),
    },
}
# The same rows at full resolution (``simple=0``), as evidence for the outline tolerance.
IEM_FULL_DAYS: dict[date, EventSlice] = {
    date(2025, 1, 21): {
        "LIX.WS.W.0001.2025": (frozenset({"LAZ077", "LAZ078"}), "Orleans and east, full"),
        "HGX.WS.W.0001.2025": (frozenset({"TXZ313"}), "Baytown's zone, full"),
        "CRP.WS.W.0001.2025": (frozenset({"TXZ231"}), "the zone with the dropped sliver, full"),
    },
}

# IEM snapshots (events_status): the events whose rows are kept, and why.
SNAPSHOTS: dict[datetime, dict[str, str]] = {
    # S0 for local 2024-05-21: midnight after the first day file (2024-04-29).
    datetime(2024, 4, 30, tzinfo=UTC): {
        "HGX.FL.W.0052.2024": "river Flood Warning since 2024-04-29 (Chambers County, TX): carried",
        "LCH.FL.W.0055.2024": "river Flood Warning since 2024-04-27 (Beaumont): carried",
        "LCH.FL.W.0035.2024": "river Flood Warning since 2024-04-10, 41 days before: carried",
        "LSX.FL.W.0047.2024": "river Flood Warning over Hardin, IL: carried",
        "LCH.FL.W.0063.2024": "same office and code, ended 2024-05-09: not carried",
        "CYS.HW.W.0021.2024": "listed twice (two statuses), ended 2024-05-01: not carried",
        "AFC.FA.A.0002.2024": "Flood Watch in Alaska: not carried",
        "ABQ.FW.A.0025.2024": "Fire Weather Watch, not on the allowlist: not carried",
    },
    # New Year's midnight inside the day files of local 2025-01-01.
    datetime(2025, 1, 1, tzinfo=UTC): {
        "BTV.WS.W.0010.2024": "Winter Storm Warning numbered in 2024, from 2025-01-01 06Z: carried",
        "AFG.WW.Y.0149.2024": "Winter Weather Advisory in Alaska: not carried",
        "AFC.SC.Y.1181.2024": "marine Small Craft Advisory, not on the allowlist: not carried",
    },
}
# The snapshot whose schema (and no rows) iem-snapshot-no-events.json keeps.
NO_EVENTS_FROM = datetime(2024, 4, 30, tzinfo=UTC)

# Range files: (office, phenomena, significance, first, end) -> events kept and why.
# Polygon versions are kept when in force during POLYGON_DAYS; county and zone rows always.
type RangeSpec = tuple[str, str, str, date, date]
POLYGON_DAYS = (datetime(2024, 5, 20, tzinfo=UTC), datetime(2024, 5, 24, tzinfo=UTC))
RANGES: dict[RangeSpec, dict[str, str]] = {
    ("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)): {
        "HGX.FL.W.0052.2024": "Trinity River at Wallisville: covers the round 3 point",
    },
    ("LCH", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)): {
        "LCH.FL.W.0055.2024": "Neches River: covers Fletcher El and St Anthony, Beaumont",
        "LCH.FL.W.0035.2024": "Sabine River: covers Deweyville El, 41 days after it began",
    },
    ("LSX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)): {
        "LSX.FL.W.0047.2024": "Illinois River: covers Calhoun High School, Hardin",
    },
    ("BTV", "WS", "W", date(2024, 12, 1), date(2025, 2, 1)): {
        "BTV.WS.W.0010.2024": "numbered in 2024; its rows are missing from the 2025-01-01 day file",
    },
}
# Day files that must not hold an event, recorded as evidence for the ranges above.
ABSENT_FROM_DAY: dict[date, str] = {date(2025, 1, 1): "BTV.WS.W.0010.2024"}

# NCES EDGE geocode rows of the schools the tests place, and why.
PUBLIC_SCHOOLS = {
    "482115002117": "Lee H S, Baytown TX: missed near a simplified outline in round 1",
    "482115012492": "Impact Early College H S, Baytown TX: likewise",
    "220028300858": "Einstein Charter School at Village De L'Est: on the LAZ077/LAZ078 edge",
    "192415001409": "Riceville Elementary, Howard County IA: outside IEM's county outline",
    "192976001693": "Fairbank Elementary, Buchanan County IA: inside IEM's Fayette outline",
    "480967004642": "Fletcher El, Beaumont TX: no row in round 2 (river Flood Warning since April)",
    "171818002089": "Calhoun High School, Hardin IL: likewise",
    "481701001472": "Deweyville El, Orange County TX: under a Flood Warning 41 days old",
    "500039700171": "Lamoille Union High School, Hyde Park VT: warning numbered in 2024",
}
PRIVATE_SCHOOLS = {
    "00541083": "Lake Castle Private School, New Orleans: missed near a simplified outline",
    "01323483": "St Anthony Cathedral Basilica School, Beaumont TX: no row in round 2",
}
PUBLIC_ZIP = "EDGE_GEOCODE_PUBLICSCH_2425"
PRIVATE_ZIP = "EDGE_GEOCODE_PRIVATESCH_2324"


def _records(shp: bytes) -> list[bytes]:
    records, offset = [], 100
    while offset < len(shp):
        _number, words = struct.unpack_from(">ii", shp, offset)
        records.append(shp[offset : offset + 8 + 2 * words])
        offset += 8 + 2 * words
    return records


def slice_shapefile(source: Path, keep: Iterable[int], dest: Path) -> list[int]:
    """Write ``dest`` holding only records ``keep`` of the shapefile zipped at ``source``."""
    wanted = sorted(set(keep))
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        shp_name = next(n for n in names if n.lower().endswith(".shp"))
        dbf_name = next(n for n in names if n.lower().endswith(".dbf"))
        shp, dbf = archive.read(shp_name), archive.read(dbf_name)
        extras = {n: archive.read(n) for n in names if n.lower().endswith((".prj", ".cpg"))}
    records = _records(shp)
    body = b"".join(records[i] for i in wanted)
    header = bytearray(shp[:100])
    struct.pack_into(">i", header, 24, (100 + len(body)) // 2)
    header_len, record_len = struct.unpack_from("<HH", dbf, 8)
    dbf_header = bytearray(dbf[:header_len])
    struct.pack_into("<I", dbf_header, 4, len(wanted))
    rows = b"".join(
        dbf[header_len + i * record_len : header_len + (i + 1) * record_len] for i in wanted
    )
    tail = b"\x1a" if dbf.endswith(b"\x1a") else b""
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = {shp_name: bytes(header) + body, dbf_name: bytes(dbf_header) + rows + tail, **extras}
    with zipfile.ZipFile(dest, "w") as out:
        for name, data in files.items():
            # A fixed timestamp keeps the fixture bytes reproducible.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            out.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return wanted


def _source(file: CachedFile) -> dict[str, object]:
    record = file.provenance
    return {
        "retrieved_at": record.retrieved_at,
        "source_sha256": record.sha256,
        "source_url": record.url,
    }


def _boundary_ugc(kind: BoundaryKind) -> Callable[[Mapping[str, object]], str]:
    def ugc(attrs: Mapping[str, object]) -> str:
        if kind == "zone":
            return f"{attrs['STATE']}Z{attrs['ZONE']}"
        return f"{attrs['STATE']}C{str(attrs['FIPS'])[2:]}"

    return ugc


type Provenance = dict[str, object]


def _alerts(snapshot: Path) -> Provenance:
    document = json.loads(snapshot.read_bytes())
    chosen, reasons = [], {}
    for suffix, why in ALERTS.items():
        matches = [f for f in document["features"] if f["properties"]["id"].endswith(suffix)]
        if len(matches) != 1:
            raise SystemExit(f"alert *{suffix} is not in {snapshot} exactly once")
        chosen.append(matches[0])
        reasons[matches[0]["properties"]["id"]] = why
    out = {k: document[k] for k in ("@context", "type", "title", "updated") if k in document}
    out["features"] = chosen
    (OUT / "active.geojson").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    sidecar = json.loads(Path(str(snapshot) + ".provenance.json").read_text())
    return {
        "active.geojson": {
            "retrieved_at": sidecar["retrieved_at"],
            "selection": "the features with these ids, unchanged, in this order",
            "features": reasons,
            "source_sha256": sha256_file(snapshot),
            "source_url": sidecar["url"],
        }
    }


def _types(cache: HttpCache) -> Provenance:
    types = cache.fetch(TYPES_URL, DEFAULT_CACHE_DIR / "api.weather.gov" / "alerts" / "types.json")
    (OUT / "alert-types.json").write_bytes(types.path.read_bytes())
    return {"alert-types.json": {**_source(types), "selection": "whole response"}}


def _pages(catalog: BoundaryCatalog) -> Provenance:
    provenance: Provenance = {}
    kind: BoundaryKind
    for kind, url in PAGES.items():
        catalog.releases(kind)  # fetches the page into the cache
        page = catalog._pages[kind]
        html = page.path.read_text(encoding="utf-8")
        start = html.index("<table")
        end = html.index("</table>", start) + len("</table>")
        name = f"{url.rsplit('/', 1)[1]}.table.html"
        (OUT / name).write_text(html[start:end] + "\n", encoding="utf-8")
        provenance[name] = {
            **_source(page),
            "selection": f"characters {start}..{end} (the first <table>), unchanged",
        }
    return provenance


BOUNDARY_SLICES: tuple[tuple[BoundaryKind, str, dict[str, str]], ...] = (
    ("zone", "z_16ap26", ZONES_16AP26),
    ("county", "c_16ap26", COUNTIES_16AP26),
    ("zone", "z_18mr25", ZONES_18MR25),
    ("county", "c_18mr25", COUNTIES_18MR25),
)


def _boundaries(catalog: BoundaryCatalog) -> Provenance:
    provenance: Provenance = {}
    for kind, stem, wanted in BOUNDARY_SLICES:
        release = next(r for r in catalog.releases(kind) if r.url.endswith(f"/{stem}.zip"))
        loaded = catalog.load(release)
        ugc = _boundary_ugc(kind)
        records = read_zip(loaded.file.path)
        keep = [r.index for r in records if ugc(r.attributes) in wanted]
        missing = set(wanted) - {ugc(records[i].attributes) for i in keep}
        if missing:
            raise SystemExit(f"{stem} lacks {sorted(missing)}")
        slice_shapefile(loaded.file.path, keep, OUT / f"{stem}.zip")
        provenance[f"{stem}.zip"] = {
            **_source(loaded.file),
            "listed_md5": release.md5,
            "valid_from": release.valid_from.isoformat(),
            "records_kept": {str(i): ugc(records[i].attributes) for i in keep},
            "reasons": wanted,
            "selection": "these records' .shp and .dbf bytes unchanged, original order",
        }
    return provenance


def _kept(rows: list[ArchiveRow], events: EventSlice) -> list[int]:
    keep = []
    for row in rows:
        if row.event_key not in events:
            continue
        ugcs = events[row.event_key][0]
        if ugcs is None or row.ugc in ugcs:
            keep.append(row.index)
    found = {rows[i].event_key for i in keep}
    if found != set(events):
        raise SystemExit(f"missing events {sorted(set(events) - found)}")
    return keep


def _describe(events: EventSlice) -> dict[str, str]:
    return {
        key: why if ugcs is None else f"{why} (rows for {', '.join(sorted(ugcs))} only)"
        for key, (ugcs, why) in events.items()
    }


def _archive_days(cache: HttpCache) -> Provenance:
    provenance: Provenance = {}
    archive = make_archive(cache, DEFAULT_CACHE_DIR)
    for day, events in IEM_DAYS.items():
        loaded_day = archive.day(day)
        rows = read_day_file(loaded_day.file.path)
        keep = _kept(rows, events)
        name = f"iem-{day.isoformat()}.zip"
        slice_shapefile(loaded_day.file.path, keep, OUT / name)
        provenance[name] = {
            **_source(loaded_day.file),
            "rows_kept": keep,
            "events": _describe(events),
            "selection": "the rows of these events (all, or the UGCs named); "
            ".shp and .dbf record bytes unchanged, original order",
        }
    for day, events in IEM_FULL_DAYS.items():
        url = day_url(day, archive_codes(), CONUS_STATES)
        if not url.endswith("&simple=1&addsvs=1"):
            raise SystemExit(f"unexpected archive request {url}")
        full_url = url.replace("&simple=1&", "&simple=0&")
        host = "mesonet.agron.iastate.edu"
        dest = DEFAULT_CACHE_DIR / host / "watchwarn-full" / f"{day:%Y}" / f"{day}.zip"
        file = cache.fetch(full_url, dest)
        rows = read_day_file(file.path)
        keep = _kept(rows, events)
        name = f"iem-full-{day.isoformat()}.zip"
        slice_shapefile(file.path, keep, OUT / name)
        provenance[name] = {
            **_source(file),
            "rows_kept": keep,
            "events": _describe(events),
            "selection": "the rows of these events for the UGCs named, from the same request "
            "as the simplified file with simple=0; record bytes unchanged, original order",
        }
    # A day file cut down to no rows: served by the tests for days they do not examine.
    source_day = archive.day(date(2026, 1, 26))
    slice_shapefile(source_day.file.path, [], OUT / "iem-no-rows.zip")
    provenance["iem-no-rows.zip"] = {
        **_source(source_day.file),
        "rows_kept": [],
        "selection": "headers only (no records); the tests serve it for days they do not "
        "examine, never as a claim that a real day had no alerts",
    }
    provenance.update(_ranges(cache))
    provenance.update(_snapshots(cache))
    return provenance


def range_fixture_name(spec: RangeSpec) -> str:
    """The fixture file name of a range file slice."""
    wfo, phenomena, significance, first, end = spec
    return f"iem-range-{wfo}-{phenomena}.{significance}-{first}_{end}.zip"


def snapshot_fixture_name(at: datetime) -> str:
    """The fixture file name of a snapshot slice."""
    return f"iem-snapshot-{at:%Y-%m-%dT%H%M}Z.json"


def _in_polygon_days(row: ArchiveRow) -> bool:
    begin, end = row.polygon_begin or row.issued, row.polygon_end or row.expired
    return (
        begin is not None and end is not None and begin < POLYGON_DAYS[1] and end > POLYGON_DAYS[0]
    )


def _ranges(cache: HttpCache) -> Provenance:
    provenance: Provenance = {}
    archive = make_archive(cache, DEFAULT_CACHE_DIR)
    for spec, events in RANGES.items():
        source = archive.range(*spec)
        keep = [
            row.index
            for row in source.rows
            if row.event_key in events and (row.gtype == "C" or _in_polygon_days(row))
        ]
        found = {source.rows[i].event_key for i in keep}
        if found != set(events):
            raise SystemExit(f"{source.label} lacks {sorted(set(events) - found)}")
        name = range_fixture_name(spec)
        slice_shapefile(source.file.path, keep, OUT / name)
        provenance[name] = {
            **_source(source.file),
            "rows_kept": keep,
            "events": events,
            "selection": "every county/zone row of these events, and those of their polygon "
            f"versions in force between {POLYGON_DAYS[0]:%Y-%m-%d} and "
            f"{POLYGON_DAYS[1]:%Y-%m-%d}; .shp and .dbf record bytes unchanged, original order",
        }
    for day, key in ABSENT_FROM_DAY.items():
        loaded = archive.day(day)
        if any(row.event_key == key for row in loaded.rows):
            raise SystemExit(f"the {day} day file holds {key}")
        spec = next(spec for spec, events in RANGES.items() if key in events)
        entry = provenance[range_fixture_name(spec)]
        assert isinstance(entry, dict)
        entry["absent_from_day_file"] = {
            **_source(loaded.file),
            "day": day.isoformat(),
            "rows": len(loaded.rows),
            "event": key,
            "note": "the day file of the day the event's rows began holds none of them",
        }
    return provenance


def _snapshot_key(row: Mapping[str, object]) -> str:
    return (
        f"{row['wfo']}.{row['phenomena']}.{row['significance']}."
        f"{int(str(row['eventid'])):04d}.{row['year']}"
    )


def _snapshots(cache: HttpCache) -> Provenance:
    provenance: Provenance = {}
    archive = make_archive(cache, DEFAULT_CACHE_DIR)
    for at, events in SNAPSHOTS.items():
        snapshot = archive.snapshot(at)
        if snapshot.file.provenance.url != snapshot_url(at):
            raise SystemExit(f"unexpected snapshot request {snapshot.file.provenance.url}")
        document = json.loads(snapshot.file.path.read_bytes())
        rows = [row for row in document["data"] if _snapshot_key(row) in events]
        found = {_snapshot_key(row) for row in rows}
        if found != set(events):
            raise SystemExit(f"snapshot {at} lacks {sorted(set(events) - found)}")
        name = snapshot_fixture_name(at)
        sliced = {"schema": document["schema"], "data": rows}
        (OUT / name).write_text(json.dumps(sliced, separators=(",", ":")) + "\n", "utf-8")
        provenance[name] = {
            **_source(snapshot.file),
            "rows_kept": [row["index"] for row in rows],
            "rows_in_source": len(document["data"]),
            "events": events,
            "selection": "the data rows of these events, each object unchanged, and the "
            "schema member; re-serialised compactly",
        }
    source = archive.snapshot(NO_EVENTS_FROM)
    document = json.loads(source.file.path.read_bytes())
    empty = {"schema": document["schema"], "data": []}
    (OUT / "iem-snapshot-no-events.json").write_text(
        json.dumps(empty, separators=(",", ":")) + "\n", "utf-8"
    )
    provenance["iem-snapshot-no-events.json"] = {
        **_source(source.file),
        "rows_kept": [],
        "selection": "the schema member only (no rows); the tests serve it for times they do "
        "not examine, never as a claim that nothing was in effect then",
    }
    return provenance


def _nces_source(stem: str) -> tuple[Path, dict[str, object]]:
    path = NCES_CACHE / f"{stem}.zip"
    sidecar = json.loads(Path(f"{path}.provenance.json").read_text())
    if sha256_file(path) != sidecar["sha256"]:
        raise SystemExit(f"{path} does not match its recorded SHA-256")
    return path, {
        "retrieved_at": sidecar["retrieved_at"],
        "source_sha256": sidecar["sha256"],
        "source_url": sidecar["url"],
    }


def _schools() -> Provenance:
    public_zip, public_source = _nces_source(PUBLIC_ZIP)
    header = read_header(read_member(public_zip, f"{PUBLIC_ZIP}.xlsx"))
    text = read_member(public_zip, f"{PUBLIC_ZIP}.TXT").decode("utf-8")
    schools: list[dict[str, object]] = []
    lines: dict[str, object] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        values = line.split("|")
        if values[0] not in PUBLIC_SCHOOLS:
            continue
        if len(values) != len(header):
            raise SystemExit(f"{PUBLIC_ZIP}.TXT line {number} has {len(values)} fields")
        row = dict(zip(header, values, strict=True))
        schools.append(
            {
                "id": row["NCESSCH"],
                "name": row["NAME"],
                "county_fips": row["CNTY"],
                "lat": row["LAT"],
                "lon": row["LON"],
                "source": f"{PUBLIC_ZIP}.TXT line {number}",
                "why": PUBLIC_SCHOOLS[row["NCESSCH"]],
            }
        )
        lines[str(number)] = line
    private_zip, private_source = _nces_source(PRIVATE_ZIP)
    workbook = read_member(private_zip, f"{PRIVATE_ZIP}.xlsx")
    names = read_header(workbook)
    cells: dict[str, object] = {}
    for number, texts in enumerate(iter_rows(workbook), start=1):
        record: dict[str, str | None] = dict(zip(names, texts, strict=False))
        if number == 1 or record.get("PPIN") not in PRIVATE_SCHOOLS:
            continue
        if not re.fullmatch(r"\d{5}", str(record["CNTY"])):
            raise SystemExit(f"{PRIVATE_ZIP}.xlsx row {number}: CNTY {record['CNTY']!r}")
        schools.append(
            {
                "id": record["PPIN"],
                "name": record["NAME"],
                "county_fips": record["CNTY"],
                "lat": record["LAT"],
                "lon": record["LON"],
                "source": f"{PRIVATE_ZIP}.xlsx row {number}",
                "why": PRIVATE_SCHOOLS[str(record["PPIN"])],
            }
        )
        cells[str(number)] = {k: v for k, v in record.items() if k in names}
    found = {str(school["id"]) for school in schools}
    if found != set(PUBLIC_SCHOOLS) | set(PRIVATE_SCHOOLS):
        raise SystemExit(f"schools not found: {sorted(set(PUBLIC_SCHOOLS) - found)}")
    schools.sort(key=lambda school: str(school["id"]))
    (OUT / "nces-schools.json").write_text(json.dumps(schools, indent=1) + "\n", encoding="utf-8")
    return {
        "nces-schools.json": {
            "sources": {
                f"{PUBLIC_ZIP}.TXT": {**public_source, "lines": lines, "columns": header},
                f"{PRIVATE_ZIP}.xlsx": {**private_source, "rows": cells},
            },
            "selection": "id, name, county code, latitude and longitude of these schools as "
            "the files store them",
        }
    }


PROVENANCE = OUT / "provenance.json"


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("snapshot", nargs="?", type=Path, default=ACTIVE)
    parts = ("alerts", "types", "pages", "boundaries", "archive", "schools")
    parser.add_argument("--only", action="append", choices=parts, help="rewrite only this part")
    args = parser.parse_args(argv)
    chosen = args.only or list(parts)
    OUT.mkdir(parents=True, exist_ok=True)
    provenance: Provenance = {}
    if args.only and PROVENANCE.is_file():
        provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    with HttpCache(make_client()) as cache:
        catalog = BoundaryCatalog(cache, DEFAULT_CACHE_DIR)
        makers: dict[str, Callable[[], Provenance]] = {
            "alerts": lambda: _alerts(args.snapshot),
            "types": lambda: _types(cache),
            "pages": lambda: _pages(catalog),
            "boundaries": lambda: _boundaries(catalog),
            "archive": lambda: _archive_days(cache),
            "schools": _schools,
        }
        for part in parts:
            if part in chosen:
                provenance.update(makers[part]())
    text = json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    PROVENANCE.write_text(text, encoding="utf-8")
    for path in sorted(OUT.iterdir()):
        sys.stdout.write(f"{path.stat().st_size:>9}  {path.name}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
