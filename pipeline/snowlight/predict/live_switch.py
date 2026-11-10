"""The live switch (predict-next TIMING-AUTO): a registered live-measured term is served ON
only once it is consistently better than its off arm on live storm mornings, and back OFF
when it falls behind; every evaluation and every switch is a counts-and-numbers line.

**The registry.** One ``live_score`` block per term, ``switch_<name>`` (:class:`Rule`): its
two arms (``arm_off`` and ``arm_on``, the values of ``arm_block.arm_key``), the arm served
with no state (``default``, which the committed config holds), the frozen variant its rows
carry (``frozen_key``, at the ``freeze``), and the decision rule's numbers. :data:`TERMS` maps
a name to its code (:class:`Term`): the group builder (a labeled date's groups from what
:class:`DayInputs` gives it: its frozen day, L1's labels of the date, the config, L1's record,
the labeled dates before it and a reader of their labels, the only labels a fitted arm may
fit on), the extra checks (the ledger to failing clause names), the term's own config checks,
and its freeze-time shadow, if it has one (the bus term's: the forecast adjustment's settings
under each arm). An arm is a name or a number, compared as stored; a group carries the
term's own counts and sums. The switch itself sees only :class:`Group` values, so a term
plugs in with its block, its :class:`Term` and nothing else.

**The key.** A term's state is made over its term sha256 (its switch block and its
``scope`` blocks, :func:`term_sha256`) and the committed model artifact's sha256. A state
under another key restarts the term: an empty ledger, ``through`` the newest labeled date,
the default arm.

**Arms only.** A state names ``off`` or ``on``, never a value; :func:`served_config` puts the
registered values in a copy of the config, which only the serving anchor is built from. The
committed config, and so the live_score sha256 every check uses, never changes.

**The ledger.** Each labeled date with a group enters once, in date order, with every group
its term built, and is frozen once counted (``through`` advances over dates with none too).
Only informative groups (some closed, some open) are scored and counted as evidence; a
term's own checks see them all. An evaluation is made once per ledger date holding a moved
informative group (the arms' frozen values differ on a row), on the ledger through that
date (:func:`evaluate`); a date-class is a distinct (date, class); the truth table
(:func:`step`) moves the streaks and the arm. The served arm, both streaks and the
evaluations are always the replay of the ledger (:func:`replay`): a day later in
``learn.excluded_days``, or one a pair of ``learn.excluded_rows`` names, is dropped whole and
the rest replayed, and serving refuses a state that is
not its own replay, or whose ``through`` is after the run's date (:func:`served_arms`); the
step writes the replay and repairs such a ``through``.

**Where and when.** :func:`run` runs at the end of ``predict read-labels`` (after its audit
and summary, before the call time counts lines), starts only before :data:`START_SECONDS`
of the step, counts no new date past :data:`COUNT_SECONDS` (nor one the longest date so far
would take past it: it writes what it counted, so a backlog is counted over runs) and writes
only before :data:`WRITE_SECONDS` (or later only through a date it counted that ran past the
count limit, so a slow date never stops the backlog); its lines are
said once the state they report is written. The state is one file on the live
host beside ``learn.json`` (:data:`SWITCH_PATH`: counts, sums and state FIPS codes, no
LEAIDs), written by a compare and swap (:func:`snowlight.live.publishers.guarded_write`: the
host's bytes must be the bytes this run read) and read back. After each read-back the frozen
record's marker (``frozen/switch.json``) is rewritten, so the frozen folder keeps each day
until it is counted (:func:`snowlight.predict.frozen.note_held`).
"""

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
import numpy.typing as npt

from snowlight.predict.config import PredictConfig, ScoreValue

if TYPE_CHECKING:
    from snowlight.predict.anchor import LiveRow
    from snowlight.predict.forecast_adjust import AdjustSettings
    from snowlight.predict.frozen import FrozenDay

type Arm = Literal["off", "on"]
type ArmValue = str | int | float
"""A registered arm's value: any JSON scalar but a bool (a name or a finite number), compared
as stored."""
type Day = date
"""A date (the name ``date`` is a field of the ledger's records)."""
ARMS: Final[tuple[Arm, Arm]] = ("off", "on")
PREFIX: Final = "switch_"
"""A ``live_score`` block named ``switch_<name>`` registers term ``name``."""
SWITCH_PATH: Final = "predictions/switch.json"
"""The state's key on the live host under the prefix (beside ``predictions/learn.json``)."""
SCHEMA: Final = 1
START_SECONDS: Final = 45.0
"""The switch starts only before the step's process has run this long (``predict
read-labels`` builds its model first, about 20 s, then labels the new days)."""
COUNT_SECONDS: Final = 55.0
"""It starts no new date past this, nor one that the longest date of the run so far would
take past it: the state is written through the last date fully counted (``through`` advances
only that far), so a backlog is counted over as many runs as it needs, at least one date a
run."""
WRITE_SECONDS: Final = 65.0
"""It writes only before this, unless a date it counted ran past :data:`COUNT_SECONDS` (that
write goes through with every date counted, so a slow date never stops a backlog). A host
write and its read-back take a few seconds, at most about 20 s each, so the step's 2-minute
limit can cut off only a worst-case or late one, which is safe: the write is one commit and
the frozen marker follows the read-back, so the days are kept."""
STATE_BYTES: Final = 2_000_000
"""A state larger than this is written with a warning (the bus term's is about 0.03 MB a
winter; every run reads, parses and replays it, so a term that keeps more per date must
say how it stays under this)."""
MOST: Final = 10**9
"""The most any count in the state may be (a district-day count is far under it)."""
LARGEST: Final = 1e12
"""The largest a sum in the state may be (either side of 0)."""
WAIT_DAYS: Final = 7
"""A labeled date whose frozen day the folder lacks (and lists as never released) waits this
many days for the evidence step's restore, then counts as absent."""
FREEZES: Final = ("d1_2007", "d1_2130", "d0_0507", "d0_0630")
"""The frozen record's freezes (:data:`snowlight.predict.frozen.NAMES`; a test holds them
equal)."""
SERVING_CLASSES: Final = ("advisory", "warning", "cold")
BOUND_MIN: Final = 0.5
"""The least interval a rule may register (its bounds the median at most)."""
CLAMP: Final = 1e-6
"""A frozen chance is taken in [CLAMP, 1 - CLAMP] for its log odds (6 decimals are kept)."""
_NAME: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_FROZEN_KEY: Final = re.compile(r"[a-z][a-z0-9]{0,7}")
_KEY: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
"""A group's own count or sum key: a short name."""
_STRATUM: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:.+-]{0,15}")
"""A group's stratum: a short name or a time (``06:30``), no space."""
_STATE: Final = re.compile(r"[0-9]{2}")
"""A group's state: a two-digit state FIPS code (never a LEAID)."""
_CLAUSE: Final = re.compile(r"[a-z][a-z0-9 _.,:;%+<>=()-]{0,79}")
"""A term's failing clause: short plain words and numbers."""
_DIGITS: Final = re.compile(r"[0-9]{5}")
"""A run of digits no count or number of a line needs (a LEAID has seven)."""


