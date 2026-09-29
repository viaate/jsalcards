"""District alert channels and status boards: the rows that announce a closing, and the proof gate.

A TV station's closings list proves itself with any row: the list exists only for
closings. Two kinds of this part's sources do not:

* A school district's alert channel (:data:`GENERAL_CHANNEL_ADAPTERS`): its homepage
  banner (Apptegy), page pops (Finalsite), pop-up alerts (Smart Sites), homepage
  alert (Edlio), organization alerts (SchoolBlocks), Pasco's emergency banner and
  Miami-Dade's alerts file carry whatever the district posts, and most days that
  is a superintendent's appointment, a hiring call or a referendum. Such a
  channel is proven only by a row that announced a closing, a delay, an early
  dismissal, a remote day, cancelled classes or activities, or weather or an
  emergency for the district: Martin County's "HURRICANE MILTON UPDATE: All
  MCSD-operated schools and offices will be closed ...", not Lake County's "School
  Board names Chad Farnsworth next Superintendent".
* A status board (:data:`STATUS_BOARD_ADAPTERS`): a county's or a state's table
  naming every school or school system with its status (Flathead County's
  closures page, the Shasta and Trinity county offices' sheets, GOHSEP's parish
  layer). It holds rows every day, most of them "Open", so a row proves nothing
  until one of them has a status other than open: "Closed", "Early Dismissal",
  "Remote", "Closing at 12:45".

:func:`announces_closing` is the channel rule (deterministic, word patterns only,
in English and, for South Texas' and Miami's districts, Spanish;
it does not read dates or decide what kind of closure a row is, which the status
reader does). A planned calendar day with no closure word ("Staff Development Day
... There is NO school for students") and a reopening with no weather word
("schools will be OPEN Friday") do not qualify. :func:`board_status_announces` is
the board rule: a status that announces a closing, or names a remote day, a delay,
a late start or a shortened day. :func:`gate_proofs` applies them to the proofs of
the gated stations (by their platform's adapter): a proof (a populated read, live,
archived or a committed fixture) is kept only when one of its rows qualifies. The
rows come from the ``rows.jsonl`` written beside each ``reads.jsonl`` (matched by
source and read time) and, for a fixture, from reading the fixture with its
adapter. The report it returns goes into ``coverage.json`` (internal) as
``district_notice_gate``::

    {source_id: {"kind": "channel" | "board",
                 "kept": n, "kept_proofs": [{"mode", "captured_at", "url", "basis", "row"}, ...],
                 "dropped_count": n,
                 "dropped": [{"mode", "captured_at", "url", "basis", "reason", "row"}, ...]}}

(``row`` is the first qualifying row of a kept proof, the first row of a dropped
one, as ``name | status``.) :func:`annotate_unproven` adds each gated station's
dropped count to its entry in the ``unproven`` list, so that list says why a
populated read did not prove it.

Which text is read: a channel row's status, and its name too when the name is the
notice's own title (Finalsite, Smart Sites, Edlio, Miami-Dade), not when it is the
district's name (Apptegy, Schoolwires, Campus Suite, SchoolBlocks, Pasco:
:data:`ORG_NAMED_VARIANTS`), so a district called "Storm Lake" never proves itself;
a board row's status only.
"""

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from snowlight.output import JSONValue
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.model import ShapeError
from snowlight.sources.stations.registry import Registry

GENERAL_CHANNEL_ADAPTERS = frozenset(
    {"apptegy", "dadeschools", "edlio", "finalsite", "pasco", "schoolblocks", "smartsites"}
)
"""Adapters of general alert channels (whose rows need not be closings)."""

STATUS_BOARD_ADAPTERS = frozenset({"coesheet", "flathead", "gohsep"})
"""Adapters of status boards (every school or system listed, most of them open)."""

ORG_NAMED_VARIANTS = frozenset(
    {
        "apptegy-nuxt-state",
        "apptegy-nuxt2-state",
        "schoolwires-important-announcements",
        "pasco-emergency-banner",
        "pasco-red-rectangle",
        "schoolblocks-org-alerts",
        "campussuite-alert-banner",
    }
)
"""Variants whose rows are named by the district itself, not by the notice."""

