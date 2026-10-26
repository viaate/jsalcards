"""The model learns on its own from the days the live pipeline read (S7-L, spec addenda c, d).

``snowlight predict learn`` runs inside the predict workflow, at the start of every run of
its chain (so the first run after the day's last decision time, and after a storm day,
takes the day in). Each run:

1. **Labels the new live days** (:mod:`snowlight.predict.live_labels`): every school day of
   the last ``morning_reads_days`` that is over everywhere, whose morning record reads and
   reaches past every read window, with a final timeline (or none, while the host's index
   does not list the day), and not yet in the store. A labeled day is frozen: it is never
   labeled again, so a rerun changes nothing; a day that is not ready is skipped, not frozen,
   and waits. The store (``predictions/learn.json`` on the live host, :class:`LearnStore`)
   keeps every labeled live district-day as the district's position in its LEAID table, by
   situation and by what the district did. Unknown district-days are counted, never kept as
   labels. A day in ``excluded_days`` (found misread) is never labeled, fit or held out.
   A day waits while its previous school day waits (not labeled yet but still able to be):
   which districts it follows a closing of is told only from that day's labels, so a day
   is never frozen with its day-after districts missing. A previous school day that can
   never be labeled (no record of its reads, a damaged record, excluded, or out of reach)
   counts as no closing, as in the archive.
2. **Holds out the newest days**: from the newest labeled day back, whole days until they
   hold ``holdout_min_storm_rows`` storm district-days (weather class not ``none``) over at
   least ``holdout_min_storm_days`` days and ``holdout_min_states`` states, never more than
   ``holdout_max_share`` of the labeled days. Everything before is the fit; the held-out days
   are only ever scored against, so a day enters a model only after a later check (a bad day
   of misread labels is in the fit only when newer days judge it). Too few held out: nothing
   is decided, the model is unchanged.
3. **Refits** (:func:`learned_from`): the committed model's archive counts plus the live
   counts of the fit days. A storm situation with ``anchor_min_days`` or more live-read
   district-days nationally in the fit, and ``holdout_min_situation_rows`` or more held out to
   check it on, is **re-anchored** (addendum d, the launch gate): its rates are counted over
   the live days at every level, the nation's being their record, and the archive gives each
   place's relative propensity only (each level shrinks toward the live rate above it times
   the archive's odds ratio of that level to its parent,
   :func:`snowlight.predict.pool.propensities`), so the archive's storm-picked absolute level
   no longer enters; its base sentence says "days we read live". A situation without storm
   (``none`` and the day after one) is never re-anchored, nor is one the held-out days cannot
   check: they keep the archive's rates and "recorded days" sentence, unchanged. While no
   situation is anchored there is nothing to swap in: the model is unchanged and the log says
   so.
4. **Checks** the refit against the model served now, both scored as published on the
   held-out district-days: it is swapped in only when its pooled storm-row Brier is no worse,
   for the chance of no school and for the published chance of a delay (re-anchoring sets
   the delay level too), and so is each in every situation either model re-anchors; it has
   no more reliability bins (of ``holdout_bin_min_rows`` held-out storm rows or more) out of
   bound; and its ECE is no more than ``ece_tolerance`` above. A score that is not a number
   is worse. A refit that does not even serve (a base sentence it cannot say truly) is never
   swapped in.
5. **Swaps** by publishing the refit's :class:`~snowlight.predict.artifact.Learned` to
   ``predictions/learned.json`` beside the predictions; the serving pass uses it with the
   committed model it was made over (and the committed model alone when it is missing, made
   over another committed model, or does not build). Or **keeps** the model served now,
   says why, and exits :data:`EXIT_KEPT` (the workflow then opens one issue, if none is
   open). A served learned file that counted a day now in ``excluded_days`` (its own list of
   the days it counted says so, whatever became of the store) is judged anew
   against the committed model, and replaced by the refit only when it passes, else by a
   file that re-anchors nothing (the committed model's chances).

Nothing here can break serving: the step runs on its own, a failure leaves the files on
the host as they were, and a learned file is read only when it validates and builds.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Final, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowlight.live.history import is_final
from snowlight.output import dumps_json
from snowlight.predict.artifact import (
    LEAID_PATTERN,
    SITUATION_KEYS,
    Learned,
    LiveCounts,
    ModelArtifact,
    RecordDay,
)
from snowlight.predict.backtest import Bin, brier, ece, reliability
from snowlight.predict.calendar import is_school_day, previous_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.geography import state_of_leaid
from snowlight.predict.labels import Outcome
from snowlight.predict.live_labels import (
    DAMAGED,
    NO_RECORD,
    NO_STATE,
    NOT_SHOWN,
    OUTSIDE_48,
    Directory,
    LiveSource,
    day_ready,
    finish_labels,
    label_live_day,
    lit_of,
    snapshot_classes,
)
from snowlight.predict.outlook import OutlookMode, chance
from snowlight.predict.serve import DeployedDirectory, ServeError, ServeModel, build_model
from snowlight.predict.situations import Situation, WeatherClass, Window

LEARN_PATH: Final = "predictions/learn.json"
LEARNED_PATH: Final = "predictions/learned.json"
EXIT_KEPT: Final = 4
"""``predict learn`` kept the model served now because the refit was worse (the workflow
opens an issue)."""
DIDS: Final = ("closed", "remote", "delayed", "open")
NO_SCHOOL_DIDS: Final = frozenset({"closed", "remote"})
_TIE: Final = 1e-12
RECORD_DAYS: Final = 8
EXCLUDED: Final = "excluded from learning (learn.excluded_days)"
ANOTHER_DIRECTORY: Final = "its timeline indexes another directory"
NEVER: Final = frozenset({EXCLUDED, NO_RECORD, NO_STATE, DAMAGED, NOT_SHOWN, ANOTHER_DIRECTORY})
"""Why a day is not labeled that no later run changes: a day after it need not wait for it."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class LiveDay(_Model):
    """One labeled live day: the districts (positions in the store's table) by situation and
    by what they did, and how many read districts stayed unknown."""

    day: date
    labels: dict[str, dict[str, tuple[int, ...]]]
    unknown: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> "LiveDay":
        seen: set[int] = set()
        for key, by_did in self.labels.items():
            if key not in SITUATION_KEYS:
                raise ValueError(f"not a situation: {key!r}")
            for did, positions in by_did.items():
                if did not in DIDS:
                    raise ValueError(f"not an outcome: {did!r}")
                if list(positions) != sorted(set(positions)) or not positions:
                    raise ValueError("positions must be sorted, unique and present")
                if seen & set(positions):
                    raise ValueError(f"{self.day}: a district is labeled twice")
                seen.update(positions)
        return self


