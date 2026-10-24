"""Heights in alerts: the school elevation table, its build from terrain tiles, its pin, and
the serving pass counting only the schools within the heights an alert names.

The October 22, 2026 advisories (KHNX WW.Y 0005 above 8,000 feet over the zone holding
Yosemite-Wawona; KREV WW.Y 0009 above 8000 feet over Mono County) are public NWS products
(fixtures/). The schools here are the synthetic world's, given the heights of the schools
those advisories reached (Wawona about 4,068 ft, Eastern Sierra's 5,150 to 6,800 ft, Mammoth
about 7,808 ft), so the replay shows the rule, not a real directory.
"""

import gzip
import hashlib
import json
import struct
import zlib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pytest

from predict import world
from predict.test_publish import make_pass
from snowlight.cli import main
from snowlight.elevation.build import build_table, jobs_for, read_tile
from snowlight.elevation.cli import pin_block
from snowlight.elevation.pins import ElevationPins, Source, TablePin, asset_name, load_pins
from snowlight.elevation.table import Row, Table, TableError, heights_for
from snowlight.elevation.terrarium import FEET_PER_METER, TileError, decode, sample, tile_of
from snowlight.predict import cli
from snowlight.predict.alerts_live import LiveEvent, Memory, UgcIndex, live_events
from snowlight.predict.heights import (
    Loaded,
    PinnedTable,
    heights_said,
    load_pinned,
    school_heights,
)
from snowlight.predict.inputs import read_local
from snowlight.predict.serve import build_model, reached_by, unit_classes
from snowlight.predict.situations import WeatherClass, Window
from snowlight.sources.nws.alerts import parse_active
from snowlight.sources.nws.elevation import Band, ElevationLimit

FIXTURE = Path(__file__).parent / "fixtures" / "nws-2026-10-22-advisories.json"
URL = "https://tiles.test/{z}/{x}/{y}.png"
WINDOW = Window(time(18), time(9), 21)


# --- terrain tiles ------------------------------------------------------------------------------


def png(meters: np.ndarray, filters: tuple[int, ...] = (0, 1, 2, 3, 4)) -> bytes:
    """A 256 by 256 Terrarium PNG of ``meters``, row ``r`` written with filter
    ``filters[r % len(filters)]`` (so every row filter is read)."""
    value = meters + 32768.0
    red = np.floor(value / 256)
    green = np.floor(value - red * 256)
    blue = np.round((value - np.floor(value)) * 256)
    raw = np.stack([red, green, blue], axis=-1).astype(np.int32).reshape(256, 768)
    lines = bytearray()
    above = np.zeros(768, dtype=np.int32)
    for r in range(256):
        line = raw[r]
        kind = filters[r % len(filters)]
        left = np.concatenate([np.zeros(3, dtype=np.int32), line[:-3]])
        corner = np.concatenate([np.zeros(3, dtype=np.int32), above[:-3]])
        if kind == 0:
            guess = np.zeros(768, dtype=np.int32)
        elif kind == 1:
            guess = left
        elif kind == 2:
            guess = above
        elif kind == 3:
            guess = (left + above) // 2
        else:
            p = left + above - corner
            pa, pb, pc = np.abs(p - left), np.abs(p - above), np.abs(p - corner)
            guess = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, above, corner))
        lines.append(kind)
        lines += bytes(((line - guess) & 0xFF).astype(np.uint8))
        above = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(lines)))
        + chunk(b"IEND", b"")
    )


def ramp() -> np.ndarray:
    """SYNTHETIC heights: 1000 m rising 2 m per pixel east and 1 m per pixel south."""
    cols, rows = np.meshgrid(np.arange(256), np.arange(256))
    return 1000.0 + 2.0 * cols + 1.0 * rows + 0.25


def test_a_terrarium_tile_reads_back_every_row_filter() -> None:
    meters = ramp()
    assert np.array_equal(decode(png(meters)), meters)
    assert np.array_equal(decode(png(meters, (4,))), meters)


def test_a_point_reads_between_the_pixel_centers_around_it() -> None:
    meters = ramp()
    assert sample(meters, 10.5, 20.5) == pytest.approx(1000.25 + 20 + 20)
    assert sample(meters, 11.0, 20.5) == pytest.approx(1000.25 + 21 + 20)
    assert sample(meters, 0.0, 0.0) == pytest.approx(1000.25)  # clamped at the edge
    assert sample(meters, 256.0, 256.0) == pytest.approx(1000.25 + 510 + 255)


