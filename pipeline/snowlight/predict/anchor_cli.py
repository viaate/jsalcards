"""``snowlight predict exposure``: build ``data/predict/exposure.json.gz`` (advisory-sane L3).

Reads the labels folder ``predict labels`` writes (``weather.parquet``, ``districts.parquet``,
``labels.parquet``) and the registered winters (``live_score.standing.seasons``), and writes
each district's storm-class days a winter, its county's medians, the national references and
the archive's region tallies of each class (:mod:`snowlight.predict.exposure`). Codes and
counts only. The same inputs give the same bytes.

It refuses to write a file whose class levels at the priors (no live labels) fail the
plausibility check (G6, Addendum A item 5) over the districts it holds, after the pull and the
backstop: such a file could only reach a pass that serves a failing chance.
"""

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

import polars as pl

from snowlight.predict import exposure, train
from snowlight.predict.anchor import NO_LABELS, AnchorSettings, Plausible, Unit, fit
from snowlight.predict.config import PredictConfig
from snowlight.predict.geography import REGION_OF


def prior_plausible(
    settings: AnchorSettings, found: exposure.Exposure, districts: pl.DataFrame
) -> Plausible:
    """The plausibility check (G6) of every district the file holds at its class levels from
    the priors alone (no live labels), as a pass would publish them."""
    places: Mapping[str, tuple[str | None, str | None]] = {
        str(leaid): (
            None if county is None else str(county),
            None if state is None else REGION_OF.get(str(state)),
        )
        for leaid, county, state in districts.select("district", "county", "state").iter_rows()
    }
    anchor = fit(settings, found, NO_LABELS, places)
    units = [Unit(leaid, *places.get(leaid, (None, None))) for leaid in sorted(found.districts)]
    return anchor.rates(units).plausible


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict exposure``."""
    parser = actions.add_parser(
        "exposure", help="each district's storm-class days a winter (data/predict)"
    )
    parser.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    parser.add_argument("--out", type=Path, default=exposure.EXPOSURE_PATH)
    parser.set_defaults(handler=run_exposure)


def run_exposure(args: argparse.Namespace) -> int:
    """Run ``predict exposure``."""
    config = PredictConfig.load(args.config)
    seasons = config.live_score["standing"]["seasons"]
    if not isinstance(seasons, list):
        sys.stderr.write("predict exposure: live_score standing seasons is not a list\n")
        return 1
    try:
        districts = pl.read_parquet(args.work / "districts.parquet")
        body = exposure.build(
            pl.read_parquet(args.work / "weather.parquet"),
            districts,
            pl.read_parquet(args.work / "labels.parquet"),
            [str(item) for item in seasons],
        )
        plausible = prior_plausible(
            AnchorSettings.of(config), exposure.parse(body, "exposure"), districts
        )
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as error:
        sys.stderr.write(f"predict exposure: {type(error).__name__}: {error}\n")
        return 1
    if not plausible.passes:
        sys.stderr.write(
            f"predict exposure: the priors fail the plausibility check, not written: "
            f"{plausible.line()}\n"
        )
        return 1
    size = exposure.write(body, args.out)
    sys.stdout.write(f"predict exposure: {args.out} ({size:,} bytes): f_ref {body['f_ref']}\n")
    return 0
