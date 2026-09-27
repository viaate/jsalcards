"""Regenerate ``tests/weights/fixtures/``: verbatim slices of real cached source files.

Run from ``pipeline/`` after ``python -m snowlight.weights build`` has filled
``.cache/weights/`` (and the school directory and station coverage exist)::

    uv run python tests/weights/make_fixtures.py

What is written, and how (``provenance.json`` records, for every fixture, the
source URL or file, its SHA-256, when it was retrieved and what was kept):

* ``iem-<first>-<last>.csv``: IEM school-year CSV files (``watchwarn.py``,
  ``accept=csv``) cut to the header and the rows named below, each line copied
  byte for byte in the original order.
* ``bp<date>.dbx``: NWS zone-county correlation files cut to the lines of the
  zones named below, unchanged.
* ``c_16ap26.zip``: the NWS county shapefile with only the records named below;
  each ``.shp`` and ``.dbf`` record is copied byte for byte and only the file
  length and record count in the headers are rewritten.
* ``iem-day-<date>.zip``: IEM day files (the pipeline's day-file client, for the
  closure-type codes) sliced the same way to the Rhode Island county and zone rows.
* ``ugcs-<date>.json``: an IEM ``ugcs.json`` answer with only the rows of the
  zones named below, each row object unchanged.
* ``schools.parquet``: the rows of the named schools from the school directory,
  every column unchanged.
* ``coverage.json``: the station coverage file's ``generated_at`` and the county
  entries named below, unchanged.
* ``research/``: the first-hand records named below (whole records) and the
  ``sources.json`` stations they link to.
* ``usa-tvdma-county.csv`` (the DMA crosswalk's header and the rows of the
  markets named below), ``2025_Gaz_counties_national.zip`` (the Gazetteer's
  header and the rows of the counties those markets and states need, in a new
  zip) and ``ct_cou_to_cousub_crosswalk.xlsx`` (the whole file).
* ``alert-types.json``: the NWS event list (``api.weather.gov/alerts/types``),
  the whole file.
* ``ugcs-<date>.geojson``: IEM's archived UGC outlines (``ugcs.geojson?valid=``)
  for 15 January of the 2018-19 and 2021-22 school years, cut to the features of
  the zones in that year's school-year slice, and for 15 January of 2019-20 (the
  first school year wholly under the served correlation releases), cut to the
  zones of the 2018-19 slice; each feature unchanged (fetched into the cache first
  when missing).
* ``z_18mr25.zip`` and ``z_16ap26.zip``: the NWS public zone releases with only the
  records of the zones the school-year slices name and of every zone within
  :data:`ZONE_BOX` degrees of a fixture school (the build's schools and
  :data:`ZONE_SCHOOLS`), sliced like the county file.
* ``iem-2019-2020-slc.csv``: the 2019-20 school-year file cut to the Salt Lake
  valley and Wasatch mountain zone rows (UTZ003, UTZ008) of three SLC Winter Storm
  Warnings, each line copied byte for byte.
* ``iem-zones-<office>-<code>-<begin>.zip``: IEM's full-resolution answers
  (``watchwarn.py``, ``simple=0``) of the requests
  :func:`snowlight.weights.zonepolys.plan_requests` picks for the zone versions of the
  school-year slices that no served release holds, cut to the zone rows of those
  versions' zones (records unchanged; fetched into the cache first when missing).
* ``iem-polygons-<first>-<last>.zip``: the storm-polygon files
  (:mod:`snowlight.weights.polygons`) cut to the polygon rows of the FF.W events of
  the school-year slice (and, for a slice with none, of the first FF.W event of the
  office named in :data:`POLYGON_OFFICES`).
* ``iem-polygons-2019-2020.zip`` (the polygon rows of SLC's FF.W 17 of 2019, for the
  Salt Lake slice) and ``iem-polygons-2016-2017-blank.zip`` (the polygon rows of BOI's
  FF.W 1 of 2017, whose ``ISSUED`` is blank).
* ``schools-zones.parquet``: the rows of :data:`ZONE_SCHOOLS` from the school
  directory, every column unchanged; ``c_16ap26-zones.zip``: the NWS county file
  cut to :data:`ZONE_COUNTY_RECORDS`, the counties around those schools.
* ``iem-2015-2016-outside.csv``, ``iem-2016-2017-outside.csv`` and
  ``iem-2017-2018-outside.csv``: the school-year files cut to the zones of
  :data:`OUTSIDE_SLICES` (every row of NCZ051, which IEM joined to two outlines by
  turns, in 2015-16 and 2016-17; every row of NYZ072, FLZ073, FLZ074 and MDZ008 in
  2017-18), each line copied byte for byte, and
  ``iem-polygons-2017-2018.zip``, the 2017-18 storm-polygon file cut to the first
  FF.W event of OKX (:data:`OUTSIDE_POLYGONS`).
* ``registry/<platform>.yaml``: the station registry's files
  (``pipeline/config/sources/``) cut to their ``platform:`` and ``id:`` lines, the
  ``stations:`` line and the whole entries of the stations named below, each line
  unchanged.

Name parts to regenerate only those (``provenance.json`` keeps the other parts'
records)::

    uv run python tests/weights/make_fixtures.py registry
"""

