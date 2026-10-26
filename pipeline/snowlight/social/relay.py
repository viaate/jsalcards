"""Hands the fresh cards from the render job to the post job (social-post.yml).

The browser runs in its own job, which holds no secret and has no environment: it parses a
third party's map tiles and the live site with no sandbox, so it never shares a machine with
the X, Anthropic and Cloudflare secrets. Its cards reach the post job through the render
job's own (public) log, which the post job reads with its ``GITHUB_TOKEN``
(``actions: read``): no artifact, cache or third-party action.

* :func:`send` (render job) prints the folder's few known files as one base64 bundle in
  lines of :data:`LINE` characters, each starting with :data:`MARK`, and writes the bundle's
  SHA-256 as the job output ``digest``.
* :func:`receive` (post job) takes those lines back out of the log, checks the count, the
  size and the digest the render job gave, and writes only the known file names, each
  within its size, to a fresh folder. Anything else in the log is ignored; anything wrong
  gives no folder, and the post falls back to the library's dated card.
"""

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

MARK: Final = "social-relay"
LINE: Final = 1000
"""Base64 characters a log line carries."""
FILES: Final[Mapping[str, int]] = {
    "picture.json": 64 * 1024,
    "dev-log.json": 64 * 1024,
    "waitlist.json": 64 * 1024,
    "dev-log.png": 5 * 1024 * 1024,
    "waitlist.png": 5 * 1024 * 1024,
}
"""The files the post job takes, each with its largest size (a card is under X's 5 MB)."""
MAX_BUNDLE: Final = 14 * 1024 * 1024
"""The largest bundle, in base64 characters."""
DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")
ROW: Final = re.compile(rf"{MARK} (\d{{5}}) ([A-Za-z0-9+/=]{{1,{LINE}}})$")
END: Final = re.compile(rf"{MARK} end (\d{{1,5}}) ([0-9a-f]{{64}})$")


class RelayError(ValueError):
    """The bundle is missing, cut, too big or not the one the render job made."""


def bundle(folder: Path) -> bytes:
    """The folder's known files as one JSON bundle (a missing file is left out)."""
    files = {
        name: base64.b64encode(path.read_bytes()).decode("ascii")
        for name, most in FILES.items()
        if (path := folder / name).is_file() and path.stat().st_size <= most
    }
    return json.dumps({"files": files}, sort_keys=True).encode("ascii")


def send(folder: Path, write: Callable[[str], None], output: Path | None) -> str:
    """Print the bundle's lines with ``write`` and write its digest to the job's outputs
    file; the digest.

    Raises:
        RelayError: the folder holds no picture, or the bundle is too big.
    """
    if not (folder / "picture.json").is_file():
        raise RelayError("the render left no picture.json")
    data = base64.b64encode(bundle(folder)).decode("ascii")
    if len(data) > MAX_BUNDLE:
        raise RelayError("the cards are too big to hand over")
    digest = hashlib.sha256(data.encode("ascii")).hexdigest()
    rows = [data[start : start + LINE] for start in range(0, len(data), LINE)]
    for number, row in enumerate(rows, start=1):
        write(f"{MARK} {number:05d} {row}")
    write(f"{MARK} end {len(rows)} {digest}")
    if output is not None:
        with output.open("a", encoding="ascii") as handle:
            handle.write(f"digest={digest}\n")
    return digest


def _data(log: str) -> tuple[str, str]:
    """The bundle's base64 and the digest its end line names, from the log."""
    rows: list[str] = []
    for line in log.splitlines():
        at = line.find(f"{MARK} ")
        if at < 0:
            continue
        text = line[at:].rstrip()
        if found := ROW.match(text):
            if int(found.group(1)) != len(rows) + 1:
                raise RelayError("the bundle's lines are out of order")
            rows.append(found.group(2))
        elif (found := END.match(text)) is not None:
            if int(found.group(1)) != len(rows) or not rows:
                break
            data = "".join(rows)
            if len(data) > MAX_BUNDLE:
                raise RelayError("the bundle is too big")
            return data, found.group(2)
    raise RelayError("the bundle is missing or cut")


def _files(data: str) -> dict[str, bytes]:
    try:
        files = json.loads(base64.b64decode(data, validate=True))["files"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        raise RelayError("the bundle does not decode") from None
    if not isinstance(files, dict) or not set(files) <= set(FILES):
        raise RelayError("the bundle holds a file the post job does not take")
    decoded: dict[str, bytes] = {}
    for name, value in files.items():
        try:
            decoded[name] = base64.b64decode(str(value), validate=True)
        except binascii.Error:
            raise RelayError(f"{name} does not decode") from None
        if len(decoded[name]) > FILES[name]:
            raise RelayError(f"{name} is too big")
    return decoded


def receive(log: str, digest: str, out: Path) -> list[str]:
    """Write the bundle the render job's log holds to ``out``; the names written.

    Raises:
        RelayError: no bundle, a cut or reordered one, a digest that differs, or a file
            that is not one the post job takes.
    """
    if not DIGEST.match(digest):
        raise RelayError("the render job gave no digest")
    data, named = _data(log)
    if hashlib.sha256(data.encode("ascii")).hexdigest() != digest or named != digest:
        raise RelayError("the bundle is not the one the render job made")
    decoded = _files(data)
    out.mkdir(parents=True, exist_ok=True)
    for name, content in decoded.items():
        (out / name).write_bytes(content)
    return sorted(decoded)
