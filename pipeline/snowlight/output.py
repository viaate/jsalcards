"""Deterministic, atomic writers for the files the website reads.

Every artifact the site fetches goes through these helpers so that:

* the same input always produces byte-identical output (stable diffs and caches);
* a reader never sees a half-written file (write to a temp file, then rename);
* invalid JSON (NaN, Infinity) is refused instead of silently shipped.
"""

import json
import os
import tempfile
from pathlib import Path

type JSONValue = bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None


def dumps_json(value: JSONValue) -> bytes:
    """Serialize ``value`` to compact, key-sorted UTF-8 JSON.

    Raises:
        ValueError: if ``value`` contains NaN or an infinity, which JSON cannot represent.
        TypeError: if ``value`` contains something that is not a JSON value.
    """
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers see either the old file or the new one.

    Parent directories are created as needed. The temporary file lives in the
    destination directory so the final rename never crosses a filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.chmod(0o644)
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, value: JSONValue) -> None:
    """Serialize ``value`` with :func:`dumps_json` and write it atomically to ``path``.

    Serialization happens before the file is touched, so a value that cannot be
    encoded leaves any existing file unchanged.
    """
    write_bytes_atomic(path, dumps_json(value))
