"""Each district's complete record from a state's dated calendar file (records-mo MO-3; spec
SPEC RECORDS-MO r2 section 4 with lead rulings LR-1 to LR-5; docs/predict.md, "Past records").

From the kept alert school days of :func:`snowlight.predict.open_days.alert_days`, per
district and kind of day (``advisory``, ``warning``, ``cold``):

* ``days``: its days with an outcome (no school, a short day or school held; a day called
  ``some`` or ``unknown`` is left out), counting only days on which at least one **district near
  it** had a kept day of the same kind (LR-5: the other districts of its NWS forecast office
  area, never statewide); a day with fewer than ``HABIT_NEAR`` of them to compare is left out
  of the record, so no day rests on one or two districts and "districts near it" is always
  several;
* ``no_school``: closed or school at home; ``home``: the days at home among them; ``short``: the
  short days (school met, so a day with school);
* ``same100``: 100 times the sum, over its days, of the share of the districts near it with the
  same kind of day on the same date that had no school (closed or at home), rounded half up;
  its verdict is tested against ``p = same100 / (100 x days)``, so both sides count no school
  the same way and nothing is judged against closings-only lists;
* ``winters``: the complete school years in which it listed a weather day (for the checks and
  the docs, never a sentence);
* ``area``: its forecast office (the peers' area).

The verdict (:func:`verdict`) is the web panel's ``verdictOf`` with that ``p``: an exact
one-sided binomial at ``HABIT_DAYS`` 5 and ``HABIT_LUCK`` 0.05; a "holds out" with fewer than
``HABIT_MIN_SCHOOL`` days with school gives no verdict at all. **Nothing here moves a chance**
(LR-9): the rows reach only the habit box, through the standing file's ``record_full``.

The file (``<state>-record-ed<n>.csv``, committed and pinned beside the state's day file) is
``leaid,kind,days,no_school,home,short,same100,winters,area``, sorted by LEAID and kind.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, Literal

from snowlight.predict.open_days import AlertDay, Kind

KINDS: Final[tuple[Kind, ...]] = ("advisory", "warning", "cold")
HEADER: Final = "leaid,kind,days,no_school,home,short,same100,winters,area"
HABIT_DAYS: Final = 5
"""The fewest days of one kind a habit is judged on (``steps.ts`` ``HABIT_DAYS``)."""
HABIT_LUCK: Final = 0.05
"""How unlikely by luck its gap must be (``steps.ts`` ``HABIT_LUCK``)."""
HABIT_MIN_SCHOOL: Final = 2
"""The fewest days with school a "holds out" verdict of a complete record rests on
(``steps.ts`` ``HABIT_MIN_SCHOOL``): on storm warning days nearly every district near it has no
school (a share of 0.99), so one day read as school held would give the verdict alone, and one
such day may be a closing the file does not hold (its codes 12 and 13). With fewer, the record
gives no verdict (never "about like most": the test said it is not)."""
HABIT_NEAR: Final = 5
"""The fewest districts near it with the same kind of day a day of its record is compared
with."""
DECIDED: Final = frozenset({"closed", "remote", "short", "open", "makeup"})
NO_SCHOOL: Final = frozenset({"closed", "remote"})

type Verdict = Literal["hold", "close", "like"]


class FullRecordError(ValueError):
    """A record row or file that does not add up."""


@dataclass(frozen=True, slots=True)
class FullRow:
    """One district's complete record of one kind of day."""

    leaid: str
    kind: Kind
    days: int
    no_school: int
    home: int
    short: int
    same100: int
    winters: int
    area: str

    def check(self) -> None:
        """Its parts add up: ``home <= no_school``, ``no_school + short <= days``, and
        ``same100 <= 100 x days``.

        Raises:
            FullRecordError: they do not.
        """
        if not (
            self.days >= 1
            and 0 <= self.home <= self.no_school
            and self.short >= 0
            and self.no_school + self.short <= self.days
            and 0 <= self.same100 <= 100 * self.days
            and self.winters >= 0
        ):
            raise FullRecordError(f"{self.leaid} {self.kind}: a record row that does not add up")


def half_up(value: Fraction) -> int:
    """``value`` rounded to a whole number, a half rounded up."""
    return math.floor(value + Fraction(1, 2))


