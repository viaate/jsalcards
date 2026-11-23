"""The monthly job (D9): score a newly posted BTS month against what was published, then refit.

Scoring reads the archive snapshot kept from each day's 00Z run, the evening before across the
US (:func:`snowlight.flights.live.archive_path`, :func:`snowlight.flights.live.archive_bytes`;
a slot holding another day is not that day's) and,
for every airport, holds its departure cancel chances for the next day and its rough-day chance
to the day's flights: the Brier score per departure of what was published (a model chance or the
usual rate) against the usual rate alone, both in tenths of a percent as published, and the
rough days caught (given 30% or more). A day without a snapshot is not scored; nothing is
guessed for it.

The host keeps only :data:`snowlight.flights.live.ARCHIVE_DAYS` days of snapshots (the lead's
ruling LR-F7), but BTS posts a month about 50 days after it ends, so every run first copies the
host's snapshots into the history cache (:func:`keep_archive`, ``<raw>/archive/<day>.json``) and
scoring reads that copy first. A day lost from both before its month was scored is said with a
warning and not scored.
"""

import gzip
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights.bts import Month, kept_months, months, scan
from snowlight.flights.live import ARCHIVE_DAYS, archive_path
from snowlight.flights.model import ROUGH_SHARE
from snowlight.flights.spans import not_weather_days, weather_rows
from snowlight.schemas.flights import (
    FlightsArchive,
    FlightsModel,
    FlightsMonthScore,
    FlightsTarget,
    FlightsTrackRecord,
)

CAUGHT_PER_MILLE = 300
"""A rough day counts as caught when the evening before said this or more (30%)."""

type ReadArchive = Callable[[str], bytes | None]
type Log = Callable[[str], None]


def _days(month: Month) -> list[date]:
    first = month.first
    after = month.next().first
    return [first + timedelta(days=i) for i in range((after - first).days)]


KEPT_DAYS: Final = 200
"""The history cache keeps each day's snapshot this many days: a month is scored about 80 days
after its first day, so this leaves about 120 days for a late BTS month or a long cold start."""


def kept_path(raw: Path, day: date) -> Path:
    """Where the history cache keeps ``day``'s snapshot (:func:`keep_archive`)."""
    return raw / "archive" / f"{day.isoformat()}.json"


def keep_archive(read: ReadArchive, raw: Path, today: date, log: Log) -> bool:
    """Copy the host's snapshots of the last :data:`snowlight.flights.live.ARCHIVE_DAYS` days
    into the history cache, each only when it validates and holds its own day; drop copies
    older than :data:`KEPT_DAYS`. Whether a new copy was kept."""
    folder = raw / "archive"
    folder.mkdir(parents=True, exist_ok=True)
    new = 0
    for back in range(ARCHIVE_DAYS):
        day = today - timedelta(days=back)
        path = kept_path(raw, day)
        if path.exists():
            continue
        try:
            found = snapshot(read, day, None)
        except Exception as error:  # a host read that fails keeps what the cache has
            log(f"flights monthly: the archive of {day} not read ({type(error).__name__})")
            continue
        if found is not None:
            path.write_bytes(found.to_json_bytes())
            new += 1
    for path in sorted(folder.glob("*.json")):
        try:
            held = date.fromisoformat(path.stem)
        except ValueError:
            path.unlink()
            continue
        if held < today - timedelta(days=KEPT_DAYS):
            path.unlink()
    log(f"flights monthly: kept {new} new archive day(s) in the history cache")
    return new > 0


def lost_days(raw: Path, scored: set[str], today: date) -> list[date]:
    """The days older than the host's ring, in months the track record has not scored, whose
    snapshot the history cache lacks: they can no longer be scored."""
    out: list[date] = []
    for back in range(ARCHIVE_DAYS, KEPT_DAYS):
        day = today - timedelta(days=back)
        if f"{day.year}-{day.month:02d}" not in scored and not kept_path(raw, day).exists():
            out.append(day)
    return sorted(out)


def snapshot(read: ReadArchive, day: date, raw: Path | None = None) -> FlightsArchive | None:
    """The snapshot from ``day``'s 00Z run (the evening before ``day`` across the US), from the
    history cache's copy when ``raw`` holds one, else from the host; ``None`` when not kept,
    when it does not validate against its schema, or when it holds another day."""
    copy = kept_path(raw, day) if raw is not None else None
    data = copy.read_bytes() if copy is not None and copy.exists() else read(archive_path(day))
    if data is None:
        return None
    try:
        found = FlightsArchive.from_json_bytes(data)
    except ValueError:
        return None
    return found if found.day == day else None