MAX_LISTED = 20
"""At most this many kept and dropped proofs are listed per station (the counts are complete)."""

_I = re.IGNORECASE
_SUBJECT = (
    r"(?:schools?|offices?|campus(?:es)?|buildings?|facilities|district|classes|"
    r"school\s+day|in-person\s+(?:classes|instruction|learning))"
)
_STATUS = [
    # "All schools and offices will be closed", "Schools/offices will remain closed",
    # "School Closure", "Schools To Be Closed September 27"
    re.compile(rf"\b{_SUBJECT}\b[^.!?]{{0,60}}?\bclos(?:e|ed|es|ing|ure|ures)\b", _I),
    # the closing named first, then what closes (the closure of all district schools)
    re.compile(rf"\bclos(?:ed|ing|ures?)\b[^.!?]{{0,40}}?\b{_SUBJECT}\b", _I),
    # a notice whose title or status is the closing itself: "CLOSED TODAY", "Closed Monday"
    re.compile(
        r"^\W*(?:closed|closing|closure)\b"
        r"|\bclosed\s+(?:today|tomorrow|on\s+\w+day|\w+day)\b",
        _I,
    ),
    re.compile(r"\b(?:\d+|one|two|three)[- ]hours?[- ](?:delay|late\s+start)", _I),
    re.compile(r"\bdelay(?:ed|s)?\s+(?:start|opening|arrival|schedule)\b", _I),
    re.compile(r"\blate\s+(?:start|arrival|opening)\b", _I),
    re.compile(r"\bearly\s+(?:dismissal|release|out)\b", _I),
    re.compile(r"\b(?:dismiss(?:ed|al|ing)?|released?)\s+early\b", _I),
    re.compile(
        r"\b(?:remote|virtual|online|e-?learning|distance)[- ](?:learning|instruction)\s+days?\b",
        _I,
    ),
    re.compile(r"\be-?learning\s+days?\b", _I),
    re.compile(
        r"\b(?:shift|move|switch|transition)\w*\s+to\s+(?:an?\s+)?"
        r"(?:remote|virtual|online|e-?learning|distance)\b",
        _I,
    ),
    re.compile(
        r"\b(?:school|classes)\s+(?:is\s+|are\s+|has\s+been\s+|have\s+been\s+|will\s+be\s+)?"
        r"cancel(?:l)?ed\b",
        _I,
    ),
    re.compile(r"\bcancel(?:l)?(?:ed|ing|s)?\s+(?:all\s+)?(?:school|classes)\b", _I),
]
"""A closing, a delay, an early dismissal, a remote day or cancelled classes."""

_NOT_A_CLOSING = re.compile(
    r"\b(?:enrollment|registration|applications?|window|portal|survey|nominations?|voting|"
    r"polls?|bids?|sign[- ]?ups?|deadline|orders?|sales?|tickets?|auditions?|tryouts?|"
    r"comment\s+period)\b[^.!?]{0,40}?\bclos(?:e|es|ed|ing)\b"
    r"|\bclosed[- ](?:sessions?|caption\w*|campus(?:\s+(?:lunch|policy))?)\b"
    r"|\bclos(?:e|es|ed|ing)\s+(?:the\s+)?(?:achievement\s+|opportunity\s+|learning\s+)?gaps?\b"
    r"|\bclosing\s+(?:ceremon\w+|remarks|date|bell|of\s+(?:the\s+)?(?:school\s+)?year)\b",
    _I,
)
"""A deadline's "closes" ("enrollment closes Friday"), a closed session, a closed
campus, closing a gap or a ceremony: not a school closing."""

_PLANNED = re.compile(
    r"\b(?:staff|professional|teacher|employee)\s+(?:development|work\s*days?|planning|in-?service)"
    r"|\bin-?service\b|\bPLCs?\b|\bconferences?\b|\bholidays?\b"
    r"|\b(?:winter|spring|fall|thanksgiving|christmas|mid-?winter|semester|harvest)\s+break\b"
    r"|\b(?:thanksgiving|labor\s+day|memorial\s+day|veterans\s+day|presidents'?\s+day"
    r"|martin\s+luther\s+king|MLK|juneteenth|columbus\s+day|indigenous\s+peoples'?\s+day"
    r"|independence\s+day|new\s+year'?s|good\s+friday|graduation|election\s+day)\b"
    r"|\bevery\s+(?:monday|tuesday|wednesday|thursday|friday)\b|\bweekly\b"
    r"|\bearly\s+release\s+days?\b|\bminimum\s+days?\b|\bmake-?up\s+days?\b",
    _I,
)
"""A planned day (a holiday, a break, staff development, a calendar's early release
or minimum day): not a weather or emergency notice."""

