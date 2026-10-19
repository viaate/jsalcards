"""The code parts of a ``derived_version``: digests of the files a derivation depends on.

A stored derivation is reused while its ``derived_version`` holds (spec S6, T4), so the
version must change whenever the reader, the matcher or the live code could derive
something else. Hand-kept version strings are not enough (a reader change without a
bump would reuse every stored reading), so each part here is the SHA-256 of the
sorted source files and tables it covers:

* :func:`reader_version`: the status reader, ``snowlight/classify/*.py``;
* :func:`matcher_version`: the matcher (``snowlight/match/*.py``), the listing
  matcher and its guards (``snowlight/listed/{matching,scope,located,evidence}.py``)
  and the committed alias table (``config/aliases.yaml``);
* :func:`live_version`: the live code, the replay gates it reuses and the status and
  reason vocabularies (``snowlight/live/*.py``, ``snowlight/replays/{gates,build,rows}.py``,
  ``snowlight/schemas/vocab.py``).

The directory edition, the rules' digest, the gazetteer's and each station's record are
added by the resolver. Each digest
is computed once per process.
"""

import hashlib
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Final

PACKAGE: Final = Path(__file__).resolve().parents[1]
"""The ``snowlight`` package."""
PIPELINE: Final = PACKAGE.parent


def files_digest(paths: Iterable[Path], *, root: Path = PIPELINE) -> str:
    """SHA-256 over each file's path (relative to ``root``) and bytes, in sorted order.

    Raises:
        FileNotFoundError: a listed file does not exist.
    """
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


@cache
def reader_version() -> str:
    """The status reader's part."""
    return "f5-" + files_digest((PACKAGE / "classify").glob("*.py"))


@cache
def matcher_version() -> str:
    """The matcher's part."""
    listed = [
        PACKAGE / "listed" / f"{name}.py" for name in ("matching", "scope", "located", "evidence")
    ]
    return "f6-" + files_digest(
        [*(PACKAGE / "match").glob("*.py"), *listed, PIPELINE / "config" / "aliases.yaml"]
    )


def live_files() -> list[Path]:
    """The files :func:`live_version` digests."""
    replays = [PACKAGE / "replays" / f"{name}.py" for name in ("gates", "build", "rows")]
    vocab = PACKAGE / "schemas" / "vocab.py"
    return sorted([*(PACKAGE / "live").glob("*.py"), *replays, vocab])


@cache
def live_version() -> str:
    """The live code's part."""
    return "live-" + files_digest(live_files())


def reader_matcher_version() -> str:
    """What :class:`~snowlight.live.resolve.Resolver` takes as ``version`` in the live ingest."""
    return f"{reader_version()}|{matcher_version()}"