def test_tiles_and_pixels_of_points() -> None:
    x, y, px, py = tile_of(-119.64805, 37.54485, 11)
    assert (x, y) == (343, 793)
    assert 0 <= px < 256
    assert 0 <= py < 256
    assert tile_of(0.0, 0.0, 1)[:2] == (1, 1)


@pytest.mark.parametrize(
    "data",
    [
        b"not a png",
        b"\x89PNG\r\n\x1a\n",
        png(ramp())[:-20],
        png(ramp()).replace(b"IHDR", b"IHDX", 1),
    ],
)
def test_bytes_that_are_not_a_tile_are_refused(data: bytes) -> None:
    with pytest.raises(TileError):
        decode(data)


def test_a_png_of_another_size_or_a_bad_filter_is_refused() -> None:
    good = png(ramp())
    header = struct.pack(">IIBBBBB", 128, 256, 8, 2, 0, 0, 0)
    body = b"IHDR" + header
    wrong = good[:8] + struct.pack(">I", 13) + body + struct.pack(">I", zlib.crc32(body))
    wrong += good[8 + 25 :]
    with pytest.raises(TileError, match="not a terrain tile"):
        decode(wrong)
    raw = bytearray(zlib.decompress(_idat(good)))
    raw[0] = 9
    with pytest.raises(TileError, match="filter"):
        decode(_with_idat(good, zlib.compress(bytes(raw))))
    with pytest.raises(TileError, match="not one tile"):
        decode(_with_idat(good, zlib.compress(bytes(raw[:-10]))))
    with pytest.raises(TileError, match="cannot be read"):
        decode(_with_idat(good, b"not zlib"))


def _idat(data: bytes) -> bytes:
    at = data.index(b"IDAT")
    (length,) = struct.unpack(">I", data[at - 4 : at])
    return data[at + 4 : at + 4 + length]


def _with_idat(data: bytes, body: bytes) -> bytes:
    at = data.index(b"IDAT") - 4
    (length,) = struct.unpack(">I", data[at : at + 4])
    chunk = struct.pack(">I", len(body)) + b"IDAT" + body
    chunk += struct.pack(">I", zlib.crc32(b"IDAT" + body))
    return data[:at] + chunk + data[at + 12 + length :]


# --- the table ----------------------------------------------------------------------------------


def tiles_for(points: list[tuple[int, int]]) -> dict[str, bytes]:
    """SYNTHETIC tiles: the ramp, at every tile the points fall in."""
    jobs, _where = jobs_for([p[0] for p in points], [p[1] for p in points], URL, 11)
    return {job.url: png(ramp()) for job in jobs}


def test_a_table_is_built_from_the_tiles_of_its_schools() -> None:
    lon_e6 = [-119648050, -119647000, -118958334, -94580000]
    lat_e6 = [37544850, 37545000, 37641613, 39100000]
    ids = ["d", "a", "c", "b"]
    tiles = tiles_for(list(zip(lon_e6, lat_e6, strict=True)))
    gone = URL.format(z=11, x=tile_of(-94.58, 39.1, 11)[0], y=tile_of(-94.58, 39.1, 11)[1])
    seen: list[tuple[int, int]] = []
    built = build_table(
        ids,
        lon_e6,
        lat_e6,
        url=URL,
        fetch=lambda url: None if url == gone else tiles[url],
        progress=lambda done, total: seen.append((done, total)),
    )
    table = built.table
    assert [row.school for row in table.rows] == ["a", "b", "c", "d"]
    assert built.tiles == 3
    assert seen[-1] == (3, 3)
    assert table.unknown == 1
    assert next(r for r in table.rows if r.school == "b").feet is None
    assert built.problems == (f"11/{gone.split('/')[-2]}/{gone.split('/')[-1][:-4]}: no such tile",)
    _x, _y, px, py = tile_of(-119.64805, 37.54485, 11)
    want = round(sample(ramp(), px, py) * FEET_PER_METER)
    assert next(r for r in table.rows if r.school == "d").feet == want
    # The same tiles make the same bytes, and the bytes read back.
    again = build_table(
        ids, lon_e6, lat_e6, url=URL, fetch=lambda u: None if u == gone else tiles[u]
    )
    assert again.table.to_bytes() == table.to_bytes()
    assert Table.from_bytes(table.to_bytes()) == table
    assert table.tiles_sha256 == again.table.tiles_sha256