_WEATHER = re.compile(
    r"\bhurricane\b|\btropical\s+(?:storm|depression|system)|\bnamed\s+storm"
    r"|\b(?:the|this|a|winter|ice|snow|tropical|severe|approaching|upcoming|major)\s+storms?\b"
    r"|\bstorm\s+(?:updates?|warnings?|watch(?:es)?|damage|preparations?|days?|conditions?)\b"
    r"|\bsnow(?:fall|storm|y)?\b(?!\s+(?:white|cones?|ball|queen|globes?|sculptures?))"
    r"|\bblizzard|\bice\s+storm|\bicy\b|\bsleet\b|\bfreezing\s+(?:rain|drizzle|temperatures)"
    r"|\bhard\s+freeze|\bfreeze\s+(?:warning|watch)|\b(?:extreme|dangerous|bitter|severe)\s+cold"
    r"|\bsub-?zero\b|\bwind\s?chills?\b"
    r"|\b(?:inclement|severe|winter|wintry|bad|cold|extreme|hazardous|dangerous|current|forecast(?:ed)?)"
    r"\s+weather\b|\bweather[- ](?:conditions?|related|forecasts?|alerts?|warnings?|advisory|event|"
    r"delays?|closures?|emergency)\b|\bdue\s+to\s+(?:the\s+)?weather\b"
    r"|\bflood(?:ing|ed|s|\s+warning|\s+watch)?\b(?!\s+of\b)|\btornado(?:es|s)?\b(?!\s+drills?)"
    r"|\bpower\s+outages?|\bwithout\s+power|\blost\s+power|\bno\s+power|\bwildfires?\b"
    r"|\bair\s+quality\s+(?:alert|advisory|warning|index)|\bwildfire\s+smoke|\bsmoke\s+(?:advisory|conditions)"
    r"|\bevacu(?:ation|ate|ated|ees?)\b(?!\s+drills?)|\bextreme\s+heat|\bheat\s+(?:advisory|warning)"
    r"|\bboil[- ]water\s+(?:notice|advisory|order)|\bwater\s+main\s+break",
    _I,
)
"""Weather, or an emergency that closes schools (an outage, a fire, an evacuation)."""

_SPANISH_WEATHER = re.compile(
    r"\bhurac[aá]n\b|\btormenta\s+(?:tropical|invernal|de\s+invierno)|\bmal\s+tiempo\b"
    r"|\bclima\s+(?:inclemente|severo|extremo)|\bcondiciones\s+(?:del\s+clima|clim[aá]ticas)"
    r"|\bheladas?\b|\bcongelaci[oó]n\b|\bnieve\b|\bnevada\b|\bfr[ií]o\s+extremo\b"
    r"|\binundaci(?:[oó]n|ones)\b|\bapag[oó]n\b|\bsin\s+electricidad\b",
    _I,
)
"""Weather or an emergency in Spanish, as South Texas' and Miami's districts post it
("debido al mal tiempo", "huracán", "tormenta invernal")."""

_SPANISH_STATUS = re.compile(
    r"\b(?:escuelas?|campus|clases|oficinas|distrito)\b[^.!?]{0,60}?\b(?:cerrad[oa]s?|cancelad[oa]s|suspendid[oa]s)\b"
    r"|\b(?:cierre|cancelaci[oó]n|suspensi[oó]n)\s+de\s+(?:las\s+)?(?:escuelas|clases|campus)\b"
    r"|\bsuspende[n]?\s+(?:las\s+)?clases\b|\bsalida\s+temprana\b"
    r"|\b(?:inicio|horario|entrada)\s+(?:tard[ií]o|retrasad[oa]|demorad[oa])\b",
    _I,
)
"""A closing, cancelled or suspended classes, an early dismissal or a delay, in Spanish
("las escuelas estarán cerradas", "clases canceladas", "salida temprana")."""