def month_departures(store: Path, month: Month) -> pl.DataFrame:
    """The month's departures and cancels per airport, day and block, for :func:`score_month`.
    As in every other count (LR-F2), the non-weather spans are left out: a span's days, and an
    airline's own span days, are never scored as weather (a day with none left goes unscored,
    never guessed)."""
    return (
        scan(store, "dep")
        .filter(pl.col("day").is_between(month.first, month.next().first - timedelta(days=1)))
        .filter(weather_rows())
        .group_by("apt", "day", "block")
        .agg(pl.col("n").sum(), pl.col("canc").sum())
        .collect()
    )


def score_month(
    month: Month, read: ReadArchive, dep: pl.DataFrame, raw: Path | None = None
) -> list[FlightsMonthScore]:
    """The month's scores (``dep``: departures per airport, day and block that month), each day
    from the history cache's copy in ``raw`` when it holds one (:func:`keep_archive`), else from
    the host. An airport day the snapshot gives no usual rate for is not scored: nothing is
    guessed."""
    happened = {
        (row["apt"], row["day"], row["block"]): (row["n"], row["canc"])
        for row in dep.iter_rows(named=True)
    }
    units = brier = brier_usual = 0.0
    rough_days = caught = 0
    day_units = day_brier = day_usual = 0.0
    dep_days: set[date] = set()
    rough_scored: set[date] = set()
    days = _days(month)
    for day in days:
        found = snapshot(read, day, raw)
        if found is None:
            continue
        usual = {entry.code: entry for entry in found.usual_tomorrow}
        for entry in found.live.airports:
            base = usual.get(entry.code)
            if base is None or entry.today + timedelta(days=1) != day:
                continue
            said = entry.dep_canc[1]
            total_n = total_c = 0
            for block, percent in enumerate(said):
                got = happened.get((entry.code, day, block))
                if got is None or percent is None:
                    continue
                n, c = got
                usual_said = base.dep_canc[block]
                if usual_said is None:
                    continue
                p = percent / 1000
                q = usual_said / 1000
                units += n
                brier += c * (1 - p) ** 2 + (n - c) * p**2
                brier_usual += c * (1 - q) ** 2 + (n - c) * q**2
                total_n += n
                total_c += c
                dep_days.add(day)
            rough = entry.rough[1]
            if rough is None or total_n < 5:  # noqa: PLR2004 - a day counts with 5 departures
                continue
            hit = total_c >= ROUGH_SHARE * total_n
            rough_scored.add(day)
            day_units += 1
            day_brier += (float(hit) - rough / 1000) ** 2
            day_usual += (float(hit) - base.rough / 1000) ** 2
            if hit:
                rough_days += 1
                caught += rough >= CAUGHT_PER_MILLE
    label = f"{month.year}-{month.month:02d}"
    out: list[FlightsMonthScore] = []
    if units:
        out.append(
            FlightsMonthScore(
                month=label,
                target=FlightsTarget.DEP_CANC,
                units=round(units),
                brier=round(min(1.0, brier / units), 6),
                brier_usual=round(min(1.0, brier_usual / units), 6),
                rough_days=rough_days,
                caught=caught,
                days_in_month=len(days),
                days_scored=len(dep_days),
            )
        )
    if day_units:
        out.append(
            FlightsMonthScore(
                month=label,
                target=FlightsTarget.ROUGH,
                units=round(day_units),
                brier=round(min(1.0, day_brier / day_units), 6),
                brier_usual=round(min(1.0, day_usual / day_units), 6),
                rough_days=rough_days,
                caught=caught,
                days_in_month=len(days),
                days_scored=len(rough_scored),
            )
        )
    return out


def unscored_warning(label: str, score: FlightsMonthScore, left_out: int) -> str | None:
    """The warning for a month ``score`` that misses days, each told by its reason: ``left_out``
    days of the month lie in a non-weather span (never scored as weather), the others had no
    snapshot kept; ``None`` when every day was scored."""
    missing = score.days_in_month - score.days_scored
    if missing <= 0:
        return None
    span = min(left_out, missing)
    reasons = [
        *([f"{span} in a non-weather span, left out"] if span else []),
        *([f"{missing - span} not kept"] if missing > span else []),
    ]
    return (
        f"flights monthly: ::warning:: {label} {score.target.name.lower()} scored on "
        f"{score.days_scored} of its {score.days_in_month} days (of the rest, "
        f"{' and '.join(reasons)}): the track record says so"
    )