def test_a_tile_that_fails_or_does_not_read_leaves_its_schools_unknown() -> None:
    jobs, _ = jobs_for([-119648050], [37544850], URL, 11)

    def broken(_url: str) -> bytes:
        raise OSError("HTTP 503")

    assert read_tile(jobs[0], broken).feet == (None,)
    assert read_tile(jobs[0], broken).problem == "HTTP 503"
    assert read_tile(jobs[0], lambda _url: b"junk").sha256 is None


def test_the_build_refuses_ids_that_repeat_or_do_not_match_the_points() -> None:
    with pytest.raises(ValueError, match="repeats"):
        build_table(["a", "a"], [1, 2], [3, 4], fetch=lambda _u: None)
    with pytest.raises(ValueError, match="one id"):
        build_table(["a"], [1, 2], [3, 4], fetch=lambda _u: None)


def table_bytes(value: object) -> bytes:
    return gzip.compress(json.dumps(value).encode(), mtime=0)


GOOD = {
    "schema": 1,
    "source": {"url": URL, "zoom": 11, "tiles_sha256": "0" * 64},
    "schools": 2,
    "unknown": 1,
    "rows": [["a", 1, 2, 4068], ["b", 3, 4, None]],
}


@pytest.mark.parametrize(
    "value",
    [
        GOOD | {"schema": 2},
        GOOD | {"unknown": 0},
        GOOD | {"schools": 3},
        GOOD | {"rows": [["b", 3, 4, None], ["a", 1, 2, 4068]]},
        GOOD | {"rows": [["a", 1, 2, 4068], ["a", 3, 4, None]]},
        GOOD | {"rows": [["a", 1, 2, 40680], ["b", 3, 4, None]]},
        GOOD | {"rows": [["a", 1, 2, 4068.5], ["b", 3, 4, None]]},
        GOOD | {"rows": [["a", 1, 2], ["b", 3, 4, None]]},
        GOOD | {"rows": [["a", True, 2, 1], ["b", 3, 4, None]]},
        GOOD | {"source": {"url": URL, "zoom": "11", "tiles_sha256": ""}},
        GOOD | {"source": None},
        [],
    ],
)
def test_a_table_that_does_not_agree_with_itself_is_refused(value: object) -> None:
    Table.from_bytes(table_bytes(GOOD))
    with pytest.raises(TableError):
        Table.from_bytes(table_bytes(value))


def test_garbage_is_not_a_table() -> None:
    with pytest.raises(TableError):
        Table.from_bytes(b"not gzip")


def test_a_height_counts_only_at_the_very_point_the_directory_has() -> None:
    points = world.points()
    ids = world.school_ids()
    lon, lat = points.lon_e6.tolist(), points.lat_e6.tolist()
    rows = (
        Row(ids[0], lon[0], lat[0], 4068),
        Row(ids[1], lon[1] + 1, lat[1], 7808),  # moved since the table was built
        Row(ids[2], lon[2], lat[2], None),
    )
    table = Table(URL, 11, "0" * 64, tuple(sorted(rows, key=lambda r: r.school)))
    feet = heights_for(table, ids, points)
    assert feet[0] == 4068
    assert np.isnan(feet[1:]).all()
    assert np.isnan(heights_for(table, None, points)).all()


# --- the pin and the pass's read of it -----------------------------------------------------------


def pinned_table() -> tuple[bytes, ElevationPins]:
    data = table_bytes(GOOD)
    sha = hashlib.sha256(data).hexdigest()
    pin = TablePin(
        url=f"https://github.com/o/r/releases/download/data-mirror-x/{asset_name(sha)}",
        sha256=sha,
        schools=2,
        unknown=1,
    )
    source = Source(url=URL.replace("tiles.test", "tiles.test/t"), zoom=11, attribution="Tiles")
    return data, ElevationPins(source=source, table=pin)