# --- the registry -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    """One term's registered switch (``live_score.switch_<name>``)."""

    name: str
    default: Arm
    arm_block: str
    arm_key: str
    arm_off: ArmValue
    arm_on: ArmValue
    scope: tuple[str, ...]
    revision: int
    frozen_key: str | None
    """The shadow variant each row of ``classes`` at ``freeze`` carries (``None``: the term
    freezes none, so its code has no :attr:`Term.shadow`)."""
    freeze: str
    classes: tuple[str, ...]
    bootstrap: int
    seed: int
    bound: float
    tolerance: float
    on_lower: float
    new_date_min: float | None
    """The new date's own on less off must be over this to switch on (``None``: the block
    leaves it out, so the rule has no such clause)."""
    on_after: int
    off_after: int
    clear_point: float
    clear_lower: float
    clear_class: float
    supply_dates: int
    supply_date_classes: int
    supply_states: int
    supply_rows: int
    max_date_share: float
    class_rows: int
    class_date_classes: int

    def value(self, arm: Arm) -> ArmValue:
        """The registered value of ``arm``."""
        return self.arm_on if arm == "on" else self.arm_off

    @classmethod
    def of(cls, name: str, block: Mapping[str, ScoreValue]) -> "Rule":  # noqa: PLR0915
        """The rule a ``switch_<name>`` block registers.

        Raises:
            ValueError: a setting is missing, of the wrong kind or out of range.
        """
        where = f"live_score.{PREFIX}{name}"
        known = {
            "default", "arm_block", "arm_key", "arm_off", "arm_on", "scope", "revision",
            "freeze", "classes", "bootstrap", "seed", "bound", "tolerance",
            "on_lower", "on_after", "off_after", "clear", "supply", "class_min",
        }  # fmt: skip
        optional = {"frozen_key", "new_date_min"}
        if not _NAME.fullmatch(name):
            raise ValueError(f"{where}: not a term name")
        if not known <= set(block) or not set(block) <= known | optional:
            missing = sorted(known - set(block))
            extra = sorted(set(block) - known - optional)
            raise ValueError(f"{where}: settings missing {missing} or unknown {extra}")

        def number(value: object, key: str) -> float:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{where}.{key} is not a number: {value!r}")
            if not math.isfinite(value):
                raise ValueError(f"{where}.{key} is not finite")
            return float(value)

        def whole(value: object, key: str, least: int) -> int:
            if isinstance(value, bool) or not isinstance(value, int) or value < least:
                raise ValueError(f"{where}.{key} is not a whole number of at least {least}")
            return value

        def text(key: str) -> str:
            value = block[key]
            if not isinstance(value, str) or not value:
                raise ValueError(f"{where}.{key} is not a name: {value!r}")
            return value

        def texts(key: str) -> tuple[str, ...]:
            value = block[key]
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            ):
                raise ValueError(f"{where}.{key} is not a list of names: {value!r}")
            if len(set(value)) != len(value):
                raise ValueError(f"{where}.{key} names one twice")
            return tuple(str(item) for item in value)

        def table(key: str, keys: Sequence[str]) -> dict[str, ScoreValue]:
            value = block[key]
            if not isinstance(value, dict) or set(value) != set(keys):
                raise ValueError(f"{where}.{key} must hold exactly {list(keys)}")
            return dict(value)

        default = block["default"]
        if default != "off":
            # the truth table is written for a term off by default: its ties, the evidence
            # and the new date's clause all go toward off (ON only once consistently better)
            raise ValueError(f"{where}.default must be off (ties go to off): {default!r}")
        arm: Arm = "off"
        classes = texts("classes")
        if not set(classes) <= set(SERVING_CLASSES):
            raise ValueError(f"{where}.classes are not serving classes: {list(classes)}")
        freeze = text("freeze")
        if freeze not in FREEZES:
            raise ValueError(f"{where}.freeze is not a freeze: {freeze!r}")
        frozen_key = text("frozen_key") if "frozen_key" in block else None
        if frozen_key is not None and not _FROZEN_KEY.fullmatch(frozen_key):
            raise ValueError(f"{where}.frozen_key is not a short key: {frozen_key!r}")
        clear = table("clear", ("point", "lower", "class"))
        supply = table("supply", ("dates", "date_classes", "states", "rows", "max_date_share"))
        least = table("class_min", ("rows", "date_classes"))
        found = cls(
            name=name,
            default=arm,
            arm_block=text("arm_block"),
            arm_key=text("arm_key"),
            arm_off=arm_value(block["arm_off"], f"{where}.arm_off"),
            arm_on=arm_value(block["arm_on"], f"{where}.arm_on"),
            scope=texts("scope"),
            revision=whole(block["revision"], "revision", 1),
            frozen_key=frozen_key,
            freeze=freeze,
            classes=classes,
            bootstrap=whole(block["bootstrap"], "bootstrap", 100),
            seed=whole(block["seed"], "seed", 0),
            bound=number(block["bound"], "bound"),
            tolerance=number(block["tolerance"], "tolerance"),
            on_lower=number(block["on_lower"], "on_lower"),
            new_date_min=(
                number(block["new_date_min"], "new_date_min") if "new_date_min" in block else None
            ),
            on_after=whole(block["on_after"], "on_after", 1),
            off_after=whole(block["off_after"], "off_after", 1),
            clear_point=number(clear["point"], "clear.point"),
            clear_lower=number(clear["lower"], "clear.lower"),
            clear_class=number(clear["class"], "clear.class"),
            supply_dates=whole(supply["dates"], "supply.dates", 1),
            supply_date_classes=whole(supply["date_classes"], "supply.date_classes", 1),
            supply_states=whole(supply["states"], "supply.states", 1),
            supply_rows=whole(supply["rows"], "supply.rows", 1),
            max_date_share=number(supply["max_date_share"], "supply.max_date_share"),
            class_rows=whole(least["rows"], "class_min.rows", 1),
            class_date_classes=whole(least["date_classes"], "class_min.date_classes", 1),
        )
        if same_value(found.arm_off, found.arm_on):
            raise ValueError(f"{where}: arm_off and arm_on are the same value")
        if not BOUND_MIN <= found.bound < 1:
            raise ValueError(f"{where}.bound must be in [0.5, 1)")
        if not 0 <= found.tolerance < 1:
            raise ValueError(f"{where}.tolerance must be in [0, 1)")
        if not -found.tolerance <= found.on_lower < 1 or (
            found.new_date_min is not None and not -1 < found.new_date_min < 1
        ):
            raise ValueError(f"{where}: on_lower or new_date_min out of range")
        if (
            not -1 < found.clear_point <= 0
            or not -1 < found.clear_lower <= -found.tolerance
            or not -1 < found.clear_class <= -found.tolerance
        ):
            raise ValueError(f"{where}.clear out of range (at most 0, and -tolerance for bounds)")
        if not 0 < found.max_date_share <= 1:
            raise ValueError(f"{where}.supply.max_date_share must be in (0, 1]")
        return found


