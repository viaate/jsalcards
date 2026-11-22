"""The committed model file: ``pipeline/data/flights/model.json.gz``.

What the live job needs and nothing else: every regression (:class:`snowlight.flights.model.Fitted`)
by target and lead class, each airport's usual rates by block and month of year (``dep`` and
``arr``: ``canc`` and ``late``) and by month (``rough``), which chances passed the held-out
test, per airport and target, as a mask of lead classes, and which targets and leads passed the
day after an observed storm (``after_storm``). Written by ``snowlight flights train``;
the monthly job publishes each refit as plain JSON (``v1/flights/model.json``, the live host takes
JSON text only), and both validate against ``schemas/flights-model.schema.json``.
"""

import gzip
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights.airports import DATA_DIR
from snowlight.flights.model import FEATURES, TARGETS, Fitted, Model, columns
from snowlight.schemas.flights import (
    FlightsAirportGate,
    FlightsAirportUsual,
    FlightsFit,
    FlightsInput,
    FlightsModel,
    FlightsTarget,
    FlightsUsualRates,
)

MODEL_FILE: Final = DATA_DIR / "model.json.gz"
FORMAT: Final = 1
"""The model file's schema version (:class:`~snowlight.schemas.flights.FlightsModel`)."""


@dataclass(slots=True)
class Artifact:
    """The model file, read."""

    model: Model
    test_first: date
    test_last: date
    base: dict[str, dict[str, dict[str, list[list[float]]]]] = field(default_factory=dict)
    """``table`` (``dep``, ``arr``) -> airport -> ``canc``/``late`` -> 5 blocks x 12 months."""
    rough: dict[str, list[float]] = field(default_factory=dict)
    """Airport -> 12 months."""
    national: dict[str, dict[str, list[list[float]]]] = field(default_factory=dict)
    """``table`` -> ``canc``/``late`` -> 5 blocks x 12 months: for an airport with no history."""

    def usual(self, table: str, kind: str, airport: str, block: int, month: int) -> float:
        """The usual rate of an airport block in a month (1-12)."""
        rows = self.base.get(table, {}).get(airport)
        source = rows[kind] if rows is not None else self.national[table][kind]
        return source[block][month - 1]

    def usual_rough(self, airport: str, month: int) -> float:
        """The usual share of rough days of an airport in a month."""
        months = self.rough.get(airport)
        return months[month - 1] if months is not None else self.national_rough[month - 1]

    national_rough: list[float] = field(default_factory=lambda: [0.02] * 12)

    def gates(self) -> dict[str, list[int]]:
        """Per airport, per target in :data:`TARGETS` order, the lead classes that passed (one
        bit per lead class)."""
        gates: dict[str, list[int]] = {}
        for (airport, target, lead), passed in sorted(self.model.published.items()):
            masks = gates.setdefault(airport, [0] * len(TARGETS))
            if passed:
                masks[TARGETS.index(target)] |= 1 << (lead - 1)
        return gates

    def _rates(self, airport: str | None) -> FlightsUsualRates:
        def table(name: str, kind: str) -> tuple[tuple[float, ...], ...]:
            rows = self.base.get(name, {}).get(airport) if airport is not None else None
            source = rows[kind] if rows is not None else self.national[name][kind]
            return tuple(tuple(float(v) for v in row) for row in source)

        rough = self.rough.get(airport) if airport is not None else None
        return FlightsUsualRates(
            dep_canc=table("dep", "canc"),
            dep_late=table("dep", "late"),
            arr_canc=table("arr", "canc"),
            arr_late=table("arr", "late"),
            rough=tuple(float(v) for v in (rough if rough is not None else self.national_rough)),
        )

    def document(self) -> FlightsModel:
        """The model file's content (``flights/model.json``)."""
        airports = sorted(
            set(self.base.get("dep", {})) | set(self.base.get("arr", {})) | set(self.rough)
        )
        return FlightsModel(
            schema_version=FORMAT,
            inputs=tuple(FlightsInput[name.upper()] for name in self.model.inputs),
            test_first=self.test_first,
            test_last=self.test_last,
            fits=tuple(
                FlightsFit(
                    target=FlightsTarget(TARGETS.index(target)),
                    lead=lead,
                    intercept=round(fitted.intercept, 6),
                    coef=tuple(round(c, 6) for c in fitted.coef),
                    mean=tuple(round(m, 6) for m in fitted.mean),
                    scale=tuple(round(v, 6) for v in fitted.scale),
                    after_storm=self.model.after.get((target, lead), False),
                )
                for (target, lead), fitted in sorted(self.model.fitted.items())
            ),
            gates=tuple(
                FlightsAirportGate(code=code, passed=(m[0], m[1], m[2], m[3], m[4]))
                for code, m in sorted(self.gates().items())
            ),
            usual=tuple(
                FlightsAirportUsual(code=code, rates=self._rates(code)) for code in airports
            ),
            national=self._rates(None),
        )

    def to_bytes(self) -> bytes:
        """The model file as published (``flights/model.json``), validated."""
        return self.document().to_json_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Artifact":
        """Read a model file (as published), validated against its schema.

        Raises:
            ValueError: it does not validate, or its inputs are not this code's.
        """
        return cls.from_document(FlightsModel.from_json_bytes(data))

    @classmethod
    def from_document(cls, document: FlightsModel) -> "Artifact":
        """The model of a validated model file.

        Raises:
            ValueError: its inputs are not this code's (:data:`FEATURES`, in their order), or
                a fit's coefficients are not one per input.
        """
        inputs = tuple(item.name.lower() for item in document.inputs)
        if not set(inputs) <= set(FEATURES):
            raise ValueError("the model file is of another feature set")
        columns(inputs)
        model = Model(inputs=inputs)
        for fit in document.fits:
            if not len(fit.coef) == len(fit.mean) == len(fit.scale) == len(inputs):
                raise ValueError("a fit's coefficients are not one per input")
            key = (TARGETS[int(fit.target)], fit.lead)
            model.fitted[key] = Fitted(
                intercept=fit.intercept, coef=fit.coef, mean=fit.mean, scale=fit.scale
            )
            model.after[key] = fit.after_storm
        for gate in document.gates:
            for index, target in enumerate(TARGETS):
                for lead in (1, 2, 3):
                    model.published[(gate.code, target, lead)] = bool(
                        gate.passed[index] >> (lead - 1) & 1
                    )

        def nested(rates: FlightsUsualRates, kind: str) -> list[list[float]]:
            tables = {
                "dep_canc": rates.dep_canc,
                "dep_late": rates.dep_late,
                "arr_canc": rates.arr_canc,
                "arr_late": rates.arr_late,
            }
            return [list(row) for row in tables[kind]]

        base: dict[str, dict[str, dict[str, list[list[float]]]]] = {"dep": {}, "arr": {}}
        rough: dict[str, list[float]] = {}
        for entry in document.usual:
            for table in ("dep", "arr"):
                base[table][entry.code] = {
                    kind: nested(entry.rates, f"{table}_{kind}") for kind in ("canc", "late")
                }
            rough[entry.code] = list(entry.rates.rough)
        national = {
            table: {kind: nested(document.national, f"{table}_{kind}") for kind in ("canc", "late")}
            for table in ("dep", "arr")
        }
        return cls(
            model=model,
            test_first=document.test_first,
            test_last=document.test_last,
            base=base,
            rough=rough,
            national=national,
            national_rough=list(document.national.rough),
        )


