"""``snowlight predict forecast-climate``: build ``data/predict/forecast-climate.json.gz``
(advisory-sane L5).

Reads the forecast history's codes (``codes-<season>.parquet``, the ``predict forecast-history``
collect output) and the labels folder ``predict labels`` writes (``weather.parquet``,
``districts.parquet``), and writes, per district, county and NOAA region, the 9 PM forecast
codes of its days of each serving class (:func:`snowlight.predict.forecast_adjust.build`).
Codes and counts only. The same inputs give the same bytes.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import polars as pl

from snowlight.predict import forecast_adjust, train


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict forecast-climate``."""
    parser = actions.add_parser(
        "forecast-climate", help="each district's 9 PM forecast codes on its storm-class days"
    )
    parser.add_argument(
        "--codes", type=Path, required=True, help="folder of the forecast history's codes-*.parquet"
    )
    parser.add_argument(
        "--window",
        choices=forecast_adjust.WINDOWS,
        required=True,
        help=(
            "how the codes counted the window period under way at 9 PM: whole (collected "
            "before SF-R5-1 was fixed, 2026-11-01) or still_to_come (collected since)"
        ),
    )
    parser.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    parser.add_argument("--out", type=Path, default=forecast_adjust.CLIMATE_PATH)
    parser.set_defaults(handler=run_climate)


def _season(first: int) -> str:
    return f"{first}-{(first + 1) % 100:02d}"


def run_climate(args: argparse.Namespace) -> int:
    """Run ``predict forecast-climate``."""
    files = sorted(args.codes.glob("codes-*.parquet"))
    if not files:
        sys.stderr.write(f"predict forecast-climate: no codes-*.parquet in {args.codes}\n")
        return 1
    try:
        codes = pl.concat(
            [
                pl.scan_parquet(path)
                .filter(pl.col("sample") == forecast_adjust.SAMPLE)
                .select("district", "night", "sample", "code_filled")
                .collect()
                for path in files
            ]
        )
        weather = pl.read_parquet(args.work / "weather.parquet")
        first = codes["night"].min()
        last = min(codes["night"].max(), weather["day"].max())  # type: ignore[type-var]
        seasons = [
            _season(day.year if day.month >= 8 else day.year - 1)  # noqa: PLR2004 - August
            for day in (first, last)
            if isinstance(day, date)
        ]
        body = forecast_adjust.build(
            codes, weather, pl.read_parquet(args.work / "districts.parquet"), seasons, args.window
        )
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as error:
        sys.stderr.write(f"predict forecast-climate: {type(error).__name__}: {error}\n")
        return 1
    size = forecast_adjust.write(body, args.out)
    districts = body["districts"]
    count = len(districts) if isinstance(districts, dict) else 0
    sys.stdout.write(
        f"predict forecast-climate: {args.out} ({size:,} bytes): {count:,} districts, "
        f"seasons {seasons[0]} to {seasons[-1]}\n"
    )
    return 0
