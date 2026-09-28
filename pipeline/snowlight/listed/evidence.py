"""Rows seen on closings lists, each tied to the recorded read it came in.

``snowlight stations fetch`` and ``snowlight stations archive parse`` write, side
by side, ``reads.jsonl`` (one read per body: live, or an archived capture, with
its SHA-256) and ``rows.jsonl`` (one raw row per line). A row names its read by
source and read time (``source_id``, ``fetched_at``: for an archived capture, the
moment the archive read the page). :func:`load_rows` ties every row to its read
and keeps it only when that is unambiguous: exactly one read of that source at
that time holds rows, and it holds as many as the rows file gives it. Anything
else is counted by reason (:data:`DROP_REASONS`) and left out.

Each row also carries the section its list files it under, when the list has
sections and the adapter kept it (:data:`SECTION_KEYS`): the matcher reads it
(``"Churches"`` and ``"Business"`` hold no schools; ``"RI Public Schools"`` names
a state), and the places it names for its organization, when its list writes
them (:mod:`snowlight.listed.located`).
"""

import json
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from snowlight.listed.located import Places, stated_places

SECTION_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    "blox-cgs-xml": ("Category",),
    "cbs-newsticker-xml-short": ("category_name1",),
    "cgs-all-active": ("category",),
    "eventdelay-list": ("category",),
    "flashalert-copy": ("category",),
    "flashalert-site-page": ("category",),
    "flathead-card-tables": ("table",),
    "flathead-closure-tables": ("table",),
    "fox-tab-list": ("category",),
    "graham-arc-page": ("category",),
    "gray-api-orgs": ("category",),
    "gray-file-flashalert": ("category",),
    "gray-file-mobile-cells": ("tab",),
    "gray-file-newsticker": ("category", "group"),
    "gray-file-newsticker-xml": ("forced_category_name", "category_name1"),
    "gray-file-sc-para": ("group",),
    "gray-file-sc-xml": ("EntityType",),
    "gray-file-ticker-xml": ("type",),
    "gray-fusion-orgs": ("category",),
    "gray-gdm-list": ("type",),
    "gray-gdm-table": ("type",),
    "gray-heartland-sc-para": ("group",),
    "gray-s3-json": ("forced_category_name",),
    "hearst-next": ("type",),
    "heritage-arc-content": ("entitytype",),
    "heritage-arc-page": ("entitytype",),
    "heritage-bti-table": ("location_type",),
    "lockwood-json": ("category_name",),
    "newsticker-html": ("group",),
    "nexstar-app-feed": ("category",),
    "nexstar-cgs-all-active": ("category",),
    "nexstar-ecc-json": ("EntityType",),
    "nexstar-newsticker-table": ("group",),
    "nexstar-page": ("category",),
    "nexstar-psg-closings": ("group",),
    "nexstar-school-information": ("group",),
    "nexstar-tribune-tab": ("tab",),
    "nexstar-typed-page": ("section",),
    "nexstar-wp-closings": ("category",),
    "snowatch-category": ("group",),
    "spectrum-json": ("orgType",),
    "weatherthreat-js": ("org_type_description",),
    "whdh-closings-block": ("category",),
    "wtop-page": ("category",),
}
"""For each list variant with sections: the row fields that name a row's section, in order.

The first one that holds text is the row's section. Fields that hold a county, a
city or an alphabetical bucket instead (``nbc-wp-json``'s ``category``,
``fox-newsticker-cell``'s ``category``, ``hearst-ibsys``'s ``bucket``) are not
sections and are not read.
"""

DROP_REASONS: Final = ("no_read", "several_reads", "count_mismatch")
"""Why a row is left out: no read of its source at its time holds rows; more than
one does; or the read's row count differs from the rows the file gives it."""


@dataclass(frozen=True, slots=True)
class Read:
    """One recorded body read, as ``reads.jsonl`` gives it (the fields used here)."""

    source_id: str
    mode: str
    fetched_at: str
    retrieved_at: str
    sha256: str
    variant: str
    rows: int