class LearnStore(_Model):
    """``predictions/learn.json`` on the live host: every labeled live district-day."""

    schema_version: Literal[1]
    districts: tuple[Annotated[str, Field(pattern=LEAID_PATTERN)], ...]
    """The LEAID table the days point into (append-only, so positions never move)."""
    days: tuple[LiveDay, ...]

    @model_validator(mode="after")
    def _check(self) -> "LearnStore":
        if len(set(self.districts)) != len(self.districts):
            raise ValueError("the district table repeats a district")
        if [d.day for d in self.days] != sorted({d.day for d in self.days}):
            raise ValueError("days must be sorted and unique")
        size = len(self.districts)
        for item in self.days:
            for by_did in item.labels.values():
                if any(p >= size for positions in by_did.values() for p in positions):
                    raise ValueError(f"{item.day}: a position is not in the district table")
        return self

    @classmethod
    def empty(cls) -> "LearnStore":
        """No live day labeled yet."""
        return cls(schema_version=1, districts=(), days=())

    def to_bytes(self) -> bytes:
        """Key-sorted JSON."""
        return dumps_json(self.model_dump(mode="json"))

    @classmethod
    def from_bytes(cls, data: bytes) -> "LearnStore":
        """Read a ``learn.json``.

        Raises:
            pydantic.ValidationError: it is not one.
        """
        return cls.model_validate_json(data, strict=False)

    def labeled(self) -> frozenset[date]:
        """The days in the store."""
        return frozenset(item.day for item in self.days)

    def no_school(self, day: date) -> frozenset[str]:
        """The districts labeled no school on ``day``."""
        for item in self.days:
            if item.day == day:
                return frozenset(
                    self.districts[p]
                    for by_did in item.labels.values()
                    for did, positions in by_did.items()
                    if did in NO_SCHOOL_DIDS
                    for p in positions
                )
        return frozenset()

    def rows(self) -> pl.DataFrame:
        """Every labeled district-day: district, day, situation (index), did, y (no school),
        delayed, storm (weather class not ``none``)."""
        index = {key: i for i, key in enumerate(SITUATION_KEYS)}
        out: dict[str, list[object]] = {k: [] for k in ("district", "day", "situation", "did")}
        for item in self.days:
            for key, by_did in item.labels.items():
                for did, positions in by_did.items():
                    for p in positions:
                        out["district"].append(self.districts[p])
                        out["day"].append(item.day)
                        out["situation"].append(index[key])
                        out["did"].append(did)
        frame = pl.DataFrame(
            out,
            schema={"district": pl.String, "day": pl.Date, "situation": pl.Int64, "did": pl.String},
        )
        storm = [Situation.from_key(key).weather is not WeatherClass.NONE for key in SITUATION_KEYS]
        return frame.with_columns(
            pl.col("did").is_in(list(NO_SCHOOL_DIDS)).cast(pl.Float64).alias("y"),
            (pl.col("did") == "delayed").cast(pl.Float64).alias("delayed"),
            pl.col("situation")
            .map_elements(lambda k: storm[k], return_dtype=pl.Boolean)
            .alias("storm"),
        ).sort("day", "district")

    def with_day(
        self, day: date, labels: Mapping[str, Mapping[str, Sequence[str]]], unknown: int
    ) -> "LearnStore":
        """The store with one more day: ``labels`` by situation key and did, as LEAIDs."""
        table = list(self.districts)
        position = {leaid: i for i, leaid in enumerate(table)}
        packed: dict[str, dict[str, tuple[int, ...]]] = {}
        for key, by_did in sorted(labels.items()):
            for did, leaids in sorted(by_did.items()):
                if not leaids:
                    continue
                for leaid in leaids:
                    if leaid not in position:
                        position[leaid] = len(table)
                        table.append(leaid)
                packed.setdefault(key, {})[did] = tuple(sorted(position[d] for d in leaids))
        days = sorted(
            [*self.days, LiveDay(day=day, labels=packed, unknown=unknown)], key=lambda d: d.day
        )
        return LearnStore(schema_version=1, districts=tuple(table), days=tuple(days))