import csv
import hashlib
import json
import struct
import sys
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from snowlight.sources.nws.boundaries import BoundaryRelease
    from snowlight.weights.archive import EventRow

PIPELINE = Path(__file__).resolve().parents[2]
REPO = PIPELINE.parent
CACHE = PIPELINE / ".cache" / "weights"
OUT = Path(__file__).parent / "fixtures"
IEM = CACHE / "mesonet.agron.iastate.edu"
NWS = CACHE / "www.weather.gov" / "source" / "gis" / "Shapefiles" / "County"

RI_UGCS = ("RIZ", "RIC")
GULF_UGCS = frozenset({"FLZ014", "FLZ114", "FLZ115", "FLC045"})
YEAR_SLICES: dict[str, tuple[str, ...]] = {
    "2024-2025": ("Rhode Island zones and counties", "Gulf and Franklin, FL", "one FF.W polygon"),
    "2018-2019": (
        "Rhode Island zones",
        "MTZ043, IDZ075 and IDZ019 (renamed or retired)",
    ),
    "2021-2022": ("every county/zone row of LIX.TR.W.1009.2021 (Ida)",),
}
ZONES_2018 = frozenset({"MTZ043", "IDZ075", "IDZ019"})
RELEASE_SLICES = ("bp02ap19", "bp10oc19", "bp05mr24", "bp10se24", "bp16ap26")
BP_ZONES = frozenset({"FL014", "FL114", "FL115", "MT043", "ID075", "WY198", "WY199", "WA567"})
COUNTY_RECORDS = (83, 170, 260, 314, 315, 324, 2323, 2348, 2349, 2757, 2953, 3093)
"""c_16ap26 records: Hartford CT, Rhode Island's five counties, Gulf FL (two records,
split by a time zone line), Franklin FL (two), Missoula MT, Blaine ID."""
DAY_FILES = tuple(
    f"2025-{m:02d}-{d:02d}" for m, d in [(1, 30), (1, 31)] + [(2, d) for d in range(1, 9)]
)
SCHOOLS = (
    "01256947",
    "01257011",
    "01257033",
    "01257022",
    "440003300225",
    "00262237",
    "120069000867",
    "00791679",
    "00230067",
    "00230045",
    "00230442",
)
"""Three Providence schools, one each in Kent and Washington RI, two in Gulf FL, one in
Missoula MT, two Connecticut schools in Hartford County (planning-region codes) and
one in Litchfield County, whose county is not in the county slice."""
COVERAGE_COUNTIES = ("44001", "44003", "44005", "44007", "44009", "09110", "12045", "30063")
FIRSTHAND = {
    "nexstar-tegna-scripps.json": ("WPRI", "WTNH", "WPIX", "KELO", "WJTV"),
    "others.json": (
        "WJAR",
        "RIBA",
        "WBBM",
        "ECC",
        "KCNC",
        "WBFF",
        "KBAK",
        "KFXL",
        "WVEIS",
        "KABC",
        "News 12 CT",
        "NJ 101.5",
        "Sonoma COE school closures",
        "WVAH",
    ),
}
DMAS = (
    "Providence, RI - New Bedford, MA DMA",
    "Hartford & New Haven, CT DMA",
    "New York, NY - CT - NJ - PA DMA",
    "Chicago, IL - IN DMA",
    "Denver, CO - NE - NV - WY DMA",
    "Baltimore, MD DMA",
    "Los Angeles, CA DMA",
    "Bakersfield, CA DMA",
    "Sioux Falls (Mitchell), SD - IA - MN - NE DMA",
    "Rapid City, SD - MT - NE - WY DMA",
    "Jackson, MS DMA",
    "Panama City, FL DMA",
    "Missoula, MT DMA",
)
STATEWIDE = ("NJ", "WV", "RI", "CT")
DMA_FILE = (
    CACHE
    / "raw.githubusercontent.com"
    / "alex-patton"
    / "US-TVDMA-BY-COUNTY"
    / "7f254b8c1843c62ec976a71c40d366d45f6f29cd"
    / "usa-tvdma-county.csv"
)
GAZ_FILE = (
    CACHE
    / "www2.census.gov"
    / "geo"
    / "docs"
    / "maps-data"
    / "data"
    / "gazetteer"
    / "2025_Gazetteer"
    / "2025_Gaz_counties_national.zip"
)
CT_FILE = (
    CACHE
    / "www2.census.gov"
    / "geo"
    / "docs"
    / "reference"
    / "ct_change"
    / "ct_cou_to_cousub_crosswalk.xlsx"
)

