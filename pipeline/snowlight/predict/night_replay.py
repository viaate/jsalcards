"""GC1 and GC3's replays (design spec chart-data r3, 6.3): the night chart a pass would have made
at a past moment, from the NBM cycles on AWS as they stood then, written as the predictions
file the pass makes (every chance the calm base: the replay is of the chart, not the chances),
checked by :mod:`snowlight.predict.night_check` against the directory itself.

The pass's own code makes it: the deciding schools of :func:`snowlight.predict.cli.night_reader`,
the NBM reader (:class:`snowlight.predict.nbm.NbmReader`, cycles chosen by their S3
``LastModified`` at the moment), the guard (:func:`snowlight.predict.night_serve.night_stage`)
and :func:`snowlight.predict.serve.forecast_file` at
:attr:`~snowlight.predict.serve.Fit.NO_RECORDS`.
Only the fetch gate is open, whatever the alerts were. Writes only where it is told; the real
directory and model are read, never changed.
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from snowlight.output import write_bytes_atomic
from snowlight.predict import artifact as artifact_module
from snowlight.predict import forecast_history, learn, nbm
from snowlight.predict.calendar import is_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.inputs import read_local
from snowlight.predict.night_serve import NightValues, night_stage
from snowlight.predict.publish import check_budget
from snowlight.predict.serve import Fit, forecast_file, pass_days
from snowlight.schemas.predictions import night_day

if TYPE_CHECKING:
    from snowlight.predict import night_check


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """``predict night-replay`` and ``predict night-check``."""
    replay = actions.add_parser("night-replay", help="the night chart at past moments (GC1, GC3)")
    replay.add_argument("--site-data", type=Path, required=True, help="the directory's folder")
    replay.add_argument("--model", type=Path, default=artifact_module.ARTIFACT_PATH)
    replay.add_argument("--out", type=Path, required=True)
    replay.add_argument("at", nargs="+", help="UTC moments, 2026-01-27T02:07")
    replay.set_defaults(handler=run_replay)
    check = actions.add_parser("night-check", help="check a file's nights against the blend")
    check.add_argument("file", type=Path)
    check.add_argument("--site-data", type=Path, required=True, help="the directory's folder")
    check.set_defaults(handler=run_check)


def run_replay(args: argparse.Namespace) -> int:  # pragma: no cover - AWS
    """Write ``<out>/<moment>.json`` for each moment."""
    from snowlight.predict import cli  # noqa: PLC0415 - cli registers this module

    config = PredictConfig.load(args.config)
    directory = read_local(args.site_data)
    committed = artifact_module.load(args.model)
    model, _why = learn.serving_model(directory, committed, None, config, lambda _x, _y: None)
    # The pass's own HTTP reader (two tries, short timeouts, range reads that refuse a whole
    # file), with a replay's time: an hour a moment, not a pass's minute.
    budget = nbm.Budget(seconds=3600.0)
    client = forecast_history._client()
    client.timeout = nbm.READ_TIMEOUT
    http = nbm.NbmHttp(client, budget)
    reader = nbm.NbmReader(http.get, http.ranged)
    max_age = timedelta(minutes=config.serve.chart_nbm_max_age_minutes)
    read = cli.night_reader(reader.read, max_age, budget.start)
    args.out.mkdir(parents=True, exist_ok=True)
    classes = np.zeros((len(model.directory.district_ids), 2), dtype=np.int64)
    for text in args.at:
        now = datetime.fromisoformat(f"{text}+00:00")
        days = pass_days(now, config)
        wanted = frozenset(
            day
            for day in {night_day(now, zone) for zone in set(model.time_zone)}
            if day in days and is_school_day(day)
        )
        generated = now.replace(microsecond=0)
        requests = reader.requests

        def reads(found: frozenset[date], at: datetime = now) -> NightValues:
            return read(model, found, at)

        nights, withheld = night_stage(
            reads,
            wanted,
            generated,
            min_inches=config.serve.chart_min_inches,
        )
        made = forecast_file(
            model,
            classes,
            days,
            now,
            closed_on=lambda _day: None,
            last=None,
            fit=Fit.NO_RECORDS,
            nights=nights,
        )
        data = made.to_json_bytes()
        packed = check_budget(data, config.serve)
        write_bytes_atomic(args.out / f"{now:%Y-%m-%dT%H%M}.json", data)
        age = (
            ""
            if nights.at is None
            else f", cycle {nights.at:%m-%d %HZ}, "
            f"{(now - nights.at) / timedelta(minutes=1):.0f} min old"
        )
        line = withheld.line() or "nothing withheld"
        sys.stdout.write(
            f"{text}: {len(nights):,} nights{age}; {len(data):,} bytes ({packed:,} gzip); "
            f"{reader.requests - requests} requests; {line}\n"
        )
    sys.stdout.write(f"blend: {reader.requests} requests, {reader.bytes:,} bytes\n")
    return 0


def checked_directory(folder: Path) -> "night_check.Directory":  # pragma: no cover - files
    """The directory's schools for the check: every school's point, deployed district and
    whether it is public (not private, charter or virtual), read from the folder itself, so the
    check finds each district's deciding schools on its own."""
    from snowlight.predict import night_check  # noqa: PLC0415
    from snowlight.predict.serve import CHARTER, PRIVATE, VIRTUAL  # noqa: PLC0415

    points = read_local(folder).points
    return night_check.directory_of(
        points.lat_e6 / 1e6,
        points.lon_e6 / 1e6,
        points.district,
        (points.kind & (PRIVATE | CHARTER | VIRTUAL)) == 0,
    )


def run_check(args: argparse.Namespace) -> int:  # pragma: no cover - AWS
    """``predict night-check FILE --site-data DIR``."""
    from snowlight.predict import night_check  # noqa: PLC0415

    return night_check.main(str(args.file), checked_directory(args.site_data))
