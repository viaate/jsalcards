"""The chance job's reader of the files our other chains write (predict-next ON-AIR): strict
first, tolerant of unknown keys only, and the stored forms that keep the two chains readable to
each other in CI for good. SYNTHETIC files only (the tests' own builders: ids and codes)."""

import inspect
import json
import re
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from predict import world
from predict.test_opens import TODAY, opens
from predict.test_publish import NOW
from snowlight.directory import build
from snowlight.directory import points as points_codec
from snowlight.notify.cli import ChanceNotifier
from snowlight.output import dumps_json
from snowlight.predict import cli, host_files, inputs
from snowlight.schemas.base import PublishedModel
from snowlight.schemas.directory import DirectoryEdition, SchoolDirectoryMeta, written_edition
from snowlight.schemas.live import (
    Closing,
    ClosingsFile,
    DayEntry,
    DayIndex,
    DayTimeline,
    OpensFile,
)
from snowlight.schemas.vocab import Detail, Reason, Status

FORMS = Path(__file__).parent / "host_files"
PREDICT = Path(host_files.__file__).parent
LATER = "x_later"
"""A key no model knows."""
READERS: dict[str, tuple[type[PublishedModel], Callable[..., Any]]] = {
    "closings": (ClosingsFile, host_files.closings),
    "opens": (OpensFile, host_files.opens),
    "timeline": (DayTimeline, host_files.timeline),
    "index": (DayIndex, host_files.index),
}


@pytest.fixture(autouse=True)
def _forgotten() -> Iterator[None]:
    host_files.forget()
    yield
    host_files.forget()


def shown() -> ClosingsFile:
    """A closings file with every part filled: a manual row, a delayed row with a shift, a
    clock and details."""
    return ClosingsFile.encode(
        [
            Closing(
                school=0,
                day=TODAY,
                status=Status.CLOSED,
                announced_at=NOW - timedelta(hours=1),
                reason=Reason.WINTER_STORM,
                manual=True,
            ),
            Closing(
                school=3,
                day=TODAY,
                status=Status.DELAYED,
                announced_at=None,
                reason=None,
                shift_minutes=120,
                clock_minute=600,
                details=(Detail.STAFF_LATE, Detail.BUSES_SNOW_ROUTES),
            ),
        ],
        generated_at=NOW,
        directory=world.STAMP,
    )


def said() -> OpensFile:
    return opens([(1, TODAY), (2, TODAY)])


def line() -> DayTimeline:
    """A day timeline with every part filled: a digest, a status taken back, a shift, a clock
    and details."""
    return DayTimeline.model_validate(
        {
            **world.timeline().model_dump(),
            "content_sha256": "ab" * 32,
            "counts": (2, 1, 1),
            "minutes": (-120, -60, -100, 300),
            "statuses": (Status.DELAYED, None, Status.REMOTE, Status.CLOSED),
            "reasons": (Reason.WINTER_STORM, None, Reason.WINTER_STORM, None),
            "shifts": (120,),
            "clocks": (600,),
            "details": ((0, (Detail.STAFF_LATE,)),),
        }
    )


def days() -> DayIndex:
    return DayIndex(
        schema_version=1,
        generated_at=NOW,
        days=(DayEntry(day=date(2026, 1, 6), schools=3, final=True),),
    )


def written() -> dict[str, PublishedModel]:
    """The four files as today's writers make them."""
    return {"closings": shown(), "opens": said(), "timeline": line(), "index": days()}


def grown(data: bytes) -> tuple[bytes, int]:
    """``data`` with a key no model knows added to every JSON object, and how many."""
    added = 0

    def grow(value: Any) -> Any:
        nonlocal added
        if isinstance(value, dict):
            added += 1
            return {**{key: grow(inner) for key, inner in value.items()}, LATER: [[0, [1]]]}
        if isinstance(value, list):
            return [grow(inner) for inner in value]
        return value

    tree = grow(json.loads(data))
    return json.dumps(tree, separators=(",", ":")).encode(), added


def unfilled(data: bytes) -> list[str]:
    """What is not filled: every empty array or object, and every key whose value is null
    everywhere it occurs."""
    found: list[str] = []
    seen: dict[str, bool] = {}

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            if not value:
                found.append(f"{where}: empty object")
            for key, inner in value.items():
                walk(inner, f"{where}.{key}")
        elif isinstance(value, list):
            if not value:
                found.append(f"{where}: empty array")
            for inner in value:
                walk(inner, f"{where}[]")
        else:
            seen[where] = seen.get(where, False) or value is not None

    walk(json.loads(data), "")
    return found + [f"{where}: always null" for where, some in sorted(seen.items()) if not some]


def warnings_of(capsys: Any) -> list[str]:
    return [text for text in capsys.readouterr().err.splitlines() if "unknown keys" in text]