ALERT_TYPES_FILE = CACHE / "api.weather.gov" / "alerts" / "types.json"
WSOM = CACHE / "www.weather.gov" / "source" / "gis" / "Shapefiles" / "WSOM"
ZONE_SETS = ("z_18mr25", "z_16ap26")
ZONE_BOX = 0.06
ZONE_SCHOOLS = (
    "01412727",
    "490014201380",
    "120039004068",
    "090171000303",
    "A0902269",
    "360010206660",
    "590006600044",
    "120039003051",
)
"""A Salt Lake valley school (UTZ105) and the county's one school in the Wasatch mountain zone
(UTZ111), and two schools just outside every zone polygon: one in Miami-Dade (0.016 km from
FLZ173) and one on the Connecticut shore (0.383 km from NYZ071). Then four for the school-year
rule: British International School of New York at Waterside Plaza and Hunters Point
Elementary in Long Island City, inside NYZ072 in z_18mr25 and 0.016 and 0.901 km outside every
earlier outline of it; a Cherokee Central school in Swain County, NC, outside one of the two
outlines IEM joined to NCZ051's rows; a school in west Miami-Dade, in FLZ074 now and in FLZ073's
outline of 2017."""
ZONE_COUNTY_RECORDS = (290, 339, 599, 935, 2000, 2002, 3031, 3035, 3076, 3241)
"""c_16ap26 records: Westchester NY, Fairfield CT, Queens NY, Swain NC, Broward and Miami-Dade
FL, Utah, Wasatch and Salt Lake UT, New York (Manhattan) NY."""
OUTSIDE_SLICES: dict[str, tuple[frozenset[str], str]] = {
    "2015-2016": (frozenset({"NCZ051"}), "every NCZ051 row"),
    "2016-2017": (frozenset({"NCZ051"}), "every NCZ051 row"),
    "2017-2018": (
        frozenset({"NYZ072", "FLZ073", "FLZ074", "MDZ008"}),
        "every NYZ072, FLZ073, FLZ074 and MDZ008 row",
    ),
}
"""The school-year slices of the school-year rule: the zones kept, and why."""
OUTSIDE_POLYGONS = {"2017-2018": "OKX"}
"""The storm-polygon slice for a school-year slice of the rule (it has no FF.W rows): the
polygon rows of the first FF.W event of this office."""
EXTRA_POLYGONS = {
    "2019-2020": ("iem-polygons-2019-2020.zip", ("SLC", 17, 2019)),
    "2016-2017": ("iem-polygons-2016-2017-blank.zip", ("BOI", 1, 2017)),
}
SLC_EVENTS = frozenset({("WS", "11", "2019"), ("WS", "12", "2019"), ("WS", "13", "2019")})
POLYGON_OFFICES = {"2018-2019": "BOX", "2021-2022": "LIX"}
YEAR_FILES = ("iem-2018-2019.csv", "iem-2021-2022.csv", "iem-2024-2025.csv")
REGISTRY = PIPELINE / "config" / "sources"
REGISTRY_STATIONS: dict[str, tuple[str, ...]] = {
    "gray": ("gray-kdlt", "gray-kktv", "gray-kold", "gray-wfsb", "gray-wlbt", "gray-wtva"),
    "nexstar": ("nexstar-wjtv", "nexstar-wpri", "nexstar-wtnh"),
    "scripps": ("scripps-kktv",),
}
"""Stations whose DMA is in the crosswalk slice (Providence, Hartford, Jackson MS; KDLT
without a county list), KKTV (under Gray and Scripps) and the Gray stations of the
Gray check's test (WTVA, KOLD), whose markets are not in the slice."""

type Provenance = dict[str, object]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar(path: Path) -> dict[str, object]:
    record = json.loads(Path(str(path) + ".provenance.json").read_text(encoding="utf-8"))
    return {
        "retrieved_at": record["retrieved_at"],
        "source_sha256": record["sha256"],
        "source_url": record["url"],
    }


def _year_keep(name: str, row: dict[str, str]) -> bool:
    ugc = row["ugc"]
    if name == "2024-2025":
        if ugc.startswith(RI_UGCS) or ugc in GULF_UGCS:
            return True
        return row["gtype"] == "P" and row["wfo"] == "BOX" and row["eventid"] == "15"
    if name == "2018-2019":
        return ugc.startswith("RIZ") or ugc in ZONES_2018
    return row["wfo"] == "LIX" and row["phenomena"] == "TR" and row["eventid"] == "1009"


def year_slices() -> Provenance:
    """Cut the school-year CSV files."""
    record: Provenance = {}
    for name, why in YEAR_SLICES.items():
        source = IEM / "watchwarn-csv" / f"{name}.csv"
        lines = source.read_bytes().split(b"\n")
        header = lines[0]
        fields = next(csv.reader([header.decode()]))
        kept: list[int] = []
        for number, line in enumerate(lines[1:], start=1):
            if not line:
                continue
            row = dict(zip(fields, next(csv.reader([line.decode()])), strict=True))
            if _year_keep(name, row):
                kept.append(number)
        body = b"\n".join([header, *(lines[i] for i in kept)]) + b"\n"
        (OUT / f"iem-{name}.csv").write_bytes(body)
        record[f"iem-{name}.csv"] = {
            **_sidecar(source),
            "selection": f"the header and lines {kept[0]}..{kept[-1]} ({len(kept)} rows): "
            + "; ".join(why),
            "lines_kept": kept,
        }
    return record


def _bp_keep(line: bytes) -> bool:
    parts = line.decode("latin-1").split("|")
    return len(parts) > 1 and (parts[0] == "RI" or parts[0] + parts[1] in BP_ZONES)