_SPANISH_PLANNED = re.compile(
    r"\bvacaciones\b|\bd[ií]as?\s+(?:festivos?|feriados?)\b|\bacci[oó]n\s+de\s+gracias\b"
    r"|\bdesarrollo\s+(?:profesional|del\s+personal)\b|\bd[ií]a\s+de\s+(?:trabajo|servicio)\b",
    _I,
)
"""A planned day in Spanish (a holiday, a break, staff development)."""

_BOARD_STATUS = re.compile(
    r"\b(?:clos(?:e|ed|es|ing|ure|ures)|remote|virtual|online|e-?learning|distance\s+learning"
    r"|delay(?:ed|s)?|late\s+(?:start|arrival)|early\s+(?:dismissal|release|out)|minimum\s+day"
    r"|shortened\s+day|modified\s+schedule|cancel(?:l)?ed)\b",
    _I,
)
"""A status board's statuses other than open ("Closed", "Planned Closure", "Remote",
"2 Hour Delay", "Closing at 12:45")."""


def announces_closing(status: str, title: str | None = None) -> bool:
    """Whether a notice announces a closing, delay, early dismissal, remote day or weather.

    ``status`` is the notice's text; ``title``, when given, its own title (not the
    district's name). A notice naming weather or an emergency qualifies; one naming
    a closing, a delay, a dismissal or a remote day qualifies unless it is a planned
    day (a holiday, a break, staff development); a deadline's "closes", a closed
    session or a closed campus is not a closing.
    """
    text = " ".join(part for part in (title, status) if part)
    if _WEATHER.search(text) or _SPANISH_WEATHER.search(text):
        return True
    if _PLANNED.search(text) or _SPANISH_PLANNED.search(text):
        return False
    text = _NOT_A_CLOSING.sub(" ", text)
    return any(pattern.search(text) for pattern in _STATUS) or bool(_SPANISH_STATUS.search(text))


def board_status_announces(status: str) -> bool:
    """Whether a status board's status is other than open: a closing, a delay, a remote day.

    The status is the board's own column for one school, so a bare word counts
    ("Closed", "Remote"); "Open" and an empty status never do.
    """
    return bool(_BOARD_STATUS.search(status)) or announces_closing(status)


def row_qualifies(name: str, status: str, variant: str, *, board: bool = False) -> bool:
    """Whether one row of a gated source announces a closing.

    A channel's row by :func:`announces_closing` (its name read as the notice's
    title unless the variant names rows by the district); a status board's row by
    :func:`board_status_announces`, its status only.
    """
    if board:
        return board_status_announces(status)
    title = None if variant in ORG_NAMED_VARIANTS else name
    return announces_closing(status, title)