def arm_value(value: object, where: str) -> ArmValue:
    """A registered arm's value: a name (a string, not empty) or a finite number, as stored.

    Raises:
        ValueError: it is neither (a bool, a list, a table, nothing).
    """
    if isinstance(value, str) and value:
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where} is not a name or a number: {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{where} is not finite")
    return value


def same_value(first: object, second: object) -> bool:
    """Whether two arm values are the same as stored: two equal names, or two equal numbers (a
    name is never a number; a bool is neither)."""
    if isinstance(first, bool) or isinstance(second, bool):
        return False
    if isinstance(first, str) or isinstance(second, str):
        return isinstance(first, str) and isinstance(second, str) and first == second
    return isinstance(first, int | float) and isinstance(second, int | float) and first == second


def arm_text(value: ArmValue) -> str:
    """An arm value as a line says it."""
    return value if isinstance(value, str) else f"{value:g}"


def rules(config: PredictConfig) -> dict[str, Rule]:
    """Every registered term's rule, by name (the ``switch_<name>`` blocks).

    Raises:
        ValueError: a block does not read as a rule.
    """
    return {
        key.removeprefix(PREFIX): Rule.of(key.removeprefix(PREFIX), block)
        for key, block in sorted(config.live_score.items())
        if key.startswith(PREFIX)
    }


def check_config(config: PredictConfig) -> None:
    """What config refuses for the switch: a block that is not a rule, an unknown term, an arm
    block or key that is not there, a scope block that is not there, a committed arm value
    that is not the default arm's (as stored: a name for a name, a number for a number), a
    ``frozen_key`` without the term's shadow (:attr:`Term.shadow`) or a shadow without one,
    and the term's own checks (:attr:`Term.check`).

    Raises:
        ValueError: any of them.
    """
    for name, rule in rules(config).items():
        where = f"live_score.{PREFIX}{name}"
        term = TERMS.get(name)
        if term is None:
            raise ValueError(f"{where}: no such term (live_switch.TERMS)")
        block = config.live_score.get(rule.arm_block)
        if block is None or rule.arm_key not in block:
            raise ValueError(f"{where}: no {rule.arm_block}.{rule.arm_key}")
        missing = [key for key in rule.scope if key not in config.live_score]
        if missing or rule.arm_block not in rule.scope:
            raise ValueError(f"{where}.scope must name live_score blocks with the arm block")
        held = block[rule.arm_key]
        kinds = {isinstance(value, str) for value in (held, rule.arm_off, rule.arm_on)}
        if isinstance(held, bool) or len(kinds) != 1:
            raise ValueError(
                f"{where}: arm_off, arm_on and the committed {rule.arm_block}.{rule.arm_key} "
                "must be all names or all numbers"
            )
        if not same_value(held, rule.value(rule.default)):
            raise ValueError(
                f"{where}: the committed {rule.arm_block}.{rule.arm_key} {held!r} is not the "
                f"default arm's ({rule.default}: {rule.value(rule.default)!r})"
            )
        if (rule.frozen_key is None) != (term.shadow is None):
            raise ValueError(
                f"{where}: frozen_key names the shadow variant of a term whose code freezes "
                "one (live_switch.Term.shadow), and only then"
            )
        term.check(config, rule)


def _bus_check(config: PredictConfig, rule: Rule) -> None:
    where = f"live_score.{PREFIX}bus_timing"
    if config.live_score.get("forecast_adjustment", {}).get("timing_bus") is not True:
        raise ValueError(
            f"{where}: forecast_adjustment.timing_bus must be true while the switch is "
            "registered (its arms are the bus term's o)"
        )
    if (rule.arm_block, rule.arm_key) != ("forecast_adjustment", "timing_after_bus"):
        raise ValueError(f"{where}: its arms are forecast_adjustment.timing_after_bus")
    for arm in ARMS:
        try:
            arm_settings(config, rule, arm)
        except (KeyError, ValueError) as error:
            raise ValueError(f"{where}: the {arm} arm's settings do not read: {error}") from error


@dataclass(frozen=True, slots=True)
class Key:
    """What a term's state and frozen rows are made over."""

    term_sha256: str
    model_sha256: str
    revision: int


def term_sha256(config: PredictConfig, rule: Rule) -> str:
    """The sha256 of the term's switch block and its scope blocks, as key-sorted compact JSON."""
    body = {f"{PREFIX}{rule.name}": config.live_score[f"{PREFIX}{rule.name}"]}
    body.update({key: config.live_score[key] for key in rule.scope})
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def key_of(config: PredictConfig, rule: Rule, model_sha256: str) -> Key:
    """The term's key with the committed model's sha256."""
    return Key(term_sha256(config, rule), model_sha256, rule.revision)


def served_config(config: PredictConfig, arms: Mapping[str, Arm]) -> PredictConfig:
    """A copy of ``config`` with each term's registered value of its arm put in (only the
    serving anchor is built from it; the committed config stays as it is). A term not named
    keeps the committed (default) value.

    Raises:
        ValueError: an arm or a term is not registered.
    """
    found = rules(config)
    score = {key: dict(block) for key, block in config.live_score.items()}
    for name, arm in arms.items():
        if name not in found or arm not in ARMS:
            raise ValueError(f"the switch: no registered arm {arm!r} of {name!r}")
        rule = found[name]
        score[rule.arm_block][rule.arm_key] = rule.value(arm)
    return config.model_copy(update={"live_score": score})


def arm_settings(config: PredictConfig, rule: Rule, arm: Arm) -> "AdjustSettings":
    """The forecast adjustment's settings with ``arm`` served (the bus term's shadow,
    :func:`bus_shadow`).

    Raises:
        KeyError, ValueError: as :meth:`snowlight.predict.forecast_adjust.AdjustSettings.of`.
    """
    from snowlight.predict.forecast_adjust import AdjustSettings  # noqa: PLC0415

    return AdjustSettings.of(served_config(config, {rule.name: arm}))


# --- the groups ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Group:
    """One labeled date's rows of one class (and stratum), scored under both arms: the exact
    conditional log-likelihood of which closed given how many (:func:`cll`) per arm, and the
    concordance's closed-over-open pairs (``wins2``: twice the wins plus the ties)."""

    day: Day
    klass: str
    stratum: str | None
    n: int
    closed: int
    cll_on: float
    cll_off: float
    pairs: int
    wins2_on: int
    wins2_off: int
    moved: bool
    states: tuple[str, ...]
    counts: Mapping[str, int] = field(default_factory=dict)
    """The term's own counts (its extra checks and lines read them)."""
    sums: Mapping[str, float] = field(default_factory=dict)
    """The term's own sums (finite numbers: an expected count, a calibration's terms)."""

    @property
    def informative(self) -> bool:
        """Some closed and some open (only such a group is scored)."""
        return 0 < self.closed < self.n

    def check(self) -> None:
        """What the state may hold of a group, whatever term made it: a serving class, its
        stratum a short name or a time and its own count and sum keys short names (no space, no
        run of five digits), each state a two-digit FIPS code
        (counts and numbers only, never a LEAID or list text), and counts that hold.

        Raises:
            ValueError: any of them does not.
        """
        names = [(_KEY, k) for k in (*self.counts, *self.sums)]
        if self.stratum is not None:
            names.append((_STRATUM, self.stratum))
        if self.klass not in SERVING_CLASSES:
            raise ValueError("a group's class is not a serving class")
        if not all(_matches(pattern, k) and not _DIGITS.search(str(k)) for pattern, k in names):
            raise ValueError("a group's stratum or count or sum key is not a short name")
        if not all(_matches(_STATE, s) for s in self.states):
            raise ValueError("a group's state is not a two-digit FIPS code")
        if not 0 <= self.closed <= self.n or self.pairs != self.closed * (self.n - self.closed):
            raise ValueError("a group's counts do not hold")

    @property
    def diff(self) -> float:
        """On less off, summed over the rows."""
        return self.cll_on - self.cll_off

    def as_json(self) -> dict[str, object]:
        """The ledger's form."""
        return {
            "class": self.klass,
            "stratum": self.stratum,
            "n": self.n,
            "closed": self.closed,
            "cll_on": self.cll_on,
            "cll_off": self.cll_off,
            "pairs": self.pairs,
            "wins2_on": self.wins2_on,
            "wins2_off": self.wins2_off,
            "moved": self.moved,
            "states": list(self.states),
            "counts": dict(sorted(self.counts.items())),
            "sums": dict(sorted(self.sums.items())),
        }

    @classmethod
    def of(cls, day: "Day", value: object) -> "Group":
        """A ledger group.

        Raises:
            ValueError: it does not read.
        """
        if not isinstance(value, dict):
            raise ValueError("a group is not an object")
        try:
            states = value["states"]
            counts = value.get("counts") or {}
            sums = value.get("sums") or {}
            stratum = value.get("stratum")
            found = cls(
                day=day,
                klass=_str(value["class"]),
                stratum=None if stratum is None else _str(stratum),
                n=_int(value["n"]),
                closed=_int(value["closed"]),
                cll_on=_finite(value["cll_on"]),
                cll_off=_finite(value["cll_off"]),
                pairs=_int(value["pairs"]),
                wins2_on=_int(value["wins2_on"]),
                wins2_off=_int(value["wins2_off"]),
                moved=_bool(value["moved"]),
                states=tuple(_str(s) for s in states),
                counts={_str(k): _int(v) for k, v in dict(counts).items()},
                sums={_str(k): _finite(v) for k, v in dict(sums).items()},
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"a group does not read: {type(error).__name__}") from error
        found.check()
        return found


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    """Whether ``value`` is text the whole of which ``pattern`` matches."""
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _warned(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("a ledger date's warned_sha256 is not a sha256")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MOST:
        raise TypeError
    return value


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError
    if isinstance(value, int) and abs(value) > LARGEST:
        raise TypeError  # before float(): a whole number past a float's range
    if not math.isfinite(value) or abs(value) > LARGEST:
        raise TypeError
    return float(value)


def cll(logits: npt.NDArray[np.float64], closed: npt.NDArray[np.bool_]) -> float:
    """The exact conditional log-likelihood of which rows closed given how many closed:
    the closed rows' log odds less the log of the elementary symmetric polynomial of order
    ``m`` (the count closed) of their exponentials, by its recursion; 0 when none or all
    closed."""
    n, m = len(logits), int(closed.sum())
    if m in {0, n}:
        return 0.0
    e = np.full(m + 1, -np.inf)
    e[0] = 0.0
    for t in logits:
        e[1:] = np.logaddexp(e[1:], e[:-1] + t)
    return float(logits[closed].sum() - e[m])


def wins2(values: npt.NDArray[np.float64], closed: npt.NDArray[np.bool_]) -> int:
    """Twice the closed-over-open pairs a closed row's value is over, plus the ties."""
    shut = values[closed]
    opened = np.sort(values[~closed])
    below = np.searchsorted(opened, shut, side="left")
    upto = np.searchsorted(opened, shut, side="right")
    return int(2 * below.sum() + (upto - below).sum())


def logit(values: Sequence[float]) -> npt.NDArray[np.float64]:
    """Log odds of frozen chances, each taken in [CLAMP, 1 - CLAMP]."""
    p = np.clip(np.asarray(values, dtype=np.float64), CLAMP, 1.0 - CLAMP)
    return np.asarray(np.log(p) - np.log1p(-p), dtype=np.float64)


def scored(  # noqa: PLR0913, PLR0917 - the date, the cell and its rows
    day: date,
    klass: str,
    stratum: str | None,
    off: Sequence[float],
    on: Sequence[float],
    closed: Sequence[bool],
    states: Sequence[str],
    counts: Mapping[str, int] | None = None,
    sums: Mapping[str, float] | None = None,
) -> Group:
    """One group from its rows' frozen chances under each arm and whether each closed."""
    shut = np.asarray(closed, dtype=np.bool_)
    t_off, t_on = logit(off), logit(on)
    m = int(shut.sum())
    return Group(
        day=day,
        klass=klass,
        stratum=stratum,
        n=len(shut),
        closed=m,
        cll_on=cll(t_on, shut),
        cll_off=cll(t_off, shut),
        pairs=m * (len(shut) - m),
        wins2_on=wins2(t_on, shut),
        wins2_off=wins2(t_off, shut),
        moved=any(a != b for a, b in zip(off, on, strict=True)),
        states=tuple(sorted(set(states))),
        counts=dict(counts or {}),
        sums=dict(sums or {}),
    )


@dataclass(frozen=True, slots=True)
class DayInputs:
    """What a term's group builder reads for one labeled date D. What the arms are judged by
    (``labels``) is D's. A fitted arm fits only on the dates before D: through ``earlier``
    (their labels; it refuses D and every later date) and the ledger's own sums of them
    (``ledger``: their frozen rows are released once counted, so a fit over many dates keeps
    what it needs in its groups' sums).

    The guard is partly the term's own code: ``reads`` is L1's whole record folder, D's labels
    and later dates' included, so a term reads from it only D's inputs cut at a time on D,
    never a label, and a review of the term checks that."""

    day: date
    labels: Mapping[str, "LiveRow"]
    """L1's labeled rows of D by district (``no_school``, ``delayed`` or ``unnamed``, tier A
    or B): the outcome the arms are judged by, never fitted on."""
    frozen: "FrozenDay"
    rule: Rule
    key: Key
    class_of: Callable[[str], str | None]
    """The serving class of a situation (the anchor's)."""
    config: PredictConfig | None = None
    """The committed config (the term's own settings: ``live_score`` and the rest)."""
    reads: Path | None = None
    """L1's private record folder: for D's inputs cut at a time on D only. It also holds D's
    and later dates' labels (``rows/``), which a term never reads from here and never fits
    on."""
    before: tuple[date, ...] = ()
    """The labeled dates before D, oldest first (none in ``learn.excluded_days``)."""
    ledger: tuple["LedgerDate", ...] = ()
    """The ledger counted so far (every date in it is before D), every group each date's
    term built with its counts and sums: what a fitted arm fits on over many dates."""
    earlier: Callable[[date], Mapping[str, "LiveRow"]] | None = None
    """L1's labeled rows of a date in ``before``, to fit on (any other date is refused with a
    ValueError: :func:`earlier_reader`)."""


def earlier_reader(
    reads: Path, day: date, before: Sequence[date]
) -> Callable[[date], Mapping[str, "LiveRow"]]:
    """L1's labeled rows of a date before ``day`` (one of ``before``), by district: the only
    labels a term may fit on.

    The reader raises ValueError for ``day``, any later date or a date not in ``before``, and
    OSError where the file does not read."""
    allowed = frozenset(d for d in before if d < day)

    def read(wanted: date) -> Mapping[str, "LiveRow"]:
        if wanted not in allowed:
            raise ValueError(f"the switch fits on dates before {day.isoformat()} only")
        return _label_rows(reads, wanted)[1]

    return read


def keyed(row: Any, rule: Rule, key: Key) -> bool:
    """Whether a frozen row's freeze header names the term's current key (only such rows
    count)."""
    found = row.switch.get(rule.name) if isinstance(row.switch, Mapping) else None
    return (
        isinstance(found, Mapping)
        and found.get("sha256") == key.term_sha256
        and found.get("model_sha256") == key.model_sha256
    )


def pair_of(value: object) -> tuple[float, float] | None:
    """A row's ``[off, on]`` variant, ``None`` unless it is two chances in [0, 1]."""
    if not isinstance(value, list | tuple) or len(value) != len(ARMS):
        return None
    found: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        if not math.isfinite(item) or not 0 <= item <= 1:
            return None
        found.append(float(item))
    return found[0], found[1]


def bus_groups(inputs: DayInputs) -> list[Group]:
    """The bus term's groups of a labeled date: per class, the served ``d0_0507`` rows with
    ``v.bt`` under the term's key that L1 labeled, where L1's class of the day is the row's
    (``no_school`` closed; ``unnamed`` or ``delayed`` open)."""
    rule = inputs.rule
    cells: dict[str, tuple[list[float], list[float], list[bool], list[str]]] = {}
    seen: set[str] = set()
    for row in inputs.frozen.rows:
        if row.freeze != rule.freeze or not row.served or row.leaid in seen:
            continue
        if not keyed(row, rule, inputs.key):
            continue
        pair = pair_of(row.variants.get(rule.frozen_key or ""))
        label = inputs.labels.get(row.leaid)
        if pair is None or label is None:
            continue
        klass = inputs.class_of(label.weather)
        if klass is None or klass != row.klass or klass not in rule.classes:
            continue
        seen.add(row.leaid)
        off, on, shut, states = cells.setdefault(klass, ([], [], [], []))
        off.append(pair[0])
        on.append(pair[1])
        shut.append(label.label == "no_school")
        states.append(row.leaid[:2])
    return [
        scored(inputs.day, klass, None, *cells[klass]) for klass in rule.classes if klass in cells
    ]


def _no_extra(
    _config: PredictConfig, _rule: Rule, _ledger: Sequence["LedgerDate"]
) -> tuple[str, ...]:
    return ()


def _no_check(_config: PredictConfig, _rule: Rule) -> None:
    return None


def bus_shadow(config: PredictConfig, rule: Rule) -> tuple["AdjustSettings", "AdjustSettings"]:
    """The bus term's shadow: the forecast adjustment's settings under each arm (off, on),
    whose chances every served row of its classes at its freeze carries."""
    return arm_settings(config, rule, "off"), arm_settings(config, rule, "on")


@dataclass(frozen=True, slots=True)
class Term:
    """A registered term's code: its group builder, its extra checks (failing clause names,
    from the ledger through the date judged), its own config checks, and its freeze-time
    shadow, if any.

    A term whose arm is fitted on live labels fits each date's group only on the dates
    before it (:attr:`DayInputs.earlier` and the ledger's sums), never on ``reads``' labels,
    and the group is frozen once counted. The ledger, the evaluation, the truth table, the
    replay and the state are the switch's and the same for every term. Its arm reaches the
    anchor (:func:`served_config`); a term whose serving code reads its value elsewhere reads
    it through :func:`served_value`."""

    groups: Callable[[DayInputs], list[Group]]
    checks: Callable[[PredictConfig, Rule, Sequence["LedgerDate"]], tuple[str, ...]] = _no_extra
    """The term's failing clause names on the ledger through the date judged (every group it
    built, informative or not), with the committed config and the rule, so a check reads its
    registered numbers from the config's ``live_score`` (its scope blocks), never from code.
    Each clause is short plain text (:func:`clauses`)."""
    check: Callable[[PredictConfig, Rule], None] = _no_check
    shadow: Callable[[PredictConfig, Rule], tuple["AdjustSettings", "AdjustSettings"]] | None = None
    """The forecast adjustment's settings under each arm (off, on), whose chances each served
    row of the rule's classes at its freeze carries as ``v.<frozen_key>`` (the frozen record's
    shadow; ``None``: the term freezes no variant and builds its groups from other inputs)."""


TERMS: Final[dict[str, Term]] = {
    "bus_timing": Term(groups=bus_groups, check=_bus_check, shadow=bus_shadow)
}
"""Each registered term's code, by name."""


# --- the ledger, the evaluation and the truth table ---------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerDate:
    """One counted date: every group its term built (informative or not: a term's own
    checks read them all, e.g. a calibration over every row at risk) and the sha256 of L1's
    file it was counted from. Only its informative groups (:attr:`scored`) are scored and
    counted as evidence."""

    day: Day
    label_sha256: str
    groups: tuple[Group, ...]
    warned_sha256: str | None = None
    """The sha256 of a later L1 file of the date already warned of (said once a file)."""

    @property
    def scored(self) -> tuple[Group, ...]:
        """Its informative groups (some closed, some open): the only ones scored."""
        return tuple(g for g in self.groups if g.informative)

    @property
    def informative(self) -> bool:
        """Whether it holds an informative group (it is a block of the evaluation)."""
        return any(g.informative for g in self.groups)

    @property
    def moved(self) -> bool:
        """Whether an informative group of it moved (it is judged)."""
        return any(g.moved for g in self.scored)

    def as_json(self) -> dict[str, object]:
        found: dict[str, object] = {
            "date": self.day.isoformat(),
            "label_sha256": self.label_sha256,
            "groups": [g.as_json() for g in self.groups],
        }
        if self.warned_sha256 is not None:
            found["warned_sha256"] = self.warned_sha256
        return found

    @classmethod
    def of(cls, value: object) -> "LedgerDate":
        """A ledger date.

        Raises:
            ValueError: it does not read.
        """
        if not isinstance(value, dict):
            raise ValueError("a ledger date is not an object")
        try:
            day = date.fromisoformat(_str(value["date"]))
            sha = _str(value["label_sha256"])
            groups = tuple(Group.of(day, g) for g in value["groups"])
            warned = value.get("warned_sha256")
        except (KeyError, TypeError) as error:
            raise ValueError(f"a ledger date does not read: {type(error).__name__}") from error
        if not groups:
            raise ValueError("a ledger date holds no group")
        return cls(day, sha, groups, None if warned is None else _warned(warned))


@dataclass(frozen=True, slots=True)
class ClassScore:
    klass: str
    diff: float
    rows: int
    moved: int
    binding: bool

    @property
    def per_row(self) -> float:
        return self.diff / self.rows if self.rows else 0.0


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One evaluation, on the ledger through ``date`` (its numbers per district-day)."""

    day: Day
    number: int
    moved_dates: int
    date_classes: int
    states: int
    rows: int
    largest_share: float
    point: float
    lower: float
    upper: float
    classes: tuple[ClassScore, ...]
    new_date: float
    concordance_on: float | None
    concordance_off: float | None
    extra: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "date": self.day.isoformat(),
            "number": self.number,
            "moved_dates": self.moved_dates,
            "date_classes": self.date_classes,
            "states": self.states,
            "rows": self.rows,
            "largest_share": round(self.largest_share, 6),
            "point": round(self.point, 8),
            "lower": round(self.lower, 8),
            "upper": round(self.upper, 8),
            "classes": {
                c.klass: {"per_row": round(c.per_row, 8), "rows": c.rows, "binding": c.binding}
                for c in self.classes
            },
            "new_date": round(self.new_date, 8),
            "concordance_on": None
            if self.concordance_on is None
            else round(self.concordance_on, 6),
            "concordance_off": (
                None if self.concordance_off is None else round(self.concordance_off, 6)
            ),
            "extra": list(self.extra),
        }


def evaluate(
    rule: Rule, ledger: Sequence[LedgerDate], number: int, extra: Sequence[str] = ()
) -> Evaluation:
    """The evaluation on ``ledger`` (every counted date through the one judged, the last,
    which holds an informative group), over its informative groups only: P the overall on
    less off per district-day, L and U the bounds of :attr:`Rule.bootstrap` date-block
    resamples (one block per date with an informative group) from ``default_rng(seed)`` (so
    the same ledger always gives the same numbers), each class's own, and the last date's own.
    A date-class is a distinct (date, class) with a moved group, however many strata it is
    split into.

    Raises:
        ValueError: the last date holds no informative group.
    """
    blocks = [entry.scored for entry in ledger if entry.informative]
    if not ledger or not ledger[-1].informative:
        raise ValueError("an evaluation is of a date with an informative group")
    groups = [g for block in blocks for g in block]
    d = np.array([sum(g.diff for g in block) for block in blocks], dtype=np.float64)
    n = np.array([sum(g.n for g in block) for block in blocks], dtype=np.float64)
    rows = int(n.sum())
    rng = np.random.default_rng(rule.seed)
    picks = rng.integers(0, len(blocks), size=(rule.bootstrap, len(blocks)))
    draws = d[picks].sum(axis=1) / n[picks].sum(axis=1)
    tail = (1.0 - rule.bound) / 2.0
    lower = float(np.percentile(draws, 100.0 * tail))
    upper = float(np.percentile(draws, 100.0 * (1.0 - tail)))
    classes: list[ClassScore] = []
    for klass in rule.classes:
        mine = [g for g in groups if g.klass == klass]
        count = sum(g.n for g in mine)
        moved = len({g.day for g in mine if g.moved})
        classes.append(
            ClassScore(
                klass=klass,
                diff=sum(g.diff for g in mine),
                rows=count,
                moved=moved,
                binding=count >= rule.class_rows and moved >= rule.class_date_classes,
            )
        )
    pairs = sum(g.pairs for g in groups)
    last = ledger[-1]
    return Evaluation(
        day=last.day,
        number=number,
        moved_dates=sum(1 for entry in ledger if entry.moved),
        date_classes=moved_date_classes(groups),
        states=len({s for g in groups for s in g.states}),
        rows=rows,
        largest_share=float(n.max() / n.sum()),
        point=float(d.sum() / n.sum()),
        lower=lower,
        upper=upper,
        classes=tuple(classes),
        new_date=float(d[-1] / n[-1]),
        concordance_on=sum(g.wins2_on for g in groups) / (2 * pairs) if pairs else None,
        concordance_off=sum(g.wins2_off for g in groups) / (2 * pairs) if pairs else None,
        extra=tuple(extra),
    )


def moved_date_classes(groups: Sequence[Group]) -> int:
    """The distinct (date, class) pairs with a moved group (a stratified term's groups of one
    date and class are one date-class)."""
    return len({(g.day, g.klass) for g in groups if g.moved})


def short_of_evidence(rule: Rule, found: Evaluation) -> tuple[str, ...]:
    """The evidence's failing counts (switching on only)."""
    short: list[str] = []
    if found.moved_dates < rule.supply_dates:
        short.append(f"{found.moved_dates} of {rule.supply_dates} moved dates")
    if found.date_classes < rule.supply_date_classes:
        short.append(f"{found.date_classes} of {rule.supply_date_classes} date-classes")
    if found.states < rule.supply_states:
        short.append(f"{found.states} of {rule.supply_states} states")
    if found.rows < rule.supply_rows:
        short.append(f"{found.rows:,} of {rule.supply_rows:,} rows")
    if found.largest_share > rule.max_date_share:
        short.append(f"largest date {found.largest_share:.0%} over {rule.max_date_share:.0%}")
    return tuple(short)


def _tol(rule: Rule) -> str:
    return f"-{rule.tolerance:g}" if rule.tolerance else "0"


def held_clauses(rule: Rule, found: Evaluation) -> list[str]:
    """What a term served or switching on must hold besides the evidence, ``on_lower`` and
    the new date: P over 0, L and every binding class at least -tolerance, no failing extra
    (each failing one named)."""
    failing: list[str] = []
    if not found.point > 0:
        failing.append("on - off at or under 0")
    if not found.lower >= -rule.tolerance:
        failing.append(f"lower bound under {_tol(rule)}")
    failing.extend(
        f"{c.klass} under {_tol(rule)}"
        for c in found.classes
        if c.binding and not c.per_row >= -rule.tolerance
    )
    failing.extend(found.extra)
    return failing


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the truth table made of one evaluation."""

    word: str
    """``confident``, ``not confident``, ``holding``, ``behind`` or ``clear``."""
    clauses: tuple[str, ...]
    served: Arm
    on_streak: int
    off_streak: int
    switched: bool


def step(  # noqa: PLR0911 - each cell of the truth table
    rule: Rule, served: Arm, on_streak: int, off_streak: int, found: Evaluation
) -> Verdict:
    """The truth table (ties go to the default, which is always off):

    - OFF, CONFIDENT (the evidence, P > 0, L > on_lower, L >= -tolerance, every binding class
      >= -tolerance, the new date > new_date_min where registered, no failing extra): the ON
      streak + 1; at ``on_after`` ON, both streaks 0. Anything else: the ON streak 0.
    - ON, CLEAR (P < clear.point, L < clear.lower or a binding class < clear.class): OFF at
      once, both streaks 0.
    - ON, HOLDING (not clear; P > 0, L >= -tolerance, every binding class >= -tolerance, no
      failing extra): the OFF streak 0.
    - ON, BEHIND (anything else): the OFF streak + 1; at ``off_after`` OFF, both streaks 0.
    """
    held = held_clauses(rule, found)
    if served == "off":
        failing: list[str] = []
        short = short_of_evidence(rule, found)
        if short:
            failing.append(f"short of evidence ({', '.join(short)})")
        if not found.lower > rule.on_lower:
            # on_lower is at least -tolerance, so this names a lower bound under it too
            held = [c for c in held if not c.startswith("lower bound")]
            held.insert(int(not found.point > 0), f"lower bound at or under {rule.on_lower:g}")
        failing.extend(held)
        if rule.new_date_min is not None and not found.new_date > rule.new_date_min:
            failing.append(f"this date at or under {rule.new_date_min:g}")
        if failing:
            return Verdict("not confident", tuple(failing), "off", 0, off_streak, switched=False)
        if on_streak + 1 >= rule.on_after:
            return Verdict("confident", (), "on", 0, 0, switched=True)
        return Verdict("confident", (), "off", on_streak + 1, off_streak, switched=False)
    clear: list[str] = []
    if found.point < rule.clear_point:
        clear.append(f"on - off {_fmt(found.point)}")
    if found.lower < rule.clear_lower:
        clear.append(f"lower bound {_fmt(found.lower)}")
    clear.extend(
        f"{c.klass} {_fmt(c.per_row)}"
        for c in found.classes
        if c.binding and c.per_row < rule.clear_class
    )
    if clear:
        return Verdict("clear", tuple(clear), "off", 0, 0, switched=True)
    if not held:
        return Verdict("holding", (), "on", on_streak, 0, switched=False)
    if off_streak + 1 >= rule.off_after:
        return Verdict("behind", tuple(held), "off", 0, 0, switched=True)
    return Verdict("behind", tuple(held), "on", on_streak, off_streak + 1, switched=False)


@dataclass(frozen=True, slots=True)
class Judged:
    """One evaluation and its verdict, with the arm served before it."""

    evaluation: Evaluation
    before: Arm
    verdict: Verdict
    streak: tuple["Day", ...]
    """The dates of the evaluations that made the switch (a switch only)."""


@dataclass(frozen=True, slots=True)
class Replay:
    """The ledger replayed: the served arm, both streaks and every evaluation in order."""

    served: Arm
    on_streak: int
    off_streak: int
    judged: tuple[Judged, ...]
    length: int = 0
    """How many ledger dates it replayed (the prefix a later replay may go on from)."""
    run: tuple["Day", ...] = ()
    """The dates of the confident or behind evaluations since the last switch or reset."""


def clauses(found: Sequence[object]) -> tuple[str, ...]:
    """A term's failing clauses as checked: each short plain text (lower-case words and
    numbers, at most 80 characters, no run of five digits), so no LEAID or list text reaches
    a line or the state.

    Raises:
        ValueError: one is not.
    """
    for item in found:
        if not _matches(_CLAUSE, item) or _DIGITS.search(str(item)):
            raise ValueError("a term's clause is not short plain text")
    return tuple(str(item) for item in found)


def replay(
    rule: Rule,
    ledger: Sequence[LedgerDate],
    term: Term,
    config: PredictConfig,
    *,
    prior: Replay | None = None,
) -> Replay:
    """The truth table over the ledger's dates in order, from the default arm: one evaluation
    per date holding a moved informative group, on the ledger through it (:func:`evaluate`;
    the term's checks see every group of it, with ``config`` and the rule).

    ``prior``: the replay of this same ledger's first ``prior.length`` dates (the step's of
    its stored ledger, before it appends the dates it counts), gone on from rather than
    replayed again: each evaluation is of its own prefix only, so the result is the same to
    the bit and the step replays each date once a run.

    Raises:
        ValueError: ``prior`` replayed more dates than ``ledger`` holds.
    """
    served: Arm = rule.default
    on_streak = off_streak = 0
    judged: list[Judged] = []
    run: list[date] = []
    begin = 0
    if prior is not None:
        if prior.length > len(ledger):
            raise ValueError("a prior replay is of a longer ledger")
        served, on_streak, off_streak = prior.served, prior.on_streak, prior.off_streak
        judged, run, begin = list(prior.judged), list(prior.run), prior.length
    for i in range(begin, len(ledger)):
        entry = ledger[i]
        if not entry.moved:
            continue
        through = ledger[: i + 1]
        extra = clauses(term.checks(config, rule, through))
        found = evaluate(rule, through, len(judged) + 1, extra)
        verdict = step(rule, served, on_streak, off_streak, found)
        word = verdict.word
        run = [*run, entry.day] if word in {"confident", "behind"} else []
        made = tuple(run) if verdict.switched else ()
        if verdict.switched and word == "clear":
            made = (entry.day,)
        judged.append(Judged(found, served, verdict, made))
        if verdict.switched:
            run = []
        served, on_streak, off_streak = verdict.served, verdict.on_streak, verdict.off_streak
    return Replay(served, on_streak, off_streak, tuple(judged), len(ledger), tuple(run))


# --- the state ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TermState:
    """One term's state on the host."""

    term_sha256: str
    model_sha256: str
    revision: int
    served: Arm
    on_streak: int
    off_streak: int
    through: date | None
    ledger: tuple[LedgerDate, ...] = ()
    evaluations: tuple[Mapping[str, object], ...] = ()
    switches: tuple[Mapping[str, object], ...] = ()

    @property
    def key(self) -> Key:
        return Key(self.term_sha256, self.model_sha256, self.revision)

    def as_json(self) -> dict[str, object]:
        return {
            "term_sha256": self.term_sha256,
            "model_sha256": self.model_sha256,
            "revision": self.revision,
            "served": self.served,
            "on_streak": self.on_streak,
            "off_streak": self.off_streak,
            "through": None if self.through is None else self.through.isoformat(),
            "ledger": [entry.as_json() for entry in self.ledger],
            "evaluations": [dict(item) for item in self.evaluations],
            "switches": [dict(item) for item in self.switches],
        }

    @classmethod
    def of(cls, value: object) -> "TermState":
        """A term's state.

        Raises:
            ValueError: it does not read.
        """
        if not isinstance(value, dict):
            raise ValueError("a term's state is not an object")
        try:
            served = value["served"]
            if served not in ARMS:
                raise ValueError(f"served is not an arm: {served!r}")
            through = value["through"]
            ledger = tuple(LedgerDate.of(item) for item in value["ledger"])
            found = cls(
                term_sha256=_str(value["term_sha256"]),
                model_sha256=_str(value["model_sha256"]),
                revision=_int(value["revision"]),
                served="on" if served == "on" else "off",
                on_streak=_int(value["on_streak"]),
                off_streak=_int(value["off_streak"]),
                through=None if through is None else date.fromisoformat(_str(through)),
                ledger=ledger,
                evaluations=tuple(dict(item) for item in value.get("evaluations") or ()),
                switches=tuple(dict(item) for item in value.get("switches") or ()),
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"a term's state does not read: {type(error).__name__}") from error
        days = [entry.day for entry in ledger]
        if days != sorted(set(days)) or (
            days and (found.through is None or days[-1] > found.through)
        ):
            raise ValueError("the ledger's dates are not in order, once each, through through")
        return found


def parse_state(data: bytes) -> dict[str, TermState]:
    """The host's state, by term.

    Raises:
        ValueError: it does not read as schema 1.
    """
    body = json.loads(data)
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA:
        raise ValueError("not a switch state of schema 1")
    terms = body.get("terms")
    if not isinstance(terms, dict):
        raise ValueError("no terms")
    return {str(name): TermState.of(value) for name, value in sorted(terms.items())}


def state_bytes(terms: Mapping[str, TermState]) -> bytes:
    """The host file's bytes (key-sorted, compact, one line)."""
    body = {
        "schema_version": SCHEMA,
        "terms": {name: terms[name].as_json() for name in sorted(terms)},
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def why_not_served(  # noqa: PLR0911 - each reason said
    config: PredictConfig, rule: Rule, state: TermState | None, key: Key, today: date
) -> str | None:
    """Why a term's stored arm is not served (``None``: it is), with ``::warning::`` first
    where it is a fault: a ``through`` after ``today`` (the run's UTC date: ``through`` only
    ever advances to a labeled date, so a later one is a hand edit or a bug), or a served arm,
    a streak or the evaluations that are not the replay of its ledger (so the serving line
    never says a number the ledger does not give)."""
    if state is None:
        return "no state for it"
    if state.key != key:
        return "another key"
    if state.through is not None and state.through > today:
        return f"::warning::through {state.through.isoformat()} is after the run's date"
    excluded = sorted(set(config.learn.left_out_days()) & {e.day for e in state.ledger})
    if excluded:
        named = config.learn.left_out_by(excluded[0])
        return f"its ledger holds {excluded[0].isoformat()}, in {named}"
    term = TERMS.get(rule.name)
    if term is None:
        return "no such term"
    found = replay(rule, state.ledger, term, config)
    if not is_replay(state, found):
        return "::warning::not the replay of its ledger"
    return None


def is_replay(state: TermState, found: Replay) -> bool:
    """Whether the state's served arm, both streaks and its evaluations are ``found``, the
    replay of its ledger (its ``switches`` are its history, kept over restarts and
    exclusions, and never served or said)."""
    return (found.served, found.on_streak, found.off_streak) == (
        state.served,
        state.on_streak,
        state.off_streak,
    ) and [dict(e) for e in state.evaluations] == [j.evaluation.as_json() for j in found.judged]


def marker_of(terms: Mapping[str, TermState], names: Sequence[str]) -> date | None:
    """The frozen record's marker a state gives (``frozen/switch.json``): the earliest
    ``through`` of the registered terms ``names`` (``None``: one has none, or no state)."""
    throughs = [terms[name].through if name in terms else None for name in names]
    if not throughs or None in throughs:
        return None
    return min(d for d in throughs if d is not None)


def behind(config: PredictConfig, data: bytes | None, marker: date | None) -> date | None:
    """The marker a read state gives when it is behind the frozen record's ``marker`` (the
    step's last read-back, so a host replica that has not caught up yet), else ``None``; a
    state that does not read is never behind (serving says why it takes the default)."""
    if marker is None:
        return None
    if data is None:
        return date.min
    try:
        found = marker_of(parse_state(data), list(rules(config)))
    except Exception:  # serving says it does not read
        return None
    if found is None:
        return date.min
    return found if found < marker else None


@dataclass(frozen=True, slots=True)
class Served:
    """What a run serves: each term's arm, its key and the lines that say so."""

    arms: Mapping[str, Arm]
    keys: Mapping[str, Key]
    lines: tuple[str, ...] = ()
    rules: Mapping[str, Rule] = field(default_factory=dict)


def served_arms(
    config: PredictConfig,
    data: bytes | None,
    model_sha256: str,
    *,
    today: date,
    why: str | None = None,
) -> Served:
    """Each term's arm from the host's state (``data``; ``None``: none there), and its key:
    the committed default on any of: no state, a state that does not read, another key, a
    ``through`` after ``today`` (the run's UTC date), a ledger holding an excluded day, or a
    served arm, streak or evaluation that is not the replay of its ledger; and on whatever
    goes wrong reading or replaying it (any error: a run never fails on the state). ``why``:
    the state was not read (said instead)."""
    found = rules(config)
    arms: dict[str, Arm] = {}
    keys: dict[str, Key] = {}
    lines: list[str] = []
    states: dict[str, TermState] = {}
    broken: str | None = why
    if broken is None and data is None:
        broken = f"no {Path(SWITCH_PATH).name}"
    elif broken is None and data is not None:
        try:
            states = parse_state(data)
        except Exception as error:  # a state that does not read serves the default
            broken = f"::warning::{Path(SWITCH_PATH).name} does not read ({type(error).__name__})"
    for name, rule in found.items():
        key = key_of(config, rule, model_sha256)
        keys[name] = key
        state = states.get(name)
        reason = broken
        if reason is None:
            try:
                reason = why_not_served(config, rule, state, key, today)
            except Exception as error:  # and so does one whose replay fails
                reason = f"::warning::its ledger does not replay ({type(error).__name__})"
        arms[name] = rule.default
        if reason is None and state is not None:
            arms[name] = state.served
            through = "none" if state.through is None else state.through.isoformat()
            lines.append(
                f"switch: {name} served {state.served} ({Path(SWITCH_PATH).name} through "
                f"{through}, {len(state.evaluations)} evaluations)"
            )
            continue
        text = (reason or "").removeprefix("::warning::")
        warn = "::warning::" if (reason or "").startswith("::warning::") else ""
        lines.append(f"{warn}switch: {name} served {rule.default}, the committed default ({text})")
    return Served(arms, keys, tuple(lines), found)


def served_value(switch: Served | None, config: PredictConfig, name: str) -> ArmValue:
    """The registered value of the arm a run serves for term ``name`` (the committed
    default's with no switch read, as in tests and ``predict read-labels``).

    The anchor is built from :func:`served_config`, so a term read through the anchor's
    settings (the bus term's ``timing_after_bus``) needs nothing more. A term whose own
    serving code reads its value anywhere else (CALL-TIME-2's ``call_time.serve``, read by
    its per-pass decline) reads it here, from the run's :class:`Served` (the pass's
    ``switch``), never from the committed config, which always holds the default.

    Raises:
        ValueError: no such term is registered.
    """
    rule = rules(config).get(name)
    if rule is None:
        raise ValueError(f"the switch: no registered term {name!r}")
    arm = switch.arms.get(name, rule.default) if switch is not None else rule.default
    return rule.value(arm)


# --- the step in predict read-labels ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepInputs:
    """What :func:`run` reads (tests replace them)."""

    config: PredictConfig
    host: Any
    """The live host (:class:`snowlight.live.publishers.Publisher`)."""
    prefix: str
    reads: Path
    """L1's private record."""
    frozen: Path | None
    model_sha256: str | None
    now: datetime
    started: float
    clock: Callable[[], float] = time.monotonic


@dataclass(slots=True)
class _Count:
    new: int = 0
    informative: int = 0
    moved: int = 0
    absent: int = 0
    held: int = 0
    """The labeled dates not counted this run (from ``held_at`` on, for ``why``)."""
    held_at: date | None = None
    why: Literal["", "wait", "late", "unread"] = ""


class _LateError(Exception):
    """Past :data:`WRITE_SECONDS`: nothing is written."""


@dataclass(frozen=True, slots=True)
class _Said:
    """A line of the step, said once the state it reports is written (``unwritten``: as it is
    said when the state is not)."""

    text: str
    unwritten: str

    @classmethod
    def of(cls, text: str) -> "_Said":
        return cls(text, f"{text} (not written)")


def _label_rows(reads: Path, day: date) -> tuple[str, dict[str, "LiveRow"]]:
    """L1's file of ``day``: its sha256 and its labeled rows by district.

    Raises:
        OSError, ValueError: it does not read.
    """
    from snowlight.predict import live_read  # noqa: PLC0415
    from snowlight.predict.anchor_labels import day_rows  # noqa: PLC0415

    data = live_read.rows_path(reads, day).read_bytes()
    rows = day_rows(day, json.loads(data))
    found: dict[str, LiveRow] = {}
    for row in rows:
        found.setdefault(row.district, row)
    return hashlib.sha256(data).hexdigest(), found


def _class_of(config: PredictConfig) -> Callable[[str], str | None]:
    from snowlight.predict.anchor import CHAIN, AnchorSettings  # noqa: PLC0415

    mapping = AnchorSettings.of(config).class_of

    def of(situation: str) -> str | None:
        found = mapping.get(situation, CHAIN)
        return None if found == CHAIN else found

    return of


def _fmt(value: float) -> str:
    return f"{value:+.4f}"


def counts_line(rule: Rule, state: TermState, count: _Count) -> str:
    """The term's line each run (counts and numbers only, over its whole ledger), with the
    labeled dates not counted this run and why (waiting for a frozen day, left past
    :data:`COUNT_SECONDS`, or held at a date that does not read)."""
    through = "none" if state.through is None else state.through.isoformat()
    moved = sum(1 for e in state.ledger if e.moved)
    groups = [g for e in state.ledger for g in e.scored]
    classes = moved_date_classes(groups)
    states = len({s for g in groups for s in g.states})
    rows = sum(g.n for g in groups)
    streak = (
        f"ON streak {state.on_streak} of {rule.on_after}"
        if state.served == "off"
        else f"OFF streak {state.off_streak} of {rule.off_after}"
    )
    plural = "date" if count.new == 1 else "dates"
    found = (
        f"switch {rule.name} (served {state.served}): through {through}; {moved} of "
        f"{rule.supply_dates} moved dates, {classes} of {rule.supply_date_classes} date-classes, "
        f"{states} of {rule.supply_states} states, {rows:,} of {rule.supply_rows:,} rows; "
        f"{streak}; {count.new} new labeled {plural} ({count.informative} informative, "
        f"{count.moved} moved, {count.absent} with no frozen rows)"
    )
    if count.held and count.held_at is not None:
        held = f"{count.held} labeled {'date' if count.held == 1 else 'dates'}"
        at = count.held_at.isoformat()
        if count.why == "wait":
            found += f"; {held} waiting for the frozen day of {at}"
        elif count.why == "late":
            found += f"; {held} from {at} left for the next run (past {COUNT_SECONDS:.0f} s)"
        else:
            found += f"; {held} held at {at}, which does not read"
    return found


def evaluation_line(rule: Rule, judged: Judged) -> str:
    """One evaluation's line."""
    found, verdict = judged.evaluation, judged.verdict
    parts = []
    for c in found.classes:
        bound = "" if c.binding else ", not binding"
        parts.append(f"{c.klass} {_fmt(c.per_row)} ({c.rows:,} rows{bound})")
    concordance = (
        f"concordance on {found.concordance_on:.3f} off {found.concordance_off:.3f}"
        if found.concordance_on is not None and found.concordance_off is not None
        else "concordance none"
    )
    if verdict.word == "confident":
        said = (
            f"confident, ON streak {rule.on_after} of {rule.on_after}"
            if verdict.switched
            else f"confident, ON streak {verdict.on_streak} of {rule.on_after}"
        )
    elif verdict.word == "not confident":
        said = f"not confident: {', '.join(verdict.clauses)}; ON streak 0 of {rule.on_after}"
    elif verdict.word == "holding":
        said = f"holding, OFF streak 0 of {rule.off_after}"
    elif verdict.word == "behind":
        streak = rule.off_after if verdict.switched else verdict.off_streak
        said = f"behind, OFF streak {streak} of {rule.off_after}: {', '.join(verdict.clauses)}"
    else:
        said = f"clear: {', '.join(verdict.clauses)}"
    return (
        f"switch {rule.name}: {found.day.isoformat()} evaluation {found.number} (served "
        f"{judged.before}): {found.moved_dates} moved dates, {found.date_classes} date-classes, "
        f"{found.states} states, {found.rows:,} rows, largest date {found.largest_share:.0%}; "
        f"on - off {_fmt(found.point)} a district-day ({rule.bound:.0%} {_fmt(found.lower)} to "
        f"{_fmt(found.upper)}); {', '.join(parts)}; this date {_fmt(found.new_date)}; "
        f"{concordance}; {said}"
    )


def switch_line(rule: Rule, judged: Judged, *, written: bool = True) -> str:
    """The line of a switch the truth table made (``written`` false: the state saying it was
    not written, so nothing switched)."""
    verdict = judged.verdict
    value = f"{rule.arm_key} {arm_text(rule.value(verdict.served))}"
    value += " serves from this run's passes" if written else " would serve (not written)"
    dates = ", ".join(d.isoformat() for d in judged.streak)
    if verdict.word == "confident":
        return (
            f"switch {rule.name}: SWITCHED on after {rule.on_after} confident evaluations "
            f"({dates}): {value}"
        )
    if verdict.word == "clear":
        return (
            f"switch {rule.name}: SWITCHED off at once: clear ({', '.join(verdict.clauses)}): "
            f"{value}"
        )
    return f"switch {rule.name}: SWITCHED off: behind {rule.off_after} in a row ({dates}): {value}"


def _start(rule: Rule, key: Key, held: TermState | None) -> TermState:
    """A term's state started, or restarted under its new key (``held``'s switches kept)."""
    return TermState(
        term_sha256=key.term_sha256,
        model_sha256=key.model_sha256,
        revision=key.revision,
        served=rule.default,
        on_streak=0,
        off_streak=0,
        through=None,
        switches=() if held is None else held.switches,
    )


def _start_line(rule: Rule, key: Key, held: TermState | None, unreadable: bool) -> str:
    keys = f"term sha {key.term_sha256[:8]}, model sha {key.model_sha256[:8]}"
    if unreadable:
        return f"switch {rule.name}: restarted (a state that does not read, to {keys})"
    if held is None:
        return f"switch {rule.name}: started (no state; {keys})"
    if held.term_sha256 != key.term_sha256:
        was, now = f"term sha {held.term_sha256[:8]}", f"term sha {key.term_sha256[:8]}"
    elif held.model_sha256 != key.model_sha256:
        was, now = f"model sha {held.model_sha256[:8]}", f"model sha {key.model_sha256[:8]}"
    else:
        was, now = f"revision {held.revision}", f"revision {key.revision}"
    return f"switch {rule.name}: restarted ({was} to {now})"


def _relabeled(
    inputs: StepInputs,
    rule: Rule,
    ledger: list[LedgerDate],
    warn: Callable[[str], None],
    over: Callable[[], bool],
) -> None:
    """Warn once for each new L1 file of a counted date (its counted numbers are kept; the
    sha256 warned of is kept with it)."""
    from snowlight.predict import live_read  # noqa: PLC0415

    for at, entry in enumerate(ledger):
        if over():
            return
        try:
            data = live_read.rows_path(inputs.reads, entry.day).read_bytes()
        except OSError:
            continue
        now = hashlib.sha256(data).hexdigest()
        if now in {entry.label_sha256, entry.warned_sha256}:
            continue
        warn(
            f"::warning::predict read-labels: switch {rule.name}: L1's file of "
            f"{entry.day.isoformat()} changed after it was counted: its counted numbers are kept"
        )
        ledger[at] = replace(entry, warned_sha256=now)


def _count_day(  # noqa: PLR0913, PLR0917 - the step, the term and the date
    inputs: StepInputs,
    rule: Rule,
    term: Term,
    key: Key,
    day: date,
    found_day: "FrozenDay",
    counted: tuple[tuple[date, ...], tuple[LedgerDate, ...]],
) -> tuple[LedgerDate | None, bool]:
    """A labeled date's ledger entry, every group its term built (``None``: none) and whether
    its frozen day held no row under the key.

    Raises:
        Exception: any its files or the term's code raise, and ValueError for a group the
            state may not hold (:meth:`Group.check`).
    """
    before, ledger = counted
    sha, labels = _label_rows(inputs.reads, day)
    built = term.groups(
        DayInputs(
            day=day,
            labels=labels,
            frozen=found_day,
            rule=rule,
            key=key,
            class_of=_class_of(inputs.config),
            config=inputs.config,
            reads=inputs.reads,
            before=before,
            ledger=ledger,
            earlier=earlier_reader(inputs.reads, day, before),
        )
    )
    for group in built:
        if group.day != day or group.klass not in rule.classes:
            raise ValueError("a group is not of the date and the rule's classes")
        group.check()
    absent = not any(row.freeze == rule.freeze and keyed(row, rule, key) for row in found_day.rows)
    return (LedgerDate(day, sha, tuple(built)) if built else None), absent


def _repaired(
    rule: Rule, key: Key, state: TermState, today: date, labeled: Sequence[date]
) -> tuple[TermState, _Said]:
    """A state whose ``through`` is after the run's date (a hand edit or a bug: it only ever
    advances to a labeled date) repaired, with its warning: ``through`` back to its ledger's
    last date (the dates after it are counted again: each adds to the ledger only once), or
    to the newest labeled date with an empty ledger; a ledger holding a date after the run's
    date is restarted over."""
    was = "" if state.through is None else state.through.isoformat()
    head = (
        f"::warning::predict read-labels: switch {rule.name}: through {was} is after the run's date"
    )
    future = [e.day for e in state.ledger if e.day > today]
    if future:
        text = f"{head}, and so is its ledger's {future[0].isoformat()}"
        fixed = replace(_start(rule, key, state), through=labeled[-1] if labeled else None)
        return fixed, _Said(
            f"{text}: restarted over it", f"{text}: would restart over it (not written)"
        )
    to: date | None = state.ledger[-1].day if state.ledger else None
    why = "its ledger's last date"
    if to is None:
        to, why = (labeled[-1] if labeled else None), "the newest labeled date"
    text = f"{'none' if to is None else to.isoformat()} ({why})"
    fixed = replace(state, through=to)
    return fixed, _Said(
        f"{head}: repaired to {text}", f"{head}: would repair to {text} (not written)"
    )


def _streak_text(served: Arm, on_streak: int, off_streak: int) -> str:
    return f"ON streak {on_streak}" if served == "off" else f"OFF streak {off_streak}"


def _excluded_line(
    rule: Rule, excluded: Sequence[date], was: Replay, now: Replay, named: str
) -> _Said:
    """The line of days dropped as left out (a switch line when the arm the rest replays to
    differs); ``named``: the list or lists that leave them out (``learn.excluded_days``,
    ``learn.excluded_rows``, or both: :func:`_left_out_named`)."""
    listed = ", ".join(d.isoformat() for d in excluded)
    if now.served != was.served:
        return _Said.of(
            f"switch {rule.name}: SWITCHED {now.served}: {listed} excluded "
            f"({named}); the ledger without it ends {now.served}"
        )
    before = _streak_text(was.served, was.on_streak, was.off_streak)
    after = _streak_text(now.served, now.on_streak, now.off_streak)
    moved = f"{before} to {after.split()[-1]}" if before != after else f"{after} unchanged"
    return _Said.of(
        f"switch {rule.name}: {listed} excluded ({named}): dropped from the ledger; "
        f"served {now.served}, {moved}"
    )


def _left_out_named(config: PredictConfig, days: Sequence[date]) -> str:
    """The take-back list that leaves ``days`` out: ``learn.excluded_days`` when every one is
    in that list, ``learn.excluded_rows`` when every one is named only by pairs, both names
    when the days are of both kinds."""
    names = sorted({config.learn.left_out_by(day) or "learn.excluded_days" for day in days})
    return ", ".join(names)


@dataclass(slots=True)
class _Limits:
    """The step's clock (seconds since the step's process began) and how far a date counted
    ran past :data:`COUNT_SECONDS` (``None``: none did)."""

    elapsed: Callable[[], float]
    overran: float | None = None

    def over(self) -> bool:
        return self.elapsed() > COUNT_SECONDS


def _step_term(  # noqa: PLR0912, PLR0913, PLR0915 - one term's whole step
    inputs: StepInputs,
    rule: Rule,
    term: Term,
    key: Key,
    held: TermState | None,
    *,
    unreadable: bool = False,
    warn: Callable[[str], None],
    limits: _Limits,
) -> tuple[TermState, list[_Said]]:
    """One term's new state (``held``: the host's; ``unreadable``: the host's did not read)
    and its lines, said once the state is written (a warning of a fault no write changes is
    said at once). Counting stops at :data:`COUNT_SECONDS` (a date starts only if the longest
    date of the run so far would end by it; one that ends past it is kept and noted in
    ``limits``), at a date waiting for its frozen day and at a date that does not read: the
    state is through the last date fully counted.

    Raises:
        OSError, ValueError: L1's record does not list its days, or a term's check or the
            replay does not hold.
    """
    from snowlight.predict import live_read  # noqa: PLC0415

    config = inputs.config
    today = inputs.now.date()
    every = [d for d in live_read.labeled_days(inputs.reads) if d <= today]
    left_out = set(config.learn.left_out_days())
    labeled = [d for d in every if d not in left_out]
    said: list[_Said] = []
    state = held
    if state is None or state.key != key:
        said.append(_Said.of(_start_line(rule, key, state, unreadable)))
        state = replace(_start(rule, key, state), through=labeled[-1] if labeled else None)
    elif state.through is not None and state.through > today:
        state, line = _repaired(rule, key, state, today, labeled)
        said.append(line)
    if every and state.through is not None and state.through > every[-1]:
        warn(
            f"::warning::predict read-labels: switch {rule.name}: through "
            f"{state.through.isoformat()} is after L1's newest labeled date, "
            f"{every[-1].isoformat()}"
        )
    # A day later in learn.excluded_days, or named by a pair of learn.excluded_rows (the
    # ledger keeps sums per date, so one row cannot be taken out of a counted date): dropped
    # whole, and the rest replayed (Decision 9).
    excluded = sorted({e.day for e in state.ledger} & left_out)
    ledger = [e for e in state.ledger if e.day not in left_out]
    switches = list(state.switches)
    stored = replay(rule, state.ledger, term, config)
    if not is_replay(state, stored):
        # a fault (a hand edit, a bug, a numpy change): the replay is what is written
        text = (
            f"::warning::predict read-labels: switch {rule.name}: the stored arm, streaks or "
            f"evaluations are not the replay of its ledger: the replay's ({stored.served}, "
            f"{len(stored.judged)} evaluations)"
        )
        said.append(_Said(f"{text} is written", f"{text} would be written (not written)"))
    before = replay(rule, ledger, term, config) if excluded else stored
    if excluded:
        said.append(
            _excluded_line(rule, excluded, stored, before, _left_out_named(config, excluded))
        )
        if before.served != stored.served:
            switches.append(
                {"date": excluded[0].isoformat(), "to": before.served, "why": "excluded"}
            )
    _relabeled(inputs, rule, ledger, warn, limits.over)
    count = _Count()
    through = state.through
    pending = [d for d in labeled if through is None or d > through]
    longest = 0.0
    for at, day in enumerate(pending):
        began = limits.elapsed()
        if began > COUNT_SECONDS or (count.new and began + longest > COUNT_SECONDS):
            count.held, count.held_at, count.why = len(pending) - at, day, "late"
            break
        try:
            status, found_day = (
                _frozen_day(inputs.frozen, day, rule.freeze)
                if inputs.frozen is not None
                else ("missing", None)
            )
            if status == "wait" or (
                status == "missing" and inputs.now.date() - day <= timedelta(days=WAIT_DAYS)
            ):
                # in date order: this date and every later one wait
                count.held, count.held_at, count.why = len(pending) - at, day, "wait"
                break
            entry, absent = (
                (None, True)
                if found_day is None
                else _count_day(
                    inputs, rule, term, key, day, found_day,
                    (tuple(d for d in labeled if d < day), tuple(ledger)),
                )
            )  # fmt: skip
        except Exception as error:  # one date that does not read stops the count
            warn(
                f"::warning::predict read-labels: switch {rule.name}: {day.isoformat()} does "
                f"not read ({type(error).__name__}): counting stops before it "
                "(learn.excluded_days passes it)"
            )
            count.held, count.held_at, count.why = len(pending) - at, day, "unread"
            break
        ended = limits.elapsed()
        if ended > COUNT_SECONDS:
            # it ran past the limit: kept (its write goes through even if late), and said at
            # once, so a step cut off before it writes still says which date was slow
            limits.overran = max(limits.overran or 0.0, ended)
            warn(
                f"switch {rule.name}: {day.isoformat()} ran to {ended:.0f} s of the step, past "
                f"{COUNT_SECONDS:.0f} s: kept"
            )
        longest = max(longest, ended - began)
        count.new += 1
        count.absent += int(absent)
        through = day
        if entry is None:
            continue
        count.informative += int(entry.informative)
        count.moved += int(entry.moved)
        ledger.append(entry)
    after = replay(rule, ledger, term, config, prior=before)
    old = {j.evaluation.day for j in before.judged}
    for judged in after.judged:
        if judged.evaluation.day in old:
            continue
        said.append(_Said.of(evaluation_line(rule, judged)))
        if judged.verdict.switched:
            said.append(_Said(switch_line(rule, judged), switch_line(rule, judged, written=False)))
            switches.append(
                {
                    "date": judged.evaluation.day.isoformat(),
                    "to": judged.verdict.served,
                    "why": judged.verdict.word,
                }
            )
    new = replace(
        state,
        served=after.served,
        on_streak=after.on_streak,
        off_streak=after.off_streak,
        through=through,
        ledger=tuple(ledger),
        evaluations=tuple(j.evaluation.as_json() for j in after.judged),
        switches=tuple(switches),
    )
    said.append(_Said.of(counts_line(rule, new, count)))
    return new, said


def _frozen_day(folder: Path, day: date, freeze: str) -> tuple[str, "FrozenDay | None"]:
    from snowlight.predict import frozen as frozen_module  # noqa: PLC0415

    return frozen_module.switch_day(folder, day, freeze)


def _newer(data: bytes) -> bool:
    """Whether the host's state is of a later schema than this code's (never overwritten)."""
    try:
        body = json.loads(data)
    except Exception:  # not JSON: not a later schema either
        return False
    version = body.get("schema_version") if isinstance(body, dict) else None
    return isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA


def _outcome(host: Any, key: str, body: bytes, data: bytes | None) -> str:
    """What a write whose answer was lost did, read back once: ``written`` (the host holds
    ``body``), ``unchanged`` (it holds ``data``, what the run read) or why it is unknown."""
    try:
        now = host.read(key)
    except Exception as error:  # unknown
        return f"the read-back failed ({type(error).__name__})"
    if now == body:
        return "written"
    if now == data:
        return "unchanged"
    return "the host holds other bytes"


def run(  # noqa: PLR0911, PLR0912, PLR0915 - the step, each way it ends said
    inputs: StepInputs, out: Callable[[str], None]
) -> None:
    """The switch's step at the end of ``predict read-labels`` (see the module): each term's
    new labeled dates counted, evaluated and switched, the state written by a compare and
    swap and read back, and the frozen record's marker rewritten from the host's state.

    Its lines are said once the state is written (marked ``not written`` where it is not); a
    host state that does not read restarts every term over it, with one warning. Any failure
    is one warning and writes nothing; it never changes a label, the audit, ``added`` or the
    exit."""
    from snowlight.live.publishers import (  # noqa: PLC0415
        GuardRefusedError,
        KeyRefusedError,
        MovedError,
        WriteGuard,
        guarded_write,
    )
    from snowlight.predict import frozen as frozen_module  # noqa: PLC0415

    def said(line: str) -> None:
        out(line if line.startswith("::warning::") else f"predict read-labels: {line}")

    if inputs.clock() - inputs.started > START_SECONDS:
        said(f"switch: skipped past {START_SECONDS:.0f} s of the step")
        return

    limits = _Limits(lambda: inputs.clock() - inputs.started)
    lines: list[_Said] = []

    def unwritten() -> None:
        for line in lines:
            said(line.unwritten)

    key = f"{inputs.prefix}/{SWITCH_PATH}"
    try:
        found = rules(inputs.config)
        if not found:
            return
        if inputs.model_sha256 is None:
            said("switch: no committed model sha256: nothing written")
            return
        data = inputs.host.read(key)
        held: dict[str, TermState] = {}
        unreadable = False
        if data is not None:
            try:
                held = parse_state(data)
            except Exception as error:  # restarted over, below
                if _newer(data):
                    said(
                        f"::warning::predict read-labels: switch: {SWITCH_PATH} is of a later "
                        "schema: nothing written"
                    )
                    return
                text = (
                    f"::warning::predict read-labels: switch: {SWITCH_PATH} does not read "
                    f"({type(error).__name__}): every term"
                )
                lines.append(
                    _Said(
                        f"{text} restarted over it",
                        f"{text} would restart over it (not written)",
                    )
                )
                unreadable = True
        terms = dict(held)
        for name, rule in found.items():
            terms[name], mine = _step_term(
                inputs,
                rule,
                TERMS[name],
                key_of(inputs.config, rule, inputs.model_sha256),
                held.get(name),
                unreadable=unreadable,
                warn=said,
                limits=limits,
            )
            lines.extend(mine)
        body = state_bytes(terms)
        if body != data:
            if limits.elapsed() > WRITE_SECONDS and limits.overran is None:
                raise _LateError
            if limits.overran is not None:
                lines.append(
                    _Said.of(
                        f"switch: a date counted ran to {limits.overran:.0f} s, past "
                        f"{COUNT_SECONDS:.0f} s: written through every date counted"
                    )
                )
            if len(body) > STATE_BYTES:
                lines.append(
                    _Said.of(
                        f"::warning::predict read-labels: switch: {SWITCH_PATH} is "
                        f"{len(body):,} B, over {STATE_BYTES:,} B"
                    )
                )
    except _LateError:
        unwritten()
        said(f"switch: skipped past {WRITE_SECONDS:.0f} s of the step: nothing written")
        return
    except Exception as error:  # the switch never changes what the step did
        unwritten()
        said(f"::warning::predict read-labels: switch: {type(error).__name__}: nothing written")
        return
    lost = False
    if body != data:
        try:
            guarded_write(inputs.host, {key: body}, WriteGuard(key, lambda now: now != data))
        except (GuardRefusedError, MovedError, KeyRefusedError) as error:  # nothing written
            unwritten()
            said(f"::warning::predict read-labels: switch: {type(error).__name__}: nothing written")
            return
        except Exception as error:  # the answer may be lost: the host says what it holds
            name = type(error).__name__
            outcome = _outcome(inputs.host, key, body, data)
            if outcome != "written":
                unwritten()
                said(
                    f"::warning::predict read-labels: switch: {name}: nothing written"
                    if outcome == "unchanged"
                    else f"::warning::predict read-labels: switch: {name}: the write's outcome "
                    f"is unknown ({outcome}): nothing is said as written and the frozen days "
                    "are kept"
                )
                return
            lost = True
    for line in lines:
        said(line.text)
    if lost:
        said(
            f"::warning::predict read-labels: switch: the write's answer was lost: "
            f"{SWITCH_PATH} ({len(body):,} B) read back as written"
        )
    elif body != data:
        try:
            back = inputs.host.read(key)
        except Exception as error:  # written: only the read-back failed
            said(
                f"::warning::predict read-labels: switch: wrote {SWITCH_PATH} ({len(body):,} B), "
                f"read back failed ({type(error).__name__})"
            )
            return
        if back != body:
            said(
                f"::warning::predict read-labels: switch: wrote {SWITCH_PATH} ({len(body):,} B), "
                "but it did not read back as written"
            )
            return
        said(f"switch: wrote {SWITCH_PATH} ({len(body):,} B), read back")
    if inputs.frozen is not None:
        marker = marker_of(terms, list(found))
        try:
            # never past the run's date (a through after it is repaired above)
            frozen_module.write_marker(
                inputs.frozen, None if marker is None else min(marker, inputs.now.date())
            )
        except OSError as error:
            said(
                f"::warning::predict read-labels: switch: the frozen marker: "
                f"{type(error).__name__}: the frozen days are kept"
            )
