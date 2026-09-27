"""Dumps the school directory's own tables as JSON Lines for the search index.

The directory build (``snowlight directory build`` in pipeline/) publishes
schools/meta.json and schools/points.bin, and keeps the rest of what NCES
says about each school and district in two tables it never publishes:
``schools.parquet`` and ``districts.parquet`` in pipeline/out/internal/directory.
Search needs a little of that rest: the town and state a school or district
is in, and its enrollment, which ranks equal matches. This script reads those
columns and writes them, one JSON object per row, in the directory's order:

    schools.jsonl    {"index", "id", "city", "state", "enrollment"}
    districts.jsonl  {"index", "id", "city", "state", "lat", "lon"}

``enrollment`` is null where NCES reports none. Nothing is added or guessed:
scripts/stage-data.mjs checks every row against the published directory and
builds the search records from both.

Run with the pipeline's environment, which has polars:

    uv run --project ../pipeline python scripts/directory-rows.py --internal DIR --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

SCHOOL_COLUMNS = ["index", "id", "city", "state", "enrollment"]
DISTRICT_COLUMNS = ["index", "district_id", "city", "state", "lat", "lon"]


def write_rows(frame: pl.DataFrame, target: Path) -> int:
    """Write ``frame`` as JSON Lines in index order; return the row count."""
    ordered = frame.sort("index")
    with target.open("w", encoding="utf-8") as out:
        for row in ordered.iter_rows(named=True):
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return ordered.height


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--internal", type=Path, required=True, help="the directory's tables")
    parser.add_argument("--out", type=Path, required=True, help="where the .jsonl files go")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    schools = pl.read_parquet(args.internal / "schools.parquet", columns=SCHOOL_COLUMNS)
    districts = pl.read_parquet(args.internal / "districts.parquet", columns=DISTRICT_COLUMNS)
    school_count = write_rows(schools, args.out / "schools.jsonl")
    district_count = write_rows(
        districts.rename({"district_id": "id"}), args.out / "districts.jsonl"
    )
    sys.stdout.write(f"{school_count} schools, {district_count} districts\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