class ProofLike(Protocol):
    """What the gate reads of a proof (``snowlight.sources.stations.proof.Proof``)."""

    @property
    def source_id(self) -> str: ...
    @property
    def mode(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def captured_at(self) -> datetime: ...
    @property
    def variant(self) -> str: ...
    @property
    def basis(self) -> str: ...


type RowIndex = Mapping[tuple[str, datetime], list[tuple[str, str]]]


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def load_rows(paths: Iterable[Path], source_ids: set[str]) -> RowIndex:
    """Rows of ``rows.jsonl`` files, by (source, read time), for the given sources only."""
    found: dict[tuple[str, datetime], list[tuple[str, str]]] = defaultdict(list)
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                source = row.get("source_id")
                if source not in source_ids:
                    continue
                key = (str(source), _instant(str(row["fetched_at"])))
                found[key].append((str(row["raw_name"]), str(row.get("raw_status") or "")))
    return dict(found)


def _fixture_rows(root: Path, basis: str, adapter: str) -> list[tuple[str, str]] | None:
    relative = basis.removeprefix("fixture ").strip()
    path = root / relative
    if not path.is_file():
        return None
    try:
        listing = adapter_for(adapter)(path.read_bytes())
    except ShapeError:
        return None
    return [(row.name, row.status) for row in listing.rows]


def _rows_of(
    item: ProofLike, rows: Mapping[str, RowIndex], fixtures: Path | None, adapter: str
) -> list[tuple[str, str]] | None:
    if item.basis.startswith("fixture "):
        return _fixture_rows(fixtures, item.basis, adapter) if fixtures is not None else None
    index = rows.get(item.mode, {})
    return index.get((item.source_id, item.captured_at.astimezone(UTC)))


def gated_adapters(registry: Registry) -> dict[str, bool]:
    """Each gated station's id, and whether it is a status board (else a channel)."""
    found: dict[str, bool] = {}
    for station in registry.stations.values():
        adapter = registry.platform_of(station).adapter
        if adapter in GENERAL_CHANNEL_ADAPTERS or adapter in STATUS_BOARD_ADAPTERS:
            found[station.id] = adapter in STATUS_BOARD_ADAPTERS
    return found


def _listed(item: ProofLike, row: tuple[str, str] | None) -> dict[str, JSONValue]:
    return {
        "mode": item.mode,
        "captured_at": item.captured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": item.url,
        "basis": item.basis,
        "row": " | ".join(row)[:300] if row is not None else None,
    }


def gate_proofs[P: ProofLike](
    proofs: MutableMapping[str, list[P]],
    registry: Registry,
    *,
    live_rows: Iterable[Path],
    archive_rows: Iterable[Path],
    fixtures: Path | None,
) -> dict[str, JSONValue]:
    """Keep a gated station's proofs only when a row of theirs announces a closing.

    Gated stations are those whose platform's adapter is a general alert channel
    or a status board; proofs of every other station are left as they are. A
    proof whose rows cannot be found is dropped. Returns the report written into
    ``coverage.json`` as ``district_notice_gate`` (see the module docstring).
    """
    boards = gated_adapters(registry)
    adapters = {sid: registry.platform_of(registry.stations[sid]).adapter for sid in boards}
    wanted = set(boards) & set(proofs)
    rows = {
        "live": load_rows(live_rows, wanted),
        "archive": load_rows(archive_rows, wanted),
    }
    report: dict[str, JSONValue] = {}
    for source_id in sorted(wanted):
        board = boards[source_id]
        kept: list[P] = []
        kept_listed: list[JSONValue] = []
        dropped: list[JSONValue] = []
        for item in proofs[source_id]:
            found = _rows_of(item, rows, fixtures, adapters[source_id])
            proving = next(
                (
                    row
                    for row in found or []
                    if row_qualifies(row[0], row[1], item.variant, board=board)
                ),
                None,
            )
            if proving is not None:
                kept.append(item)
                kept_listed.append(_listed(item, proving))
                continue
            entry = _listed(item, found[0] if found else None)
            if found is None:
                entry["reason"] = "rows not found"
            elif board:
                entry["reason"] = "every row's status is open"
            else:
                entry["reason"] = (
                    "no row announces a closing, delay, dismissal, remote day, weather or emergency"
                )
            dropped.append(entry)
        proofs[source_id] = kept
        report[source_id] = {
            "kind": "board" if board else "channel",
            "kept": len(kept),
            "kept_proofs": kept_listed[:MAX_LISTED],
            "dropped_count": len(dropped),
            "dropped": dropped[:MAX_LISTED],
        }
    return report


def annotate_unproven(
    result: MutableMapping[str, JSONValue], report: Mapping[str, JSONValue]
) -> None:
    """Say in each unproven gated station's ``checked`` how many of its reads the gate dropped."""
    unproven = result.get("unproven")
    if not isinstance(unproven, list):
        return
    for entry in unproven:
        if not isinstance(entry, dict):
            continue
        gate = report.get(str(entry.get("id")))
        checked = entry.get("checked")
        if not isinstance(gate, dict) or not isinstance(checked, dict):
            continue
        checked["notice_gate"] = {
            "kind": gate.get("kind"),
            "populated_reads_dropped": gate.get("dropped_count"),
            "rule": "board: a status other than open"
            if gate.get("kind") == "board"
            else "channel: a closing, delay, dismissal, remote day, weather or emergency notice",
        }