def test_the_committed_pins_read() -> None:
    pins = load_pins()
    assert pins.source.zoom == 11
    assert "U.S. Geological Survey" in pins.source.attribution
    if pins.table is not None:
        assert pins.table.url.endswith(asset_name(pins.table.sha256))


def test_a_pin_whose_url_is_not_its_asset_is_refused(tmp_path: Path) -> None:
    _data, pins = pinned_table()
    assert pins.table is not None
    text = (
        "source:\n  url: 'https://t.test/{z}/{x}/{y}.png'\n  zoom: 11\n  attribution: x\n"
        f"table:\n  url: https://github.com/o/r/releases/download/t/other.json.gz\n"
        f"  sha256: '{pins.table.sha256}'\n  schools: 2\n  unknown: 1\n"
    )
    path = tmp_path / "elevation.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="does not end in"):
        load_pins(path)
    with pytest.raises(ValueError, match="SHA-256"):
        TablePin(url=pins.table.url, sha256="ABC", schools=1, unknown=0)


def test_the_pass_reads_the_pinned_table_once_and_checks_it(tmp_path: Path) -> None:
    data, pins = pinned_table()
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return data

    loaded = load_pinned(pins, tmp_path, get)
    assert loaded.table is not None
    assert loaded.problem is None
    assert load_pinned(pins, tmp_path, get).table == loaded.table
    assert len(asked) == 1  # the second read is the cache's


def test_a_table_that_is_not_the_pinned_one_is_not_used(tmp_path: Path) -> None:
    data, pins = pinned_table()
    other = table_bytes(GOOD | {"rows": [["a", 1, 2, 9999], ["b", 3, 4, None]]})
    assert "SHA-256" in str(load_pinned(pins, tmp_path, lambda _u: other).problem)
    assert pins.table is not None
    (tmp_path / pins.table.url.rsplit("/", 1)[-1]).write_bytes(other)
    assert load_pinned(pins, tmp_path, lambda _u: data).table is not None  # the cache is redone
    counted = pins.model_copy(update={"table": pins.table.model_copy(update={"schools": 3})})
    assert "counts" in str(load_pinned(counted, tmp_path / "b", lambda _u: data).problem)

    def down(_url: str) -> bytes:
        raise OSError("HTTP 502")

    failed = load_pinned(pins, tmp_path / "c", down)
    assert "HTTP 502" in str(failed.problem)
    assert failed.retry
    bare = ElevationPins(source=pins.source)
    assert load_pinned(bare, tmp_path, down) == Loaded(None, "no elevation table is pinned")
    assert not load_pinned(bare, tmp_path, down).retry
    assert school_heights(Loaded(None, "none"), world.school_ids(), world.points()) is None


# --- the replay of October 22 -------------------------------------------------------------------

NOW = datetime(2026, 10, 22, 13, 10, tzinfo=UTC)
DAY = date(2026, 10, 22)
WAWONA, EASTERN_SIERRA, MAMMOTH = 1, 2, 3
"""The world's districts standing in for Yosemite-Wawona, Eastern Sierra and Mammoth."""
FEET = {0: 4068.0, 1: 4068.0, 2: 6806.0, 3: 5375.0, 4: 7808.0}
"""The heights of the advisories' schools, given to the world's district schools."""


def oct22() -> tuple[UgcIndex, list[LiveEvent]]:
    """The October 22 feed's advisories over the world: CAZ323 holds district 1's schools,
    CAZ073 those of districts 2 and 3."""
    feed = parse_active(FIXTURE.read_bytes())
    current = [alert for alert in feed.alerts if alert.sent.date() == DAY]
    events = live_events(type(feed)(feed.updated, tuple(current)))
    index = UgcIndex({"CAZ323": np.array([0, 1]), "CAZ073": np.array([2, 3, 4])})
    return index, events


def heights() -> np.ndarray:
    found = np.full(len(world.SCHOOLS), np.nan)
    for position, feet in FEET.items():
        found[position] = feet
    return found