def full_rows(
    kept: Iterable[AlertDay],
    area_of: Mapping[str, str],
    winters_of: Mapping[str, int],
    near: int = HABIT_NEAR,
) -> list[FullRow]:
    """Each district's rows (see the module), sorted by LEAID and kind: a day counts only with
    ``near`` or more districts near it to compare. A district with no area has no row."""
    decided = [d for d in kept if d.outcome in DECIDED and d.leaid in area_of]
    same: dict[tuple[str, Kind, object], list[tuple[str, bool]]] = defaultdict(list)
    for d in decided:
        same[area_of[d.leaid], d.kind, d.day].append((d.leaid, d.outcome in NO_SCHOOL))
    parts: dict[tuple[str, Kind], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    shares: dict[tuple[str, Kind], Fraction] = defaultdict(Fraction)
    for d in decided:
        others = [no for leaid, no in same[area_of[d.leaid], d.kind, d.day] if leaid != d.leaid]
        if len(others) < near:
            continue
        row = parts[d.leaid, d.kind]
        row[0] += 1
        row[1] += d.outcome in NO_SCHOOL
        row[2] += d.outcome == "remote"
        row[3] += d.outcome == "short"
        shares[d.leaid, d.kind] += Fraction(sum(others), len(others))
    found = [
        FullRow(
            leaid,
            kind,
            days,
            no,
            home,
            short,
            half_up(100 * shares[leaid, kind]),
            winters_of.get(leaid, 0),
            area_of[leaid],
        )
        for (leaid, kind), (days, no, home, short) in parts.items()
    ]
    found.sort(key=lambda r: (r.leaid, KINDS.index(r.kind)))
    for item in found:
        item.check()
    return found


def record_file(rows: Sequence[FullRow]) -> bytes:
    """The rows as the record file."""
    lines = [HEADER] + [
        f"{r.leaid},{r.kind},{r.days},{r.no_school},{r.home},{r.short},{r.same100},"
        f"{r.winters},{r.area}"
        for r in rows
    ]
    return ("\n".join(lines) + "\n").encode()


def read_record_file(data: bytes) -> list[FullRow]:
    """A record file's rows, each checked.

    Raises:
        FullRecordError: not a record file, a row that does not read or add up, or a district
            and kind twice.
    """
    lines = data.decode().splitlines()
    if not lines or lines[0] != HEADER:
        raise FullRecordError("not a record file")
    found: list[FullRow] = []
    for line in lines[1:]:
        cells = line.split(",")
        if len(cells) != len(HEADER.split(",")) or cells[1] not in KINDS:
            raise FullRecordError("a record row that does not read")
        leaid, kind, *numbers, area = cells
        days, no, home, short, same, winters = (int(n) for n in numbers)
        row = FullRow(leaid, kind, days, no, home, short, same, winters, area)  # type: ignore[arg-type]
        row.check()
        found.append(row)
    if len({(r.leaid, r.kind) for r in found}) != len(found):
        raise FullRecordError("a district and kind twice")
    return found


def tails(n: int, k: int, p: float) -> tuple[float, float]:
    """P(X <= k) and P(X >= k) for X binomial with n tries and chance p, summed in the web
    panel's order (``steps.ts`` ``tails``)."""
    low = 0.0
    high = 0.0
    choose = 1.0
    for x in range(n + 1):
        if x > 0:
            choose = choose * (n - x + 1) / x
        mass = choose * p**x * (1 - p) ** (n - x)
        if x <= k:
            low += mass
        if x >= k:
            high += mass
    return low, high


def verdict(no_school: int, days: int, p: float) -> Verdict | None:
    """The habit's verdict for a complete record: ``None`` under ``HABIT_DAYS`` days, and
    ``None`` for a "holds out" on fewer than ``HABIT_MIN_SCHOOL`` days with school."""
    if days < HABIT_DAYS or not 0 <= p <= 1:
        return None
    low, high = tails(days, no_school, p)
    if low < HABIT_LUCK:
        return "hold" if days - no_school >= HABIT_MIN_SCHOOL else None
    if high < HABIT_LUCK:
        return "close"
    return "like"


def stored_share(row: FullRow) -> float:
    """The peer share the stored row gives (``same100 / (100 x days)``)."""
    return row.same100 / (100 * row.days)