def merge(
    old: Sequence[FlightsMonthScore], new: Sequence[FlightsMonthScore]
) -> tuple[FlightsMonthScore, ...]:
    """The scores of every month, a month scored again replacing its old rows."""
    months = {score.month for score in new}
    kept = [score for score in old if score.month not in months]
    return tuple(sorted([*kept, *new], key=lambda s: (s.month, int(s.target))))


# --- the monthly command, in steps ---------------------------------------------------------------

HISTORY_FIRST: Final = Month(2015, 1)
FIRST_RUN: Final = date(2020, 6, 1)
AWS_FIRST: Final = date(2020, 6, 1)
"""The bucket's bulletins are fetched from this run on; a first run before it reads IEM's copy
of the NBS for the winters before (:func:`snowlight.flights.history.fetch_iem_nbs`)."""
FETCH_SECONDS: Final = 200 * 60.0
"""A run fetches history for this long at most, then stops; the next day's run goes on from
what the cache kept (a cold start takes several days)."""
MODEL_KEY: Final = "flights/model.json"
TRACK_KEY: Final = "flights/track-record.json"

type Get = Callable[[str], bytes | None]
type Write = Callable[[Mapping[str, bytes]], None]
type Step = Callable[[Path, Path, Path, date], int]
type Static = Callable[[Path, Path], int]


@dataclass(slots=True)
class Budget:
    """The fetch clock of one run: ``out`` is true once its seconds have passed, and records
    that the run stopped for it."""

    seconds: float = FETCH_SECONDS
    clock: Callable[[], float] = time.monotonic
    ran_out: bool = False
    required_out: bool = False
    """Whether the time ran out before the steps the refit needs whole were done (the BTS
    months and the bulletins); running out in the reports of the oldest months does not stop
    a publish, since the months the fit needs are fetched first (:func:`fetch_history`)."""
    start: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.start = self.clock()

    def out(self) -> bool:
        """Whether the time is up (and say so once it is)."""
        if self.clock() - self.start >= self.seconds:
            self.ran_out = True
        return self.ran_out


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a monthly run did."""

    code: int
    fetched: bool
    """Whether it kept anything new (the cache is saved only then)."""
    published: int = 0
    scored: tuple[str, ...] = ()
    said: str = ""


def published_through(read_host: Get, committed_last: date) -> Month:
    """The newest BTS month the published model's test year holds: the host's refit when it
    reads, else the committed model's (nothing published yet)."""
    data = read_host(MODEL_KEY)
    if data is not None:
        try:
            last = FlightsModel.from_json_bytes(data).test_last
        except ValueError:
            pass
        else:
            return Month(last.year, last.month)
    return Month(committed_last.year, committed_last.month)


AIRPORTS_KEY: Final = "flights/airports.json"


def host_has_files(read_host: Get) -> bool:
    """Whether the host has the Flights files a refit publishes: the airports file and a model
    file that validates. Without them the run builds and publishes everything, with or without
    a new month (the first run after landing, or a host that lost them)."""
    if read_host(AIRPORTS_KEY) is None:
        return False
    data = read_host(MODEL_KEY)
    if data is None:
        return False
    try:
        FlightsModel.from_json_bytes(data)
    except ValueError:
        return False
    return True