def release_slices() -> Provenance:
    """Cut the correlation files."""
    record: Provenance = {}
    for name in RELEASE_SLICES:
        source = NWS / f"{name}.dbx"
        lines = source.read_bytes().split(b"\n")
        kept = [i for i, line in enumerate(lines) if _bp_keep(line)]
        (OUT / f"{name}.dbx").write_bytes(b"\n".join(lines[i] for i in kept) + b"\n")
        record[f"{name}.dbx"] = {
            **_sidecar(source),
            "selection": "lines of Rhode Island and of FL014, FL114, FL115, MT043, ID075, "
            "WY198, WY199, WA567 (those present), unchanged",
            "lines_kept": kept,
        }
    return record


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
    files = {shp_name: bytes(header) + body, dbf_name: bytes(dbf_header) + rows + tail, **extras}
    with zipfile.ZipFile(dest, "w") as out:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            out.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return wanted


def _dbf_rows(source: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(source) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
        dbf = archive.read(name)
    count, header_len, record_len = struct.unpack_from("<IHH", dbf, 4)
    fields = []
    for offset in range(32, header_len - 1, 32):
        raw = dbf[offset : offset + 32]
        fields.append((raw[:11].split(b"\x00")[0].decode(), raw[16]))
    rows = []
    for i in range(count):
        record = dbf[header_len + i * record_len + 1 : header_len + (i + 1) * record_len]
        values, cursor = {}, 0
        for field_name, length in fields:
            values[field_name] = record[cursor : cursor + length].decode("latin-1").strip()
            cursor += length
        rows.append(values)
    return rows


def county_slice() -> Provenance:
    """Cut the county shapefile."""
    source = NWS / "c_16ap26.zip"
    kept = slice_shapefile(source, COUNTY_RECORDS, OUT / "c_16ap26.zip")
    return {
        "c_16ap26.zip": {
            **_sidecar(source),
            "selection": "these records' .shp and .dbf bytes unchanged, original order",
            "records_kept": kept,
            "listed_md5": "734d75df3791bdc0cbb29fd6ed75a387",
        }
    }


def day_slices() -> Provenance:
    """Cut the day files to their Rhode Island county and zone rows."""
    record: Provenance = {}
    for day in DAY_FILES:
        source = IEM / "watchwarn" / day[:4] / f"{day}.zip"
        rows = _dbf_rows(source)
        keep = [i for i, row in enumerate(rows) if row.get("NWS_UGC", "").startswith(RI_UGCS)]
        slice_shapefile(source, keep, OUT / f"iem-day-{day}.zip")
        record[f"iem-day-{day}.zip"] = {
            **_sidecar(source),
            "selection": "the Rhode Island county and zone rows (NWS_UGC RIZ/RIC), bytes unchanged",
            "records_kept": keep,
        }
    return record


def ugcs_slice(zones: set[str]) -> Provenance:
    """Cut IEM's UGC list for 2019-01-15 to the zones of the 2018-19 slice."""
    source = IEM / "api-ugcs" / "2019-01-15.json"
    document = json.loads(source.read_bytes())
    rows = [row for row in document["data"] if row["ugc"] in zones]
    out = {"schema": document["schema"], "data": rows}
    (OUT / "ugcs-2019-01-15.json").write_text(json.dumps(out) + "\n", encoding="utf-8")
    return {
        "ugcs-2019-01-15.json": {
            **_sidecar(source),
            "selection": f"the schema and the rows of {len(rows)} zones, each row unchanged",
        }
    }


def schools_slice() -> Provenance:
    """Cut the school directory."""
    source = PIPELINE / "out" / "internal" / "directory" / "schools.parquet"
    frame = pl.read_parquet(source)
    kept = frame.filter(pl.col("id").is_in(list(SCHOOLS))).sort("index")
    if kept.height != len(SCHOOLS):
        raise SystemExit("a named school is missing from the directory")
    kept.write_parquet(OUT / "schools.parquet")
    return {
        "schools.parquet": {
            "source_file": "pipeline/out/internal/directory/schools.parquet",
            "source_sha256": _sha(source.read_bytes()),
            "selection": f"rows of schools {', '.join(SCHOOLS)}, every column unchanged",
        }
    }


def coverage_slice() -> Provenance:
    """Cut the station coverage file."""
    source = PIPELINE / "out" / "internal" / "stations" / "coverage.json"
    document = json.loads(source.read_bytes())
    out = {
        "generated_at": document["generated_at"],
        "counties": {fips: document["counties"][fips] for fips in COVERAGE_COUNTIES},
    }
    (OUT / "coverage.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return {
        "coverage.json": {
            "source_file": "pipeline/out/internal/stations/coverage.json",
            "source_sha256": _sha(source.read_bytes()),
            "selection": f"generated_at and the entries of counties {', '.join(COVERAGE_COUNTIES)}",
        }
    }


def research_slices() -> tuple[Provenance, set[str]]:
    """Cut the first-hand records and the sources.json stations they link to."""
    record: Provenance = {}
    links: set[str] = set()
    folder = OUT / "research" / "firsthand"
    folder.mkdir(parents=True, exist_ok=True)
    for name, names in FIRSTHAND.items():
        source = REPO / "docs" / "research" / "firsthand" / name
        records = json.loads(source.read_bytes())
        kept = [r for r in records if (r.get("call_sign") or r.get("source_id")) in names]
        if len(kept) != len(names):
            raise SystemExit(f"{name}: a named record is missing")
        for r in kept:
            link = r.get("sources_json_id") or r.get("lead_id")
            if link:
                links.add(link)
        (folder / name).write_text(json.dumps(kept, indent=1) + "\n", encoding="utf-8")
        record[f"research/firsthand/{name}"] = {
            "source_file": f"docs/research/firsthand/{name}",
            "source_sha256": _sha(source.read_bytes()),
            "selection": f"records {', '.join(names)}, whole and unchanged",
        }
    source = REPO / "docs" / "research" / "sources.json"
    stations = [s for s in json.loads(source.read_bytes())["stations"] if s["id"] in links]
    (OUT / "research" / "sources.json").write_text(
        json.dumps({"stations": stations}, indent=1) + "\n", encoding="utf-8"
    )
    record["research/sources.json"] = {
        "source_file": "docs/research/sources.json",
        "source_sha256": _sha(source.read_bytes()),
        "selection": f"the stations {', '.join(sorted(links))}, whole and unchanged",
    }
    return record, links


def _dma_of(line: bytes) -> str | None:
    if not line.strip():
        return None
    row = next(csv.reader([line.decode("utf-8")]))
    return row[4].strip() if len(row) > 4 else None


def reference_slices() -> Provenance:
    """Cut the DMA crosswalk and the Gazetteer; copy the Connecticut crosswalk."""
    raw = DMA_FILE.read_bytes()
    lines = raw.split(b"\n")
    header = lines[0]
    kept = [i for i, line in enumerate(lines[1:], start=1) if _dma_of(line) in DMAS]
    body = b"\n".join([header, *(lines[i] for i in kept)]) + b"\n"
    (OUT / "usa-tvdma-county.csv").write_bytes(body)
    states = {next(csv.reader([lines[i].decode()]))[1].strip() for i in kept}
    states |= set(STATEWIDE) | {"CA"}
    with zipfile.ZipFile(GAZ_FILE) as archive:
        member = next(n for n in archive.namelist() if n.endswith(".txt"))
        text = archive.read(member)
    gaz_lines = text.split(b"\n")
    gaz_kept = [
        i
        for i, line in enumerate(gaz_lines[1:], start=1)
        if line and line.split(b"|")[0].decode() in states
    ]
    body = b"\n".join([gaz_lines[0], *(gaz_lines[i] for i in gaz_kept)]) + b"\n"
    with zipfile.ZipFile(OUT / "2025_Gaz_counties_national.zip", "w") as out:
        info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
        out.writestr(info, body, compress_type=zipfile.ZIP_DEFLATED)
    (OUT / "ct_cou_to_cousub_crosswalk.xlsx").write_bytes(CT_FILE.read_bytes())
    return {
        "usa-tvdma-county.csv": {
            **_sidecar(DMA_FILE),
            "selection": f"the header and the rows of {len(DMAS)} markets ({len(kept)} rows), "
            "unchanged",
            "lines_kept": kept,
        },
        "2025_Gaz_counties_national.zip": {
            **_sidecar(GAZ_FILE),
            "selection": f"the header and the rows of states {', '.join(sorted(states))}, "
            "unchanged, in a new zip",
        },
        "ct_cou_to_cousub_crosswalk.xlsx": {**_sidecar(CT_FILE), "selection": "the whole file"},
    }


def alert_types_copy() -> Provenance:
    """Copy the NWS event list whole."""
    (OUT / "alert-types.json").write_bytes(ALERT_TYPES_FILE.read_bytes())
    return {"alert-types.json": {**_sidecar(ALERT_TYPES_FILE), "selection": "the whole file"}}


def outline_slices() -> Provenance:
    """Cut IEM's archived outlines to the zones of the school-year slices."""
    from snowlight.sources.nws.http import HttpCache, make_client  # noqa: PLC0415
    from snowlight.weights.cache import WeightsCache  # noqa: PLC0415
    from snowlight.weights.outlines import load_outlines, outline_valid  # noqa: PLC0415

    record: Provenance = {}
    with HttpCache(make_client()) as http:
        cache = WeightsCache(http, CACHE)
        for year, name in ((2018, "2018-2019"), (2019, "2018-2019"), (2021, "2021-2022")):
            with (OUT / f"iem-{name}.csv").open(encoding="utf-8") as handle:
                wanted = {row["ugc"] for row in csv.DictReader(handle) if row["ugc"][2:3] == "Z"}
            _, file = load_outlines(cache, year)
            document = json.loads(file.path.read_bytes())
            kept = [f for f in document["features"] if f["properties"]["ugc"] in wanted]
            out = {k: v for k, v in document.items() if k != "features"} | {"features": kept}
            stamp = f"{outline_valid(year):%Y-%m-%d}"
            (OUT / f"ugcs-{stamp}.geojson").write_text(json.dumps(out) + "\n", encoding="utf-8")
            record[f"ugcs-{stamp}.geojson"] = {
                **_sidecar(file.path),
                "selection": f"the collection's keys and the features of {len(kept)} zones "
                f"(those of the {name} school-year slice), each feature unchanged",
            }
    return record


def slc_slice() -> Provenance:
    """Cut the 2019-20 school-year file to three SLC Winter Storm Warnings' UTZ003/UTZ008 rows."""
    source = IEM / "watchwarn-csv" / "2019-2020.csv"
    lines = source.read_bytes().split(b"\n")
    fields = next(csv.reader([lines[0].decode()]))
    kept = []
    for number, line in enumerate(lines[1:], start=1):
        if not line:
            continue
        row = dict(zip(fields, next(csv.reader([line.decode()])), strict=True))
        key = (row["phenomena"], row["eventid"], row["vtec_year"])
        if row["wfo"] == "SLC" and row["ugc"] in {"UTZ003", "UTZ008"} and key in SLC_EVENTS:
            kept.append(number)
    body = b"\n".join([lines[0], *(lines[i] for i in kept)]) + b"\n"
    (OUT / "iem-2019-2020-slc.csv").write_bytes(body)
    return {
        "iem-2019-2020-slc.csv": {
            **_sidecar(source),
            "selection": "the header and the UTZ003 and UTZ008 rows of SLC.WS.W.0011, 0012 and "
            f"0013 of 2019 ({len(kept)} rows), unchanged",
            "lines_kept": kept,
        }
    }


def outside_slices() -> Provenance:
    """Cut two school-year files to the zones of the school-year rule's tests."""
    record: Provenance = {}
    for years, (zones, why) in OUTSIDE_SLICES.items():
        source = IEM / "watchwarn-csv" / f"{years}.csv"
        lines = source.read_bytes().split(b"\n")
        fields = next(csv.reader([lines[0].decode()]))
        kept = []
        for number, line in enumerate(lines[1:], start=1):
            if not line:
                continue
            row = dict(zip(fields, next(csv.reader([line.decode()])), strict=True))
            if row["ugc"] in zones:
                kept.append(number)
        body = b"\n".join([lines[0], *(lines[i] for i in kept)]) + b"\n"
        name = f"iem-{years}-outside.csv"
        (OUT / name).write_bytes(body)
        record[name] = {
            **_sidecar(source),
            "selection": f"the header and {why} ({len(kept)} rows), unchanged",
            "lines_kept": kept,
        }
    for years, office in OUTSIDE_POLYGONS.items():
        source = IEM / "watchwarn-polygons" / f"{years}.zip"
        rows = _dbf_rows(source)
        first = next(r for r in rows if r["GTYPE"] == "P" and r["WFO"] == office)
        event = _event_of(first)
        keep = [i for i, row in enumerate(rows) if row["GTYPE"] == "P" and _event_of(row) == event]
        name = f"iem-polygons-{years}.zip"
        slice_shapefile(source, keep, OUT / name)
        record[name] = {
            **_sidecar(source),
            "selection": f"the polygon rows of FF.W {event[0]} {event[1]} {event[2]} (the first "
            f"FF.W event of {office}), .shp and .dbf bytes unchanged",
            "records_kept": keep,
        }
    return record


def zone_schools_slice() -> Provenance:
    """Cut the school directory to the per-school zone test schools."""
    source = PIPELINE / "out" / "internal" / "directory" / "schools.parquet"
    frame = pl.read_parquet(source)
    kept = frame.filter(pl.col("id").is_in(list(ZONE_SCHOOLS))).sort("index")
    if kept.height != len(ZONE_SCHOOLS):
        raise SystemExit("a named school is missing from the directory")
    kept.write_parquet(OUT / "schools-zones.parquet")
    return {
        "schools-zones.parquet": {
            "source_file": "pipeline/out/internal/directory/schools.parquet",
            "source_sha256": _sha(source.read_bytes()),
            "selection": f"rows of schools {', '.join(ZONE_SCHOOLS)}, every column unchanged",
        }
    }


def _fixture_rows() -> list["EventRow"]:
    from snowlight.weights.archive import read_rows  # noqa: PLC0415

    rows: list[EventRow] = []
    outside = [f"iem-{years}-outside.csv" for years in OUTSIDE_SLICES]
    for name in (*YEAR_FILES, "iem-2019-2020-slc.csv", *outside):
        found, _ = read_rows((OUT / name).read_text(encoding="utf-8"))
        rows.extend(found)
    return rows


def zone_set_slices() -> Provenance:
    """Cut the served zone releases to the zones the fixtures need."""
    import shapely  # noqa: PLC0415

    from snowlight.sources.nws.shapefile import read_zip  # noqa: PLC0415
    from snowlight.weights import zonepolys  # noqa: PLC0415

    points = []
    for name in ("schools.parquet", "schools-zones.parquet"):
        frame = pl.read_parquet(OUT / name)
        points += list(zip(frame["lon"].to_list(), frame["lat"].to_list(), strict=True))
    boxes = [shapely.box(x - ZONE_BOX, y - ZONE_BOX, x + ZONE_BOX, y + ZONE_BOX) for x, y in points]
    full = [zonepolys.read_zone_set(WSOM / f"{name}.zip", r) for name, r in _releases()]
    matched: dict[str, set[str]] = {name: set() for name in ZONE_SETS}
    for version in zonepolys.versions_of(_fixture_rows()):
        found = zonepolys.served_match(version, full)
        if found is not None:
            matched[found[0].name].add(version.ugc)
    record: Provenance = {}
    for name in ZONE_SETS:
        source = WSOM / f"{name}.zip"
        keep = []
        for item in read_zip(source):
            ugc = f"{item.attributes['STATE']}Z{item.attributes['ZONE']}"
            near = item.geometry is not None and any(item.geometry.intersects(b) for b in boxes)
            if ugc in matched[name] or near:
                keep.append(item.index)
        kept = slice_shapefile(source, keep, OUT / f"{name}.zip")
        record[f"{name}.zip"] = {
            **_sidecar(source),
            "selection": "the records of the zones whose polygon here holds a version of the "
            "school-year slices' rows, and of every zone within "
            f"{ZONE_BOX} degrees of a fixture school; .shp and .dbf bytes unchanged",
            "records_kept": kept,
        }
    return record


def _releases() -> list[tuple[str, "BoundaryRelease"]]:
    from snowlight.weights import zonepolys  # noqa: PLC0415

    return [(r.url.rsplit("/", 1)[-1].removesuffix(".zip"), r) for r in zonepolys.ZONE_RELEASES]


def zone_version_slices() -> Provenance:
    """Fetch (or reuse) and cut IEM's full-resolution answers for the fixtures' zone versions."""
    from snowlight.sources.nws.boundaries import BoundaryRelease  # noqa: PLC0415
    from snowlight.sources.nws.http import HttpCache, make_client  # noqa: PLC0415
    from snowlight.weights import zonepolys  # noqa: PLC0415
    from snowlight.weights.cache import WeightsCache  # noqa: PLC0415

    rows = _fixture_rows()
    sets = [
        zonepolys.read_zone_set(
            OUT / f"{name}.zip",
            BoundaryRelease(release.kind, release.valid_from, release.url, "", None),
        )
        for name, release in _releases()
    ]
    record: Provenance = {}
    with HttpCache(make_client()) as http:
        cache = WeightsCache(http, CACHE)
        book = zonepolys.build_book(cache, rows, sets, fetch=False)
        needed = set(book.unresolved)
        for key in zonepolys.plan_requests(rows, book.unresolved):
            file = cache.fetch(key.url, key.path(cache.root))
            keep = [
                zone.index
                for zone in _zone_records(file.path)
                if zonepolys.Version(zone.ugc, zone.area) in needed
            ]
            name = f"iem-zones-{key.wfo}-{key.code}-{key.begin:%Y%m%dT%H%M}.zip"
            slice_shapefile(file.path, keep, OUT / name)
            record[name] = {
                **_sidecar(file.path),
                "selection": "the zone rows of the versions no served release holds (zone code "
                "and AREA_KM2), .shp and .dbf bytes unchanged",
                "records_kept": keep,
            }
    return record


@dataclass(frozen=True)
class _ZoneRecord:
    index: int
    ugc: str
    area: float


def _zone_records(path: Path) -> list[_ZoneRecord]:
    from snowlight.sources.nws.shapefile import read_zip  # noqa: PLC0415

    found = []
    for item in read_zip(path):
        ugc, area = str(item.attributes.get("NWS_UGC") or ""), item.attributes.get("AREA_KM2")
        if item.attributes.get("GTYPE") == "C" and ugc[2:3] == "Z" and isinstance(area, float):
            found.append(_ZoneRecord(item.index, ugc, area))
    return found


def zone_county_slice() -> Provenance:
    """Cut the county shapefile to the counties around the per-school zone test schools."""
    source = NWS / "c_16ap26.zip"
    kept = slice_shapefile(source, ZONE_COUNTY_RECORDS, OUT / "c_16ap26-zones.zip")
    return {
        "c_16ap26-zones.zip": {
            **_sidecar(source),
            "selection": "these records' .shp and .dbf bytes unchanged, original order",
            "records_kept": kept,
        }
    }


def _event_of(row: dict[str, str]) -> tuple[str, int, int]:
    return (row["WFO"], int(float(row["ETN"])), int(float(row["VTEC_YR"])))


def polygon_slices() -> Provenance:
    """Cut the storm-polygon files to the FF.W events of the school-year slices."""
    record: Provenance = {}
    for years, (name, event) in EXTRA_POLYGONS.items():
        source = IEM / "watchwarn-polygons" / f"{years}.zip"
        rows = _dbf_rows(source)
        keep = [i for i, row in enumerate(rows) if row["GTYPE"] == "P" and _event_of(row) == event]
        slice_shapefile(source, keep, OUT / name)
        record[name] = {
            **_sidecar(source),
            "selection": f"the polygon rows of FF.W {event[0]} {event[1]} {event[2]}, .shp and "
            ".dbf bytes unchanged",
            "records_kept": keep,
        }
    for name in YEAR_FILES:
        years = name.removeprefix("iem-").removesuffix(".csv")
        with (OUT / name).open(encoding="utf-8") as handle:
            events = {
                (row["wfo"], int(row["eventid"]), int(row["vtec_year"]))
                for row in csv.DictReader(handle)
                if row["phenomena"] == "FF"
            }
        source = IEM / "watchwarn-polygons" / f"{years}.zip"
        rows = _dbf_rows(source)
        if not events:
            office = POLYGON_OFFICES[years]
            first = next(r for r in rows if r["GTYPE"] == "P" and r["WFO"] == office)
            events = {(office, int(float(first["ETN"])), int(float(first["VTEC_YR"])))}
        keep = [
            i
            for i, row in enumerate(rows)
            if row["GTYPE"] == "P"
            and (row["WFO"], int(float(row["ETN"])), int(float(row["VTEC_YR"]))) in events
        ]
        slice_shapefile(source, keep, OUT / f"iem-polygons-{years}.zip")
        record[f"iem-polygons-{years}.zip"] = {
            **_sidecar(source),
            "selection": "the polygon rows of the FF.W events "
            + ", ".join(f"{w} {e} {y}" for w, e, y in sorted(events))
            + ", .shp and .dbf bytes unchanged",
            "records_kept": keep,
        }
    return record


def _entries(lines: list[bytes]) -> tuple[int, dict[str, tuple[int, int]]]:
    """Return the ``stations:`` line and each station entry's [first, last) line range."""
    start = lines.index(b"stations:")
    firsts = [i for i in range(start + 1, len(lines)) if lines[i].startswith(b"- id: ")]
    ranges: dict[str, tuple[int, int]] = {}
    for position, first in enumerate(firsts):
        end = firsts[position + 1] if position + 1 < len(firsts) else len(lines)
        while end > first and not lines[end - 1].strip():
            end -= 1
        ranges[lines[first][len(b"- id: ") :].decode().strip()] = (first, end)
    return start, ranges


def registry_slice() -> Provenance:
    """Cut the station registry files to the named stations."""
    record: Provenance = {}
    folder = OUT / "registry"
    folder.mkdir(parents=True, exist_ok=True)
    for platform, wanted in REGISTRY_STATIONS.items():
        source = REGISTRY / f"{platform}.yaml"
        raw = source.read_bytes()
        lines = raw.split(b"\n")
        head = [lines.index(b"platform:"), lines.index(f"  id: {platform}".encode())]
        start, ranges = _entries(lines)
        kept = [*head, start]
        for station in wanted:
            first, end = ranges[station]
            kept.extend(range(first, end))
        (folder / f"{platform}.yaml").write_bytes(b"\n".join(lines[i] for i in kept) + b"\n")
        record[f"registry/{platform}.yaml"] = {
            "source_file": f"pipeline/config/sources/{platform}.yaml",
            "source_sha256": _sha(raw),
            "selection": "the platform: and id: lines, the stations: line and the whole "
            f"entries of {', '.join(wanted)}, each line unchanged",
            "lines_kept": kept,
        }
    return record


def _ugcs_2018() -> Provenance:
    with (OUT / "iem-2018-2019.csv").open(encoding="utf-8") as handle:
        zones_2018 = {row["ugc"] for row in csv.DictReader(handle)}
    return ugcs_slice(zones_2018)


def _research() -> Provenance:
    return research_slices()[0]


PARTS: dict[str, Callable[[], Provenance]] = {
    "years": year_slices,
    "releases": release_slices,
    "counties": county_slice,
    "days": day_slices,
    "ugcs": _ugcs_2018,
    "schools": schools_slice,
    "coverage": coverage_slice,
    "research": _research,
    "references": reference_slices,
    "alert-types": alert_types_copy,
    "outlines": outline_slices,
    "registry": registry_slice,
    "slc": slc_slice,
    "outside": outside_slices,
    "zone-schools": zone_schools_slice,
    "zone-sets": zone_set_slices,
    "zone-versions": zone_version_slices,
    "polygons": polygon_slices,
    "zone-counties": zone_county_slice,
}
"""Each part and what writes it, in the order they run (the UGC slice reads the 2018-19
school-year slice; the zone parts read the school-year slices, the SLC slice and the two
school slices)."""


def main(argv: Sequence[str] = ()) -> None:
    """Write the named parts (every part when none is named) and ``provenance.json``."""
    unknown = sorted(set(argv) - set(PARTS))
    if unknown:
        raise SystemExit(f"unknown parts {unknown}; the parts are {', '.join(PARTS)}")
    OUT.mkdir(parents=True, exist_ok=True)
    record = OUT / "provenance.json"
    provenance: Provenance = {}
    if argv and record.exists():
        provenance = json.loads(record.read_text(encoding="utf-8"))
    for name, part in PARTS.items():
        if not argv or name in argv:
            provenance.update(part())
    text = json.dumps(provenance, indent=1, sort_keys=True) + "\n"
    record.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
