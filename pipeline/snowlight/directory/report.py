"""The build report: every source row either kept or explained, by state.

:func:`reconcile` turns an assembled frame (one row per source row, with a
``drop_reason``) into counts and refuses to continue unless, overall and within
every state, ``kept + sum(dropped) == source rows``. :func:`render_markdown`
prints the same numbers as tables for people.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import polars as pl

from snowlight.directory.filters import REASON_DESCRIPTIONS, Reason
from snowlight.directory.supplement import EXPIRY_WARNING_DAYS

UNKNOWN_STATE = "unknown"


class ReconciliationError(RuntimeError):
    """Kept and dropped rows do not add up to the source row count."""


def _reason_counts(frame: pl.DataFrame) -> dict[str, int]:
    dropped = frame.filter(pl.col("drop_reason").is_not_null())
    counts = dropped.group_by("drop_reason").agg(n=pl.len()).sort("drop_reason")
    return {str(row["drop_reason"]): int(row["n"]) for row in counts.iter_rows(named=True)}


def reconcile(
    frame: pl.DataFrame, source_rows: int, what: str, reasons: Sequence[Reason]
) -> dict[str, Any]:
    """Count kept and dropped rows overall and per ``state``; check they add up.

    ``reasons`` lists every filter that applies to this set, in order; each is
    counted in the totals even when it dropped nothing.

    Raises:
        ReconciliationError: if ``frame`` does not have exactly ``source_rows``
            rows, carries a reason not in ``reasons``, or kept + dropped differs
            from the row count anywhere.
    """
    if frame.height != source_rows:
        raise ReconciliationError(f"{what}: {frame.height} rows assembled from {source_rows}")
    found = frame["drop_reason"].drop_nulls().unique().to_list()
    unknown = [reason for reason in found if reason not in reasons]
    if unknown:
        raise ReconciliationError(f"{what}: undocumented drop reasons {unknown}")
    kept = frame.filter(pl.col("drop_reason").is_null()).height
    counted = _reason_counts(frame)
    dropped = {reason.value: counted.get(reason.value, 0) for reason in reasons}
    if kept + sum(dropped.values()) != source_rows:
        raise ReconciliationError(f"{what}: kept {kept} + dropped {dropped} != {source_rows}")
    by_state: dict[str, dict[str, Any]] = {}
    states = frame.with_columns(pl.col("state").fill_null(UNKNOWN_STATE))
    for (state,), rows in sorted(states.group_by("state"), key=lambda item: str(item[0][0])):
        state_kept = rows.filter(pl.col("drop_reason").is_null()).height
        state_dropped = _reason_counts(rows)
        if state_kept + sum(state_dropped.values()) != rows.height:
            raise ReconciliationError(f"{what}: {state} does not add up")
        by_state[str(state)] = {
            "source_rows": rows.height,
            "kept": state_kept,
            "dropped": state_dropped,
        }
    if sum(entry["source_rows"] for entry in by_state.values()) != source_rows:
        raise ReconciliationError(f"{what}: states do not sum to {source_rows}")
    return {"source_rows": source_rows, "kept": kept, "dropped": dropped, "by_state": by_state}


def _cell(entry: Mapping[str, Any] | None) -> str:
    if entry is None:
        return "-"
    return f"{entry['kept']:,} / {entry['source_rows']:,}"


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the build report as Markdown tables."""
    public, private, districts = report["public"], report["private"], report["districts"]
    empty: dict[str, Any] = {"source_rows": 0, "kept": 0, "dropped": {}, "by_state": {}}
    supplement = report.get("supplement", empty)
    lines = [
        "# School directory build report",
        "",
        f"Generated {report['generated_at']}.",
        "",
        "## Totals",
        "",
        "| | Source rows | Kept | Dropped |",
        "|---|---:|---:|---:|",
    ]
    for label, section in (
        ("Public schools", public),
        ("Private schools", private),
        ("Supplement schools (private)", supplement),
        ("Districts (LEA file)", districts),
    ):
        dropped = sum(section["dropped"].values())
        lines.append(
            f"| {label} | {section['source_rows']:,} | {section['kept']:,} | {dropped:,} |"
        )
    lines += ["", "## Dropped rows by reason", "", "| Set | Reason | Rows | Meaning |"]
    lines.append("|---|---|---:|---|")
    sets = (
        ("public", public),
        ("private", private),
        ("supplement", supplement),
        ("districts", districts),
    )
    for label, section in sets:
        for reason, count in section["dropped"].items():
            meaning = REASON_DESCRIPTIONS[Reason(reason)]
            lines.append(f"| {label} | `{reason}` | {count:,} | {meaning} |")
    lines += [
        "",
        "## By state (kept / source rows)",
        "",
        "| State | Public schools | Private schools | Supplement schools | Districts |",
        "|---|---:|---:|---:|---:|",
    ]
    states = sorted(
        set(public["by_state"])
        | set(private["by_state"])
        | set(supplement["by_state"])
        | set(districts["by_state"])
    )
    for state in states:
        lines.append(
            f"| {state} | {_cell(public['by_state'].get(state))} | "
            f"{_cell(private['by_state'].get(state))} | "
            f"{_cell(supplement['by_state'].get(state))} | "
            f"{_cell(districts['by_state'].get(state))} |"
        )
    by_source = supplement.get("kept_by_source", {})
    if by_source:
        lines += ["", "## Supplement schools kept, by source", "", "| Source | Schools |"]
        lines.append("|---|---:|")
        lines += [f"| {source} | {count:,} |" for source, count in by_source.items()]
    by_address = supplement.get("kept_by_address_source", {})
    if by_address:
        lines += ["", "## Supplement schools kept, by address source", ""]
        lines += ["| Address matched against | Schools |", "|---|---:|"]
        lines += [f"| {source} | {count:,} |" for source, count in by_address.items()]
    if "oldest_evidence_on" in supplement:
        lines += [
            "",
            "## Supplement checks",
            "",
            "- Oldest evidence that an entry operates: "
            f"{supplement['oldest_evidence_on'] or 'none'} "
            "(entries whose evidence is from before last school year or older than "
            f"{supplement['max_evidence_age_days']} days are dropped as `evidence_stale`).",
            "- Oldest match of an entry's street address against a current source: "
            f"{supplement['oldest_address_checked_on'] or 'none'} (entries not matched since "
            "August 1 of this school year are dropped as `address_stale`).",
            f"- Nearby NCES schools reviewers ruled are other schools: "
            f"{supplement['near_nces_cleared']:,}.",
        ]
        listed = supplement["listed_by_nces"]
        lines.append(f"- Entries the NCES files now list: {len(listed):,}.")
        lines += [f"  - {entry} is NCES {nces_id}" for entry, nces_id in listed.items()]
        soon = supplement.get("expiring", [])
        lines.append(
            f"- Kept entries whose evidence or address goes stale within "
            f"{EXPIRY_WARNING_DAYS} days: {len(soon):,}"
            + ("." if not soon else " (check each again before the date):")
        )
        lines += [
            f"  - {e['id']} {e['name']}: {e['what']} goes stale on {e['expires_on']}" for e in soon
        ]
    check = report.get("tileset_check")
    if check:
        per_zoom = ", ".join(f"z{z}: {n:,}" for z, n in check["schools_per_zoom"].items())
        lines += [
            "",
            "## Tileset check",
            "",
            f"Decoded {check['tiles']:,} tiles holding {check['feature_instances']:,} "
            "features; every feature's id, name, kind and position matched its school.",
            f"Schools present per zoom: {per_zoom}.",
            f"String-pool collision pairs kept apart: {check['string_pool_pairs_separated']}.",
        ]
    extra = report.get("notes", [])
    if extra:
        lines += ["", "## Notes", ""]
        lines += [f"- {note}" for note in extra]
    outputs = report.get("outputs", {})
    if outputs:
        lines += ["", "## Published files", "", "| File | Bytes | Gzipped bytes |"]
        lines.append("|---|---:|---:|")
        for name, info in sorted(outputs.items()):
            lines.append(f"| {name} | {info['bytes']:,} | {info['gzip_bytes']:,} |")
    return "\n".join(lines) + "\n"