@dataclass(frozen=True, slots=True)
class ListRow:
    """One row of a closings list, tied to the read it came in."""

    source_id: str
    mode: str
    fetched_at: str
    """When the list was read (an archived capture's time), ``YYYY-MM-DDTHH:MM:SSZ``."""
    read_sha256: str
    variant: str
    name: str
    status: str
    section: str | None
    places: Places = ()
    """Where the row says its organization is (:func:`~snowlight.listed.located.stated_places`)."""


@dataclass(frozen=True, slots=True)
class LoadedRows:
    """The rows of one reads/rows pair, and what was left out."""

    rows: tuple[ListRow, ...]
    reads: tuple[Read, ...]
    dropped: Mapping[str, int]


class EvidenceError(ValueError):
    """A reads or rows file does not have the shape its writer gives it."""


def utc_text(value: str) -> str:
    """An ISO 8601 instant as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, whole seconds).

    Raises:
        EvidenceError: the text is not an instant with a time zone.
    """
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise EvidenceError(f"not an ISO instant: {value!r}") from error
    if moment.tzinfo is None:
        raise EvidenceError(f"an instant without a time zone: {value!r}")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def section_of(variant: str, extra: Mapping[str, object]) -> str | None:
    """The section a row is filed under, from its variant's fields (see :data:`SECTION_KEYS`)."""
    for key in SECTION_KEYS.get(variant, ()):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _lines(path: Path) -> Iterator[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise EvidenceError(f"{path.name}:{number}: not a JSON object")
            yield item


def _field(item: Mapping[str, object], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{where}: no {key!r}")
    return value


def read_reads(path: Path) -> list[Read]:
    """Every read in a ``reads.jsonl``, in file order.

    Raises:
        EvidenceError: a line lacks a field the reader needs.
    """
    reads: list[Read] = []
    for number, item in enumerate(_lines(path), start=1):
        where = f"{path.name}:{number}"
        rows = item.get("rows")
        if not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
            raise EvidenceError(f"{where}: no row count")
        reads.append(
            Read(
                source_id=_field(item, "source_id", where),
                mode=_field(item, "mode", where),
                fetched_at=utc_text(_field(item, "fetched_at", where)),
                retrieved_at=utc_text(_field(item, "retrieved_at", where)),
                sha256=_field(item, "sha256", where),
                variant=_field(item, "variant", where),
                rows=rows,
            )
        )
    return reads


def load_rows(reads_path: Path, rows_path: Path) -> LoadedRows:
    """Tie every row of ``rows_path`` to its read in ``reads_path`` (see the module docstring).

    Raises:
        EvidenceError: a line lacks a field the reader needs.
    """
    reads = read_reads(reads_path)
    holding: dict[tuple[str, str], list[Read]] = defaultdict(list)
    for read in reads:
        if read.rows > 0:
            holding[(read.source_id, read.fetched_at)].append(read)
    raw: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for number, item in enumerate(_lines(rows_path), start=1):
        where = f"{rows_path.name}:{number}"
        key = (_field(item, "source_id", where), utc_text(_field(item, "fetched_at", where)))
        _field(item, "raw_name", where)
        if key not in raw:
            order.append(key)
        raw[key].append(item)
    kept: list[ListRow] = []
    dropped: Counter[str] = Counter()
    for key in order:
        items = raw[key]
        candidates = holding.get(key, [])
        if not candidates:
            dropped["no_read"] += len(items)
            continue
        if len(candidates) > 1:
            dropped["several_reads"] += len(items)
            continue
        read = candidates[0]
        if read.rows != len(items):
            dropped["count_mismatch"] += len(items)
            continue
        for item in items:
            raw_extra = item.get("raw_extra")
            extra = raw_extra if isinstance(raw_extra, dict) else {}
            status = item.get("raw_status")
            kept.append(
                ListRow(
                    source_id=read.source_id,
                    mode=read.mode,
                    fetched_at=read.fetched_at,
                    read_sha256=read.sha256,
                    variant=read.variant,
                    name=str(item["raw_name"]),
                    status=status if isinstance(status, str) else "",
                    section=section_of(read.variant, extra),
                    places=stated_places(read.variant, extra),
                )
            )
    return LoadedRows(
        rows=tuple(kept),
        reads=tuple(reads),
        dropped={reason: dropped[reason] for reason in DROP_REASONS},
    )