def publishable(out: Path) -> dict[str, bytes]:
    """Every file of a build folder (``out``: ``files/`` and ``model.json.gz``) by its key on the
    host, once the whole build validates (:func:`snowlight.schemas.site.validate_site`).

    Raises:
        ValueError: a file does not validate, the airports file or the model is missing, or
            the files take more than :data:`BUILD_BUDGET` bytes.
    """
    from snowlight.schemas.site import validate_site  # noqa: PLC0415

    root = out / "files"
    model_path = out / "model.json.gz"
    if not (root / AIRPORTS_KEY).is_file() or not model_path.is_file():
        raise ValueError(f"{out}: the build lacks the airports file or the model")
    model = gzip.decompress(model_path.read_bytes())
    (root / MODEL_KEY).write_bytes(model)
    size = sum(path.stat().st_size for path in root.rglob("*.json"))
    if size > BUILD_BUDGET:
        raise ValueError(f"{out}: the build is {size:,} bytes, over its {BUILD_BUDGET:,}")
    result = validate_site(root)
    if result.problems:
        raise ValueError(
            f"{out}: {len(result.problems)} files do not validate ({result.problems[0]})"
        )
    return {
        f"{ROOT}/{path.relative_to(root).as_posix()}": path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


BUILD_BUDGET: Final = 40_000_000
"""The most bytes the monthly build (every file but the live ones and the archive) may take; a
larger build is not published (:func:`publishable`)."""
PART_BYTES: Final = 6_000_000
"""One write to the host carries at most this many bytes (a larger commit may be refused)."""
LAST_KEYS: Final = (MODEL_KEY, TRACK_KEY)
"""Written last, in a part of their own: the model and its track record name the files before
them, so a reader never sees a new model before its files."""


def write_in_parts(files: Mapping[str, bytes], write_host: Write) -> int:
    """Write ``files`` in parts of at most :data:`PART_BYTES`, :data:`LAST_KEYS` last; how
    many writes."""
    last = {f"{ROOT}/{key}" for key in LAST_KEYS}
    parts: list[dict[str, bytes]] = [{}]
    size = 0
    for key in sorted(k for k in files if k not in last):
        if parts[-1] and size + len(files[key]) > PART_BYTES:
            parts.append({})
            size = 0
        parts[-1][key] = files[key]
        size += len(files[key])
    tail = {key: files[key] for key in sorted(last) if key in files}
    for part in [*parts, tail]:
        if part:
            write_host(part)
    return sum(1 for part in [*parts, tail] if part)


def seed(out: Path, write_host: Write, log: Log) -> int:
    """Publish a checked local build (``snowlight flights seed``): the integrator's one-time
    step so the Flights files are on the host at landing; the exit code."""
    try:
        files = publishable(out)
    except ValueError as error:
        log(f"flights seed: not published: {error}")
        return EXIT_ERROR
    writes = write_in_parts(files, write_host)
    log(f"flights seed: published {len(files)} files in {writes} writes")
    return EXIT_OK


def scored_months(read_host: Get) -> tuple[FlightsMonthScore, ...]:
    """The months the host's track record has scored."""
    data = read_host(TRACK_KEY)
    if data is None:
        return ()
    try:
        return FlightsTrackRecord.from_json_bytes(data).months
    except ValueError:
        return ()


def fetch_history(  # noqa: PLR0913 - the source, the store, the airports and the clock
    get: Get,
    raw: Path,
    *,
    first_month: Month,
    first_run: date,
    newest: Month,
    stations: Sequence[str],
    wanted: frozenset[str],
    today: date,
    log: Log,
    budget: Budget,
    get_iem: Get | None = None,
) -> bool:
    """Fetch what the cache lacks, oldest gaps last, until the budget is spent; whether any
    file was kept. ``get_iem``: the polite client for IEM's NBS (``get`` when not given)."""
    from snowlight.flights import history  # noqa: PLC0415

    every = list(months(first_month, newest))
    added = history.fetch_bts(get, raw / "bts", raw / "scratch", every, log, out_of_time=budget.out)
    # Only what the refit and the scoring need: bulletins and reports through the newest posted
    # month, so a day with no new month keeps nothing new (and saves no cache).
    last = min(today, newest.next().first - timedelta(days=1))
    runs = history.fetch_nbs(
        get,
        raw / "nbs",
        wanted,
        first=max(first_run, AWS_FIRST),
        last=last,
        log=log,
        out_of_time=budget.out,
    )
    if first_run < AWS_FIRST:
        runs += history.fetch_iem_nbs(
            get_iem or get, raw / "nbs-iem", sorted(wanted), log, out_of_time=budget.out
        )
    budget.required_out = budget.ran_out
    reports = history.fetch_obs(
        get,
        raw / "obs",
        stations,
        list(reversed(list(months(first_month, newest)))),
        log,
        out_of_time=budget.out,
    )
    return bool(added) or runs > 0 or reports > 0


def run(  # noqa: PLR0913, PLR0917 - the steps of one run, each one injectable for the tests
    raw: Path,
    out: Path,
    get: Get,
    read_host: Get,
    write_host: Write,
    log: Log,
    today: date,
    committed_last: date,
    train_all: Step,
    static_all: Static,
    stations: Sequence[str],
    wanted: frozenset[str],
    budget: Budget | None = None,
    first_month: Month = HISTORY_FIRST,
    first_run: date = FIRST_RUN,
    get_iem: Get | None = None,
) -> Outcome:
    """One monthly run: check for a new BTS month, fetch what the cache lacks (bounded), then,
    once the history is whole and the host has not published that month yet, score every
    month after the published one that the host's track record lacks, refit, rebuild and
    publish everything in one write. What is published is read back from the host each run,
    so a run stopped anywhere before the publish is done again the next day."""
    from snowlight.flights import history  # noqa: PLC0415

    budget = budget if budget is not None else Budget()
    archived = keep_archive(read_host, raw, today, log)
    lost = lost_days(raw, {score.month for score in scored_months(read_host)}, today)
    if lost:
        log(
            f"flights monthly: ::warning:: {len(lost)} archive day(s) lost before their month "
            f"was scored ({lost[0]} to {lost[-1]}): those days are not scored"
        )
    kept = kept_months(raw / "bts")
    start = kept[-1] if kept else Month(today.year, today.month).back(4)
    newest = history.newest_posted(get, start) or (kept[-1] if kept else None)
    if newest is None:
        return Outcome(EXIT_ERROR, fetched=False, said="no BTS month is posted")
    got_history = fetch_history(
        get,
        raw,
        first_month=first_month,
        first_run=first_run,
        newest=newest,
        stations=stations,
        wanted=wanted,
        today=today,
        log=log,
        budget=budget,
        get_iem=get_iem,
    )
    fetched = archived or got_history
    from snowlight.flights.build import observed_gaps  # noqa: PLC0415

    have_months = set(kept_months(raw / "bts"))
    missing = [m for m in months(first_month, newest) if m not in have_months]
    reports_missing = observed_gaps(raw / "obs", first_run, first_month, newest)
    if first_run < AWS_FIRST:
        # IEM's winters are part of the fit: a refit without them is never published.
        reports_missing += [
            f"IEM NBS {name}" for name in history.iem_nbs_missing(raw / "nbs-iem", sorted(wanted))
        ]
    if budget.required_out or missing or reports_missing:
        # Stuck from the history fetch alone: a new archive copy is kept nearly every day.
        stuck = not got_history and not budget.ran_out and bool(missing or reports_missing)
        return Outcome(
            EXIT_OK,
            fetched=fetched,
            said=("::warning:: " if stuck else "")
            + f"history not whole yet ({len(missing)} BTS months and "
            f"{len(reports_missing)} report months to go"
            + (
                f", none of them could be fetched with time to spare: "
                f"{', '.join([m.key for m in missing][:3] + reports_missing[:3])}"
                if stuck
                else ""
            )
            + "); the next run goes on",
        )
    done = published_through(read_host, committed_last)
    whole = host_has_files(read_host)
    if (done.year, done.month) >= (newest.year, newest.month) and whole:
        return Outcome(EXIT_OK, fetched=fetched, said=f"published through {done.key}: nothing new")
    if not whole:
        log("flights monthly: the host lacks the Flights files: building and publishing them all")
    old = scored_months(read_host)
    have = {score.month for score in old}
    scores: list[FlightsMonthScore] = []
    labels: list[str] = []
    for month in months(done.next(), newest):
        label = f"{month.year}-{month.month:02d}"
        if label in have:
            continue
        dep = month_departures(raw / "bts", month)
        month_scores = score_month(month, read_host, dep, raw)
        left_out = not_weather_days(month.first, month.next().first - timedelta(days=1))
        for score in month_scores:
            if (line := unscored_warning(label, score, left_out)) is not None:
                log(line)
        scores += month_scores
        labels.append(label)
    model_path = out / "model.json.gz"
    code = train_all(raw, out, model_path, first_run) or static_all(raw, out)
    if code:
        return Outcome(code, fetched=fetched, said="the refit or the files did not check out")
    track = out / "files" / TRACK_KEY
    made = FlightsTrackRecord.from_json_bytes(track.read_bytes())
    track.write_bytes(made.model_copy(update={"months": merge(old, scores)}).to_json_bytes())
    try:
        files = publishable(out)
    except ValueError as error:
        return Outcome(EXIT_ERROR, fetched=fetched, said=f"the files did not check out: {error}")
    write_in_parts(files, write_host)
    return Outcome(
        EXIT_OK,
        fetched=fetched,
        published=len(files),
        scored=tuple(labels),
        said=f"published {len(files)} files through {newest.key}, scored "
        f"{', '.join(labels) or 'no month (none new)'}",
    )


ROOT: Final = "v1"
EXIT_OK: Final = 0
EXIT_ERROR: Final = 1
