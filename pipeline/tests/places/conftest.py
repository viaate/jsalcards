"""Shared helpers for the places tests.

Every ``fixtures/`` file is a verbatim slice of a real source file; see
``fixtures/provenance.json``. The only synthetic things here are containers:
the zip archives and the one-sheet workbook that wrap those real slices the way
the publishers ship them, and the in-memory HTTP server that serves them.

Test modules cannot import this file under ``--import-mode=importlib``, so the
helpers reach them through the ``kit``, ``server`` and ``cache`` fixtures (the
classes are imported only for type checking).
"""

import io
import zipfile
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest

from snowlight.places.download import SourceCache
from snowlight.places.grf import GRF_PAGE_URL
from snowlight.sources.census import gazetteer, popest
from snowlight.sources.census.lsad import LSAD_URL
from snowlight.sources.census.zcta_county import ZCTA_COUNTY_URL

FIXTURES = Path(__file__).parent / "fixtures"
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def fixture_bytes(name: str) -> bytes:
    """Return the bytes of a real fixture slice."""
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    """Return a UTF-8 fixture slice as text."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def zip_bytes(members: dict[str, bytes]) -> bytes:
    """Wrap files in a zip archive, as the publishers ship them."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def xlsx_bytes(rows: list[list[str]], *, inline: bool = False) -> bytes:
    """Build a minimal one-sheet workbook whose cells hold ``rows`` as text.

    Cells are shared strings, like the NCES workbooks, unless ``inline`` asks
    for inline strings.
    """
    strings: dict[str, int] = {}
    cells_xml: list[str] = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_column_letters(c)}{r}"
            if inline:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                index = strings.setdefault(value, len(strings))
                cells.append(f'<c r="{ref}" t="s"><v>{index}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{_MAIN_NS}">'
        f"<sheetData>{''.join(cells_xml)}</sheetData></worksheet>"
    )
    shared = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    return zip_bytes(
        {
            "xl/workbook.xml": (
                f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets>'
                '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ).encode(),
            "xl/_rels/workbook.xml.rels": (
                f'<Relationships xmlns="{_PKG_NS}"><Relationship Id="rId1" '
                'Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>'
            ).encode(),
            "xl/sharedStrings.xml": f'<sst xmlns="{_MAIN_NS}">{shared}</sst>'.encode(),
            "xl/worksheets/sheet1.xml": sheet.encode(),
        }
    )


def grf_rows() -> list[list[str]]:
    """Return the real GRF LEA-ZCTA slice as rows of cell text, header first."""
    text = fixture_text("grf25_lea_zcta5ce20.tsv")
    return [line.split("\t") for line in text.splitlines()]


def grf_zip_bytes() -> bytes:
    """Wrap the GRF slice in a GRF25-style zip."""
    return zip_bytes({"GRF25/grf25_lea_zcta5ce20.xlsx": xlsx_bytes(grf_rows())})


def real_sources() -> dict[str, bytes]:
    """Map every URL the places build reads to the bytes of its real fixture slice."""
    gaz26 = gazetteer.release_dir_url(2026)
    totals = popest.totals_dir_url(2020, 2025)
    return {
        gazetteer.INDEX_URL: fixture_bytes("gazetteer-index.table.html"),
        gaz26: fixture_bytes("gazetteer-2026.table.html"),
        gazetteer.national_file_url(2026, "place"): zip_bytes(
            {"2026_Gaz_place_national.txt": fixture_bytes("2026_Gaz_place_national.txt")}
        ),
        gazetteer.national_file_url(2026, "zcta"): zip_bytes(
            {"2026_Gaz_zcta_national.txt": fixture_bytes("2026_Gaz_zcta_national.txt")}
        ),
        gazetteer.national_file_url(2025, "zcta"): zip_bytes(
            {"2025_Gaz_zcta_national.txt": fixture_bytes("2025_Gaz_zcta_national.txt")}
        ),
        GRF_PAGE_URL: fixture_bytes("nces-relationship-files.lines-222-414.html"),
        "https://nces.ed.gov/programs/edge/data/GRF25.zip": grf_zip_bytes(),
        popest.DATASETS_URL: fixture_bytes("popest-datasets.table.html"),
        totals: fixture_bytes("popest-2020-2025-cities-totals.table.html"),
        totals + "sub-est2025.csv": fixture_bytes("sub-est2025.csv"),
        LSAD_URL: fixture_bytes("legal-status-codes.table.html"),
        ZCTA_COUNTY_URL: fixture_bytes("tab20_zcta520_county20_natl.txt"),
    }


class FakeServer:
    """An in-memory HTTPS server for :class:`httpx.MockTransport`."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.hits: Counter[str] = Counter()
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits[url] += 1
        if url in self.overrides:
            return self.overrides[url](request)
        if url not in self.files:
            return httpx.Response(404, request=request)
        body = self.files[url]
        etag = f'"{len(body)}-{sum(body) % 9973}"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, request=request)
        return httpx.Response(
            200,
            content=body,
            headers={"ETag": etag, "Last-Modified": "Tue, 08 Sep 2026 21:00:12 GMT"},
            request=request,
        )

    def client(self) -> httpx.Client:
        """Return a client that talks only to this server."""
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


class FixtureKit:
    """The helpers above, bundled for tests that receive them as a fixture."""

    fixtures = FIXTURES
    bytes_of = staticmethod(fixture_bytes)
    text_of = staticmethod(fixture_text)
    zip_of = staticmethod(zip_bytes)
    xlsx_of = staticmethod(xlsx_bytes)
    grf_rows = staticmethod(grf_rows)
    grf_zip = staticmethod(grf_zip_bytes)
    real_sources = staticmethod(real_sources)


@pytest.fixture
def kit() -> FixtureKit:
    """Fixture-file helpers."""
    return FixtureKit()


@pytest.fixture
def server() -> FakeServer:
    """A fake server holding the real fixture slices at their real URLs."""
    return FakeServer(real_sources())


@pytest.fixture
def cache(server: FakeServer, tmp_path: Path) -> Iterator[SourceCache]:
    """A source cache in a temporary directory, backed by the fake server."""
    with SourceCache(tmp_path / "cache", server.client(), sleep=lambda _s: None) as source_cache:
        yield source_cache