def write(artifact: Artifact, path: Path = MODEL_FILE) -> None:
    """Write the model file (gzip with no time stamp, so the same model gives the same bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(artifact.to_bytes(), mtime=0))


def read(path: Path = MODEL_FILE) -> Artifact:
    """Read the model file."""
    return Artifact.from_bytes(gzip.decompress(path.read_bytes()))


def base_tables(
    rates: pl.DataFrame,
) -> tuple[dict[str, dict[str, list[list[float]]]], dict[str, list[list[float]]]]:
    """Usual rates (:func:`snowlight.flights.model.base_rates`) as nested lists per airport, and
    the departure-weighted national rates."""
    per: dict[str, dict[str, list[list[float]]]] = {}
    for row in rates.iter_rows(named=True):
        tables = per.setdefault(
            row["apt"],
            {"canc": [[0.0] * 12 for _ in range(5)], "late": [[0.0] * 12 for _ in range(5)]},
        )
        for kind in ("canc", "late"):
            tables[kind][row["block"]][row["moy"] - 1] = round(float(row[kind]), 5)
    national = rates.group_by("block", "moy").agg(
        ((pl.col("canc") * pl.col("n")).sum() / pl.col("n").sum()).alias("canc"),
        ((pl.col("late") * pl.col("n")).sum() / pl.col("n").sum()).alias("late"),
    )
    whole: dict[str, list[list[float]]] = {
        "canc": [[0.0] * 12 for _ in range(5)],
        "late": [[0.0] * 12 for _ in range(5)],
    }
    for row in national.iter_rows(named=True):
        for kind in ("canc", "late"):
            whole[kind][row["block"]][row["moy"] - 1] = round(float(row[kind]), 5)
    # An airport missing a block-month (no flights then) takes the national rate.
    for tables in per.values():
        for kind in ("canc", "late"):
            for block in range(5):
                for month in range(12):
                    if tables[kind][block][month] == 0.0:
                        tables[kind][block][month] = whole[kind][block][month]
    return per, whole


def rough_table(rates: pl.DataFrame) -> tuple[dict[str, list[float]], list[float]]:
    """Usual rough-day shares (:func:`snowlight.flights.model.rough_rates`) per airport, and
    the national shares."""
    per: dict[str, list[float]] = {}
    for row in rates.iter_rows(named=True):
        per.setdefault(row["apt"], [0.0] * 12)[row["moy"] - 1] = round(float(row["rough"]), 5)
    national = rates.group_by("moy").agg(
        ((pl.col("rough") * pl.col("days")).sum() / pl.col("days").sum()).alias("rough")
    )
    whole = [0.02] * 12
    for row in national.iter_rows(named=True):
        whole[row["moy"] - 1] = round(float(row["rough"]), 5)
    for months in per.values():
        for month in range(12):
            if months[month] == 0.0:
                months[month] = whole[month]
    return per, whole