def test_the_october_22_advisories_reach_mammoth_and_not_wawona_or_eastern_sierra() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    index, events = oct22()
    assert {event.key for event in events} == {"KHNX.WW.Y.0005", "KREV.WW.Y.0009"}
    margin = world.CONFIG.serve.elevation_margin_feet
    classes, _private = unit_classes(
        built, events, index, [DAY], NOW, WINDOW, world.CONFIG.weather.covered_share,
        heights(), margin,
    )  # fmt: skip
    assert classes[WAWONA, 0] == WeatherClass.NONE
    assert classes[EASTERN_SIERRA, 0] == WeatherClass.NONE
    assert classes[MAMMOTH, 0] == WeatherClass.ADVISORY
    # Before heights were read (or with none known) all three were advisory days.
    before, _ = unit_classes(built, events, index, [DAY], NOW, WINDOW, 0.5)
    assert [before[d, 0] for d in (WAWONA, EASTERN_SIERRA, MAMMOTH)] == [WeatherClass.ADVISORY] * 3
    said = heights_said(events, index, heights(), margin)
    assert (said.alerts, said.left_out, said.unknown) == (2, 4, 0)
    assert said.line() == (
        "predict: 2 alerts name heights; 4 schools of their zones lie outside them, "
        "0 with no known height counted as reached"
    )
    unknown = heights_said(events, index, None, margin)
    assert (unknown.left_out, unknown.unknown) == (0, 5)
    assert heights_said([], index, None, margin).line() is None


def test_an_unknown_height_is_reached_and_counted() -> None:
    index, events = oct22()
    feet = heights()
    feet[0] = np.nan
    kept, unknown = reached_by(
        next(e for e in events if e.key == "KHNX.WW.Y.0005"), index, feet, 500
    )
    assert kept.tolist() == [0]
    assert unknown == 1


def test_the_alert_memory_keeps_the_heights_and_a_change_of_them_is_a_change() -> None:
    _index, events = oct22()
    memory = Memory(30)
    memory.update(events, NOW)
    again = Memory.from_json(30, json.loads(json.dumps(memory.as_json())))
    assert {item.event.elevation for item in again.seen.values()} == {
        ElevationLimit((Band(8000, None),))
    }
    event = events[0]
    lower = type(event)(event.key, event.ugcs, event.event, event.action,
                        ElevationLimit((Band(6000, None),)))  # fmt: skip
    plain = type(event)(event.key, event.ugcs, event.event, event.action)
    assert len({event.change_key, lower.change_key, plain.change_key}) == 3
    assert "|" not in plain.change_key.split(",")[-1]  # no heights: the key as before
    # A remembered entry whose heights do not read is kept, reaching its whole zones, and
    # counted (the pass warns): the pass never crashes on it.
    stored = memory.as_json()
    stored[0]["elevation"] = "high"
    stored[1]["elevation"] = [[8000]]
    kept = Memory.from_json(30, stored)
    assert len(kept.seen) == len(memory.seen)
    assert kept.unread_heights == 2
    assert sum(1 for item in kept.seen.values() if item.event.elevation is None) == 2
    assert Memory.from_json(30, memory.as_json()).unread_heights == 0


def test_the_pinned_command_says_whether_a_table_is_the_pinned_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data, pins = pinned_table()
    assert pins.table is not None
    table = tmp_path / "table.json.gz"
    table.write_bytes(data)
    path = tmp_path / "elevation.yaml"
    path.write_text(
        "source:\n  url: 'https://t.test/{z}/{x}/{y}.png'\n  zoom: 11\n  attribution: x\n"
        + pin_block(pins.table.url, pins.table.sha256, 2, 1)
    )
    assert main(["elevation", "pinned", "--table", str(table), "--pins", str(path)]) == 0
    assert "the pinned one" in capsys.readouterr().out
    other = tmp_path / "other.json.gz"
    other.write_bytes(table_bytes(GOOD | {"rows": [["a", 1, 2, 1], ["b", 3, 4, None]]}))
    assert main(["elevation", "pinned", "--table", str(other), "--pins", str(path)]) == 1
    assert "not the pinned one" in capsys.readouterr().out
    bare = tmp_path / "bare.yaml"
    bare.write_text(path.read_text().split("table:")[0] + "table: null\n")
    assert main(["elevation", "pinned", "--table", str(table), "--pins", str(bare)]) == 1
    assert "no table is pinned" in capsys.readouterr().out
    # A pin that names the directory it was built from: another table from that very
    # directory does not rebuild the same (exit 3); from another directory, re-pin (exit 1).
    folder = tmp_path / "schools"
    folder.mkdir()
    (folder / "meta.json").write_bytes(world.meta_bytes())
    (folder / "points.bin").write_bytes(world.points_bytes())
    digest = read_local(folder).content_sha256
    assert digest is not None
    named = tmp_path / "named.yaml"
    named.write_text(
        "source:\n  url: 'https://t.test/{z}/{x}/{y}.png'\n  zoom: 11\n  attribution: x\n"
        + pin_block(pins.table.url, pins.table.sha256, 2, 1, digest)
    )
    args = ["elevation", "pinned", "--pins", str(named), "--directory", str(folder)]
    assert main([*args, "--table", str(table)]) == 0
    assert main([*args, "--table", str(other)]) == 3
    assert "does not rebuild the same" in capsys.readouterr().out
    elsewhere = named.read_text().replace(digest, "0" * 64)
    named.write_text(elsewhere)
    assert main([*args, "--table", str(other)]) == 1
    junk = tmp_path / "junk.json.gz"
    junk.write_bytes(b"junk")
    assert main(["elevation", "pinned", "--table", str(junk), "--pins", str(path)]) == 2


