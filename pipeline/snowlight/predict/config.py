"""The model's settings, read from ``pipeline/config/predict.yaml``."""

from datetime import date, time
from pathlib import Path
from typing import Final, Literal

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, Field

PIPELINE_ROOT: Final = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final = PIPELINE_ROOT / "config" / "predict.yaml"


class _Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LabelSettings(_Settings):
    """How the archive's captures become district-day outcomes (spec a)."""

    read_from: time
    read_until: time
    no_school_share: float = Field(gt=0, le=1)
    delayed_share: float = Field(gt=0, le=1)
    open_max_share: float = Field(ge=0, lt=1)
    audience_days: int = Field(ge=1)
    market_rows_void: int = Field(ge=1)
    station_min_captures: int = Field(ge=1)
    capture_min_share: float = Field(ge=0, le=1)
    storm_absence_share: float = Field(gt=0, le=1)
    first_season: int
    excluded_from: date
    excluded_until: date


class WeatherSettings(_Settings):
    """Which alerts count for a school day (spec b)."""

    snapshot_hour: int = Field(ge=0, le=23)
    window_from: time
    window_until: time
    covered_share: float = Field(gt=0, le=1)
    memory_hours: int = Field(ge=1)


class ModelSettings(_Settings):
    """The pooled rates (spec c.1)."""

    own_min_days: int = Field(ge=1)
    level_min_days: int = Field(ge=1)
    nation_min_days: int = Field(ge=1)
    almost_share: float = Field(gt=0, lt=0.5)
    fallback: dict[str, str]
    m_grid: tuple[float, ...] = Field(min_length=1)
    floor: float = Field(gt=0, lt=0.5)
    ceiling: float = Field(gt=0.5, lt=1)
    record_days: int = Field(ge=1, le=8)
    private_level_min_days: int = Field(ge=1)
    """The private schools' chain names a place below the nation only with this many labeled
    private school-days (contract C3): private lists come a storm day at a time."""

    def private(self) -> "ModelSettings":
        """The settings of the private schools' chain."""
        return self.model_copy(update={"level_min_days": self.private_level_min_days})


class BacktestSettings(_Settings):
    """The walk-forward backtest (spec c.3)."""

    test_seasons: tuple[int, ...]
    apart: tuple[int, ...]
    storm_day_market_closings: int = Field(ge=1)
    reliability_bins: int = Field(ge=2)
    reliability_min_rows: int = Field(ge=1)
    g1_min_storm_rows: int = Field(ge=1)
    g1_tolerance: float = Field(ge=0, lt=0.1)


class ServeSettings(_Settings):
    """The serving pass (spec d)."""

    forecast_zone: str
    neighbor_miles: float = Field(gt=0)
    min_district_share: float = Field(gt=0, le=1)
    alerts_max_age_minutes: int = Field(ge=1)
    collapse_from: int = Field(ge=1)
    collapse_drop: float = Field(gt=0, lt=1)
    budget_raw_bytes: int = Field(ge=1)
    budget_gzip_bytes: int = Field(ge=1)
    heartbeat_minutes: int = Field(ge=1)
    heartbeat_skip_minutes: int = Field(ge=0)
    memory_gap_minutes: int = Field(ge=1)
    history_lead_hours: int = Field(ge=0)
    check_minutes: int = Field(ge=1)
    min_gap_minutes: int = Field(ge=1)
    grid_minutes: tuple[int, ...] = Field(min_length=1)
    opens_max_age_minutes: int = Field(ge=1)
    elevation_margin_feet: float = Field(ge=0, le=5000)
    """An alert that names heights reaches a school within this many feet of its band
    (:mod:`snowlight.sources.nws.elevation`)."""
    reasons: bool = False
    """Piece 3: the districts' chances carry the reasons' terms (the forecast amounts and the
    districts next door, ``data/predict/terms.json.gz``). Off: the base alone, as before."""
    announces: bool = False
    """Piece 3: a district's usual posting time is its forecasts' ``announces_at``."""
    reasons_gate_override: str = ""
    """Piece 3: terms whose recorded backtest v2 gate failed (or that record none) serve only
    while this names the lead who signed off on serving them anyway (for example "lead
    2026-11-02"); empty, the default: such terms are refused and the pass serves the base
    alone."""
    neighbors_max_age_minutes: int = Field(default=60, ge=1)
    """A closings file older than this says nothing of the districts next door."""
    forecast_stale: Literal["identity", "dark"] = "identity"
    """S7-F with the outlook on: a district whose zone has no forecast run under 3 hours old
    gets the issued-alerts-only chance (``identity``, the lead's decision of 2026-10-20: every
    school gets a chance every day), or the pass goes dark (``dark``, ``Dark.FORECAST``)."""


class LearnSettings(_Settings):
    """Automatic learning from live-read days (:mod:`snowlight.predict.learn`)."""

    anchor_min_days: int = Field(ge=1)
    holdout_min_storm_rows: int = Field(ge=1)
    holdout_max_share: float = Field(gt=0, lt=1)
    ece_tolerance: float = Field(ge=0, lt=0.1)
    snapshot_slack_minutes: int = Field(ge=1)
    morning_reads_days: int = Field(ge=1)
    holdout_min_storm_days: int = Field(ge=1)
    holdout_min_states: int = Field(ge=1)
    holdout_min_situation_rows: int = Field(ge=1)
    holdout_bin_min_rows: int = Field(ge=1)
    excluded_days: tuple[date, ...] = ()
    """Live days never learned from (a day found misread): never labeled, never fit or held
    out, and a learned file that counted one is no longer served."""


class PredictConfig(_Settings):
    """Every setting of ``config/predict.yaml``."""

    labels: LabelSettings
    weather: WeatherSettings
    model: ModelSettings
    backtest: BacktestSettings
    serve: ServeSettings
    learn: LearnSettings

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "PredictConfig":
        """Read the settings file.

        Raises:
            OSError: it cannot be read.
            yaml.YAMLError: it is not YAML.
            pydantic.ValidationError: a setting is missing or out of range.
        """
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