def test_what_todays_writers_produce_reads_as_it_does_strictly(capsys: Any) -> None:
    for name, made in written().items():
        model, read = READERS[name]
        data = made.to_json_bytes()
        found = read(data, where=f"v1/live/{name}.json")
        assert found == model.from_json_bytes(data) == made
        assert type(found) is model
        assert unfilled(data) == [], name
    assert warnings_of(capsys) == []


def test_an_unknown_key_at_every_level_is_dropped(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    parents = {
        "closings": "(top), days[], directory",
        "opens": "(top), directory, opens[]",
        "timeline": "(top), directory",
        "index": "(top), days[]",
    }
    for name, made in written().items():
        _model, read = READERS[name]
        plain = made.to_json_bytes()
        more, added = grown(plain)
        where = f"v1/live/{name}.json"
        found = read(more, where=where)
        assert found == made
        assert found.to_json_bytes() == plain
        assert warnings_of(capsys) == [
            f"warning: predict: {where}: {added} unknown keys dropped (in {parents[name]}); "
            "the rest validates"
        ]
        assert LATER not in capsys.readouterr().err
        assert read(more, where=where) == made
        assert warnings_of(capsys) == []
        host_files.forget()
        assert read(more, where=where) == made
        assert len(warnings_of(capsys)) == 1


def test_the_warning_never_names_the_key_and_counts_past_five_places(
    capsys: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    tree = json.loads(said().to_json_bytes())
    tree["opens"] = [dict(tree["opens"][0], school=school) for school in range(8)]
    more, added = grown(json.dumps(tree).encode())
    found = host_files.opens(more, where="v1/live/opens.json")
    assert len(found.opens) == 8
    err = capsys.readouterr().err
    assert err == (
        f"::warning::predict: v1/live/opens.json: {added} unknown keys dropped (in (top), "
        "directory, opens[]); the rest validates\n"
    )
    assert LATER not in err

    class Leaf(PublishedModel):
        rows: tuple[int, ...]

    class Wide(PublishedModel):
        a: Leaf
        b: Leaf
        c: Leaf
        d: Leaf
        e: Leaf
        f: Leaf

    leaf = Leaf(rows=(1,))
    wide, added = grown(Wide(a=leaf, b=leaf, c=leaf, d=leaf, e=leaf, f=leaf).to_json_bytes())
    assert host_files.read(Wide, wide, where="toy").a == leaf
    assert capsys.readouterr().err == (
        f"::warning::predict: toy: {added} unknown keys dropped (in (top), a, b, c, d and 2 "
        "more); the rest validates\n"
    )


CASES: dict[str, Callable[[dict[str, Any]], Any]] = {
    "a status code of 99": lambda doc: doc["days"][0]["statuses"].__setitem__(0, 99),
    # Any whole reason code up to 255 reads (ALL-CLOSINGS lane T, tests/live/test_reason_codes.py).
    "a reason code of 256": lambda doc: doc["days"][0]["reasons"].__setitem__(0, 256),
    "a detail code of 99": lambda doc: doc["days"][0]["details"][0][1].__setitem__(0, 99),
    "schema_version 2": lambda doc: doc.__setitem__("schema_version", 2),
    "a missing key": lambda doc: doc.pop("generated_at"),
}


def test_an_unknown_code_version_or_repeated_key_is_refused(capsys: Any) -> None:
    plain = shown().to_json_bytes()
    where = "v1/live/closings.json"
    for change in CASES.values():
        doc = json.loads(plain)
        change(doc)
        alone = json.dumps(doc).encode()
        beside, _added = grown(alone)
        for data in (alone, beside):
            with pytest.raises(ValidationError):
                host_files.closings(data, where=where)
            with pytest.raises(ValidationError):
                ClosingsFile.from_json_bytes(data)
    text = plain.decode()
    hostile = {
        "a known key twice": text.replace('"schema_version":1', '"schema_version":1,"days":[]'),
        "a known key twice beside an unknown key": text.replace(
            '"schema_version":1', f'"schema_version":1,"days":[],"{LATER}":1'
        ),
        "an unknown key twice": text.replace(
            '"schema_version":1', f'"schema_version":1,"{LATER}":1,"{LATER}":2'
        ),
        "NaN in a known key": text.replace('"schools":11', '"schools":NaN'),
        "NaN beside an unknown key": text.replace('"schools":11', f'"schools":NaN,"{LATER}":1'),
        "NaN in an unknown key": text.replace('"schools":11', f'"schools":11,"{LATER}":NaN'),
        "Infinity in an unknown key": text.replace(
            '"schools":11', f'"schools":11,"{LATER}":[Infinity]'
        ),
        "an empty object": "{}",
        "an object of one unknown key": f'{{"{LATER}":1}}',
        "not JSON": text[:-1],
        "not JSON beside an unknown key": grown(plain)[0].decode()[:-1],
        "an array": "[]",
    }
    for name, document in hostile.items():
        assert document != text, name
        with pytest.raises(ValidationError):
            host_files.closings(document.encode(), where=where)
    # The same for the other three files: an unknown version beside unknown keys.
    for name, made in written().items():
        doc = json.loads(made.to_json_bytes())
        doc["schema_version"] = 2
        with pytest.raises(ValidationError):
            READERS[name][1](grown(json.dumps(doc).encode())[0], where=name)
    assert warnings_of(capsys) == []


def test_what_is_left_must_pass_the_models_own_rules(capsys: Any) -> None:
    doc = json.loads(shown().to_json_bytes())
    doc["days"][0]["reasons"] = [0]  # two statuses, one reason
    doc["days"][0][LATER] = 1
    with pytest.raises(ValidationError) as refused:
        host_files.closings(json.dumps(doc).encode(), where="v1/live/closings.json")
    # The second, strict validation refused it: the unknown key is gone from its errors.
    assert all(error["type"] != "extra_forbidden" for error in refused.value.errors())
    day = json.loads(line().to_json_bytes())
    day["counts"] = [2, 1]  # three schools, two counts
    day["directory"][LATER] = 1
    with pytest.raises(ValidationError) as refused:
        host_files.timeline(json.dumps(day).encode(), where="v1/live/days/2026-01-06.json")
    assert all(error["type"] != "extra_forbidden" for error in refused.value.errors())
    assert warnings_of(capsys) == []


def test_only_the_chance_job_reads_tolerantly() -> None:
    for name, made in written().items():
        model, _read = READERS[name]
        with pytest.raises(ValidationError):
            model.from_json_bytes(grown(made.to_json_bytes())[0])
    strict = re.compile(r"\b(ClosingsFile|OpensFile|DayTimeline|DayIndex)\.from_json_bytes\b")
    for path in sorted(PREDICT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not strict.search(source), path.name
        if path.name != "host_files.py":
            assert "host_files.read(" not in source, path.name
            assert not re.search(
                r"\bfrom snowlight\.predict\.host_files import\b.*\bread\b", source
            )
    own = (PREDICT / "host_files.py").read_text(encoding="utf-8")
    assert len(re.findall(r"(?<![\w.])read\(", own)) == len(READERS)  # its four functions' calls
    for _model, read in READERS.values():
        assert re.search(r"return read\(\w+, data, where=where\)", inspect.getsource(read))
    notifier = inspect.getsource(ChanceNotifier.__call__)
    assert "from_json_bytes" not in notifier
    assert "self.parse(data)" in notifier
    assert "host_files.closings" in inspect.getsource(cli._make_notifier)


# --- the stored forms ---------------------------------------------------------------------------


def forms() -> list[Path]:
    """The dated folders, oldest first."""
    found = sorted(path for path in FORMS.iterdir() if path.is_dir() and path.name != "next")
    assert found
    for path in found:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}[a-z]?", path.name), path.name
    return found


def stored() -> list[Path]:
    """Every stored file: the dated forms' and the coming ones' (``next/``)."""
    folders = [*forms(), *([FORMS / "next"] if (FORMS / "next").is_dir() else [])]
    return [path for folder in folders for path in sorted(folder.iterdir())]


def newest(name: str) -> Path:
    """The newest dated form of a file."""
    found = [folder / name for folder in forms() if (folder / name).is_file()]
    assert found, name
    return found[-1]


def directory_of(folder: Path) -> tuple[bytes, bytes, bytes]:
    """The directory's three files as a form reads them: its own, else the newest older."""
    older = [item for item in forms() if item.name <= folder.name]
    found = []
    for name in ("edition.json", "meta.json", "points.bin"):
        held = [item / name for item in older if (item / name).is_file()]
        assert held, name
        found.append(held[-1].read_bytes())
    return found[0], found[1], found[2]


def test_every_stored_form_reads_and_the_newest_is_what_today_writes(capsys: Any) -> None:
    """The rule of docs/predict.md, "Staying on air", held in CI for good.

    ``tests/predict/host_files/<form>/`` holds the files our other chains write as they have
    written them: a form is a folder named by the date of the commit that first wrote it
    (``YYYY-MM-DD``, a letter after it for a second on one day), holding only the files whose
    form changed then; ``next/`` holds a form no writer writes yet.

    (i) Every stored file of every folder reads, through the chance job's own functions, with
    no "unknown keys dropped" warning: a commit whose reader can no longer read a stored form
    fails here, and a key this code no longer reads must be removed by name in the file's
    function, never dropped unseen.

    (ii) The newest dated form of each file is, byte for byte, what today's writer writes for
    the content read from it, and it is filled (no empty array or object, no key that is null
    everywhere): a commit that changes what a writer writes fails here until it stores the new
    form beside the old ones.

    Neither half is ever dropped, and a stored form is removed only by a commit that says why
    no file of that form can be read any more (no writer of it is running and, for a day
    timeline, no day of that form is left in the index).
    """
    names = {f"{name}.json" for name in READERS} | {"edition.json", "meta.json", "points.bin"}
    # Half (i): every stored file reads.
    for path in stored():
        assert path.name in names, path
        if path.stem in READERS and path.suffix == ".json":
            READERS[path.stem][1](path.read_bytes(), where=f"{path.parent.name}/{path.name}")
        else:
            edition, meta, points = directory_of(path.parent)
            found, _meta = inputs.directory_from_files(
                DirectoryEdition.from_json_bytes(edition), meta, points
            )
            assert found.stamp == DirectoryEdition.from_json_bytes(edition).stamp()
    assert warnings_of(capsys) == []
    # Half (ii): the newest form is what today's writers write, and is filled.
    for name, (model, _read) in READERS.items():
        data = newest(f"{name}.json").read_bytes()
        assert model.from_json_bytes(data).to_json_bytes() == data, name
        assert unfilled(data) == [], name
    edition = newest("edition.json").read_bytes()
    meta = newest("meta.json").read_bytes()
    points = newest("points.bin").read_bytes()
    assert DirectoryEdition.from_json_bytes(edition).to_json_bytes() == edition
    assert written_edition(meta, points).to_json_bytes() == edition
    read = SchoolDirectoryMeta.from_json_bytes(meta)
    rebuilt = build.meta_document(
        pl.DataFrame({"id": list(read.ids), "name": list(read.names)}),
        pl.DataFrame({"district_id": list(read.districts.ids), "name": list(read.districts.names)}),
        read.generated_on.isoformat(),
        {"private": read.school_years.private, "public": read.school_years.public},
    )
    assert dumps_json(rebuilt) == meta
    decoded = points_codec.decode(points)
    again = points_codec.encode(
        decoded.lon_e6, decoded.lat_e6, decoded.district, decoded.kind, decoded.district_count
    )
    assert again == points
    assert unfilled(edition) == []
    assert unfilled(meta) == []
    # Stored at landing: today's seven files, and the timeline before `details` (the final day
    # files of earlier days keep that form on the host, and the label step still reads them).
    assert {path.name for path in (FORMS / "2026-11-10").iterdir()} == names
    older = json.loads((FORMS / "2026-11-08" / "timeline.json").read_bytes())
    assert "details" not in older
    assert host_files.timeline(json.dumps(older), where="older").details == ()


def test_the_stored_forms_are_the_tests_own_builders() -> None:
    """Synthetic: the stored files are exactly what this file's builders give."""
    for name, made in written().items():
        assert (FORMS / "2026-11-10" / f"{name}.json").read_bytes() == made.to_json_bytes()
    meta, points = world.meta_bytes(), world.points_bytes()
    assert (FORMS / "2026-11-10" / "meta.json").read_bytes() == meta
    assert (FORMS / "2026-11-10" / "points.bin").read_bytes() == points
    edition = written_edition(meta, points).to_json_bytes()
    assert (FORMS / "2026-11-10" / "edition.json").read_bytes() == edition
    before = json.loads(line().to_json_bytes())
    del before["details"]
    assert json.loads((FORMS / "2026-11-08" / "timeline.json").read_bytes()) == before


def test_a_key_added_then_changed_fails_the_stored_form() -> None:
    """The hole a single stored form left, on toy models: a key added with a default and
    stored (half ii), then its type changed, no longer reads (half i)."""

    class First(PublishedModel):
        schema_version: int
        rows: tuple[int, ...]

    class Added(First):
        notes: tuple[int, ...] = ()

    class Changed(First):
        notes: tuple[tuple[int, int], ...] = ()

    first = First(schema_version=1, rows=(1, 2)).to_json_bytes()
    # Half (ii) makes the commit that adds the key store its form: the old one is not what
    # the new writer writes, and a form with the key left empty is not filled.
    assert host_files.read(Added, first, where="toy").to_json_bytes() != first
    assert unfilled(Added(schema_version=1, rows=(1, 2)).to_json_bytes()) == [".notes: empty array"]
    form = Added(schema_version=1, rows=(1, 2), notes=(1, 2)).to_json_bytes()
    assert host_files.read(Added, form, where="toy").to_json_bytes() == form
    assert unfilled(form) == []
    # Half (i) stops the later commit: the oldest form still reads, the stored one does not.
    assert host_files.read(Changed, first, where="toy").notes == ()
    with pytest.raises(ValidationError):
        host_files.read(Changed, form, where="toy")