# --- 1. labeling the new days -----------------------------------------------------------------


@dataclass(slots=True)
class Labeling:
    """What a run labeled, and why other days were not."""

    store: LearnStore
    added: list[date] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    waiting: set[date] = field(default_factory=set)
    """Days skipped this run that a later run may still label."""

    def skip(self, day: date, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1
        if why not in NEVER:
            self.waiting.add(day)


def directory_of(model: ServeModel) -> Directory:
    """The deployed directory as the labels need it."""
    found = model.directory
    return Directory(
        districts=found.district_ids,
        eligible=model.eligible,
        zones=model.time_zone,
        content=content_key(found),
        stamp=found.stamp,
        digest=found.content_sha256,
    )


def content_key(directory: DeployedDirectory) -> str:
    """What names a directory's indexes: its content digest, or its stamp without one."""
    if directory.content_sha256 is not None:
        return directory.content_sha256
    stamp = directory.stamp
    return f"{stamp.generated_on.isoformat()}/{stamp.schools}/{stamp.districts}"


def label_new_days(  # noqa: PLR0913, PLR0917 - the store, the inputs and when
    store: LearnStore,
    source: LiveSource,
    directory: Directory,
    snapshots: Mapping[str, object],
    config: PredictConfig,
    now: datetime,
) -> Labeling:
    """The store with every new live day that can be labeled now (see the module docstring)."""
    done = Labeling(store)
    settings = config.learn
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    slack = timedelta(minutes=settings.snapshot_slack_minutes)
    today = now.astimezone(UTC).date()
    first = today - timedelta(days=settings.morning_reads_days)
    index = None
    index_read = False
    day = first
    while day < today:
        candidate, day = day, day + timedelta(days=1)
        if not is_school_day(candidate) or candidate in done.store.labeled():
            continue
        if candidate in settings.excluded_days:
            done.skip(candidate, EXCLUDED)
            continue
        if not is_final(candidate, now):
            done.skip(candidate, "not over everywhere yet")
            continue
        if previous_school_day(candidate) in done.waiting:
            done.skip(candidate, "its previous school day is not labeled yet")
            continue
        morning = source.morning(candidate)
        if isinstance(morning, str):
            done.skip(candidate, morning)
            continue
        timeline = source.timeline(candidate)
        if not index_read:
            index, index_read = source.index(), True
        waiting = day_ready(candidate, timeline, index)
        if waiting is not None:
            done.skip(candidate, waiting)
            continue
        if timeline is not None and timeline.gaps and not directory.indexes(timeline):
            done.skip(candidate, ANOTHER_DIRECTORY)
            continue
        classes = snapshot_classes(
            snapshots,
            candidate,
            content=directory.content,
            zones=directory.zones,
            window=window,
            slack=slack,
        )
        rows = label_live_day(
            candidate,
            lit=lit_of(timeline),
            morning=morning,
            classes=classes,
            directory=directory,
            settings=config.labels,
        )
        frame = finish_labels(rows, config.labels.storm_absence_share)
        after = done.store.no_school(previous_school_day(candidate))
        done.store = done.store.with_day(candidate, *situated(frame, after))
        done.added.append(candidate)
    return done


def situated(
    frame: pl.DataFrame, after: frozenset[str]
) -> tuple[dict[str, dict[str, list[str]]], int]:
    """One day's labeled districts by situation and outcome (``after``: the districts labeled
    no school on its previous school day), and how many stayed unknown."""
    labels: dict[str, dict[str, list[str]]] = {}
    unknown = 0
    for row in frame.iter_rows(named=True):
        if row["outcome"] == Outcome.UNKNOWN.value or row["did"] is None:
            unknown += 1
            continue
        key = Situation.of(WeatherClass(int(row["weather"])), row["district"] in after).key
        labels.setdefault(key, {}).setdefault(str(row["did"]), []).append(str(row["district"]))
    return labels, unknown


# --- 2-4. the held-out check and the refit ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Split:
    """The fit days (up to ``through``) and the held-out ones."""

    through: date
    held: pl.DataFrame
    """Every held-out district-day."""


def state_column(rows: pl.DataFrame) -> pl.Series:
    """Each row's state, from its LEAID."""
    return rows["district"].map_elements(
        lambda leaid: state_of_leaid(leaid) or OUTSIDE_48.get(leaid[:2], leaid[:2]),
        return_dtype=pl.String,
    )


def split(rows: pl.DataFrame, config: PredictConfig) -> Split | str:
    """The newest days held out, or why there are too few to judge a refit by."""
    settings = config.learn
    if rows.is_empty():
        return "no live-read district-days labeled yet"
    days = sorted(set(rows["day"].to_list()), reverse=True)
    allowed = math.floor(settings.holdout_max_share * len(days))
    storm = rows.filter(pl.col("storm"))
    storm = storm.with_columns(state_column(storm).alias("state"))
    held: list[date] = []
    count = 0
    storm_days: set[date] = set()
    states: set[str] = set()
    for day in days[:allowed]:
        held.append(day)
        today = storm.filter(pl.col("day") == day)
        count += today.height
        if today.height:
            storm_days.add(day)
            states.update(today["state"].to_list())
        if (
            count >= settings.holdout_min_storm_rows
            and len(storm_days) >= settings.holdout_min_storm_days
            and len(states) >= settings.holdout_min_states
        ):
            through = days[len(held)]
            return Split(through, rows.filter(pl.col("day") > through))
    return (
        f"{storm.height:,} live storm district-days on {len(days):,} live days: too few to hold "
        f"out {settings.holdout_min_storm_rows:,} over {settings.holdout_min_storm_days} storm "
        f"days and {settings.holdout_min_states} states (at most {settings.holdout_max_share:.0%}"
        " of the days)"
    )


STORM_KEYS: Final = frozenset(
    key for key in SITUATION_KEYS if Situation.from_key(key).weather is not WeatherClass.NONE
)
"""The situations re-anchoring may touch: a weather class above ``none``."""


def learned_from(  # noqa: PLR0913, PLR0917 - the fit rows, the committed model and what it passed
    rows: pl.DataFrame,
    through: date,
    archive_sha256: str,
    config: PredictConfig,
    check: Mapping[str, float | int],
    made_at: datetime,
) -> Learned:
    """The live counts of the rows up to ``through``, with the storm situations they anchor:
    ``anchor_min_days`` fit rows nationally and ``holdout_min_situation_rows`` held-out rows
    (after ``through``) to check them on."""
    fit = rows.filter(pl.col("day") <= through)
    later = rows.filter(pl.col("day") > through)
    size = len(SITUATION_KEYS)
    totals = np.zeros(size, dtype=np.int64)
    checked = np.bincount(later["situation"].to_numpy().astype(np.int64), minlength=size)
    counts: dict[str, list[list[int]]] = {}
    records: dict[str, dict[int, list[RecordDay]]] = {}
    for row in fit.sort("day").iter_rows(named=True):
        k = int(row["situation"])
        cells = counts.setdefault(row["district"], [[0] * size for _ in range(4)])
        no_school = row["did"] in NO_SCHOOL_DIDS
        cells[0][k] += int(no_school)
        cells[1][k] += 1
        cells[2][k] += int(row["did"] == "delayed")
        cells[3][k] += int(not no_school)
        totals[k] += 1
        records.setdefault(row["district"], {}).setdefault(k, []).append(
            RecordDay(day=row["day"], did=row["did"])
        )
    settings = config.learn
    anchored = tuple(
        key
        for k, key in enumerate(SITUATION_KEYS)
        if key in STORM_KEYS
        and totals[k] >= settings.anchor_min_days
        and checked[k] >= settings.holdout_min_situation_rows
    )
    anchored_index = {SITUATION_KEYS.index(key) for key in anchored}
    return Learned(
        schema_version=1,
        archive_sha256=archive_sha256,
        through=through,
        labeled_days=fit.height,
        anchored=anchored,
        live={
            district: LiveCounts(y=tuple(c[0]), n=tuple(c[1]), yd=tuple(c[2]), nd=tuple(c[3]))
            for district, c in sorted(counts.items())
        },
        records={
            district: {
                SITUATION_KEYS[k]: tuple(days[-RECORD_DAYS:])
                for k, days in sorted(by_k.items())
                if k in anchored_index
            }
            for district, by_k in sorted(records.items())
            if any(k in anchored_index for k in by_k)
        },
        check=dict(check),
        made_at=made_at.astimezone(UTC).replace(microsecond=0),
        days=tuple(sorted(set(fit["day"].to_list()))),
    )


def reset_of(archive_sha256: str, through: date, made_at: datetime) -> Learned:
    """A learned file that re-anchors nothing: served, it gives the committed model's
    chances (a served file that counted an excluded day is replaced by it)."""
    return Learned(
        schema_version=1,
        archive_sha256=archive_sha256,
        through=through,
        labeled_days=0,
        anchored=(),
        live={},
        records={},
        check={},
        made_at=made_at.astimezone(UTC).replace(microsecond=0),
        days=(),
    )


@dataclass(frozen=True, slots=True)
class Score:
    """A model scored on the held-out district-days."""

    rows: int
    """Held-out storm district-days in deployed districts."""
    brier: float
    """Of the chance of no school, pooled over those storm rows."""
    delay_brier: float
    """Of the published chance of a delay against the days the district delayed, pooled over
    those storm rows."""
    ece: float
    out_of_bound: int
    """Reliability bins of ``holdout_bin_min_rows`` storm rows or more outside their bound."""
    situations: Mapping[str, tuple[int, float, float]] = field(default_factory=dict)
    """Per situation asked for: its held-out rows, their Brier and their delay Brier."""


def score(
    model: ServeModel,
    held: pl.DataFrame,
    config: PredictConfig,
    situations: Sequence[str] = (),
) -> Score:
    """The model's published chances on the held-out rows of deployed districts: pooled over
    the storm rows, and per situation of ``situations``."""
    position = {leaid: i for i, leaid in enumerate(model.directory.district_ids)}
    kept = held.filter(pl.col("district").is_in(list(position)))
    rows = np.array([position[d] for d in kept["district"].to_list()], dtype=np.int64)
    k = kept["situation"].to_numpy().astype(np.int64)
    p, q = served_chances(model, rows, k)
    y = kept["y"].to_numpy().astype(np.float64)
    yd = kept["delayed"].to_numpy().astype(np.float64)
    storm = kept["storm"].to_numpy().astype(np.bool_)
    days = [day.isoformat() for day in kept["day"].to_list()]
    bins: list[Bin] = reliability(
        p[storm], y[storm], [d for d, s in zip(days, storm, strict=True) if s],
        config.backtest.reliability_bins,
    )  # fmt: skip
    minimum = config.learn.holdout_bin_min_rows
    per: dict[str, tuple[int, float, float]] = {}
    for key in situations:
        mask = k == SITUATION_KEYS.index(key)
        per[key] = (int(mask.sum()), brier(p[mask], y[mask]), brier(q[mask], yd[mask]))
    return Score(
        rows=int(storm.sum()),
        brier=brier(p[storm], y[storm]),
        delay_brier=brier(q[storm], yd[storm]),
        ece=ece(bins),
        out_of_bound=sum(1 for item in bins if item.rows >= minimum and not item.within()),
        situations=per,
    )


def served_chances(
    model: ServeModel, rows: npt.NDArray[np.int64], situation: npt.NDArray[np.int64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """The chances of no school and of a delay the model publishes for each held-out row (its
    deployed district ``rows``, its ``situation``), through the one chance function the
    serving pass and the outlook's backtest use (:func:`snowlight.predict.outlook.chance`,
    spec-f s. 10): a labeled day is the morning of, so the outlook is the identity and the
    chance is the situation's own published rate, exactly as served."""
    if not rows.size:
        return np.zeros(0), np.zeros(0)
    p_table = model.p_rate if model.p_rate.size else model.p
    q_table = model.q_rate if model.q_rate.size else model.q
    own = np.zeros(rows.size, dtype=np.int64)
    found = chance(
        p_table[rows, situation][:, None],
        q_table[rows, situation][:, None],
        own,
        None,
        np.zeros(rows.size, dtype=np.bool_),
        mode=OutlookMode.OFF,
        floor=model.artifact.settings.floor,
        ceiling=model.artifact.settings.ceiling,
    )
    return found.p, found.delay


def _worse(name: str, mine: float, theirs: float, tolerance: float = 0.0) -> str | None:
    """Why the refit's ``name`` is worse than the served model's, or ``None``: a refit score
    that is not a number always is (a comparison with it would pass)."""
    if not math.isfinite(mine):
        return f"its {name} is not a number"
    if math.isfinite(theirs) and mine > theirs + tolerance + _TIE:
        return f"its {name} {mine:.5f} is worse than {theirs:.5f}"
    return None


def no_worse(
    refit: Score, current: Score, tolerance: float, situations: Sequence[str] = ()
) -> str | None:
    """``None`` when the refit is no worse than the model served now, pooled over the storm
    rows and in each of ``situations`` (those either model re-anchors), for the chance of no
    school and the chance of a delay, else why it is."""
    if not refit.rows:
        return "no held-out storm district-day is in a deployed district"
    checks: list[tuple[str, float, float]] = [
        ("storm Brier", refit.brier, current.brier),
        ("storm delay Brier", refit.delay_brier, current.delay_brier),
    ]
    for key in situations:
        mine, theirs = refit.situations.get(key), current.situations.get(key)
        if mine is None or theirs is None or not mine[0]:
            return f"no held-out district-day checks {key}"
        checks += [(f"{key} Brier", mine[1], theirs[1]), (f"{key} delay Brier", mine[2], theirs[2])]
    for name, mine_score, theirs_score in checks:
        why = _worse(name, mine_score, theirs_score)
        if why is not None:
            return why
    if refit.out_of_bound > current.out_of_bound:
        return f"{refit.out_of_bound} reliability bins out of bound against {current.out_of_bound}"
    found = _worse("ECE", refit.ece, current.ece, tolerance)
    return None if found is None else f"{found} by more than {tolerance}"


# --- 5. one run --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decision:
    """What a run decided: ``swap`` (publish ``learned``), ``keep`` (worse; ``why``),
    ``reset`` (publish ``learned``, a file that re-anchors nothing, in place of a served one
    that counted an excluded day; ``why``), or ``unchanged`` (nothing to decide; ``why``)."""

    kind: Literal["swap", "keep", "unchanged", "reset"]
    why: str
    learned: Learned | None = None


type Builder = Callable[[Learned | None], ServeModel]
"""Builds the serving model of the committed model plus a learned file (or none)."""


def tainted(current: Learned | None, config: PredictConfig) -> list[date]:
    """The excluded days a served learned file counted (its own list of the days)."""
    if current is None or not current.anchored:
        return []
    counted = set(current.days)
    return sorted(d for d in config.learn.excluded_days if d in counted)


def decide(  # noqa: PLR0913, PLR0917 - the store, the models, the settings
    store: LearnStore,
    current: Learned | None,
    build: Builder,
    archive_sha256: str,
    config: PredictConfig,
    now: datetime,
) -> Decision:
    """Whether to swap in a refit on the store's live days (see the module docstring)."""
    excluded = set(config.learn.excluded_days)
    rows = store.rows().filter(~pl.col("day").is_in(sorted(excluded)))
    bad = tainted(current, config)
    if bad:
        decision = _decide(rows, None, build, archive_sha256, config, now)
        listed = ", ".join(day.isoformat() for day in bad)
        if decision.kind == "swap":
            return replace(
                decision, why=f"{decision.why}; it replaces a file that counted {listed}"
            )
        through = current.through if current is not None else now.date()
        return Decision(
            "reset",
            f"the served learned file counted {listed} (excluded from learning): it is replaced "
            f"by one that re-anchors nothing ({decision.why})",
            reset_of(archive_sha256, through, now),
        )
    return _decide(rows, current, build, archive_sha256, config, now)


def _decide(  # noqa: PLR0911, PLR0913, PLR0917 - the rows, the models, the settings
    rows: pl.DataFrame,
    current: Learned | None,
    build: Builder,
    archive_sha256: str,
    config: PredictConfig,
    now: datetime,
) -> Decision:
    found = split(rows, config)
    if isinstance(found, str):
        return Decision("unchanged", f"nothing to learn: {found}; the model is unchanged")
    if current is not None and current.through >= found.through:
        return Decision(
            "unchanged",
            f"the model served counts the live days through {current.through}; nothing newer "
            "to check yet; the model is unchanged",
        )
    candidate = learned_from(rows, found.through, archive_sha256, config, {}, now)
    served_anchors = set(current.anchored) if current is not None else set()
    if not candidate.anchored and not served_anchors:
        fit = rows.filter(pl.col("day") <= found.through)
        storm = fit.filter(pl.col("storm"))
        most = storm.group_by("situation").len().sort("len", "situation", descending=[True, False])
        top = (
            f"the most: {most['len'][0]:,} {SITUATION_KEYS[most['situation'][0]]}"
            if most.height
            else "none yet"
        )
        return Decision(
            "unchanged",
            f"nothing to learn yet: no storm situation has {config.learn.anchor_min_days:,} "
            f"live-read district-days through {found.through} and "
            f"{config.learn.holdout_min_situation_rows:,} held out ({top}); every chance keeps "
            "the recorded days; the model is unchanged",
        )
    unchecked = sorted(served_anchors - set(candidate.anchored), key=SITUATION_KEYS.index)
    if unchecked:
        return Decision(
            "unchanged",
            f"the held-out days after {found.through} cannot check {', '.join(unchecked)}, which "
            "the model served re-anchors; the model is unchanged",
        )
    try:
        served = build(current)
    except ServeError as error:
        return Decision("unchanged", f"the model served now does not build ({error}); unchanged")
    try:
        refit = build(candidate)
    except ServeError as error:
        return Decision("keep", f"the refit through {found.through} does not serve: {error}")
    checked = sorted(served_anchors | set(candidate.anchored), key=SITUATION_KEYS.index)
    mine = score(refit, found.held, config, checked)
    theirs = score(served, found.held, config, checked)
    check: dict[str, float | int] = {
        "held_out_rows": mine.rows,
        "refit_brier": _number(mine.brier),
        "served_brier": _number(theirs.brier),
        "refit_delay_brier": _number(mine.delay_brier),
        "served_delay_brier": _number(theirs.delay_brier),
        "refit_ece": _number(mine.ece),
        "served_ece": _number(theirs.ece),
        "refit_out_of_bound": mine.out_of_bound,
        "served_out_of_bound": theirs.out_of_bound,
    }
    for key in checked:
        count, refit_brier, refit_delay = mine.situations[key]
        _rows, served_brier, served_delay = theirs.situations[key]
        check[f"{key}_rows"] = count
        check[f"{key}_refit_brier"] = _number(refit_brier)
        check[f"{key}_served_brier"] = _number(served_brier)
        check[f"{key}_refit_delay_brier"] = _number(refit_delay)
        check[f"{key}_served_delay_brier"] = _number(served_delay)
    worse = no_worse(mine, theirs, config.learn.ece_tolerance, checked)
    summary = (
        f"{mine.rows:,} held-out storm district-days after {found.through}: storm Brier "
        f"{mine.brier:.5f} refit, {theirs.brier:.5f} served; delay Brier "
        f"{mine.delay_brier:.5f} refit, {theirs.delay_brier:.5f} served"
    )
    if worse is not None:
        return Decision("keep", f"kept the model served: the refit is worse ({worse}); {summary}")
    learned = learned_from(rows, found.through, archive_sha256, config, check, now)
    anchored = ", ".join(learned.anchored) or "none"
    return Decision(
        "swap",
        f"swapped in the refit through {found.through} ({learned.labeled_days:,} live "
        f"district-days; re-anchored: {anchored}); {summary}",
        learned,
    )


def _number(value: float) -> float:
    """A score as the check records it (``-1.0`` for one that is not a number)."""
    return round(value, 6) if math.isfinite(value) else -1.0


def read_learned(data: bytes | None, archive_sha256: str) -> tuple[Learned | None, str | None]:
    """A learned file the serving pass may use with the committed model, or ``None`` and why
    not (``None`` and no reason when there is none)."""
    if data is None:
        return None, None
    try:
        found = Learned.from_bytes(data)
    except ValueError as error:
        return None, f"the learned file does not validate ({type(error).__name__})"
    if found.archive_sha256 != archive_sha256:
        return None, "the learned file was made over another committed model"
    return found, None


def serving_model(
    directory: DeployedDirectory,
    artifact: ModelArtifact,
    learned: Learned | None,
    config: PredictConfig,
    zone_fallback: Callable[[float, float], str | None],
) -> tuple[ServeModel, str | None]:
    """The serving model with the learned file, or the committed model alone when that one
    does not build (and why): a learned file never darkens a pass the committed model can
    serve."""
    if learned is not None:
        try:
            return build_model(directory, artifact, config, zone_fallback, learned), None
        except ServeError as error:
            reason = f"the learned file does not build ({error}); serving the committed model"
            return build_model(directory, artifact, config, zone_fallback), reason
    return build_model(directory, artifact, config, zone_fallback), None
