"""Where the weights build keeps its downloads, and reuse of copies other builds already hold.

Every file is cached under ``pipeline/.cache/weights/<host>/<path>`` through
:class:`snowlight.sources.nws.http.HttpCache`, next to its provenance sidecar
(URL, SHA-256, retrieval time). Other parts of the pipeline cache some of the
same official files with the same layout (the NWS county shapefile under
``.cache/weather/``, the Census and DMA reference files under
``.cache/stations/reference/``). Before downloading, :meth:`WeightsCache.fetch`
looks there: a copy whose sidecar names the same URL and whose bytes still hash
to the recorded SHA-256 is linked (or copied) into this cache with its sidecar,
so a file is never downloaded twice. The other caches are only read.
"""

import os
import shutil
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from snowlight.sources.nws.http import CachedFile, HttpCache, sidecar_path

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PIPELINE_ROOT / ".cache" / "weights"
SIBLING_CACHE_DIRS: tuple[Path, ...] = (
    PIPELINE_ROOT / ".cache" / "weather",
    PIPELINE_ROOT / ".cache" / "stations" / "reference",
)


class CacheLayoutError(ValueError):
    """A URL cannot be mapped to a cache path."""


def cache_path(root: Path, url: str, *, suffix: str = "") -> Path:
    """Return ``root/<host>/<path segments>`` for ``url`` (plus ``suffix`` on the last segment).

    The query string is not part of the path; callers that fetch several queries
    of one path pass a distinguishing ``suffix`` or build the path themselves.

    Raises:
        CacheLayoutError: the URL has no host or path, or a ``.``/``..`` segment.
    """
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if not parts.hostname or not segments or any(s in {".", ".."} for s in segments):
        raise CacheLayoutError(f"cannot cache {url!r}")
    segments[-1] += suffix
    return root.joinpath(parts.hostname, *segments)


def _link_or_copy(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.adopt")
    tmp.unlink(missing_ok=True)
    try:
        os.link(source, tmp)
    except OSError:
        shutil.copyfile(source, tmp)
    tmp.replace(dest)


class WeightsCache:
    """The weights build's view of the download cache."""

    def __init__(
        self,
        cache: HttpCache,
        root: Path = DEFAULT_CACHE_DIR,
        siblings: tuple[Path, ...] = SIBLING_CACHE_DIRS,
    ) -> None:
        self.cache = cache
        self.root = root
        self.siblings = tuple(
            sibling for sibling in siblings if sibling.resolve() != root.resolve()
        )
        self.adopted: list[str] = []
        """URLs whose bytes came from another build's cache in this run."""

    def adopt(self, url: str, dest: Path) -> CachedFile | None:
        """Link a verified copy of ``url`` from a sibling cache to ``dest``, if one exists."""
        relative = dest.relative_to(self.root)
        for sibling in self.siblings:
            found = self.cache.cached(url, sibling / relative)
            if found is None:
                continue
            _link_or_copy(found.path, dest)
            _link_or_copy(sidecar_path(found.path), sidecar_path(dest))
            self.adopted.append(url)
            return self.cache.cached(url, dest)
        return None

    def fetch(
        self,
        url: str,
        dest: Path | None = None,
        *,
        max_age: timedelta | None = None,
        expected_md5: str | None = None,
    ) -> CachedFile:
        """Return a verified copy of ``url``: cached, adopted from a sibling cache, or downloaded.

        ``max_age`` is :meth:`HttpCache.fetch`'s (``None``: a cached copy is final).
        """
        target = dest if dest is not None else cache_path(self.root, url)
        if self.cache.cached(url, target) is None:
            self.adopt(url, target)
        return self.cache.fetch(url, target, max_age=max_age, expected_md5=expected_md5)