def test_a_failed_table_read_is_tried_again_after_the_retry_time() -> None:
    """A transient release error costs the passes of one retry time, not the whole run; a
    table that read, or no table pinned, is kept."""
    data, _pins = pinned_table()
    table = Table.from_bytes(data)
    answers = [Loaded(None, "the pinned elevation table cannot be read (HTTP 502)", retry=True),
               Loaded(table)]  # fmt: skip
    reads: list[datetime] = []
    clock = [NOW]

    def read() -> Loaded:
        reads.append(clock[0])
        return answers[min(len(reads), len(answers)) - 1]

    pinned = PinnedTable(read=read, retry=timedelta(minutes=15), clock=lambda: clock[0])
    assert pinned.current().table is None
    clock[0] = NOW + timedelta(minutes=10)
    assert pinned.current().table is None
    assert len(reads) == 1
    clock[0] = NOW + timedelta(minutes=15)
    assert pinned.current().table == table
    clock[0] = NOW + timedelta(hours=5)
    assert pinned.current().table == table
    assert len(reads) == 2
    none = PinnedTable(read=lambda: Loaded(None, "no elevation table is pinned"),
                       retry=timedelta(minutes=15), clock=lambda: clock[0])  # fmt: skip
    first = none.current()
    clock[0] = NOW + timedelta(hours=6)
    assert none.current() is first


def test_the_pass_asks_for_heights_again_while_it_has_none() -> None:
    run = make_pass(directory=world.directory())
    given: list[np.ndarray | None] = [None, heights()]
    asked: list[int] = []

    def ask(_directory: object) -> np.ndarray | None:
        asked.append(1)
        return given[min(len(asked), len(given)) - 1]

    run.heights = ask
    directory = world.directory()
    assert run.school_heights(directory) is None
    found = run.school_heights(directory)
    assert found is not None
    assert run.school_heights(directory) is found
    assert len(asked) == 2


def test_the_learning_snapshots_count_each_zone_whole() -> None:
    """The pass serves the classes within the heights, but the snapshots the learning step
    labels live days from count each alert's zones whole, as the history labels do (E1 is
    serve only: training data stays as it was)."""
    index, events = oct22()
    run = make_pass(directory=world.directory())
    run.ugcs = lambda _d: index
    run.heights = lambda _d: heights()
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    classes, _private, whole, line = cli._classes(
        run, built, world.directory(), events, (DAY, DAY), NOW, WINDOW
    )
    assert [classes[d, 0] for d in (WAWONA, EASTERN_SIERRA, MAMMOTH)] == [
        WeatherClass.NONE, WeatherClass.NONE, WeatherClass.ADVISORY,
    ]  # fmt: skip
    assert [whole[d, 0] for d in (WAWONA, EASTERN_SIERRA, MAMMOTH)] == [WeatherClass.ADVISORY] * 3
    assert line is not None
    # With no heights known the two are one array.
    run.heights = lambda _d: None
    run._heights = None
    same, _p, again, _l = cli._classes(
        run, built, world.directory(), events, (DAY, DAY), NOW, WINDOW
    )
    assert again is same
