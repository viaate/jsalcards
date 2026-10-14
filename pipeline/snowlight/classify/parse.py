"""parse_status: what a closings listing says, for which local dates.

The steps, all over the normalized text (:func:`snowlight.classify.text.normalize`):

1. Find date groups and status mentions (:mod:`~snowlight.classify.dates`,
   :mod:`~snowlight.classify.mentions`). A status word whose subject is not the
   school's day is a side note (:mod:`~snowlight.classify.subjects`): "Payroll
   delayed", "School pictures cancelled", "Lightning delay", and a delay of the
   end of the day ("Dismissal delayed", "Delayed dismissal due to severe
   weather"), which holds students past the bell and is no late start.
2. Split the text into clauses at sentence marks, semicolons, commas and spaced
   dashes, never inside a date group or a mention. Attach each word that calls
   a status off to the status it calls off (:mod:`~snowlight.classify.revoke`):
   "2 hour delay cancelled" and "Cancel delay" state no delay. A status called
   off claims no day, but it dates the status named in its place ("Tomorrow's
   delay cancelled. Closed." closes tomorrow), and a status of its kind stated
   for its day is a contradiction ("Closure cancelled. Closed."). A bare
   "cancelled" attached to nothing could be the school cancelled: a status it
   would change on its day is in doubt.
3. Decide each mention with its clause: the noun it is about (the school, staff,
   offices, activities, part of the program, buses), including a label before
   it ("AM kindergarten: no school") or a restriction after it ("2 hour delay
   (elementary only)"); whether it is negated ("no delay", "closure not
   expected", "Closed not", "Closed - not"; "no school closures" negates the
   closure, see :mod:`~snowlight.classify.mentions`; a "no" joined to the word
   before it is spaced out by normalize, so "Closed/no virtual" denies the
   remote day as "Closed / no virtual" does), left open by a field's answer
   ("Closed: yes/no"), hedged ("possible early dismissal", "if roads are icy",
   "snow day tomorrow?", "closure unlikely", "Closed tomorrow. Decision at 5
   AM.") or replaces another ("changed to closed", "was
   a delay", "2 hour delay is now a closing", "turned into an e-learning day",
   "2 hr delay -> closed"). A status replaced keeps none of its details, and one
   changed into something unread, unclear or only possible ("2 hour delay has
   been changed", "is now a full day", "Update: possible closure") states no
   status at all (see :func:`_changes`); a new length, time or day after the
   change is the status's ("2 hour delay - now 3 hours"). An evening ("closed
   tonight", "closing early at 5:00 PM") is activities, not the school day,
   and a day to be made up ("snow day make-up day") is no status. A closing
   time late in the afternoon ("closing at 3:00 PM") is unclear, unless an
   early dismissal with no time of its own stands beside it ("Early release.
   Closing at 3:00 today."): then it is its time.
   A status that leaves some of the district's schools out ("All schools closed
   except Lincoln Elementary", "2 hour delay for all schools but Lincoln"), is
   restricted to some ("Closed (Lincoln Elementary only)") or names a place
   ("Closed at some locations", "Closed north of Route 9", "North campus
   closed", "PTEC and Howard campuses closed") is about part of the program
   as well, and so is every status after the phrase in its sentence (see
   :mod:`~snowlight.classify.partial`); one that leaves out staff, offices or
   services ("Closed except essential staff") stands, and an exception for a
   day ("Closed all week except Wednesday") leaves the days unread. A school
   named open beside a status ("Closed. Lincoln Elementary open.") leaves the
   status standing as a judgment call.
   A status marked as past ("school was closed Friday") names a weekday it
   cannot place; one only marked as past or replaced is no status for a day
   nothing else claims (see :func:`_past_reports` and :func:`_schedule`). When
   every status is before the posting day and the text says school is open
   ("Yesterday's closure: snow. Today: open"), the news is that it is open
   (see :func:`_open_after_past`), unless the open day is as past ("Open
   Friday 1/9; closed Monday 1/12" seen on the 13th states those days).
4. Attach date groups to mentions: "closed today" and "today: closed" both work,
   and a clause that is only dates ("Tuesday and Wednesday") attaches to its
   neighbour. Heading the text or a sentence, it reaches a status across a
   clause that only says where ("(Tomorrow) All locations - no classes"); at
   the text's end, across a phrase of what else ("Closed - no extended care;
   through January 23"; see :func:`_across_scope`). Beside a status that
   already has a date, such a clause restates it ("Closed tomorrow. Jan.
   22."), and the two must agree; so must two day words side by side
   ("tomorrow, Thursday") and a day heading a status and a day in it
   ("Monday: Closed Monday"). When they disagree ("tomorrow (Friday)",
   "Thursday 1/23" when 1/23 is a Friday) either could be the day meant, so the
   status has no day anyone can trust and is left out (note
   ``date_mismatch``). A list led by "today" or "tomorrow" and a plain comma
   ("Closed today, Thursday and Friday") is a list when its days run on one
   after another; with a bracket, a colon, a dash, a slash or a space instead
   ("today (Thursday), Friday", "today - Thursday and Friday") the weekday names
   the day again (see :meth:`~snowlight.classify.dates.Calendar._led_run` and
   :func:`_restate`). A statement that
   school is open, reopens or is back ("Students return Friday", "Classes will
   be held Friday") on a day a closure names too takes that day from it, or
   leaves the day with no status when nothing says which came last (see
   :data:`_Opening`), and so does a status denied on a day ("Update: tomorrow
   is not closed", "Closed today but not tomorrow", "Update: not tomorrow"),
   for its kind of status only. A status whose only dates are hedged ("closed, possibly
   Wednesday") is hedged. A status with no day of its own takes the day named
   after its cause ("no school due to snow tomorrow") as a judgment call, but
   not a possessive one ("due to Monday's storm"). Weekdays listed together are
   one forward run; a weekday named again is the same day. A list of days is
   its status's only when nothing after it could take its last days: in its
   clause, any word but the few that leave a list its days (a restatement or an
   addition, who it is for, a reason or a cause, a time or a length that fits
   the status: see :data:`_LIST_STANDS`), and in its sentence a status of
   another kind with no day of its own, a status of its kind denied, or an open
   school; so does a part of today leading it ("Closed today, tomorrow under
   review", "Closed today, Thursday and Friday not affected", "Closed today,
   Thursday and Friday - 2 hour delay", "Closed this afternoon, Thursday and
   Friday"). Such a text says no status for sure, as ambiguous (see
   :func:`_carried_elsewhere`). A day right after "not" is not the status's
   ("Closed today and not tomorrow" is closed today; see
   :func:`_without_denied_days`). "Only" beside a status's day ("Closed today
   only", "only closed today", "closing just for today") is the one day it is
   for: an update that says
   so replaces the statuses of its kind before it, and with no update another
   day of the status contradicts it (see :func:`_only_days`).
5. A closure limited to part of a day is not a closure of the day (see
   :mod:`~snowlight.classify.dayparts`). Closed for the afternoon ("closed this
   afternoon", "Wednesday PM: closed", "closed after lunch") or from a time on
   ("closed after 11:30", "closed from noon") is an early dismissal, at that
   time when one is given; "closed for the rest of the day" is the posting
   day's. Closed for the morning is a late start when the text says when school
   opens ("closed tomorrow until 10", "closed Wednesday AM, reopening at 11")
   and otherwise unclear, and then so is every status in the text that names
   no day. A day bounded among others leaves them closed ("closed this
   afternoon and tomorrow"); the morning and the afternoon of one day together
   are the whole day ("Monday Morning: Closed...... Monday Afternoon: Closed"),
   and so is a closings page's morning slot for a weekday alone ("Tuesday
   Morning: Closed", "Tuesday Morning: Closed-Flexible Instruction Day"),
   unless the day's other slots say the school opens later ("Tuesday
   Afternoon: Opening At Noon" makes it a late start; "Tuesday Afternoon:
   Open" leaves it unclear). A slot that repeats a day's closure is that
   closure ("Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed
   Tuesday", "... Tuesday Afternoon: Closed"), and an afternoon slot before a
   closure for another day by name or date is that day's ("Thursday Afternoon:
   Closed Friday"). A day that heads an entry ("Tuesday:", "Tuesday
   Morning:") dates every status in it that merges with the one it heads, as
   stated: "Tuesday: Closed - NTI Day" is remote learning on Tuesday at 0.95.
   A program on a weekend day ("Saturday school cancelled") is no school day,
   and the school opening after an update ("Closed. Update: open.") replaces
   the statuses before it. A closing at a time that runs over several days
   ("closing at 1 PM today through Friday", "closed from noon Wednesday
   through Thursday") is an early dismissal on its first day at 0.8: the days
   after it fit a closing at that time each day as well as a closure, so they
   state nothing.
6. A text that names a day in a form the date patterns cannot read ("1-21",
   "next week", "Wensday", "the 21st everyone", a year alone as in "closed in
   2019", "last year", "for the summer"), or weekdays whose order cannot
   be one run, states no status at all: its status could be for any day. A day
   of the month alone that stands clear ("closed through the 27th") is read
   (see :mod:`~snowlight.classify.dates`). A weekday that heads a closings
   page's slot is among the weekdays in order whatever its slot says, a status
   or not: "Wednesday: Closed...... Thursday: Open on time" seen on a Thursday
   closed yesterday, not next Wednesday (and today is open: see step 3).
   Weekday names alone that were a day or two before the posting day state no
   status either ("2-hr delay Tues." seen on a Thursday, "Closed Monday and
   Tuesday" seen on a Thursday, "Closed through Wednesday" seen on a
   Thursday): most likely a listing still up after its days, or else days a
   week on, and nothing says which (see :func:`_past_week`).
7. A status that names no day, in a text where another status does, never
   takes its day from the posting time (see :func:`_fold_undated`): it restates
   a dated status beside it ("Closed Friday. No school."), joins one it adds to
   ("Closed tomorrow. NTI day."), takes the days of the one it updates
   ("2 hour delay tomorrow. Update: now closed."), or is left out.
8. A status with no date in a text that names none gets the next school day
   from the posting time: the posting day until a cut-off that depends on the
   status (a delay can still apply before 11 a.m., a closure before noon, an
   early dismissal before 3 p.m.), the next school day after that. A closure or
   remote day first seen between noon and 3 p.m. could be today's or
   tomorrow's, and a school day more than a day away (Monday, seen on a Friday
   evening or a Saturday) is too far to read from the posting time: neither
   states a day. Nor does a posting day that a day named for a side note
   contradicts ("Closed; offices open Monday"), or that such a day leaves in
   doubt because it cannot be told ("Closed; offices open through 2/30");
   an event's new date ("concert rescheduled to Feb. 13") is no such day. A
   listing that joins a side note to its status with a dash and ends with the
   day ("Closed-Activities Canceled Today") names that day for the status too,
   and so does one that ends with a status it denies and a day ("Closed - no
   virtual tomorrow").
   The posting time is when the listing says it was written, when it says so
   with a date and a time ("As of Jan 28, 1:58pm:", "Last Updated: 01/09/2025
   05:13am", see :func:`snowlight.classify.text.written_at`): its "today",
   "tomorrow" and weekday names were meant then, however much later it was seen.
9. Resolve each date: when two different statuses claim one day, compatible ones
   merge (a closure with remote learning is remote learning; a delay with an
   early dismissal is a delay with a dismissal time); anything else is a
   conflict, and that day gets no status. Ambiguity never becomes ``closed``.

Two phrasings get a reading of their own in step 3. A delay with no length or
time until a day ("School delayed until Monday") puts the start off to that
day, so it is a closure before it, at 0.8. "No school" beside a status another
"no" denies, with no day named ("No school - no delay"), reads as two answers
of no as much as a closure: it is unclear.

The analysis of steps 1 to 7 depends on the text alone and is cached. Texts that
differ only in their names share one entry (see :func:`canonical`), and so do
texts that differ only in the month and the day number of their one plain date
(see :func:`_day_template`): a feed of listings that name their schools and
their days parses fast.
"""

import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Container, Iterator, Sequence
from collections.abc import Set as AbstractSet
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from itertools import chain, pairwise
from operator import itemgetter
from typing import Final, NamedTuple

from snowlight.classify import dates as dates_module
from snowlight.classify import dayparts as dayparts_module
from snowlight.classify import gate as gate_module
from snowlight.classify import lexicon as lexicon_module
from snowlight.classify import mentions as mentions_module
from snowlight.classify import partial as partial_module
from snowlight.classify import revoke as revoke_module
from snowlight.classify import subjects as subjects_module
from snowlight.classify import text as text_module
from snowlight.classify import weather as weather_module
from snowlight.classify.dates import (
    ATOM_DAY,
    ATOM_END,
    ATOM_EVENING,
    ATOM_KIND,
    ATOM_MODIFIER,
    ATOM_MONTH,
    ATOM_NAMED,
    ATOM_OFFSET,
    ATOM_REST_OF_WEEK,
    ATOM_START,
    ATOM_WEEKDAY,
    DATE_START,
    DATE_START_BITS,
    EVENING,
    FURTHER_NOTICE,
    GROUP_ATOMS,
    GROUP_END,
    GROUP_LINKS,
    GROUP_OPEN_START,
    GROUP_START,
    HINT_BITS,
    INVALID,
    MISMATCH,
    MONTH_NAMES,
    MONTH_WORD,
    MONTHS,
    OVERNIGHT,
    RECURRING,
    UNCLEAR,
    UNREADABLE_HINTS,
    Calendar,
    DateAtom,
    DateGroup,
    Link,
    check_moment,
    date_atom,
    date_groups_at,
    daylike_word,
    dot_pair,
    find_unreadable,
    join_groups,
    restates,
    unreadable_possible,
    weekdays_out_of_order,
    year_alone,
    zone,
)
from snowlight.classify.dates import start_hint as date_start_hint
from snowlight.classify.dates import word_hints as date_hints
from snowlight.classify.dayparts import (
    Bound,
    Split,
    closure_bounds,
    entry_start,
    may_bound,
    own_bound,
    slot_heading,
    time_follows,
)
from snowlight.classify.gate import (
    ATTACHED,
    CORRECTION_SIGNS,
    DAY_SPAN,
    EITHER_SIGNS,
    HELD_SIGNS,
    HOPE_SIGNS,
    NOTE_SPAN,
    OPEN_SPAN,
    STALE_LABELS,
    STATEMENT,
    STATUS_SPAN,
    TRUTH_SIGNS,
    inert_word,
    names_read,
    not_name,
    noun_word,
    unread_sentence,
    word_class,
)
from snowlight.classify.lexicon import (
    CAUSES,
    CONDITION_OPENERS,
    CONDITIONALS,
    CONDITIONS_ANYWHERE,
    DENIED_AFTER,
    FACILITY_NOUNS,
    FILLERS,
    HEDGE_CLAUSE_FILLERS,
    HEDGE_CLAUSE_WORDS,
    HEDGES,
    HEDGES_AFTER,
    MAKE_UP_WORDS,
    MODIFIERS,
    NEGATIONS,
    NOT_CONDITIONS,
    PURPOSES,
    REGION_STOPS,
    SCOPES,
    SUPERSEDED,
    SUPERSEDING,
    SUPERSEDING_WITH,
    UNSETTLED_AFTER,
    UNVERIFIED,
    Scope,
)
from snowlight.classify.mentions import (
    CLOCK_RULES,
    INSTITUTION_NOUNS,
    RULE_BITS,
    SCOPE_NOTES,
    Mention,
    harvest_details,
    late_opening,
    length_after,
    mentions_at,
    rule_mask,
    school_dismissal,
    school_opening,
    start_mask,
)
from snowlight.classify.model import (
    CERTAIN,
    CONFLICTING,
    EMPTY,
    HEDGED,
    INFERRED,
    JUDGMENT,
    UNKNOWN,
    UNSURE,
    WEAK,
    DatedStatus,
    Note,
    ParsedStatus,
    Reason,
    StatusKind,
)
from snowlight.classify.partial import CARVE_WORDS, carved
from snowlight.classify.revoke import may_revoke, pair_revocations
from snowlight.classify.subjects import settle_subjects
from snowlight.classify.text import (
    CLOCK_STRICT,
    DASH_RUN,
    DURATION,
    MAX_CHARS,
    NOT_ALONE,
    Written,
    normalize,
    normalize_stamped,
    normalize_stretch,
    one_of,
    trie,
    within_limit,
    words,
    written_at,
)
from snowlight.classify.text import WORD as _WORD
from snowlight.classify.text import duration_minutes as _duration_minutes
from snowlight.classify.weather import (
    CAUSE_START,
    NAME_KINDS,
    WEATHER_START,
    WEATHER_START_BITS,
    find_weather,
)
from snowlight.classify.weather import NO_FINDINGS as _NO_FINDINGS
from snowlight.classify.weather import candidate_in as weather_candidate_in
from snowlight.classify.weather import start_hint as weather_start_hint
from snowlight.classify.weather import word_hints as weather_hints

_STATUS_KINDS: frozenset[str] = frozenset({"closed", "delayed", "remote", "early_dismissal"})
# The kinds a label beside them can scope: "Offices - Closed", "Offices - Open".
_LABELED_KINDS: frozenset[str] = _STATUS_KINDS | {"open"}
_new = tuple.__new__  # builds a named tuple from its fields without a Python-level call
# For a status that names no day, in minutes after local midnight: until the first it applies
# to the posting day, from the second to the next school day. A delay or an early dismissal
# happens at a set time of the school day, so once that time has passed it can only be for
# the next one. A closure holds all day: first seen between noon and 3 p.m. it could be
# today's or tomorrow's.
_UNDATED: dict[StatusKind, tuple[int, int]] = {
    "delayed": (11 * 60, 11 * 60),
    "closed": (12 * 60, 15 * 60),
    "remote": (12 * 60, 15 * 60),
    "early_dismissal": (15 * 60, 15 * 60),
}
_SATURDAY = 5
# Clause marks in a normalized text, whose only spaces are single: a sentence mark (strong),
# or a comma, a spaced dash, "but" or "however" (weak). Every branch opens with a character,
# so the regex engine skips to the marks. A dash that opens the text is weak too.
_SEPARATOR = re.compile(r";|!|\?|\||\.(?= |$)|,| -+(?= |$)| but | however\b", re.ASCII)
_OPENING_DASH = re.compile(r"-+(?= )", re.ASCII)
_STRONG_MARKS = frozenset(";!?|.")
_STOP = re.compile(r"\b" + trie(REGION_STOPS) + r"\b", re.ASCII)
_CAUSE_WORDS = ("due", "because", "owing")
_AFTER = re.compile(
    r"\s*(?P<prep>for|to|:)?\s*(?:all\s+|the\s+|our\s+|any\s+)?(?P<w1>[a-z0-9][a-z0-9'/-]*)"
    r"(?:\s+(?P<w2>[a-z0-9][a-z0-9'/-]*))?",
    re.ASCII,
)
# A noun and "only" right after a status: "2 hour delay kindergarten only".
_ONLY_AFTER = re.compile(
    r" (?P<w1>[a-z0-9][a-z0-9'/-]*)(?: (?P<w2>[a-z0-9][a-z0-9'/-]*))? only\b", re.ASCII
)
_SENTENCE_END = re.compile(r"\.(?=\s|$)|" + one_of(";!?|"), re.ASCII)  # (see text.one_of)
_DIGIT = re.compile(r"\d", re.ASCII)
# Every word that can make a clause conditional (see _conditional): a text with none is not.
_ANY_CONDITIONAL = re.compile(
    r"\b(?:" + trie([*CONDITIONALS, *CONDITION_OPENERS, "in case", "when", "long"]) + r")\b",
    re.ASCII,
)
# "When school is closed, students do NTI": a policy, not a status for a day.
_WHEN = re.compile(r" ?(?:(?:and|or|but|only) )*when(?:ever)? (?=[a-z0-9])", re.ASCII)
_EVENT_PHRASE = re.compile(r"\bin\s+case\b", re.ASCII)
_DAY_PARTS = frozenset({"morning", "am", "afternoon", "pm"})
_DAY_PART_AFTER = re.compile(r" (?:morning|am|afternoon|pm)(?=\s*(?:[:,;.!?-]|$))", re.ASCII)
_DAY_PART_STARTS = (" morning", " am", " afternoon", " pm")
# Each of _DAY_PART_STARTS by its first two letters, with its length; and the marks after it
# that end its phrase (see _without_dates).
_DAY_PART_LENGTHS = {start[1:3]: len(start) for start in _DAY_PART_STARTS}
_DAY_PART_MARKS = ":,;.!?-"
_DATE_HEDGES = frozenset(
    ["possibly", "maybe", "perhaps", "possible", "likely", "potentially", "probably"]
)
# The other words a day's hedge can hold (see _date_hedged): a modal, and "not yet decided".
_DAY_HEDGE_WORDS = frozenset(
    {"may", "might", "could", "tentatively", "unlikely", "undecided", "yet", "decided",
     "expected", "anticipated"}
)  # fmt: skip
# A status given as a field and answered no: "Closed: No", "Delay - none", "Closed: N/A", or
# with a count of none or a blank: "Delay: 0", "Closed: 0", "Delay: --".
_ANSWERS_NO = frozenset({"no", "none", "n/a", "na", "false", "nope", "0", "00"})
# The answers after the colon or the dash: a no, "N" (not "N. Main St."), or a zero or a zero
# time ("Closed: 0", "Delay: 0:00").
_NO_ANSWERS = (
    r"(?:(?:no|none|n/a|na|false|nope|not)(?=\s*(?:$|[;,.|!?]|-+(?:\s|$)|\s-))"
    r"|n(?=\s*(?:$|[;,|!?]))"
    r"|0+(?::0+)?(?=\s*(?:$|[;,|!?]|\.(?:\s|$)|-+(?:\s|$)|\s-)))"
)
# (The spaces before the mark are read once for every answer: a run of them is a day blanked
# out, which the text after a status often holds. An answer starts with a letter or a digit,
# so it can follow only all the spaces or dashes before it: one way to read them.)
_ANSWERED_NO = re.compile(
    r"\s*(?::\s*(?:"
    + _NO_ANSWERS
    + r"|-+(?=\s*(?:$|[;,|!?]|\.(?:\s|$))))"  # a blank: "Delay: --"
    + r"|-+\s*"
    + _NO_ANSWERS
    + r")"
    # A field left empty: "Closed:" (see _field_answer; a run of spaces is a day blanked out).
    r"|(?P<empty>\s?:)(?=$| ?\|)",
    re.ASCII,
)
# A form's value after "=", which normalize turns into a space, at the end of the text:
# "Closed=false", "closed=0", "Delayed=N" (looked at only with a word of _ANSWER_RUNS).
_ANSWERED_FORM = re.compile(r" (?:false|0+(?::0+)?|n|no|none|n/a)\Z", re.ASCII).match
# (A quick look before it, with no call: the value is at most _FORM_REACH long with its space,
# or is zeros, which end the text with "0".)
_FORM_REACH = 6
# A field's answer left open: both answers, as a form gives them ("Closed: yes/no").
_ANSWERED_EITHER = re.compile(r"\s*(?::|-+|,)?\s*(?:yes/no|y/n|yes or no)(?![a-z0-9'/-])", re.ASCII)
_FIELD_MARKS = (":", " :")  # (where a field's answer can start, after its status)
# A zero time right before a status: "00:00 delay", "0:00 - delay" (not "10:00 delay"). The
# endings are a quick look before the pattern, which wants the time whole; the character two
# before the status ("0", ":" or "-") a quicker one before them, with no call.
_ZERO_CLOCKS = ("0:00 ", "0:00: ", "0:00 - ")
_ZERO_CLOCK_MARKS = "0:-"
_ZERO_CLOCK = re.compile(r"(?<![0-9:.])0{1,2}:00(?: -|:)? \Z", re.ASCII).search
# What an answer of _ANSWERED_NO starts with, past spaces, as a quick look: a colon or a dash,
# right away or after a space, or more spaces (which the pattern reads).
_ANSWER_LEADS = (
    ":", "-", " :", " -", "  ", " \t", " \n", " \r", " \f", " \v", "\t", "\n", "\r", "\f", "\v",
)  # fmt: skip
_DASHED_MARKS = ("-", " -")  # (where an answer after a dash can start: "Closed - not")
_LOOKBACK_TOKENS = 6
_NEGATION_TOKENS = 3
_SUPERSEDED_TOKENS = 2
_JOINERS = frozenset({"or", "and", "nor"})
_PREPOSITIONS = (" for ", " to ", ":", " :")
_CLOCK_NEXT = re.compile(r"\s*(?:\d{1,2}(?::\d\d|\s*[ap]m\b)|noon\b)", re.ASCII)
# Every word that is, or is part of, a scope noun: a window with none of them names no scope.
_SCOPE_WORDS = frozenset(word for noun in SCOPES for word in noun.split())
_COPULAS = frozenset({"is", "are", "be", "being", "will", "a", "an", "now", "day", "days"})


class _Clause:
    """A stretch of the text between clause marks (see :func:`_clauses_at`).

    A plain class with slots, not a named tuple: its fields are read often, and a slot is
    read faster than a named tuple's field.
    """

    __slots__ = ("end", "start", "strong")

    def __init__(self, start: int, end: int, strong: bool) -> None:
        self.start = start
        self.end = end
        self.strong = strong  # a sentence mark separates it from the clause before


class _ClauseTable(dict[tuple[int, int, bool], _Clause]):
    """Each clause, made once: a clause is never changed, and texts share their clauses'
    places (a lookup costs less than making one)."""

    def __missing__(self, key: tuple[int, int, bool]) -> _Clause:
        clause = _Clause(*key)
        if len(self) >= _MOST_CLAUSES:
            self.clear()  # a bound on memory; a clause is the same when made again
        self[key] = clause
        return clause


_MOST_CLAUSES = 4096
_CLAUSES = _ClauseTable()
_clause = _CLAUSES.__getitem__


# A settled status mention: what it states and the date groups attached to it. A plain
# tuple, read by the field numbers below: a named tuple's field is read several times
# slower, and one is made several times slower, and statuses are made and read for
# every text.
type _Status = tuple[
    StatusKind,  # _KIND
    int,  # _POSITION
    float,  # _STRENGTH
    int | None,  # _DELAY
    time | None,  # _OPENS_AT
    time | None,  # _DISMISSAL
    int | None,  # _EARLY
    bool,  # _IS_SUPERSEDING
    bool,  # _IS_SUPERSEDED
    tuple[DateGroup, ...],  # _GROUPS
    # Names no day, beside statuses that do, and restates none of them: its day is unknown,
    # so it only makes a named day uncertain (see _float).
    bool,  # _FLOATING
    # The text calls it off ("2 hour delay cancelled"): it claims no day, but a status of
    # its kind on its days contradicts it, and it dates the status that replaces it.
    bool,  # _REVOKED
    # _LED: a day named before this status that its days go on from. With False, a day an
    # earlier status of another kind named before a run with no first day of its own that this
    # status's days start with, or before "all week" or "this week": the run starts on it only
    # if it comes first (see _anchored_runs and _led_later). With True, the day a closure that
    # this status continues starts at a time of ("will close at 5 p.m. today and remain closed
    # through Friday"): its days start on the school day after it (see _continued_closures).
    # None for any other status.
    tuple[DateGroup, bool] | None,
]
_KIND: Final = 0
_POSITION: Final = 1
_STRENGTH: Final = 2
_DELAY: Final = 3
_OPENS_AT: Final = 4
_DISMISSAL: Final = 5
_EARLY: Final = 6
_IS_SUPERSEDING: Final = 7
_IS_SUPERSEDED: Final = 8
_GROUPS: Final = 9
_FLOATING: Final = 10
_REVOKED: Final = 11
_LED: Final = 12


def _with_groups(status: _Status, groups: tuple[DateGroup, ...]) -> _Status:
    """The status with other date groups (its field number 9, _GROUPS)."""
    fields = list(status)
    fields[_GROUPS] = groups
    return tuple(fields)  # type: ignore[return-value]


# One status's claim on one day. A plain tuple, read by the field numbers below (see _Status).
type _Claim = tuple[
    _Status,  # _CLAIM_STATUS
    bool,  # _CLAIM_STATED
    float,  # _CLAIM_CONFIDENCE
]
_CLAIM_STATUS: Final = 0
_CLAIM_STATED: Final = 1
_CLAIM_CONFIDENCE: Final = 2


# Everything that depends on the text alone (cached per text). A plain tuple, as a status
# is (see _Status), read by the field numbers below.
type _Opening = tuple[int, int, tuple[DateGroup, ...]]
"""A statement that school is open on days the text names: where it stands, how it reads (the
``_OPEN_*`` bits) and its date groups (see :func:`_openings`)."""
type _Analysis = tuple[
    str,  # _TEXT
    tuple[_Status, ...],  # _STATUSES
    frozenset[Note],  # _NOTES
    bool,  # _RECOGNIZED
    bool,  # _AMBIGUOUS
    # _NARROWED: a status was about part of the program ("for grades 6-12", "except Lincoln
    # Elementary"), or part of it is open ("Lincoln Elementary open")
    bool,
    bool,  # _OFFICES_OPEN
    bool,  # _SAYS_OPEN
    # _WEATHER: the result's weather fields: terms, names_weather, reason, reasons,
    # other_causes.
    tuple[tuple[str, ...], bool, Reason | None, tuple[Reason, ...], tuple[str, ...]],
    # _WINDOW and _ANCHOR, for resolving dates (see _frame): the cut-offs for the statuses
    # that name no day, and the position, weekday and modifier of the last weekday name the
    # statuses carry or a closings page's day heading names ("Thursday: Open on time").
    tuple[int, int] | None,
    tuple[int, int, str | None] | None,
    tuple[Note, ...],  # _SORTED_NOTES: the notes in order
    # _HINTS: the days named for side notes ("offices open Monday"): a status that names no
    # day is read from the posting time only when that day is among them (see _frame).
    tuple[DateGroup, ...],
    # _DOUBTS: a bare "cancelled" that nothing claims ("2 hour delay (Lincoln Elementary)
    # cancelled"), read as the school cancelled: on its day, a status it would change is in
    # doubt.
    tuple[_Status, ...],
    # _RESULT: the result for a text that states no status, whenever it was posted (``None``
    # for one that states some): nothing in it needs the posting time.
    ParsedStatus | None,
    # _LEAD: when every day the statuses and the day headings name is a weekday name alone
    # ("Closed Wednesday", "Wednesday: Closed...... Thursday: No First Shift"), their date
    # groups in text order; ``None`` otherwise. Whether the first of those days is the one just
    # past or the one a week on depends on the posting time (see _past_week).
    tuple[DateGroup, ...] | None,
    # _ONE_DATE: the date groups of a text with a digit, () for one with none: when they hold
    # one date with a day number at most (see _one_date), no step compares the values of two,
    # and the analysis can stand for the texts that differ from it only in that date's month
    # and day (see _day_template). (Looked at only for such a text: see _shared_analysis.)
    tuple[DateGroup, ...],
    # _OPENINGS: the statements that school is open, or reopens, on a day a closure or a
    # remote day may name too ("Closed Thursday and Friday. Open Friday."): see _Opening.
    tuple[_Opening, ...],
    # _GATED: the result for a text whose statuses the precision gate stops (see
    # classify.gate), whenever a result of 0.7 or more would be given; ``None`` for one it
    # lets through.
    ParsedStatus | None,
]
_TEXT: Final = 0
_STATUSES: Final = 1
_NOTES: Final = 2
_RECOGNIZED: Final = 3
_AMBIGUOUS: Final = 4
_NARROWED: Final = 5
_OFFICES_OPEN: Final = 6
_SAYS_OPEN: Final = 7
_WEATHER: Final = 8
_WINDOW: Final = 9
_ANCHOR: Final = 10
_SORTED_NOTES: Final = 11
_HINTS: Final = 12
_DOUBTS: Final = 13
_RESULT: Final = 14
_LEAD: Final = 15
_ONE_DATE: Final = 16
_OPENINGS: Final = 17
_GATED: Final = 18


def _clauses(text: str, protected: list[tuple[int, int]]) -> list[_Clause]:
    """Split ``text`` at its separators, never inside a protected span (a date or a mention)."""
    clauses: list[_Clause] = []
    start = 0
    strong = True
    matches = _SEPARATOR.finditer(text)
    if text.startswith("-"):
        opening = _OPENING_DASH.match(text)
        if opening is not None:
            matches = chain((opening,), _SEPARATOR.finditer(text, opening.end()))
    for match in matches:
        low, high = match.span()
        if _blocked(protected, low, high):
            continue
        if text[start:low].strip():
            clauses.append(_Clause(start, low, strong))
            strong = False
        strong = strong or text[low] in _STRONG_MARKS
        start = high
    if text[start:].strip():
        clauses.append(_Clause(start, len(text), strong))
    return clauses


def _blocked(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    """Whether ``start:end`` overlaps a protected span (a date group or a mention)."""
    for span_start, span_end in spans:  # noqa: SIM110 - a loop beats any() on this hot path
        if start < span_end and end > span_start:
            return True
    return False


def _home(clauses: list[_Clause], position: int) -> int:
    """The index of the clause that holds ``position``: one of :func:`_homes`."""
    index = 0
    last = len(clauses) - 1
    while index < last and clauses[index + 1].start <= position:
        index += 1
    return index


def _homes(clauses: list[_Clause], mentions: list[Mention]) -> list[int]:
    """The index of the clause that holds each mention's start (in order).

    That is the last clause that starts at or before it (the first clause for a
    start before it).
    """
    homes: list[int] = []
    index = 0
    last = len(clauses) - 1
    for mention in mentions:
        position = mention.start
        while index < last and clauses[index + 1].start <= position:
            index += 1
        homes.append(index)
    return homes


# Scope --------------------------------------------------------------------------------


# A grade, or a span or a pair of grades, right after a status, with or without "for": part
# of the program, as "for grades 1-3" is.
# Who the grades are, between "for" and them: "for students in grades 6-12".
_GRADE_WHO = r"(?:(?:all\s+)?(?:students|pupils|kids|children|scholars|learners)\s+(?:in|from)\s+)?"
_GRADES_AFTER = re.compile(
    # (An adverb can stand first: "closed only grades 6-12", "remote learning again grades 6-12",
    # "not delayed anymore for grades 6-12".)
    r" (?:(?:only|again|now|also|still|anymore)\s+)?(?:(?:for|in)\s+)?"
    + _GRADE_WHO
    + r"(?:grades?\s+(?:k|pk|tk|\d{1,2})\b|(?:k|pk|tk|kindergarten|pre-?k|\d{1,2}(?:st|nd|rd|th))"
    r"(?:\s*(?:-|to|through|thru|and|or)\s*\d{1,2}(?:st|nd|rd|th))?\s*-?\s*grad(?:e|es|er|ers)\b)"
    # A band of grades alone after "for" or "in": "for K-5", "in 6-12", "for PK-8", "for
    # students in K-8".
    r"| (?:(?:only|again|now|also|still|anymore)\s+)?(?:for|in)\s+"
    + _GRADE_WHO
    + r"(?:pre-?k|pk|tk|k|\d{1,2})\s*-\s*(?:k|\d{1,2})(?![\d/-])",
    re.ASCII,
).match
# What a band of grades alone comes after (see _GRADES_AFTER): "closed for K-5", "closed only
# for K-5", "remote learning again in 6-12".
_BAND_LEADS = tuple(
    f" {adverb}{lead} "
    for adverb in ("", "only ", "again ", "now ", "also ", "still ", "anymore ")
    for lead in ("for", "in")
)
# A preposition before a date blanked out of the text: "closed on Friday for staff".
_DATE_LEADS = (" for   ", " on   ")


def _scope_after(text: str, mention: Mention, end: int) -> Scope | None:  # noqa: PLR0911 - one per form
    """The noun a following phrase names: "closed for students", "cancelled: all classes".

    A date between them is blanked out of ``text``: "closed tomorrow for staff",
    "closed on Friday for staff".
    """
    start = mention.end
    if text.startswith(" only for ", start):
        start += 5  # "delay only for buses": the noun after "only for"
    if text.startswith(_DATE_LEADS, start):
        start += 4 if text.startswith(" for", start) else 3  # past " for" or " on"
    if text.startswith("  ", start):
        start = end - len(text[start:end].lstrip(" ")) - 1  # the space before the next word
    if ("grad" in text or ("-" in text and text.startswith(_BAND_LEADS, start))) and _GRADES_AFTER(
        text, start, end
    ) is not None:
        return "partial"  # "closed grades 1-3", "closed 1st grade", "closed for 1st and 2nd grade"
    if not mention.needs_school_noun and not text.startswith(_PREPOSITIONS, start):
        only = _ONLY_AFTER.match(text, start, end)
        if only is None:
            return None
        scope = _noun_phrase_scope(only.group("w1"), only.group("w2"))
        return None if scope == "school" else scope  # "closed kindergarten only"
    match = _AFTER.match(text, start, end)
    if match is None or (match.group("prep") is None and not mention.needs_school_noun):
        return None
    if _CLOCK_NEXT.match(text, match.end("w1")) is not None:
        return None  # "early dismissal: elementary 1:15, middle 1:45": times by level
    first = match.group("w1")
    if (first in _LEVEL_WORDS and _LEVEL_PAIR.match(text, match.end("w1"), end)) or (
        "/" in first and _LEVEL_WORDS.issuperset(first.split("/"))
    ):
        return "partial"  # "closed for middle and high school", "for middle/high school"
    return _noun_phrase_scope(match.group("w1"), match.group("w2"))


# Nouns for part of the program that also end a school's name: "Lincoln Elementary".
_SCHOOL_TYPES = frozenset(
    {
        "elementary", "elementary school", "middle school", "high school", "junior high",
        "intermediate school", "primary school", "secondary", "secondary school",
        "upper school", "lower school", "preschool", "pre-school",
        "kindergarten", "nursery", "early childhood", "career center", "tech center",
        "technical center",
        # The levels abbreviated: "Kubaze HS: closed", "Kubaze Elem. closed" (see SCOPES).
        "es", "elem", "ms", "hs", "jh", "jhs", "shs", "ms/hs", "jh/hs", "jr/sr",
    }
)  # fmt: skip
# The nouns of a program, not of a level: a center of one with no name of its own is the
# district's program ("Early Childhood Center: Closed", as "Early childhood closed" is), and
# with a name, a school's ("Holy Family Preschool: Closed").
_PROGRAM_TYPES = frozenset(
    {"preschool", "pre-school", "kindergarten", "nursery", "early childhood"}
)
# Words after a noun that make the phrase an institution's name: "Kindergarten Center".
_INSTITUTIONS = frozenset({"center", "centre", "academy", "institute", "complex"})
# Words that describe which schools, not which school: "all elementary", "our middle schools".
_NOT_NAMES = frozenset(
    {
        "all", "the", "our", "their", "its", "any", "every", "each", "some", "both", "these",
        "those", "this", "that", "other", "others", "remaining", "select", "selected", "certain",
        "most", "many", "several", "few", "only", "also", "plus", "or", "nor", "but", "in",
        "at", "to", "with", "by", "from", "on", "for", "due", "except", "including", "public",
    }
)  # fmt: skip
# Words that can join the parts of a name: "Lincoln and Washington Elementary", "St. Mary".
_NAME_JOINERS = frozenset({"and", "of", "st", "saint", "mt", "mount"})
# Nouns for roads, which name schools too: "Mill Road Elementary", "Oak Street Elementary".
_STREET_WORDS = frozenset({"road", "street", "lane", "bridge", "highway", "route"})
# Words for a level of school, and those that open one ("junior high", "senior high").
_LEVEL_WORDS = frozenset(
    {
        "high", "middle", "junior", "senior", "elementary", "intermediate", "primary",
        "secondary", "upper", "lower",
    }
)  # fmt: skip
_LEVEL_PREFIXES = frozenset({"junior", "senior"})
# A second level joined to a first: "middle and high school", "middle & high schools",
# "elementary/middle" (see _scope_after).
_LEVEL_PAIR = re.compile(
    r"(?:\s+high)?\s*(?:and|&|/|or)\s*(?:junior\s+|senior\s+)?(?:high|middle|elementary|intermediate"
    r"|primary|secondary)\b",
    re.ASCII,
)
# Words found only inside a two-word noun ("central office", "early childhood", "career
# center"), which alone can be part of a school's name: "Central High School", "Early College
# High School". Not a level, a time of the day or a status word.
_PAIR_NAME_WORDS = frozenset(
    word
    for noun in SCOPES
    if " " in noun
    for word in noun.split()
    if word.isalpha()
    and word not in SCOPES
    and word not in MODIFIERS
    and word not in _LEVEL_WORDS
    and word not in {"before", "after", "open", "day"}
)


def _name_word(token: str) -> bool:
    """Whether ``token`` can be part of a school's name: a word no list here gives a role."""
    return (
        token.isalpha()
        and token not in _NOT_NAMES
        and token not in _SCOPE_WORDS
        and token not in MODIFIERS
        and token not in NEGATIONS
        and token not in HEDGES
        and token not in CONDITIONALS
        and _GRADE_SPAN.fullmatch(token) is None
    )


def _school_name(tokens: list[str], head: int, end: int, name_from: int = 0) -> bool:
    """Whether the noun at ``head:end + 1`` is in a name that opens the text.

    "Lincoln Elementary", "Maple Grove Middle School", "Kindergarten Center":
    the name's other words are names, joiners or numbers. The name starts at
    ``name_from``, after a heading's mark ("Update: Elementary School closed" names
    no school).
    """
    before, after = tokens[name_from:head], tokens[end + 1 :]
    if after and all(token in _INSTITUTIONS for token in after):
        return bool(before) or " ".join(tokens[head : end + 1]) not in _PROGRAM_TYPES
    while after and after[-1] in _NAME_VERBS:
        after = after[:-1]  # "Lincoln Elementary will be closed", "... is on a 2 hour delay"
    if after and not _placed(after):
        return False
    while before and (before[-1] in _LEVEL_PREFIXES or _slashed_levels(before[-1])):
        # "Lincoln Junior High School": the level is "junior high school"; "Lincoln Jr./Sr.
        # High School", "Lincoln Junior/Senior High School": a school of two levels.
        before = before[:-1]
    return _names_only(before)


def _names_only(before: list[str]) -> bool:
    """Whether ``before`` is a school's name before its level: names, joiners, numbers, and at
    least one name ("Lincoln", "St. Mary", "Bridge Street")."""
    named = any(_in_school_name(token) for token in before) or (
        len(before) > 1 and before[0] in _STREET_WORDS  # "Bridge Street", "Route 9"
    )
    return named and all(
        _in_school_name(token)
        or token in _NAME_JOINERS
        or token in _STREET_WORDS
        or token.isdigit()
        for token in before
    )


# The parts of two levels joined by a slash, as a school of both writes them: "Elementary/
# Middle", "Middle/High", "Jr./Sr." (which words splits as "jr/sr").
_SLASHED_LEVEL_PARTS = _LEVEL_WORDS | {"jr", "sr"}


def _slashed_levels(token: str) -> bool:
    """Whether ``token`` is two levels joined by a slash: "middle/high", "jr/sr"."""
    return "/" in token and _SLASHED_LEVEL_PARTS.issuperset(token.split("/"))


# How a statewide list writes an entry for one school: its name, its county, then the status.
# "Philip Barbour High School Complex in Barbour County will be closed on Thu. Dec. 11".
_PLACE_NOUNS = frozenset({"county", "parish", "borough"})
_NAME_VERBS = frozenset(
    {"will", "shall", "be", "is", "are", "has", "have", "been", "on", "a", "an"}
)


def _placed(after: list[str]) -> bool:
    """Whether the words after a school's level are its county and a verb: "complex in
    barbour county will be" (see :data:`_PLACE_NOUNS`)."""
    index = 0
    while index < len(after) and after[index] in _INSTITUTIONS:
        index += 1  # "high school complex"
    if index == len(after) or after[index] != "in":
        return False
    place = index + 1
    while place < len(after) and after[place] not in _PLACE_NOUNS:
        if not _name_word(after[place]):
            return False
        place += 1
    return index + 1 < place < len(after) and all(
        token in _NAME_VERBS for token in after[place + 1 :]
    )


# Nouns for places that a listing can report on ("Stadium closed") and that name schools too:
# "Community Elementary", "Stadium Drive Elementary", "Library Road Elementary".
_PLACE_NAME_WORDS = FACILITY_NOUNS


def _in_school_name(token: str) -> bool:
    """Whether ``token`` can be a word of a school's name before its level: "Central", "Early",
    the "Campus" of "South Campus High School"."""
    return (
        _name_word(token)
        or token in _PAIR_NAME_WORDS
        or token in _PLACE_NAME_WORDS
        or token in _SITE_NAME_WORDS
    )


_SITE_NAME_WORDS = frozenset({"campus"})  # "South Campus High School"


def _noun_phrase_scope(first: str, second: str | None) -> Scope | None:
    if second is None:
        return SCOPES.get(first)
    if second in PURPOSES:
        return None  # "closed for teacher workday", "closed for staff development"
    pair = f"{first} {second}"
    if pair in SCOPES:
        return SCOPES[pair]
    if (first in MODIFIERS or first in _SOME_OF or first in _COUNTS) and second in SCOPES:
        # A school noun after "evening" or "some" is part of the program, or not the day.
        return MODIFIERS.get(first, "partial") if SCOPES[second] == "school" else SCOPES[second]
    if SCOPES.get(second) == "partial" and _GRADE_SPAN.fullmatch(first):
        return "partial"  # "no school for 3rd grade"
    return SCOPES.get(first)


# The school nouns for classes, which a word for part of the program before them makes that
# part's ("preschool classes"; see _scope_before).
_CLASS_NOUNS = frozenset({"class", "classes", "session", "sessions"})


def _clock_tokens(tokens: list[str]) -> bool:
    """Whether the last words of ``tokens`` are a time of the day as words splits one: "8 00"
    ("8:00"), "7 30", "8 am"."""
    if len(tokens) < 2:  # noqa: PLR2004 - an hour and its minutes or its mark
        return False
    hour, minutes = tokens[-2], tokens[-1]
    return (
        hour.isdigit()
        and len(hour) <= 2  # noqa: PLR2004
        and ((minutes.isdigit() and len(minutes) == 2) or minutes in {"am", "pm"})  # noqa: PLR2004
    )


# Words before a school noun that pick out some of the schools: "some schools closed".
_SOME_OF = frozenset(
    {"some", "select", "selected", "several", "certain", "most", "many", "few", "specific"}
)
# A count of schools is some of them ("Three schools closed", "2 schools closed"), but not
# after a word for all of them ("all three campuses", "our two schools").
_COUNT_WORDS = frozenset(
    {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"}
)
_COUNTS = _COUNT_WORDS | frozenset(str(number) for number in range(2, 100))
# A count in figures before a noun of schools or sites: "4 schools closed" (see _lone_status;
# a count in words has a bit of its own).
_COUNT_SCHOOLS = re.compile(
    # (The digit first, then the word's start behind it: a pattern that starts with a digit
    # is looked for quickly.)
    r"\d(?<![a-z0-9]\d)\d? (?:schools|campuses|buildings|sites|locations)\b",
    re.ASCII,
).search
_ALL_OF = frozenset({"all", "the", "our", "both", "these", "those", "each", "every"})
# A count in words before a noun of schools or of places they run, or a word before one: "two
# schools", "three elementary schools", "at two locations". Such a count moves the status
# to some of them (see _lone_status, partial.carved); any other ("Two Hour Delay") is a
# length, or says nothing of who.
_COUNTED = re.compile(
    # (No word's start before the count: one within a word, "often schools", only sends the
    # text the long way, which reads it right; a pattern that starts with a word is quicker.)
    rf"(?:{'|'.join(sorted(_COUNT_WORDS))})\s+(?:[a-z0-9'-]+\s+)?"
    r"(?:schools?|class(?:es)?|students?|campus(?:es)?|buildings?|facilities|districts?"
    r"|instruction|locations?|sites?|branch(?:es)?|areas?|parts|regions?|zones?|communities"
    r"|neighborhoods)\b",
    re.ASCII,
).search


def _scope_before(  # noqa: PLR0911 - one return per kind of noun found
    tokens: list[str], *, label: bool = False, marks: tuple[int, ...] = ()
) -> tuple[Scope | None, Scope | None]:
    """Return the scope of the noun nearest before a mention, and a second scope for a note.

    "Schools and offices closed" is about the schools (and notes the offices).
    With ``label``, ``tokens`` are every word from the start of the text, and a
    noun inside a school's own name there ("Lincoln Elementary: closed",
    "Kindergarten Center: closed") names the school, not part of it. A name
    starts after the last heading mark before its level: ``marks`` holds the index
    of the word after each.
    """
    if _SCOPE_WORDS.isdisjoint(tokens):
        return None, None
    for index in range(len(tokens) - 1, -1, -1):
        pair = f"{tokens[index - 1]} {tokens[index]}" if index > 0 else ""
        if pair in SCOPES:
            noun, head = pair, index - 1
        elif tokens[index] in SCOPES:
            noun, head = tokens[index], index
        else:
            continue
        scope = SCOPES[noun]
        if scope == "school":
            before = tokens[max(0, head - 2) : head]
            if (len(before) == 2 and SCOPES.get(" ".join(before)) == "partial") or (  # noqa: PLR2004
                before and noun in _CLASS_NOUNS and SCOPES.get(before[-1]) == "partial"
            ):
                # "Early bird classes cancelled", "Preschool classes canceled": classes of part
                # of the program. ("Lincoln Elementary School" names a school.)
                return "partial", None
            if noun in _CLASS_NOUNS and (
                _clock_tokens(before)
                or (
                    tokens[index + 1 : index + 3][:1] in (["at"], ["from"])
                    and _clock_tokens(tokens[index + 2 : index + 4])
                )
            ):
                # "8:00 classes cancelled", "Classes at 8:00 cancelled": the classes at that
                # time, part of the day.
                return "partial", None
            levels = _level_scope(tokens, head, noun, marks, label=label)
            if levels is not None:
                return levels
            modifiers = [MODIFIERS[token] for token in reversed(before) if token in MODIFIERS]
            if not _SOME_OF.isdisjoint(before) or (
                before and before[-1] in _COUNTS and (len(before) < 2 or before[-2] not in _ALL_OF)  # noqa: PLR2004
            ):
                modifiers.append("partial")  # "some schools closed": not every school
            return (modifiers[0] if modifiers else "school"), None
        if (
            label
            and noun in _SCHOOL_TYPES
            and _school_name(tokens, head, index, _name_start(marks, head))
        ):
            return "school", "school"  # (the second "school" says the name decided it)
        joined = [j for j in range(head) if tokens[j] in {"and", "plus"}] if head else None
        if joined and any(
            SCOPES.get(tokens[j]) == "school"
            and (j == 0 or tokens[j - 1] not in MODIFIERS)
            # (Not the first word of a noun for something else: "Campus Rec and activities".)
            and SCOPES.get(f"{tokens[j]} {tokens[j + 1]}", "school") == "school"
            for j in range(joined[-1])
        ):
            return "school", scope
        return scope, None
    return None, None


def _level_scope(
    tokens: list[str], head: int, noun: str, marks: tuple[int, ...], *, label: bool
) -> tuple[Scope | None, Scope | None] | None:
    """The scope a level or two levels joined by a slash before the noun at ``head`` give it.

    "Secondary students: remote learning": part of the district. "Middle/high school
    closed": two levels of the district's schools. With a name before them ("Lincoln
    Middle/High School", "Barrackville Elementary/Middle School"), one school of both
    levels, whose status the school's own is, as a named school of one level's is (see
    _school_name).
    """
    if head and noun in _PEOPLE_NOUNS and SCOPES.get(tokens[head - 1]) == "partial":
        return "partial", None
    for j in range(head - 1, max(0, head - 2) - 1, -1):
        if _slashed_levels(tokens[j]):
            if _names_only(tokens[_name_start(marks, j) : j]):
                return ("school", "school") if label else ("school", None)
            return "partial", None
    return None


def _name_start(marks: tuple[int, ...], head: int) -> int:
    """The index of the first word of a name whose level starts at ``head``: the word after
    the last heading mark before it (see :func:`_scope_before`)."""
    start = 0
    for mark in marks:
        if mark <= head:
            start = mark
    return start


# Nouns for the students a word for part of the program before them makes that part's.
_PEOPLE_NOUNS = frozenset({"students", "student", "pupils", "kids", "children", "learners"})


# Hedges, negation, replacement --------------------------------------------------------


# Words before a word of hearsay that answer it: "despite rumors, closed" is the school's word.
_ANSWERING_HEARSAY = frozenset({"despite", "contrary", "regardless", "notwithstanding", "ignore"})


def _hedged_before(tokens: list[str]) -> bool:
    """Whether a hedge comes before a status in its clause ("possible closing", "rumor: closed").

    A hedge inside a cause phrase hedges nothing ("closed due to possible flooding"), and
    neither does hearsay that the text answers ("contrary to rumors, closed").
    """
    in_cause = answering = False
    for token in tokens:
        if token in CAUSES:
            in_cause = True
        elif token in _ANSWERING_HEARSAY:
            answering = True
        elif token in HEDGES and not in_cause and not (answering and token in UNVERIFIED):
            return True
    return False


def _hedged_after(tokens: list[str]) -> bool:
    """Whether the words after a status open with a hedge: "closing possible", "delay
    tentatively", "closure to be determined", "closing tomorrow is a possibility", "... is an
    option"."""
    for index, word in enumerate(tokens[:4]):
        if word in _COPULAS or word in _HEDGE_LEADS or word in _HEDGE_SKIPS:
            continue
        if word == "to":
            return tokens[index + 1 : index + 2] == ["be"] and (
                index + 2 < len(tokens) and tokens[index + 2] in _TO_BE_SETTLED
            )
        return (
            word in HEDGES_AFTER
            or word == "tentatively"
            or (word in _UNDER_HEDGES and index > 0 and tokens[index - 1] == "under")
            or (word in _POSSIBILITIES and (index > 0 or word in _CHANCES))
            or (word == "subject" and tokens[index + 1 : index + 3] in _TO_CHANGE)
            # "Closing tomorrow is still being decided"
            or (word in _TO_BE_SETTLED and index > 0 and tokens[index - 1] == "being")
        )
    return False


def _notice(tokens: list[str], *, dated: bool, watched: Callable[[], None]) -> bool:
    """Whether a noun right after a status makes it a notice of a decision or news about it to
    come, or a rule's definition: "Closure decision by 5 a.m.", "Closure update coming at 5
    am", "Closure status: TBD", "Closure call by 5 am", "A 2 hour delay means school starts at
    10:00". ``tokens`` are the words after the status in its clause, and ``dated`` whether
    a day was blanked out of them ("Closure update tonight"). A watch makes it one, and
    ``watched()`` notes it so, to be read again when another status stands beside it (see
    :func:`_read_watched`)."""
    position = 0
    while position < 2 and tokens[position] in _NOTICE_JOINED and position + 1 < len(tokens):  # noqa: PLR2004 - "or closure"
        position += 1  # "Delay or closure decision by 5 am", "Delay/closure decision"
    tokens = tokens[position:]
    noun = tokens[0]
    if noun not in _NOTICE_NOUNS and noun not in _REPORT_NOUNS:
        return False
    if noun in _NOTICE_ALWAYS:
        return True
    if noun in _WATCH_NOUNS:
        watched()
        return True
    if noun == "status":
        return not _PENDING_ANSWERS.isdisjoint(tokens[1:4])  # "Closure status: closed" is one
    # "update by 8 pm", "call tonight", "notice will be sent by 9 pm"
    if len(tokens) > 1:
        return tokens[1] in _NOTICE_TIMES
    return dated and noun in _NOTICE_DATED  # ("Closure update tonight"; not "Alert Monday")


# The words a status that a notice noun can follow ends with: a noun ("Closure decision", "Snow
# day decision", "Delay update at 5 am"), not a word a label follows ("Closed UPDATE", "Closed -
# Call by appointment").
_NOTICE_HEADS = (
    "closure", "closures", "closing", "closings", "delay", "delays", "day", "days",
    "cancellation", "cancellations", "dismissal", "release", "start", "learning", "opening",
)  # fmt: skip


# Nouns after a status that make it a notice (see _notice): always, or before a time or a
# pending answer only ("Delay update: 2 hours" gives the update).
_NOTICE_ALWAYS = frozenset({"decision", "decisions", "announcement", "announcements"})
# ("Closure watch for tomorrow": watched for, as a storm watch is, not stated: a notice. Beside
# a status of its own kind it is read as written, so "Closed tomorrow - closure watch" agrees
# with itself (see _read_watched); beside one of another kind it casts doubt on it, as a status
# only possible does, so "2 hour delay tomorrow; closure watch in effect" says nothing sure, as
# "2 hour delay tomorrow, possibility of closure" does (see _hedged_doubts).)
_WATCH_NOUNS = frozenset({"watch", "watches"})
# ("Closure report by 5:30 a.m.": a notice right after a status only, as _REPORT_LEAD looks;
# in no word list, so "Staff report at 10" anywhere else changes no path a text takes.)
_REPORT_NOUNS = frozenset({"report", "reports"})
_REPORT_LEAD = " report"  # (see _report_notice)
_NOTICE_NOUNS = _NOTICE_ALWAYS | _WATCH_NOUNS | {
    "update", "updates", "call", "status", "notice", "notices", "alert", "alerts", "message",
    "messages", "notification", "notifications", "news", "post", "details",
    "email", "emails", "text", "texts", "voicemail", "voicemails", "letter", "letters",
    "robocall", "robocalls", "tweet", "tweets",
}  # fmt: skip
_NOTICE_DATED = frozenset({"update", "updates", "call"})  # (the nouns a bare day can follow)
_NOTICE_TIMES = frozenset(
    {"by", "at", "tonight", "tomorrow", "coming", "expected", "will", "soon", "later", "around",
     "before", "after", "this", "to", "is", "in", "go", "goes", "going", "sent", "out", "on",
     "via", "posted"}
)  # fmt: skip
# Words between a status and the notice noun that make it the notice of both: "Delay or closure
# decision", "Delay/closure decision".
_NOTICE_JOINED = frozenset(
    {"or", "and", "and/or", "closure", "closing", "closings", "closures", "delay", "delays",
     "cancellation", "cancellations", "dismissal", "release"}
)  # fmt: skip
_PENDING_ANSWERS = frozenset({"tbd", "tba", "pending", "unknown", "undecided", "undetermined"})
# Words a hedge after a status can follow besides a copula: "a closure tomorrow has been
# discussed", "closure tomorrow remains a possibility".
_HEDGE_SKIPS = frozenset({"has", "have", "had", "was", "were", "been", "remains", "remain"})


def _report_notice(text: str, mention: Mention) -> bool:
    """Whether "report" right after ``mention`` (as ``_REPORT_LEAD`` looks) can make it a notice,
    as :func:`_open_after` reads one: after a status noun with no length ("Closure report by
    5:30 a.m."), not after a length ("2 hour delay report at 10": the staff's verb) or after a
    word no notice follows ("No Personnel Report"), whose status takes its short path.
    """
    return (
        mention.delay is None
        and mention.early is None
        and text.endswith(_NOTICE_HEADS, mention.start, mention.end)
    )


def _notice_time(text: str, mention: Mention, notice_time: int) -> int:
    """Where the next status starts if ``mention``, just qualified, is a notice by the report
    right after it, else ``notice_time`` as it was.

    That report's own words are the notice's, not a status of their own: in "Closure report
    at 10", "report at 10" is when the report comes, not staff or students reporting late, so
    the status found there (a late start) is hedged with the notice.
    """
    if mention.dropped == "hedged" and text.startswith(_REPORT_LEAD, mention.end):
        return mention.end + 1
    return notice_time


_TO_CHANGE = (["to", "change"], ["to", "changes"], ["to", "revision"])  # "subject to change"


# Words a hedge after a status can follow ("closure under review", "delay still undecided").
_HEDGE_LEADS = frozenset({"under", "still"})
# Nouns that, said of a status, make it one possibility ("closing tomorrow is a possibility",
# "a delay is an option"): after a copula or an article only ("eLearning option" names one).
# Words for its odds make it one right after it too ("Snow day chance: 90%").
_CHANCES = frozenset({"chance", "chances", "odds", "probability", "likelihood", "prediction"})
_POSSIBILITIES = frozenset({"possibility", "possibilities", "option", "options"}) | _CHANCES


# A preposition before a date, in a text whose dates are blanked out: "closure for Jan. 22".
_DATE_PREPOSITION = re.compile(r"\b(?:for|on)(?= {3})", re.ASCII)


def _words_after(text: str, start: int, end: int) -> list[str]:
    """The words after a status in its clause, less a preposition that only introduced a date.

    The text has its dates blanked out, so "closing for Jan. 22 possible" reads
    "closing for" and spaces before "possible": the "for" belongs to the date.
    """
    if "  " not in text[start:end]:
        return words(text, start, end)
    return words(_DATE_PREPOSITION.sub(" ", text[start:end]))


# Words between "not" and the word it turns: "closure is not currently expected".
_AFTER_NOT = _COPULAS | {"currently", "presently", "being", "been"}
# The forms of "have" before "not": "closing tomorrow has not been decided".
_AUXILIARIES = frozenset({"has", "have", "had"})


def _denied_after(tokens: list[str]) -> Note | None:  # noqa: PLR0911 - one return per reading
    """What "not" after a status says of it: that it is not coming, or not settled.

    "Closure not expected" and "a delay is not planned" deny the status
    (``negated``); "delay not yet decided", "closure not ruled out" and "delay
    not expected to change" leave it open (``hedged``). ``tokens`` are the words
    after the status in its clause.
    """
    position = 0
    while position < len(tokens) and (
        tokens[position] in _COPULAS or tokens[position] in _AUXILIARIES
    ):
        position += 1
    if position >= len(tokens) or tokens[position] not in NEGATIONS:
        return None
    position += 1
    if position == len(tokens):
        return "negated"  # "closed not", "closed not today": the "not" denies the status
    while position < len(tokens) and tokens[position] in _AFTER_NOT:
        position += 1
    if position >= len(tokens):
        return "negated"  # "delay will not be Thursday" (the day blanked out), as "not" alone
    following = tokens[position]
    if following == "out" and tokens[position + 1 : position + 4] == ["of", "the", "question"]:
        return "hedged"  # "closure tomorrow is not out of the question"
    if following in DENIED_AFTER:
        # "Closure not expected to happen" denies it; "delay not expected to change" does not.
        # Which one is meant turns on the verb after "to", so the status is left open.
        after = tokens[position + 1] if position + 1 < len(tokens) else None
        return "hedged" if after == "to" else "negated"
    if following in UNSETTLED_AFTER or following in HEDGES_AFTER:
        return "hedged"
    return None


def _conditional(text: str, clause: _Clause, tokens: list[str]) -> tuple[bool, bool]:
    """Return whether the clause is conditional, and whether it opens with the condition.

    A condition opens it ("if roads are icy", "should conditions worsen", "in case
    of snow", "pending road conditions", "weather permitting", "whether or not",
    "when school is closed") or stands anywhere in it ("closed if roads are icy",
    "closed tomorrow depending on the forecast"). ``tokens`` are the clause's words.
    """
    if not tokens:
        return False, False
    lead = _condition_lead(tokens)
    opens = (
        _condition_opens(tokens, lead)
        or tokens[lead] == "whether"
        or _WHEN.match(text, clause.start) is not None
    )
    return opens or (
        not _CONDITION_AT_WORDS.isdisjoint(tokens)
        and any(
            _condition_at(tokens, index)
            for index, word in enumerate(tokens)
            if word in _CONDITION_AT_WORDS
        )
    ), opens


# Words before a condition that leave it opening its phrase: "only if", "and if needed".
_CONDITION_LEADS = frozenset({"and", "or", "only", "but", "though", "although", "just"})
# Words of a sentence that states what follows from its condition ("If conditions improve we
# will reopen"): such a sentence is its own statement, not a fragment about the one before.
_CONSEQUENCES = frozenset(
    {"will", "would", "we", "we'll", "then", "shall", "must", "can", "may", "might", "could",
     "please", "call", "check", "it'll", "they", "they'll"}
)  # fmt: skip


def _condition_lead(tokens: list[str]) -> int:
    """How many of ``tokens`` lead into a condition ("and only if"): never all of them."""
    lead = 0
    while lead < len(tokens) - 1 and tokens[lead] in _CONDITION_LEADS:
        lead += 1
    return lead


def _condition_opens(tokens: list[str], start: int = 0) -> bool:
    """Whether ``tokens[start:]`` open with a condition on a status.

    "if the storm hits", "unless roads are cleared", "should the storm arrive",
    "in case of snow", "depending on the forecast", "pending road conditions",
    "barring more snow", "subject to change", "as long as roads are clear",
    "whenever school is closed", "weather permitting". "If you have questions",
    "unless otherwise noted" and "should be back Thursday" are none (see
    :data:`~snowlight.classify.lexicon.NOT_CONDITIONS`); nor is "whether", which
    after a status means regardless ("closed, whether or not it snows").
    """
    if start >= len(tokens):
        return False
    first = tokens[start]
    second = tokens[start + 1] if start + 1 < len(tokens) else ""
    if first in NOT_CONDITIONS:
        return bool(second) and second not in NOT_CONDITIONS[first]
    if first in CONDITION_OPENERS:
        return first != "subject" or second == "to"
    if first == "in":
        return second == "case"
    if first in {"as", "so"}:
        return tokens[start + 1 : start + 3] == ["long", "as"]
    return "permitting" in tokens[start + 1 : start + 6]


# The words :func:`_condition_at` can find a condition at (a quick test before it is asked).
_CONDITION_AT_WORDS = (
    frozenset({"if", "unless", "whether", "pending", "case"}) | CONDITIONS_ANYWHERE
)


def _condition_at(tokens: list[str], index: int) -> bool:
    """Whether the word at ``index`` makes its clause conditional wherever it stands.

    "If", "unless" ("closed if roads are icy"), "whether", "in case", and the words of
    :data:`~snowlight.classify.lexicon.CONDITIONS_ANYWHERE`. "Even if" (the status holds
    regardless), "if you" and "unless otherwise" are no condition on it.
    """
    word = tokens[index]
    if word in {"if", "unless"}:
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if following in NOT_CONDITIONS[word]:
            return False
        return word == "unless" or index == 0 or tokens[index - 1] != "even"
    if word in {"whether", "pending"} or word in CONDITIONS_ANYWHERE:
        return True
    return word == "case" and index > 0 and tokens[index - 1] == "in"


def _hedge_only(tokens: list[str]) -> bool:
    """Whether a phrase is only a hedge: "tentative", "TBD", "possible", "not confirmed",
    "not yet final", "not yet", "to be determined", "tentative at this time" (see
    :data:`~snowlight.classify.lexicon.HEDGE_CLAUSE_WORDS`)."""
    hedged = False
    index = 0
    count = len(tokens)
    while index < count:
        word = tokens[index]
        if word in HEDGE_CLAUSE_WORDS:
            hedged = True
        elif word == "not":
            start = index + 1
            index = start
            while index < count and tokens[index] in HEDGE_CLAUSE_FILLERS:
                index += 1
            if index < count and tokens[index] in UNSETTLED_AFTER:
                hedged = True  # "not confirmed", "not yet final"
            elif index == count and "yet" in tokens[start:index]:
                hedged = True  # "(not yet)": not settled
                continue
            else:
                return False
        elif word in _TO_BE_LEADS and tokens[index + 1 : index + 2] == ["be"]:
            if index + 2 >= count or tokens[index + 2] not in _TO_BE_SETTLED:
                return False  # ("to be determined", "will be announced")
            hedged = True
            index += 2
        elif word not in HEDGE_CLAUSE_FILLERS:
            return False
        index += 1
    return hedged


# "To be determined", "to be confirmed", "will be decided": not settled yet.
_TO_BE_SETTLED = frozenset({"determined", "confirmed", "decided", "announced", "finalized"})
_TO_BE_LEADS = frozenset({"to", "will"})

# A decision still to come: "Decision at 5 AM", "final decision by 5 a.m.", "we will decide in
# the morning". The words of such a phrase besides the decision itself, and the words that say
# it was made already ("the decision was made").
_DECISIONS = frozenset({"decision", "decisions", "decide", "deciding"})
_DECISION_WORDS = frozenset(
    {
        "a", "the", "final", "official", "will", "be", "made", "make", "by", "at", "on", "before",
        "no", "later", "than", "around", "about", "approximately", "we", "district", "officials",
        "superintendent", "expect", "expected", "to", "in", "morning", "early", "am", "pm",
        "o'clock", "is", "coming", "announced", "posted", "an", "update", "with", "soon", "any",
        "further", "changes", "closing", "closings", "closure", "closures", "status", "schedule",
        "regarding", "pending",
    }
)  # fmt: skip
_DECIDED = frozenset({"was", "were", "has", "have", "had", "been"})
# The words of a phrase that says the plans changed ("Plans have changed", "Change of plans").
_PLANS = frozenset({"plan", "plans"})
_PLANS_CHANGED = frozenset({"change", "changed", "changes", "changing"})
_PLANS_CHANGED_WORDS = (
    _PLANS
    | _PLANS_CHANGED
    | frozenset(
        {"have", "has", "had", "been", "of", "our", "the", "a", "there", "is", "are", "slight"}
    )
)
# The words of a phrase that says a status will be looked at again, or waits on someone's word
# (see _decision_pending).
_PENDING_CHECKS = frozenset(
    {"reassess", "reassessing", "reassessed", "reassessment", "re-assess", "re-assessing",
     "reevaluate", "reevaluating", "reevaluated", "re-evaluate", "re-evaluating", "re-evaluated",
     "evaluate", "evaluating", "evaluated", "determination", "awaiting", "approval"}
)  # fmt: skip


def _decision_pending(tokens: list[str]) -> bool:
    """Whether a phrase only says a decision is still to come: "Decision at 5 AM".

    "Decision made" says it was taken; "decision will be made by 5 AM" that it
    is still to come. A phrase that says the status will be looked at again, or
    waits on a word from someone else, says so whatever else it holds: "Will
    reassess at 5 AM", "re-evaluating at 7:30", "A final determination will be
    made by 5 AM", "Final call at 5 AM", "Awaiting approval".
    """
    if not _PENDING_CHECKS.isdisjoint(tokens) or ("call" in tokens and "final" in tokens):
        return True
    if not _PLANS.isdisjoint(tokens) and not _PLANS_CHANGED.isdisjoint(tokens):
        return set(tokens) <= _PLANS_CHANGED_WORDS  # "Plans have changed", "Change of plans"
    return (
        not _DECISIONS.isdisjoint(tokens)
        and _DECIDED.isdisjoint(tokens)
        and ("made" not in tokens or "will" in tokens or "be" in tokens)
        and all(
            token in _DECISIONS or token in _DECISION_WORDS or token.isdigit() for token in tokens
        )
    )


def _trailing(
    text: str, clauses: list[_Clause], tokens: list[list[str]], busy: AbstractSet[int]
) -> set[int]:
    """The clauses a condition or a hedge after them leaves open.

    "No school tomorrow, if the storm hits", "Closed tomorrow - weather
    permitting", "Closed Friday (tentative)", "Closed tomorrow. TBD.": a phrase
    after a status that opens with a condition (see :func:`_condition_opens`), or
    that is only a hedge (see :func:`_hedge_only`), makes the status before it
    conditional. That status is the one in the nearest clause before it with a
    mention, back to the start of its sentence. After a sentence mark a
    condition reaches back only as a fragment ("Closed tomorrow. Pending road
    conditions.", "Closed tomorrow. If the storm hits."): a sentence with more
    after it, a status, a date or a consequence of its own ("If conditions
    improve we will reopen") states its own condition. A hedge beside a date is
    about that date ("Closed today, tomorrow TBD", "Closed tomorrow, possibly
    Wednesday", see :func:`_date_hedged`), and a condition that "and" or "or"
    opens, with more of its sentence after it, opens what follows ("Closed
    Monday, and if needed, Tuesday"). ``tokens`` are each clause's words, and
    ``busy`` the clauses with a mention.
    """
    found: set[int] = set()
    last = len(clauses) - 1
    for index in range(1, last + 1):
        clause = clauses[index]
        clause_tokens = tokens[index]
        if not clause_tokens:
            continue
        lead = _condition_lead(clause_tokens)
        dated = "  " in text[clause.start : clause.end]  # a date blanked out (see _settle)
        condition = _condition_opens(clause_tokens, lead)
        more = index < last and not clauses[index + 1].strong  # its sentence goes on
        if condition:
            if clause.strong:
                if more or dated or index in busy or not _CONSEQUENCES.isdisjoint(clause_tokens):
                    continue
            elif more and lead and clause_tokens[0] in {"and", "or"}:
                continue
        elif (
            dated
            or index in busy
            or not (_hedge_only(clause_tokens) or _decision_pending(clause_tokens))
        ):
            continue
        target = index - 1
        while target >= 0 and target not in busy:
            target = -1 if clauses[target].strong else target - 1
        if target >= 0:
            found.add(target)
    return found


# Words between "was" and the status it marks: "was on a 2 hour delay", "were all closed".
_PAST_FILLERS = frozenset({"a", "an", "the", "on", "under", "also", "all"})


# What the words before a status say of a change (see _supersedes).
_NO_CHANGE: Final = 0
_CHANGED: Final = 1  # it replaces another: "now closed", "changed to closed"
_CHANGE_DENIED: Final = 2  # it does not: "will not change to a closure"
# The words of a change that a negation before them denies ("has not been changed to"), and
# the words that can sit between ("not yet", "has not been"). "No change: closed" keeps the
# status, so "no" denies nothing here.
_CHANGE_VERBS = frozenset(
    {
        "changed", "change", "changing", "switched", "switching", "converted", "converting",
        "upgraded", "upgrade", "upgrading", "moved", "became", "become", "becomes", "becoming",
        *SUPERSEDING_WITH,
    }
)  # fmt: skip
_CHANGE_AUXILIARIES = frozenset({"be", "been", "being", "have", "has", "had", "yet", "to"})
_CHANGE_NEGATIONS = NEGATIONS - {"no", "none", "neither", "nor", "without"}


def _supersedes(tokens: list[str]) -> int:
    """What the words before a status in its clause say of a change: that it replaces
    another ("now closed", "changed to closed", "became a closure", "turned into an
    e-learning day"), that it does not ("will not change to a closure"), or nothing."""
    for index, token in enumerate(tokens):
        if token in SUPERSEDING:
            pass
        elif token in SUPERSEDING_WITH:
            if index + 1 >= len(tokens) or tokens[index + 1] not in SUPERSEDING_WITH[token]:
                continue
        else:
            continue
        if token in _CHANGE_VERBS:
            before = index - 1
            while before >= 0 and tokens[before] in _CHANGE_AUXILIARIES:
                before -= 1
            if before >= 0 and tokens[before] in _CHANGE_NEGATIONS:
                return _CHANGE_DENIED
        return _CHANGED
    return _NO_CHANGE


def _superseded(tokens: list[str]) -> bool:
    end = len(tokens)
    while end > 0 and len(tokens) - end < _SUPERSEDED_TOKENS and tokens[end - 1] in _PAST_FILLERS:
        end -= 1
    tail = tokens[max(0, end - _SUPERSEDED_TOKENS) : end]
    if any(token in SUPERSEDED for token in tail):
        return True
    joined = " ".join(tokens[-3:])
    return "instead of" in joined or "rather than" in joined


# Deciding mentions ----------------------------------------------------------------------


class _Context:
    """The text being settled and which kinds of qualifier words it contains at all.

    Most listings have no negation, hedge or update words; knowing that up front
    skips those checks. ``bits`` are the kinds of word the text holds (the union
    of :func:`_facts` bits over its words, below :data:`_OWN_BITS`); ``conditional``
    is set per clause. ``noun_starts`` and
    ``noun_ends`` hold the start and end positions, in order, of the words with
    a run of a scope noun in them (see :data:`_NOUN_RUNS`): a noun in a stretch
    of text is made of such runs, so it overlaps one of those words (the text's
    date groups, blanked out here, hold none of them). A stretch that none of
    them overlaps holds no scope noun, and the checks that look for one there
    are skipped: the first word to end after the stretch starts is the only
    one that can overlap it first (a :func:`bisect.bisect_right` on the ends).
    """

    __slots__ = ("bits", "conditional", "noun_ends", "noun_starts", "text", "watched")

    def __init__(self, text: str, bits: int, nouns: tuple[list[int], list[int]]) -> None:
        self.text = text
        self.bits = bits
        self.noun_starts, self.noun_ends = nouns
        self.conditional = False
        # The mentions a watch made notices, each with what it was before and whether its clause
        # names a day (see _read_watched).
        self.watched: list[tuple[Mention, Note | None, bool]] = []


def _read_watched(
    watched: list[tuple[Mention, Note | None, bool]], mentions: list[Mention], notes: set[Note]
) -> None:
    """Read each status a watch made a notice as it was written when a status of its own kind
    stands in the text, neither dropped nor called off, and the watch's clause names no day
    of its own ("Closed tomorrow. Closure watch for Friday" watches Friday: a notice still).
    See :data:`_WATCH_NOUNS`.

    "Closure watch for tomorrow" alone states nothing, and "No delay; closure watch for
    tomorrow" has no status standing; "Closed tomorrow - closure watch" agrees with itself,
    with no doubt: the "hedged" note the notice gave goes with it, unless another status was
    hedged too. A status of another kind beside the watch is left in doubt by it (see
    :func:`_hedged_doubts`).
    """
    read = False
    for mention, before, dated in watched:
        kind = "closed" if mention.kind == "ambiguous" else mention.kind  # ("closing watch")
        if (
            not dated
            and mention.dropped == "hedged"
            and any(
                other is not mention
                and other.kind == kind
                and other.dropped is None
                and not other.revoked
                for other in mentions
            )
        ):
            mention.dropped = before
            read = True
    if read and not any(
        mention.dropped == "hedged" and mention.kind != "note" for mention in mentions
    ):
        notes.discard("hedged")


def _watch_dated(text: str, clause: _Clause, mention: Mention) -> bool:
    """Whether the watch after ``mention`` names a day: one blanked out of its clause, but for
    one past a colon ("Closure watch: closed tomorrow" watches no day of its own)."""
    low = max(clause.start, text.rfind(":", clause.start, mention.start) + 1)
    high = text.find(":", mention.end, clause.end)
    return "  " in text[low : clause.end if high < 0 else high]


def _watched(text: str, mention: Mention) -> bool:
    """Whether a watch's noun follows ``mention``, past a status it is joined to ("Delay or
    closure watch"), as :func:`_notice` reads it."""
    after = words(text, mention.end, min(len(text), mention.end + _WATCH_REACH))
    position = 0
    while position < 2 and position + 1 < len(after) and after[position] in _NOTICE_JOINED:  # noqa: PLR2004 - "or closure"
        position += 1
    return position < len(after) and after[position] in _WATCH_NOUNS


_WATCH_REACH = 32  # (characters after a status that a watch's noun and its joint fit in)


# What a word is, as bits of _word_bits: the kinds of word this module looks for (the low
# bits, below _OWN_BITS), then the mention rules it can trigger, what it can be in a date (see
# dates.word_hints) and what it can start in the weather scans (see weather.word_hints). The
# kinds come first, and fit in 30 bits, so a text's are one small number (``bits &
# _OWN_BITS``), which Python tests fastest; the text's bits test them as they are too.
# (A run's start mask holds the rules' bits apart from the date and weather scans' bits: see
# text.DATE_START_SHIFT.)
assert not RULE_BITS & (DATE_START_BITS | WEATHER_START_BITS)  # noqa: S101 - fields apart
_OWN_FLAGS = 30  # (how many kinds of word there are, below)
_OWN_BITS = (1 << _OWN_FLAGS) - 1
_RULE_SHIFT = _OWN_FLAGS
_DATE_SHIFT = _RULE_SHIFT + RULE_BITS.bit_length()
_WEATHER_SHIFT = _DATE_SHIFT + HINT_BITS.bit_length()
_WEATHER_HINT_BITS = WEATHER_START | CAUSE_START  # (what weather.word_hints can set)
(
    _NEGATION,
    _HEDGE,
    _HEDGE_AFTER,
    _SUPERSEDING,
    _SUPERSEDED,
    _QUALIFYING,  # any word that could change how a lone status is settled
    _OTHER_SCOPE,  # a noun, or part of one, for something other than the school
    _MODIFIER,  # a word that moves a school noun to another scope ("evening classes", "some")
    _DATE_HEDGE,  # "possibly Wednesday"
    _CONDITIONAL,  # "if", "unless", "in case"
    _ANY_SCOPE,  # a noun, or part of one, for anything a status can be about (the school too)
    _MAKE_UP,  # "make", "made", "makeup": a day to be made up
    _ANSWER,  # a run of a word that answers "no" ("Closed: No"): set by _facts
    _NOUN,  # a run of a scope noun ("school" of "after-school"): set by _facts
    _DIGITS,  # a word with a digit in it: set by _facts
    _MARKS,  # a stretch of text that can hold a clause mark: set by _chunk_facts
    _NAME_KIND,  # a run of a word that school names hold (see weather.NAME_KINDS): by _facts
    _STOPS,  # a run of a word that ends a status's words (see _region_end): set by _facts
    _INSTITUTION,  # a run of a noun for an institution (see mentions.INSTITUTION_NOUNS)
    _HEDGE_CLAUSE,  # a word that can make up a hedge after a status ("tentative", "TBD")
    _PART_WORD,  # a run of a word that can bound a closure to part of a day: set by _facts
    _PART_SURE,  # one that surely does ("am", not "as" without "of"): set by _facts
    _NAME_WORD,  # a stretch with a name word, which canonical collapses: set by _chunk_facts
    _NOON,  # a stretch that holds "noon" or "midday", which can be a time: set by _chunk_facts
    _WEEKEND,  # a stretch that holds "saturday" or "sunday": set by _chunk_facts
    _COLON,  # a stretch that holds a colon: set by _chunk_facts
    _POWER,  # a stretch that holds "power" or "blackout" (see _weather_fields): by _chunk_facts
    _DOT_PAIR,  # a stretch with a full stop between two digits ("1.21"): by _chunk_facts
    _CARVE,  # a word of a phrase that limits a status to part of a district (see partial)
    _OPENING,  # a word with "open", "resum", "assess" or _RETURN_HINT in it (see _openings),
    # or a word of a withdrawal (see _withdrawals)
) = (1 << index for index in range(_OWN_FLAGS))
# The kinds of word the precision gate looks for (see classify.gate), and rare words that some
# checks need, above every field of the bits: a text's own kinds stay one small number, and
# these make another (``bits >> _RARE_SHIFT``).
_RARE_SHIFT = _WEATHER_SHIFT + _WEATHER_HINT_BITS.bit_length()
(
    _UNREAD,  # a word no rule of the grammar reads (see classify.gate), but a name word
    _ATTACHED_WORD,  # a word read only beside a status word in its clause (see classify.gate)
    _STATEMENT,  # a word of a statement on a status (see classify.gate.STATEMENT_WORDS)
    _HELD_HINT,  # "on", "day", or a stretch with "?": a statement can hold them (see the gate)
    _CAUSE_OPENER,  # "due", "because", "owing": a cause can follow (see _caused_statuses)
    _POLICY_WORD,  # a word of a rule for statuses to come (see _policies)
    _HEADING_WORD,  # a word of a heading (see _headings)
    _PROMISE_WORD,  # a word of a promise of an update (see _update_promised)
    _COUNTED_NOUN,  # a noun of places a count can come before ("4 schools": see _lone_status)
    _LEADING_WORD,  # a word a time before the closure can follow (see dayparts.closure_bounds)
    _COUNT_WORD,  # a count in words ("two", "three"): see _COUNTED
    _WITHDRAWAL_TEXT,  # a stretch that holds a word every withdrawal holds (see _text_bits)
    _YEAR_TEXT,  # a stretch that holds "19" or "20", as a year does (see year_alone)
    _ONLY_TEXT,  # a stretch that holds "only" or "just" (see _only_days)
    _BAD_ORDINAL,  # a day number whose ordinal ending disagrees with it ("2rd": see _word_bits)
    _PLACEHOLDER_WORD,  # a word that holds a place for a value to come ("TBD", "N/A")
    _PREFIXED_TEXT,  # a stretch with a prefix that unmakes a status ("non-", "post-": see there)
    _OR_WORD,  # "or", "and/or": one day or another (see _without_alternative_days)
    _TO_WORD,  # "to", "into": a status changed to another (see _unordered_changes)
    _ZERO_TEXT,  # a stretch that holds "0:00", as a zero time does (see _answers)
    _SLASH_N_TEXT,  # a stretch that holds "/n", as "yes/no" and "y/n" do (see _answers)
    _CORRECTION_TEXT,  # a stretch with a word of a correction of a day (see _corrected)
    _OPTION_TEXT,  # a stretch with a word of an option to some students (see _OPTION_HINT)
    _CONTINUE_TEXT,  # a stretch with "remain" or "stay" (see _continued_closures)
    _REPORT_TEXT,  # a stretch with "report" (see _report_notice)
) = (1 << (_RARE_SHIFT + index) for index in range(25))
# The same bits as the text's ``bits >> _RARE_SHIFT`` holds them: one small number, which
# Python tests fastest (as the text's own kinds, below _OWN_BITS).
_UNREAD_RARE = (_UNREAD | _ATTACHED_WORD) >> _RARE_SHIFT
_STATEMENT_RARE = _STATEMENT >> _RARE_SHIFT
_HELD_RARE = _HELD_HINT >> _RARE_SHIFT
_CAUSE_RARE = _CAUSE_OPENER >> _RARE_SHIFT
_POLICY_RARE = _POLICY_WORD >> _RARE_SHIFT
_HEADING_RARE = _HEADING_WORD >> _RARE_SHIFT
_PROMISE_RARE = _PROMISE_WORD >> _RARE_SHIFT
_COUNTED_RARE = _COUNTED_NOUN >> _RARE_SHIFT
_LEADING_RARE = _LEADING_WORD >> _RARE_SHIFT
_COUNT_WORD_RARE = _COUNT_WORD >> _RARE_SHIFT
_WITHDRAWAL_RARE = _WITHDRAWAL_TEXT >> _RARE_SHIFT
_YEAR_RARE = _YEAR_TEXT >> _RARE_SHIFT
_ONLY_RARE = _ONLY_TEXT >> _RARE_SHIFT
_BAD_ORDINAL_RARE = _BAD_ORDINAL >> _RARE_SHIFT
_PLACEHOLDER_RARE = _PLACEHOLDER_WORD >> _RARE_SHIFT
_MISREAD_RARE = _BAD_ORDINAL_RARE | _PLACEHOLDER_RARE
_PREFIXED_RARE = _PREFIXED_TEXT >> _RARE_SHIFT
_OR_RARE = _OR_WORD >> _RARE_SHIFT
_TO_RARE = _TO_WORD >> _RARE_SHIFT
_ZERO_RARE = _ZERO_TEXT >> _RARE_SHIFT
# The bits of the words the steps after a text's statuses are made look for, besides the
# statuses, days and notes (see _analyse_normalized): an opening's, "or", "only" or "just".
_LATE_STEP_BITS = _OPENING | _OR_WORD | _ONLY_TEXT
# (An answer left open, "yes/no", "y/n" or "yes or no", holds "/n" in a stretch or the word "or".)
_EITHER_RARE = _OR_RARE | _SLASH_N_TEXT >> _RARE_SHIFT
_CORRECTION_RARE = _CORRECTION_TEXT >> _RARE_SHIFT
_OPTION_RARE = _OPTION_TEXT >> _RARE_SHIFT
_CONTINUE_RARE = _CONTINUE_TEXT >> _RARE_SHIFT
_REPORT_RARE = _REPORT_TEXT >> _RARE_SHIFT
# The rare bits of what can stop a text's statuses past a day said again (see _later_stop).
_LATE_GATE_RARE = (_UNREAD | _ATTACHED_WORD | _CORRECTION_TEXT) >> _RARE_SHIFT
_SETTLE_RARE = _CAUSE_RARE | _POLICY_RARE | _HEADING_RARE | _COUNT_WORD_RARE | _PROMISE_RARE
# (And a noun of places, which a count in figures can come before: see _analyse_normalized.)
_MID_RARE = _SETTLE_RARE | _COUNTED_RARE
# The stretches that can hold a word no rule reads: one of _UNREAD, a name word, which a noun
# after it may make a name, or a word read only beside a status word (see classify.gate).
_UNREAD_BITS = _UNREAD | _NAME_WORD | _ATTACHED_WORD
# The stretches the precision gate looks at a text for (at the end of _analyse_normalized): a
# word no rule reads, a statement's words, and the words of a phrase that says the school is
# open (see mentions._open: "open", "on time", "regular schedule", "as scheduled", "in
# session"). A stretch of _HELD_HINT counts only with the words it hints at.
_GATE_BITS = _UNREAD_BITS | _STATEMENT | _OPENING
_ANY_GATE_BITS = _GATE_BITS | _HELD_HINT
# (_ANY_GATE_BITS as the text's own kinds hold them, and as its rare bits do.)
_ANY_GATE_OWN = _ANY_GATE_BITS & _OWN_BITS
_ANY_GATE_RARE = _ANY_GATE_BITS >> _RARE_SHIFT
_ANY_GATE_TEXT = _ANY_GATE_OWN | _ANY_GATE_RARE << _RARE_SHIFT
# "school is on", "is a school day", "full day of school", "we will have school", "there will be
# school"
_HELD_HINT_WORDS = frozenset({"on", "day", "have", "there"})
# The verbs that say the school runs, said of the school or its classes: "school will run
# Friday", "classes operating as normal" (see _bare_statement).
_HELD_VERBS = frozenset({"run", "runs", "running", "operate", "operates", "operating"})
_HELD_SUBJECTS = frozenset({"school", "schools", "class", "classes", "students"})
# Words that say a post no longer holds, in a sentence of its own ("This notice is outdated"):
# unread anywhere else, as they are no name's (see classify.gate), but read by _bare_statement.
_STALE_SIGNS = frozenset({"outdated", "obsolete"})
# The words of a statement that school is held or open, not that a status holds ("as planned").
_SAID_HELD = _HELD_SUBJECTS | {"open", "held", "session"}
_CAUSE_OPENING_WORDS = frozenset({"due", "because", "owing"})
# The words that hold a place for a day to come (see _PLACEHOLDER_PATTERN).
_PLACEHOLDER_WORDS = frozenset(
    {"tbd", "tba", "tbc", "n/a", "announced", "determined", "decided", "confirmed"}
)
# A day held by a placeholder: "Closed (date TBD)", "Closure date: TBD", "Closed on N/A",
# "Closed - date to be announced" (not a day to be made up: "make up day TBD").
_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!make up )(?<!makeup )(?<!make-up )(?<!make up)(?<!makeup)(?<!make-up)"  # (a day made up)
    r"\b(?:dates?|days?)\s*:?\s*(?:tbd|tba|tbc|n/a|(?:is\s+)?(?:still\s+)?to\s+be\s+(?:announced"
    r"|determined|decided|confirmed))\b|\b(?:on|for|until|through|thru)\s*:?\s*(?:tbd|tba|tbc|n/a)\b",
    re.ASCII,
)


# The rare bits a misread day, a day still to come or a year alone needs (see _misread_day).
_MISREAD_OR_YEAR_RARE = _MISREAD_RARE | _YEAR_RARE


def _misread_day(
    text: str, mentions: list[Mention], groups: tuple[DateGroup, ...], flags: int, rare: int
) -> bool:
    """Whether a text with a status names a day it cannot be read for: "Closed the 2rd", a day
    number misread; "Closed (date TBD)", a day still to come (see _placeholder_day); or "closed
    in 2019", a year alone, which the date patterns read only inside a date. (With no status,
    as _without_mentions reads such a text, none counts. Every year year_alone reads starts
    with "19" or "20": see _text_bits.)"""
    if rare & _MISREAD_RARE and (rare & _BAD_ORDINAL_RARE or _placeholder_day(text, mentions)):
        return True
    return bool(flags & _DIGITS and rare & _YEAR_RARE and year_alone(text, groups))


def _placeholder_day(text: str, mentions: list[Mention]) -> bool:
    """Whether a day held by a placeholder (see :data:`_PLACEHOLDER_PATTERN`) is in a sentence with
    a status: "Closed (date TBD)", "Closure date: TBD"; not an event's in a sentence of its own
    ("Closed today. Graduation date TBD.", "... Reopening date TBD.")."""
    for found in _PLACEHOLDER_FINDER(text):
        low = max([text.rfind(mark, 0, found.start()) for mark in _POLICY_MARKS]) + 1
        ended = _SENTENCE_END.search(text, found.end())
        high = len(text) if ended is None else ended.start()
        for mention in mentions:
            if low <= mention.start < high and mention.kind in _PLACEHOLDER_KINDS:
                return True
    return False


_PLACEHOLDER_FINDER = _PLACEHOLDER_PATTERN.finditer
_PLACEHOLDER_KINDS = frozenset({"closed", "delayed", "remote", "early_dismissal", "ambiguous"})
# The words that can drop a status or mark it as replaced (see _qualify and _dropped).
_QUALIFIERS = (
    _NEGATION | _HEDGE | _HEDGE_AFTER | _SUPERSEDING | _SUPERSEDED | _MAKE_UP | _ANSWER
    | _CONDITIONAL | _HEDGE_CLAUSE
)  # fmt: skip


# The words of a rule for statuses to come (see _policies), of a heading (see _headings) and of
# a promise of an update (see _update_promised): a text with none of them has none.
_POLICY_WORDS = ("any", "next", "future", "every", "each", "days", "closures", "closings",
                 "delays", "starts", "dismissals", "releases", "means", "mean")  # fmt: skip
_HEADING_WORDS = (
    "closures", "closings", "delays", "cancellations", "cancelations", "dismissals",
    "following", "procedures", "procedure", "information", "info", "packets", "packet",
    "guidelines", "policy", "policies", "faq", "faqs", "resources", "guide", "reminders",
    "tips", "options", "expectations", "instructions", "plans", "click",
)  # fmt: skip
_PROMISE_WORDS = ("tuned", "back", "update", "updates", "updated", "advise", "notify", "know",
                  "more")  # fmt: skip
_COUNTED_NOUNS = ("schools", "campuses", "buildings", "sites", "locations")
_LEADING_WORDS = ("before", "until", "till", "til", "after", "from")
# The words that join two days as alternatives, and that join a status to what it changed to.
_OR_WORDS = ("or", "and/or", "or/and")
_TO_WORDS = ("to", "into", "for", "with", "favor", "favour")
_RARE_WORDS: dict[str, int] = {
    word: (_POLICY_WORD if word in _POLICY_WORDS else 0)
    | (_HEADING_WORD if word in _HEADING_WORDS else 0)
    | (_PROMISE_WORD if word in _PROMISE_WORDS else 0)
    | (_COUNTED_NOUN if word in _COUNTED_NOUNS else 0)
    | (_LEADING_WORD if word in _LEADING_WORDS else 0)
    | (_COUNT_WORD if word in _COUNT_WORDS else 0)
    | (_OR_WORD if word in _OR_WORDS else 0)
    | (_TO_WORD if word in _TO_WORDS else 0)
    for word in (
        *_POLICY_WORDS, *_HEADING_WORDS, *_PROMISE_WORDS, *_COUNTED_NOUNS, *_LEADING_WORDS,
        *_COUNT_WORDS, *_OR_WORDS, *_TO_WORDS,
    )
}  # fmt: skip
# The words that can make a clause conditional (see _conditional), and those that can make
# up a hedge after a status (see _hedge_only).
_CONDITION_WORDS = CONDITIONALS | CONDITION_OPENERS | {"case", "when", "long"}
_HEDGE_CLAUSE_TRIGGERS = (
    HEDGE_CLAUSE_WORDS | UNSETTLED_AFTER | _TO_BE_SETTLED | _DECISIONS | _PENDING_CHECKS | _PLANS
)
# The nouns "under" makes a hedge of right after a status: "closure under review".
_UNDER_HEDGES = frozenset({"review", "consideration", "evaluation", "discussion"})


def _gate_flags(word: str) -> int:
    """The kinds of word the precision gate looks for that one word is (see classify.gate):
    a word no rule reads (_UNREAD), read only beside a status word, of a statement, a hint
    of a statement, or a word that opens a cause."""
    gate_bits = word_class(word)
    flags = 0 if gate_bits else _UNREAD
    if gate_bits & ATTACHED:
        flags |= _ATTACHED_WORD
    if gate_bits & STATEMENT:
        flags |= _STATEMENT
    if word in STALE_LABELS:
        flags |= _UNREAD  # ("Previous: closed tomorrow": the gate reads the label)
    if word in _HELD_HINT_WORDS:
        flags |= _HELD_HINT
    elif word in _HELD_VERBS or word in _STALE_SIGNS:
        # ("School will run Friday", "This notice is outdated": see _bare_statement)
        flags |= _STATEMENT
    if word in _CAUSE_OPENING_WORDS:
        flags |= _CAUSE_OPENER
    if word in _PLACEHOLDER_WORDS:
        flags |= _PLACEHOLDER_WORD
    if word in _RARE_WORDS:
        flags |= _RARE_WORDS[word]
    return flags


@lru_cache(maxsize=65536)
def _word_bits(word: str) -> int:
    """Everything the parser needs to know about one word, as bits (cached per word).

    The union over a text's words says which scans and checks can find anything.
    """
    # (The hint functions' own caches are passed by: this one keeps the word.)
    bits = (
        _rule_mask(word) << _RULE_SHIFT
        | _date_hints(word) << _DATE_SHIFT
        | _weather_hints(word) << _WEATHER_SHIFT
        | _WORD_LIST_BITS.get(word, 0)
    )
    if (
        "open" in word
        or "resum" in word
        or "assess" in word
        or _RETURN_HINT(word) is not None
        or word in _WITHDRAWAL_WORDS
    ):
        bits |= _OPENING  # ("reopen", "re-open", "resumes", "reassessing", "return", "back")
    bits |= _gate_flags(word)
    if word[-2:] in _ORDINAL_ENDINGS and word[:1].isdigit() and not _ordinal_agrees(word):
        bits |= _BAD_ORDINAL  # "the 2rd", "the 3th": no day anyone can trust
    if "-" in word or "/" in word:
        # A scope noun joined to a status by a hyphen is still read ("offices-closed"). A part
        # after the first can start a date, or a day the patterns do not read, as a word after
        # a space can: "closed-2 days", "closed-several days". (normalize spaces out the mark
        # beside a day's name or a date: "closed-wednesday" is "closed - wednesday". The first
        # part is the word's own start, which date_hints reads.)
        # (A word's parts are runs of letters and digits: none is empty. See text.WORD.)
        first, *parts = _WORD_JOINS.split(word)
        bits |= _WORD_LIST_BITS.get(first, 0) & _PART_SCOPE_BITS
        for part in parts:
            bits |= (
                _WORD_LIST_BITS.get(part, 0) & _PART_SCOPE_BITS | _date_hints(part) << _DATE_SHIFT
            )
    return bits


_ORDINAL_ENDINGS = frozenset({"st", "nd", "rd", "th"})


def _ordinal_agrees(word: str) -> bool:
    """Whether a number with an ordinal ending has the ending its number takes ("1st", "2nd",
    "3rd", "4th", "11th", "22nd"); a word that is not such a number agrees."""
    number = word[:-2]
    if not number.isdigit() or len(number) > 2:  # noqa: PLR2004 - a day number
        return True
    value = int(number)
    if 11 <= value % 100 <= 13:  # noqa: PLR2004 - "11th", "12th", "13th"
        return word.endswith("th")
    return word.endswith({1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th"))


# The marks that join the parts of a word, and the scope bits a part lends its word.
_WORD_JOINS = re.compile(r"[/-]", re.ASCII)
_PART_SCOPE_BITS = _ANY_SCOPE | _OTHER_SCOPE | _MODIFIER
_rule_mask = rule_mask.__wrapped__
_date_hints = date_hints.__wrapped__
_weather_hints = weather_hints.__wrapped__
_start_mask = start_mask.__wrapped__
_date_start_hint = date_start_hint.__wrapped__
_weather_start_hint = weather_start_hint.__wrapped__
# The bits of _word_bits that the hint functions set: a word with none of them is read by no
# rule, date scan or weather scan (see _role_free).
_HINTED = RULE_BITS << _RULE_SHIFT | HINT_BITS << _DATE_SHIFT | _WEATHER_HINT_BITS << _WEATHER_SHIFT


def _word_list_bits(word: str) -> int:
    """The bits of :func:`_word_bits` a word has by the word lists that hold it."""
    return (
        (_NEGATION if word in NEGATIONS else 0)
        | (_HEDGE if word in HEDGES else 0)
        | (
            _HEDGE_AFTER
            if word in HEDGES_AFTER
            or word in _UNDER_HEDGES
            or word in _POSSIBILITIES
            or word in _NOTICE_NOUNS
            or word in _TO_BE_SETTLED
            else 0
        )
        | (_SUPERSEDING if word in SUPERSEDING or word in SUPERSEDING_WITH else 0)
        | (_SUPERSEDED if word in SUPERSEDED or word in {"instead", "rather"} else 0)
        | (_QUALIFYING if word in _QUALIFYING_WORDS else 0)
        | (_OTHER_SCOPE if word in _SCOPE_WORDS and word not in _SCHOOL_WORDS else 0)
        | (_MODIFIER if word in MODIFIERS or word in _SOME_OF else 0)
        | (_DATE_HEDGE if word in _DATE_HEDGES or word in _DAY_HEDGE_WORDS else 0)
        | (_CONDITIONAL if word in _CONDITION_WORDS else 0)
        | (_HEDGE_CLAUSE if word in _HEDGE_CLAUSE_TRIGGERS else 0)
        | (_ANY_SCOPE if word in _SCOPE_WORDS else 0)
        | (_MAKE_UP if word in MAKE_UP_WORDS else 0)
        | (_CARVE if word in CARVE_WORDS else 0)
    )


def _run_list_bits(run: str) -> int:
    """The bits of :func:`_facts` a run of letters and digits has by the lists that hold it."""
    return (
        (_ANSWER if run in _ANSWER_RUNS else 0)
        | (_NOUN if run in _NOUN_RUNS else 0)
        | (_NAME_KIND if run in NAME_KINDS else 0)
        | (_STOPS if run in REGION_STOPS else 0)
        | (_INSTITUTION if run in INSTITUTION_NOUNS else 0)
        | ((_PART_WORD if run == "as" else _PART_WORD | _PART_SURE) if run in _PART_RUNS else 0)
    )


_RUN_MARKS = re.compile(r"['/-]", re.ASCII)
# The runs of letters and digits that scope nouns are made of ("k-12" is "k" and "12").
_NOUN_RUNS = frozenset(run for word in _SCOPE_WORDS for run in _RUN_MARKS.split(word))
# The runs of the words that answer a field "no" ("Closed: No", "Delay: N/A"): see _dropped.
_ANSWER_RUNS = frozenset({"no", "none", "n", "na", "false", "nope", "0", "00"})
_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


@lru_cache(maxsize=65536)
def _facts(token: str) -> tuple[int, tuple[tuple[int, int], ...]]:
    """What one word is to the parser: its :func:`_word_bits`, and where scans start in it.

    A word is one or more runs of letters and digits ("two-hour", "1/21"); a scan
    can only start where a run starts, and only at a run that begins the way one
    of its patterns does. Each such run is given as its offset in the word and
    its start mask: the status phrases (see :func:`mentions.start_mask`), dates
    (:func:`dates.start_hint`) and weather terms (:func:`weather.start_hint`) that
    can start there. Cached per word: listings reuse a small vocabulary.
    """
    if _plain_name(token):
        return _NO_FACTS
    found: list[tuple[int, int]] = []
    offset = 0
    bits = _word_bits(token)
    for run in _RUN_MARKS.split(token) if not token.isalnum() else (token,):
        mask = _start_mask(run) | _date_start_hint(run) | _weather_start_hint(run)
        if mask:
            found.append((offset, mask))
        bits |= _RUN_LIST_BITS.get(run, 0)
        offset += len(run) + 1
    if not token.isalpha() and _DIGIT.search(token) is not None:
        bits |= _DIGITS
    return bits, tuple(found)


type _Runs = tuple[tuple[int, int], ...]
_NO_FACTS: tuple[int, _Runs] = (0, ())  # (the facts of a word nothing reads: see _plain_name)
type _Marks = tuple[int, ...]
# What only some stretches between spaces hold (see _chunk_facts): where its words with a
# scope noun's run start and where they end, its clause marks, the stretch itself when it
# holds a word of _NOTED (``None`` otherwise), and what fewer still hold (``None`` for none):
# where its runs that end a status's words start and how long they are, how many month names
# it holds, and where the status phrases and the date scan start in it when not only at its
# start (see _ChunkFacts).
type _Pairs = tuple[tuple[int, int], ...]
type _Rarer = tuple[_Pairs, int, _Runs, _Runs]
type _Rare = tuple[_Pairs, tuple[_Marks, int] | None, str | None, _Rarer | None]
# What a stretch between spaces is: its bits, its width with the space after it, where the
# status phrases, the date scan and the weather scan can start in it, and what is rare. A
# stretch where the status phrases can start only at its start, as most do ("closed"), has
# that run's mask in place of its runs, and no runs in what is rare; so does one where the
# date scan can start only at its start. (0: none can start there, or the runs are rare.)
# Then the stretch itself: a normalized text is its stretches' facts joined (see
# _read_stretches).
type _ChunkFacts = tuple[int, int, int, int, _Runs, _Rare | None, str]
_MOST_CHUNKS = 65536
# The shapes of a stretch between spaces that can make a clause mark with the space before
# it (see _clauses): dashes alone (" - "), "but" (" but ") or "however" (" however").
_DASHES, _BUT, _HOWEVER = 1, 2, 3
_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _chunk_facts(chunk: str) -> _ChunkFacts:  # noqa: PLR0912, PLR0915 - one pass over its words
    """What a stretch of text between two spaces is to the parser.

    The union of :func:`_facts` bits over its words; its length with the space
    after it; where each scan can start in it (the status phrases, the date
    scan and the weather scan, each run with its start mask, see
    :func:`_facts`); and, for a stretch that holds any of them or a word of
    :data:`_NOTED` (``None`` otherwise): where each word that holds a scope
    noun's run starts and ends;
    where each run that ends a status's words starts, and its length
    (:data:`~snowlight.classify.lexicon.REGION_STOPS`, see
    :func:`_region_end`); how many of its words are month names (see
    :func:`~snowlight.classify.dates.find_unreadable`); and its clause marks
    (see :func:`_clauses_at`). Offsets are from the stretch's start. A
    normalized text is such stretches joined by single spaces ("monday,",
    "1/21", "snow;"), and listings reuse them as they reuse words, so the facts
    are kept per stretch (see :class:`_ChunkTable`).
    """
    if chunk.isalnum() and chunk.isascii():
        return _word_chunk_facts(chunk)
    core = _word_before_marks(chunk)
    if core is not None:
        return _marked_word_facts(chunk, core)
    bits = 0
    dated: list[tuple[int, int]] = []
    phrased: list[tuple[int, int]] = []
    weathered: list[tuple[int, int]] = []
    nouns: list[tuple[int, int]] = []
    stops: list[tuple[int, int]] = []
    months = 0
    named = False  # a word of it is a name word, as _role reads it (see _chunk_roles)
    for match in _WORD.finditer(chunk):
        token = match.group()
        start = match.start()
        found = _facts(token)
        token_bits, token_runs = found
        if found is _NO_FACTS:
            token_bits = _gate_flags(token)
            named = named or bool(token_bits & _UNREAD)
        elif not named and token_bits & _UNREAD and _role_free(token):
            named = True  # (as _role reads it: see _chunk_roles)
        bits |= token_bits
        for offset, mask in token_runs:
            run = (start + offset, mask)
            if mask & RULE_BITS:
                # (The status phrases read only the rule bits: a small number is quicker.)
                phrased.append((start + offset, mask & RULE_BITS))
            if mask & DATE_START_BITS:
                dated.append(run)
            if mask & WEATHER_START_BITS:
                weathered.append(run)
        if token_bits & _NOUN:
            nouns.append((start, start + len(token)))
        if token_bits & _STOPS:
            offset = start
            for part in _RUN_MARKS.split(token):
                if part in REGION_STOPS:
                    stops.append((offset, len(part)))
                offset += len(part) + 1
        months += token in MONTH_NAMES
        if "-" in token or "/" in token:
            # A month name after a mark is a month name as much ("mid-jan"): see _word_bits.
            months += sum([part in MONTH_NAMES for part in _WORD_JOINS.split(token)[1:]])
    marks = _clause_marks(chunk)
    if marks is not None:
        bits |= _MARKS
    if named:
        bits |= _NAME_WORD
    bits |= _text_bits(chunk)
    phrase_mask, more_phrased = _at_start(phrased)
    date_mask, more_dated = _at_start(dated)
    rarer: _Rarer | None = None
    if stops or months or more_phrased or more_dated:
        rarer = (tuple(stops), months, more_phrased, more_dated)
    rare: _Rare | None = None
    if nouns or marks is not None or bits & _NOTED or rarer is not None:
        rare = (tuple(nouns), marks, chunk if bits & _NOTED else None, rarer)
    return bits, len(chunk) + 1, phrase_mask, date_mask, tuple(weathered), rare, chunk


def _at_start(runs: list[tuple[int, int]]) -> tuple[int, _Runs]:
    """The mask of a stretch's one run, when it is the only one and at its start (0 and the
    runs otherwise: see _ChunkFacts)."""
    if len(runs) == 1 and runs[0][0] == 0:
        return runs[0][1], ()
    return 0, tuple(runs)


# The marks a stretch can end with after its one word ("closed,", "morning:", "today."): any
# character that no word holds (an apostrophe, a slash or a hyphen joins a word only to one
# more run of letters and digits, which cannot follow).
_WORDLESS = "".join(chr(code) for code in range(33, 127) if not chr(code).isalnum())


def _word_before_marks(chunk: str) -> str | None:
    """The word of a stretch that is one word of letters and digits and then marks, or ``None``."""
    core = chunk.rstrip(_WORDLESS)
    if core is chunk or not core or not core.isalnum() or not core.isascii():
        return None
    return core


def _marked_word_facts(chunk: str, core: str) -> _ChunkFacts:
    """:func:`_chunk_facts` of a stretch that is one word and marks after it ("closed,").

    The word is read as the stretch of that word alone reads it; the stretch adds
    its marks, its width, and itself as the stretch with a word of :data:`_NOTED`.
    """
    bits, _width, phrased, dated, weathered, rare, _core = _chunk_lookup(core)
    marks = _clause_marks(chunk)
    # (The word's own marks are its shape alone: "but" before a space. The stretch has its own.)
    bits = bits | _MARKS if marks is not None else bits & ~_MARKS
    # (The word's own text bits are the stretch's, but for the marks: see _text_bits.)
    if ":" in chunk:
        bits |= _COLON  # (a full stop between two digits is not among its marks)
    if "?" in chunk:
        bits |= _HELD_HINT  # ("closed tomorrow?": see _text_bits)
    if rare is not None:
        nouns, _marks, noted, rarer = rare
        rare = (
            (nouns, marks, None if noted is None else chunk, rarer)
            if nouns or marks is not None or noted is not None or rarer is not None
            else None
        )
    elif marks is not None:
        rare = ((), marks, None, None)
    return bits, len(chunk) + 1, phrased, dated, weathered, rare, chunk


def _word_chunk_facts(chunk: str) -> _ChunkFacts:
    """:func:`_chunk_facts` of a stretch that is one word of letters and digits, the most common.

    The word is the stretch, one run, with no mark: the same facts, read directly.
    """
    found = _facts(chunk)
    if found is _NO_FACTS:
        # A word nothing reads, such as a name (see _plain_name): a name word. (The precision
        # gate reads some: "families", "dorm", "BPS".)
        flags = _gate_flags(chunk)
        bits = (_NAME_WORD if flags & _UNREAD else flags) | _text_bits(chunk)
        return bits, len(chunk) + 1, 0, 0, (), None, chunk
    bits, runs = found
    # (One word of letters and digits is one run: where a scan can start, it starts at 0.)
    mask = runs[0][1] if runs else 0
    weathered = runs if mask & WEATHER_START_BITS else ()
    nouns = ((0, len(chunk)),) if bits & _NOUN else ()
    stops = ((0, len(chunk)),) if bits & _STOPS else ()
    months = 1 if chunk in MONTH_NAMES else 0
    mark_shape = _BUT if chunk == "but" else _HOWEVER if chunk == "however" else 0
    if mark_shape:
        bits |= _MARKS
    if bits & _UNREAD and _role_free(chunk):
        bits |= _NAME_WORD  # (as _role reads it: see _chunk_roles)
    bits |= _text_bits(chunk)
    rare: _Rare | None = None
    if nouns or stops or months or mark_shape or bits & _NOTED:
        marks = ((), mark_shape) if mark_shape else None
        rarer = (stops, months, (), ()) if stops or months else None
        rare = (nouns, marks, chunk if bits & _NOTED else None, rarer)
    dated = mask if mask & DATE_START_BITS else 0
    return bits, len(chunk) + 1, mask & RULE_BITS, dated, weathered, rare, chunk


def _text_bits(chunk: str) -> int:
    """The bits a stretch has for what the text holds: "noon", "saturday", a colon, "power", a
    full stop between two digits, a word of a withdrawal, "19" or "20", "only" or "just".

    (So a text's bits say whether the text holds them, with no search of the text: none of
    these holds a space, so a text holds one only within one of its stretches.)
    """
    if chunk.isalpha():
        # A stretch of letters alone (most of those first seen are names) holds no mark and
        # no digit: one search for the words first.
        if _TEXT_WORD(chunk) is None:
            return 0
        return (
            (_NOON if "noon" in chunk or "midday" in chunk else 0)
            | (_WEEKEND if "saturday" in chunk or "sunday" in chunk else 0)
            | (_POWER if "power" in chunk or "blackout" in chunk else 0)
            | (_WITHDRAWAL_TEXT if _WITHDRAWAL_PART(chunk) is not None else 0)
            | (_ONLY_TEXT if "only" in chunk or "just" in chunk else 0)
            | (_CORRECTION_TEXT if _CORRECTION_PART(chunk) is not None else 0)
            | (_OPTION_TEXT if _OPTION_PART(chunk) is not None else 0)
            | (_CONTINUE_TEXT if "remain" in chunk or "stay" in chunk else 0)
            | (_REPORT_TEXT if "report" in chunk else 0)
        )
    return (
        (_NOON if "noon" in chunk or "midday" in chunk else 0)
        | (_WEEKEND if "saturday" in chunk or "sunday" in chunk else 0)
        | (_COLON if ":" in chunk else 0)
        | (_POWER if "power" in chunk or "blackout" in chunk else 0)
        | (_DOT_PAIR if "." in chunk and dot_pair(chunk) else 0)
        | (_HELD_HINT if "?" in chunk else 0)
        | (_WITHDRAWAL_TEXT if _WITHDRAWAL_PART(chunk) is not None else 0)
        | (_YEAR_TEXT if "20" in chunk or "19" in chunk else 0)
        | (_ONLY_TEXT if "only" in chunk or "just" in chunk else 0)
        | (_PREFIXED_TEXT if "-" in chunk and _STATUS_PREFIX(chunk) is not None else 0)
        | (_ZERO_TEXT if "0:00" in chunk else 0)
        | (_SLASH_N_TEXT if "/n" in chunk else 0)
        | (_CORRECTION_TEXT if _CORRECTION_PART(chunk) is not None else 0)
        | (_OPTION_TEXT if _OPTION_PART(chunk) is not None else 0)
        | (_CONTINUE_TEXT if "remain" in chunk or "stay" in chunk else 0)
        | (_REPORT_TEXT if "report" in chunk else 0)
    )


# The words of a correction of a status's day or time (see _corrected): none holds a space.
_CORRECTION_PART_WORDS = (
    "correct|make|should|moved|reschedul|instead|typo|meant|change|oops|errat|revis|updated"
    "|shifted|pushed|postpon|\\bnow\\b"
)
_CORRECTION_PART = re.compile(_CORRECTION_PART_WORDS, re.ASCII).search


# A prefix joined to a status word that makes it no statement of the status: "Non-closed",
# "Post-closure update" (see _prefixed_statuses). None holds a space, so a text holds one only
# within a stretch.
_STATUS_PREFIXES = ("non-", "post-", "pre-", "anti-")
_STATUS_PREFIX = re.compile(r"(?:non|post|pre|anti)-", re.ASCII).search
# A word that every withdrawal _WITHDRAWAL_CUES finds holds ("mistakenly" and "untrue" hold
# "mistake" and "true"); none holds a space, so a text holds one only within a stretch.
_WITHDRAWAL_PART_WORDS = (
    "disregard|ignore|removed|error|mistake|false|fake|true|incorrect|wrong|rescinded|withdrawn"
    "|retracted|revoked"
)
_WITHDRAWAL_PART = re.compile(_WITHDRAWAL_PART_WORDS, re.ASCII).search
# Any word a stretch of letters alone can hold for _text_bits (a quick look before each).
# The words of an option to some students (see _OPTION_HINT): none holds a space.
_OPTION_PART_WORDS = "opt|unable|cannot|quarantin|isolat|choose|who"
_OPTION_PART = re.compile(_OPTION_PART_WORDS, re.ASCII).search
_TEXT_WORD = re.compile(
    "noon|midday|saturday|sunday|power|blackout|only|just|remain|stay|report|"
    f"{_WITHDRAWAL_PART_WORDS}|{_CORRECTION_PART_WORDS}|{_OPTION_PART_WORDS}",
    re.ASCII,
).search


def _clause_marks(chunk: str) -> tuple[_Marks, int] | None:
    """The clause marks a stretch between spaces holds (see :data:`_SEPARATOR`), if any.

    Where each mark it holds alone is (a comma, a semicolon, a bar, "!" or "?",
    and a full stop that ends it), and the shape that makes a mark with the
    space before it (``_DASHES``, ``_BUT`` or ``_HOWEVER``; 0 for none).
    """
    found = (
        ()
        if _MARK_CHARS.isdisjoint(chunk)
        else tuple([mark.start() for mark in _CLAUSE_MARK(chunk)])
    )
    shape = 0
    if chunk and not chunk.strip("-"):
        shape = _DASHES
    elif chunk == "but":
        shape = _BUT
    elif chunk.startswith("however") and (len(chunk) == 7 or chunk[7] not in _WORD_CHARS):  # noqa: PLR2004
        shape = _HOWEVER
    return (found, shape) if found or shape else None


_MARK_CHARS = frozenset(",;|!?.")
# Each clause mark a stretch holds alone: a comma, a semicolon, a bar, "!" or "?", and a full
# stop that ends the stretch.
_CLAUSE_MARK = re.compile(r"[,;|!?]|\.\Z").finditer
type _Separators = list[tuple[int, int, tuple[_Marks, int]]]


def _clauses_at(  # noqa: PLR0912 - one pass over the marks, with a gate on each
    text: str, protected: list[tuple[int, int]], separators: _Separators
) -> list[_Clause]:
    """:func:`_clauses` of ``text``, from the clause marks of its stretches between spaces.

    ``separators`` holds, in order, each stretch with a mark: where it starts,
    how long it is, and its :func:`_clause_marks`. The marks are the ones
    :data:`_SEPARATOR` finds, in the same order: a spaced dash, " but " and
    " however" take the space before the stretch (the one that opens the text
    takes none, and needs a space after it), " but " takes the space after it
    too, and a mark that needs a space before it cannot use one that " but "
    took.
    """
    size = len(text)
    taken = 0  # where the last mark ended: no mark starts before it
    clauses: list[_Clause] = []
    start = 0
    strong = True
    # The marks come in order, so one sweep finds those inside a date group or a mention (see
    # _blocked): ``reach`` is the furthest end of the spans that start before the mark ends.
    protected.sort()
    count = len(protected)
    guard = 0
    reach = -1
    for position, length, (marks, shape) in separators:
        if shape:
            low = high = -1
            if shape == _DASHES:
                if position:
                    if position - 1 >= taken:
                        low, high = position - 1, position + length
                elif length < size:
                    low, high = 0, length  # an opening dash: "- Closed today"
            elif shape == _BUT:
                if position and position + length < size and position - 1 >= taken:
                    low, high = position - 1, position + length + 1
            elif position and position - 1 >= taken:  # (" however")
                low, high = position - 1, position + 7
            if low >= 0:
                taken = high
                while guard < count and protected[guard][0] < high:
                    if protected[guard][1] > reach:  # noqa: PLR1730 - (max costs more)
                        reach = protected[guard][1]
                    guard += 1
                if reach <= low:  # (else inside a date group or a mention)
                    # A stretch with more than a space in it (a normalized text has no two
                    # in a row).
                    if low - start > 1 or (low > start and text[start] != " "):
                        clauses.append(_clause((start, low, strong)))
                        strong = False
                    start = high
        for offset in marks:
            low = position + offset
            high = taken = low + 1
            while guard < count and protected[guard][0] < high:
                if protected[guard][1] > reach:  # noqa: PLR1730 - (max costs more, per mark)
                    reach = protected[guard][1]
                guard += 1
            if reach <= low:
                if low - start > 1 or (low > start and text[start] != " "):
                    clauses.append(_clause((start, low, strong)))
                    strong = False
                strong = strong or text[low] in _STRONG_MARKS
                start = high
    if size - start > 1 or (size > start and text[start] != " "):
        clauses.append(_clause((start, size, strong)))
    return clauses


def _split(
    text: str, groups: tuple[DateGroup, ...], mentions: list[Mention], separators: _Separators
) -> list[_Clause]:
    """The clauses of ``text`` (see :func:`_clauses_at`), or the whole text as one.

    No clause mark falls inside a date group or a mention. A text none of whose
    stretches between spaces holds a clause mark is one clause. ``text`` is
    normalized: its only spaces are single ones.
    """
    if separators:
        clauses = _clauses_at(text, _protected(groups, mentions), separators)
        if clauses:
            return clauses
    return [_clause((0, len(text), True))]


def _protected(groups: tuple[DateGroup, ...], mentions: list[Mention]) -> list[tuple[int, int]]:
    """The spans of the date groups and the mentions: read already, and never split."""
    # (A group's first two fields are its start and end. Comprehensions, which the interpreter
    # reads with its quick forms for a tuple's item and a slot, cost less than getters here.)
    spans = [(group[0], group[1]) for group in groups]
    if mentions:
        spans += [(mention.start, mention.end) for mention in mentions]
    return spans


class _ChunkTable(dict[str, _ChunkFacts]):
    """:func:`_chunk_facts` of each stretch seen, worked out the first time it is looked up."""

    def __missing__(self, chunk: str) -> _ChunkFacts:
        facts = _chunk_facts(chunk)
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the facts are the same when worked out again
        self[chunk] = facts
        return facts


_CHUNK_FACTS = _ChunkTable()
_chunk_lookup = _CHUNK_FACTS.__getitem__


class _SpanTable(dict[str, tuple[tuple[int, int, str], ...]]):
    """The words of each stretch between spaces, with where each starts and ends in it."""

    def __missing__(self, chunk: str) -> tuple[tuple[int, int, str], ...]:
        spans = tuple(
            (match.start(), match.end(), match.group()) for match in _WORD.finditer(chunk)
        )
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the words are the same when found again
        self[chunk] = spans
        return spans


_CHUNK_SPANS = _SpanTable()
_chunk_spans = _CHUNK_SPANS.__getitem__
# The words that can decide whether a lone status is settled as it is (see _lone_status): the
# stretches that hold one are noted as the text is read.
_NOTED = _QUALIFYING | _ANY_SCOPE | _MODIFIER | _COUNT_WORD


def _noted_words(
    noted: list[tuple[int, str]], low: int, high: int, skip_low: int, skip_high: int
) -> list[str] | None:
    """The words of the noted stretches in ``low:high`` but outside ``skip_low:skip_high``.

    As :func:`words` would read them there, for the words that can qualify a
    status (see :data:`_NOTED`): ``None`` when one of them straddles an edge,
    where :func:`words` would read part of it.
    """
    found: list[str] = []
    for position, chunk in noted:
        end = position + len(chunk)
        if end <= low or position >= high:
            continue
        if low <= position and end <= high and (end <= skip_low or position >= skip_high):
            found += _chunk_tokens(chunk)
            continue
        for offset, offset_end, token in _chunk_spans(chunk):
            start = position + offset
            stop = position + offset_end
            if stop <= low or start >= high or skip_low <= start < stop <= skip_high:
                continue
            if start < low or stop > high or start < skip_low < stop or start < skip_high < stop:
                return None  # a word cut by an edge
            found.append(token)
    return found


# "instead" right after a status (its day blanked out): "No school tomorrow; 2 hour delay instead".
_INSTEAD_AFTER = re.compile(r"\s+instead\b", re.ASCII)


def _qualify(context: _Context, clause: _Clause, mention: Mention, window_start: int) -> None:
    """Settle whether the words around one mention negate, hedge or replace it, in place.

    Called only for a text with such words, or a conditional clause. The
    context's text has its date groups blanked out, so "this morning" or
    "Monday" never reads as a noun or a modifier.
    """
    text = context.text
    bits = context.bits
    window: list[str] | None = None
    if bits & (_NEGATION | _SUPERSEDED):
        window = words(text, window_start, mention.start)[-_LOOKBACK_TOKENS:]
    clause_tokens = (
        words(text, clause.start, mention.start) if bits & (_HEDGE | _SUPERSEDING) else []
    )
    if mention.dropped != "negated":  # else negated by its own words: "no school closures"
        mention.dropped = _dropped(context, clause, mention, window, clause_tokens)
    if bits & _SUPERSEDING:
        change = _supersedes(clause_tokens)
        if change == _CHANGE_DENIED:
            mention.dropped = mention.dropped or "negated"  # "will not change to a closure"
        elif change or _INSTEAD_AFTER.match(text, mention.end) is not None:
            mention.superseding = True  # (and "2 hour delay instead", after the status)
    if bits & _SUPERSEDED and window is not None and _superseded(window):
        mention.superseded = True
        mention.superseding = False


# Every word that one of the checks of _qualify and _dropped reacts to, around a status: a
# negation, a hedge before or after it ("tentatively", "to be determined"), a word of an update
# or of a past status ("instead of", "rather than"), and a word that opens a condition after
# it ("if", "in case", "as long as", "weather permitting"). The other words only fill in.
_QUALIFY_TRIGGERS = frozenset().union(
    NEGATIONS, HEDGES, HEDGES_AFTER, _UNDER_HEDGES, {"tentatively"}, _TO_BE_SETTLED, SUPERSEDING,
    SUPERSEDED,
    SUPERSEDING_WITH, {"instead", "rather"}, NOT_CONDITIONS, CONDITION_OPENERS,
    {"case", "long", "permitting"}, _POSSIBILITIES, _NOTICE_NOUNS,
)  # fmt: skip
# Such a word as a whole word of :func:`words` (see text.WORD): no letter, digit or joined
# word right before it or after it.
_QUALIFY_TRIGGER = re.compile(
    r"(?<![a-z0-9])(?<![a-z0-9]['/-])(?:"
    + trie(sorted(_QUALIFY_TRIGGERS))
    + r")(?![a-z0-9])(?!['/-][a-z0-9])",
    re.ASCII,
).search


class _StretchTable(dict[str, bool]):
    """Whether each stretch of text has what a search finds in it, found once per stretch.

    The stretches around a status repeat across listings ("closed today", " - "), and
    the search reads the stretch alone.
    """

    __slots__ = ("search",)

    def __init__(self, search: Callable[[str], re.Match[str] | None]) -> None:
        super().__init__()
        self.search = search

    def __missing__(self, stretch: str) -> bool:
        found = self.search(stretch) is not None
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the answer is the same when worked out again
        self[stretch] = found
        return found


_TRIGGERED = _StretchTable(_QUALIFY_TRIGGER)
_triggered = _TRIGGERED.__getitem__  # a word of _QUALIFY_TRIGGERS
_WORDED = _StretchTable(_WORD.search)
_worded = _WORDED.__getitem__  # a word of text.WORD


# What a text holds for a field's answer after its statuses (see _qualify_possible), read once
# per text: whether it holds a colon or a dash (an answer after a status starts with one), where
# the space before a form's value that ends the text is ("Closed=false", or -1), and whether
# it can hold a zero time before a status ("00:00 delay") or an answer left open ("yes/no").
type _Answers = tuple[bool, int, bool, bool]
# The last two characters of a form's value at the end of a text ("false", "n", "no", "none",
# "n/a", "0", "00", "0:00"): a quick look, with no call, before _FORM_TAIL.
_FORM_ENDS = frozenset({"se", " n", "no", "ne", "/a", " 0", "00", ":0"})
# A form's value at the end of the text (see _ANSWERED_FORM), looked for once per text.
_FORM_TAIL = re.compile(r" (?:false|0+(?::0+)?|n|no|none|n/a)\Z", re.ASCII).search
# What an answer of _ANSWERED_NO starts with, past one space: a colon, a dash, or more spaces
# (a quick look, with no call, before _ANSWER_LEADS: see _qualify_possible).
_LEAD_CHARS = ":- \t\n\r\f\v"
_SLASH_N_RARE = _SLASH_N_TEXT >> _RARE_SHIFT


def _answers(text: str, bits: int, rare: int) -> _Answers:
    """What ``text`` holds for a field's answer after its statuses (see :data:`_Answers`).

    ``bits`` are the text's own kinds of word and ``rare`` its rare bits (see
    :func:`_analyse_normalized`): a form's value, a zero time and an answer left
    open each hold a word of :data:`_ANSWER_RUNS`.
    """
    fields = bool(bits & _COLON) or "-" in text
    if not bits & _ANSWER:
        return fields, -1, False, False
    form = -1
    if text[-2:] in _FORM_ENDS:
        found = _FORM_TAIL(text)
        if found is not None:
            form = found.start()
    either = bool(rare & _SLASH_N_RARE and "/n" in text) or bool(
        rare & _OR_RARE and " or no" in text
    )
    return fields, form, bool(rare & _ZERO_RARE), either


def _qualify_possible(  # noqa: PLR0913, PLR0917 - the mention, its clause, and the text's facts
    text: str,
    bits: int,
    clause: _Clause,
    mention: Mention,
    window_start: int,
    answers: _Answers,
) -> bool:
    """Whether :func:`_qualify` can change a mention not in a conditional clause.

    Only a field answered "no", or both ways, right after it ("Closed: No",
    "Closed: yes/no", "Closed=false"), a zero time before it ("00:00 delay"), a day to be
    made up, or a word of :data:`_QUALIFY_TRIGGERS` among the words :func:`_qualify`
    reads (those before the mention, from ``window_start`` and from the clause's
    start, and those after it in its clause, as :func:`_words_after` reads them)
    can: with none of them it leaves the mention as it is. ``answers`` are what the
    text holds for a field's answer (see :func:`_answers`), read once for all its statuses.
    """
    if bits & _MAKE_UP:
        return True
    end = mention.end
    start = mention.start
    fields, form, zero, either = answers
    # (A field's answer starts as _ANSWER_LEADS do, past one space: a quick look with no call,
    # in a text with a colon or a dash. The quick tests are inline: this runs for every status
    # a text with a qualifier holds.)
    lead = text[end : end + 1] if fields else "x"
    if lead == " ":
        lead = text[end + 1 : end + 2]
    if (
        (
            lead in _LEAD_CHARS
            and text.startswith(_ANSWER_LEADS, end)
            and _ANSWERED_NO.match(text, end) is not None
        )
        or end == form
        or (
            zero
            and text[start - 2 : start - 1] in _ZERO_CLOCK_MARKS
            and text.endswith(_ZERO_CLOCKS, 0, start)
        )
        or (either and _ANSWERED_EITHER.match(text, end) is not None)
        or (
            # "Closure status: open", "Closed: 0 schools" (see _label_answer)
            bits & _COLON
            and (colon := text.find(":", end, end + _LABEL_REACH)) >= 0
            and _label_colon(text, end, colon)
        )
    ):
        return True
    if window_start < start and _triggered(text[window_start:start]):
        return True
    if clause.start < window_start and _triggered(text[clause.start : start]):
        return True
    if end >= clause.end:
        return False  # (no word after it in its clause)
    after = text[end : clause.end]
    if "  " in after and ("on   " in after or "for   " in after):
        after = _DATE_PREPOSITION.sub(" ", after)  # (as _words_after reads it)
    return _triggered(after)


def _scope_of(
    context: _Context, clause: _Clause, mention: Mention, window_start: int
) -> tuple[Scope | None, Scope | None]:
    """The noun a mention is about, from the words after it or before it in its clause.

    Called only for a text with a scope noun, and a mention whose rule reads one.
    A cancelled status word with the school noun ("Classes cancelled") is a closure,
    and a noun right before it is its subject whatever noun follows it with nothing
    between them ("Classes cancelled today buses running").
    """
    text = context.text
    starts, ends = context.noun_starts, context.noun_ends
    scope: Scope | None = None
    extra: Scope | None = None
    index = bisect_right(ends, mention.end)
    if index < len(starts) and starts[index] < clause.end:  # a noun after it (see _Context)
        scope = _scope_after(text, mention, clause.end)
        if (
            scope is not None
            and mention.needs_school_noun
            and scope not in _SCHOOL_SCOPES
            and index
            and ends[index - 1] <= mention.start
            and text[ends[index - 1] : mention.start].isspace()
            and text[mention.end : starts[index]].isspace()
        ):
            # "Classes cancelled today buses running": the noun right before a cancelled
            # status is what it calls off, and one right after it ("buses") starts another
            # phrase, unlike "Cancelled: buses" or "Cancelled all practices".
            scope = None
    if (
        scope is None
        and mention.scope_rule == "both"
        and (index := bisect_right(ends, window_start)) < len(starts)
        and starts[index] < mention.start
    ):
        if window_start == 0:
            # The text opens with this mention's words: "Lincoln Elementary: closed".
            scope, extra = _label_scope_before(text[: mention.start])
            mention.named = scope == "school" and extra == "school"
            extra = None if mention.named else extra
        else:
            scope, extra = _window_scope_before(text[window_start : mention.start])
    if mention.kind == "ambiguous" and mention.needs_school_noun and scope == "school":
        mention.kind = "closed"
        mention.note = None
    if scope == "partial" and _whole_district(text, mention):
        return "school", None  # "Closed for grades K-12", "All elementary, middle and high"
    return scope, extra


# Every grade, or every level, of the district: "K-12", "PreK-12", "all elementary, middle and
# high schools" (see _scope_of).
_WHOLE_DISTRICT = re.compile(
    r"\b(?:pre-?k|pk|tk|k)\s*-\s*12\b(?!\s*-)"
    r"|\ball\s+(?:of\s+)?(?:the\s+|our\s+)?elementary,?\s+middle,?\s+(?:and|&)\s+high\b"
    r"|\b(?:upper\s+(?:and|&)\s+lower|lower\s+(?:and|&)\s+upper)\s+schools?\b",
    re.ASCII,
)


def _whole_district(text: str, mention: Mention) -> bool:
    """Whether a status's sentence names every grade or every level of the district (see
    _WHOLE_DISTRICT), not part of it."""
    if "12" not in text and "middle" not in text and "upper" not in text:
        return False
    low = max([text.rfind(mark, 0, mention.start) for mark in _POLICY_MARKS]) + 1
    ended = _SENTENCE_END.search(text, mention.end)
    high = len(text) if ended is None else ended.start()
    return _WHOLE_DISTRICT.search(text, low, high) is not None


class _ScopeTable(dict[str, tuple[Scope | None, Scope | None]]):
    """:func:`_scope_before` of the words of each stretch of text, worked out once.

    The stretch before a status repeats across listings ("qq elementary: ", "no
    school for "), and its words alone decide the scope.
    """

    __slots__ = ("label",)

    def __init__(self, *, label: bool) -> None:
        super().__init__()
        self.label = label

    def __missing__(self, stretch: str) -> tuple[Scope | None, Scope | None]:
        tokens = words(stretch)
        if not self.label:
            found = _scope_before(tokens[-_LOOKBACK_TOKENS:])
        else:
            # A name starts after the last heading mark with words after it: "Update:
            # Elementary School closed" names no school, "Snow: Middle/High School closed"
            # neither.
            marks = tuple(
                len(words(stretch, 0, match.end()))
                for match in _NAME_HEADING_MARK.finditer(stretch)
            )
            found = _scope_before(tokens, label=True, marks=marks)
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the scope is the same when worked out again
        self[stretch] = found
        return found


# A heading's mark with a word after it, before which no school's name reaches.
_NAME_HEADING_MARK = re.compile(r"(?:[:|]|\s[-\u2013\u2014]+)\s*(?=[a-z0-9])", re.ASCII)


def _name_heading_end(stretch: str) -> int:
    """Where a name can start in ``stretch``: after its last heading mark with a word after
    it ("update: elementary school" -> "elementary school"), or at its start."""
    if not (
        ":" in stretch
        or "|" in stretch
        or "-" in stretch
        or "\u2013" in stretch
        or "\u2014" in stretch
    ):
        return 0  # (no mark of _NAME_HEADING_MARK: a quick look before the pattern)
    end = 0
    for match in _NAME_HEADING_MARK.finditer(stretch):
        end = match.end()
    return end


_LABEL_SCOPES = _ScopeTable(label=True)
_WINDOW_SCOPES = _ScopeTable(label=False)
_label_scope_before = _LABEL_SCOPES.__getitem__
_window_scope_before = _WINDOW_SCOPES.__getitem__


# Making up a lost day: "make-up day", "makeup", "to be made up", "will make up".
_MAKE_UP_PHRASE = re.compile(r"\b(?:make|makes|made|making)[ -]?ups?\b|\bmakeups?\b", re.ASCII)


def _dropped(  # noqa: PLR0911 - one return per way a status is dropped
    context: _Context,
    clause: _Clause,
    mention: Mention,
    window: list[str] | None,
    clause_tokens: list[str],
) -> Note | None:
    """Whether the words around a mention negate it or hedge it (see :func:`_qualify`)."""
    text = context.text
    bits = context.bits
    if bits & (_ANSWER | _NEGATION) or text.startswith(_FIELD_MARKS, mention.end):
        answer = _field_answer(text, mention.end, bits)
        if answer is not None:
            return answer
    if bits & _COLON and ":" in text[mention.end : mention.end + _LABEL_REACH]:
        answer = _label_answer(text, mention)
        if answer is not None:
            return answer
    if (
        bits & _ANSWER
        and text[mention.start - 2 : mention.start - 1] in _ZERO_CLOCK_MARKS
        and text.endswith(_ZERO_CLOCKS, 0, mention.start)
        and _ZERO_CLOCK(text, max(0, mention.start - 9), mention.start) is not None
    ):
        return "negated"  # "00:00 delay": a length of nothing
    if bits & _NEGATION and mention.negatable:
        if window is not None and (
            any(t in NEGATIONS for t in window[-_NEGATION_TOKENS:])
            # "None of our schools are closed": "none of" reaches across its noun phrase.
            or any(t == "none" and after == "of" for t, after in pairwise(window))
        ):
            return "negated"
        denied = _denied_status(text, clause, mention)
        if denied is not None:
            return denied  # "closure not expected", "delay not yet decided"
    if bits & _MAKE_UP and _MAKE_UP_PHRASE.search(text, clause.start, clause.end) is not None:
        # "Snow day make-up day", "the snow day will be made up on March 2": about a day
        # to be made up, whose status the text does not state.
        return "ambiguous"
    if (
        context.conditional
        or (bits & _HEDGE and _hedged_before(clause_tokens))
        or (
            (
                bits & (_HEDGE_AFTER | _HEDGE_CLAUSE | _CONDITIONAL)
                or (text.startswith(_REPORT_LEAD, mention.end) and _report_notice(text, mention))
            )
            and _open_after(context, clause, mention)
        )
        or (
            bits & _HEDGE_AFTER
            and text.endswith(_CHANCE_OF_ENDS, clause.start, mention.start)
            and _chance_of(text, clause.start, mention.start)
        )
    ):
        return "hedged"
    return mention.dropped


# A noun of the odds of a status right before it: "possibility of closure", "chance of a delay",
# "the odds of an early dismissal" (see _dropped). Its end comes first, as a quick look.
_CHANCE_OF_ENDS = ("of ", "of a ", "of an ", "for a ", "for an ")
_CHANCE_OF = re.compile(
    r"\b(?:possibilit(?:y|ies)|chances?|odds|likelihood|probability)\s+(?:of|for)"
    r"(?:\s+an?)?\s+$",
    re.ASCII,
)
_CHANCE_OF_REACH = 24


def _chance_of(text: str, low: int, start: int) -> bool:
    """Whether a noun of a status's odds and "of" or "for" end ``text[low:start]``."""
    return _CHANCE_OF.search(text, max(low, start - _CHANCE_OF_REACH), start) is not None


def _denied_status(text: str, clause: _Clause, mention: Mention) -> Note | None:
    """What a "not" after a status says of it (see :func:`_denied_after`), in its clause.

    A "not" that ends the clause after a day the status names ("Closed today not
    tomorrow") denies the day after it, not the status (see
    :func:`_without_denied_days`). (``text`` has its dates blanked out, so a day
    before the "not" is a run of spaces.)
    """
    after = _words_after(text, mention.end, clause.end)
    denied = _denied_after(after)
    if denied == "negated":
        last = len(after) - 1
        while last and after[last] in _AFTER_NOT:
            last -= 1  # ("closed today, will not be Thursday": the "not" before the copula)
        stretch = text[mention.end : clause.end]
        if after[last] in NEGATIONS and "  " in stretch[: stretch.rfind(after[last])]:
            return None  # (the day after it is left out: see _without_denied_days)
    return denied


def _field_answer(text: str, end: int, bits: int) -> Note | None:
    """What a field's answer after a status says of it, if it answers.

    A field answered no denies the status ("Closed: No", "2 hour delay - none",
    "Delay: --", "Closed - not"); one answered both ways leaves it open
    ("Closed: yes/no", "Delay: Y/N").
    """
    answered = _ANSWERED_NO.match(text, end)
    if answered is not None and answered.group("empty") is not None:
        return "ambiguous"  # "Closed:": a field left empty answers nothing
    if (
        bits & _ANSWER
        and (len(text) - end <= _FORM_REACH or text[-1] == "0")
        and _ANSWERED_FORM(text, end) is not None
    ):
        return "negated"  # "Closed=false"
    if (
        answered is not None
        and not text.startswith("  ", answered.end())
        and ("  " not in answered.group() or not answered.group().endswith("not"))
    ):
        # (A run of spaces is a day blanked out: "Closed today - not tomorrow" and "Closed -
        # not tomorrow" deny the day, not the status; "Closed tomorrow - FALSE" denies it.)
        return "negated"
    if bits & _ANSWER and _either_hint(text) and _ANSWERED_EITHER.match(text, end) is not None:
        return "ambiguous"
    return None


# A status as a field's label, with a noun of the label at most before its colon, and an answer
# that says no ("Closure status: open", "Delay status: on time", "Closed: 0 schools", "Closed
# schools: 0") or that nothing is decided ("Closure: maybe", "Snow day alert: possible",
# "Closure tomorrow: no decision yet"). (A day is blanked out of the text: spaces.)
_LABEL_ANSWER = re.compile(
    r"(?: (?:status|alert|alerts|update|updates|notice|schools?))?(?P<gap>\s*): ?"
    r"(?:(?P<no>open|opened|reopened|on time|on schedule|in session|as scheduled"
    r"|(?:normal|regular)(?: schedule| hours| day| operations)?|none|no|zero|0(?: schools?)?)"
    r"|(?P<open>maybe|possible|possibly|likely|undecided|tbd|tba|pending|unknown"
    r"|no decision(?: yet| made)?|not (?:yet )?decided(?: yet)?|to be (?:determined|decided)))"
    r"(?=\s*(?:$|[;,.|!?-]))",
    re.ASCII,
).match
_LABEL_REACH = 16  # (how far after a status the label's colon can stand)
_BLANKED_GAP = 2  # (spaces before the colon that are a day blanked out of the text)


def _field_colon(text: str, end: int) -> bool:
    """Whether a colon a field's answer follows comes after a status ending at ``end``: in the
    two characters after it (as _FIELD_MARKS, or more), or after a label's noun as
    _LABEL_ANSWER reads it ("Closure status: open")."""
    colon = text.find(":", end, end + _LABEL_REACH)
    return colon >= 0 and (colon < end + 2 or _label_colon(text, end, colon))


def _label_colon(text: str, end: int, colon: int) -> bool:
    """Whether a label's answer (see _LABEL_ANSWER) follows a status ending at ``end``, the
    colon at ``colon``: only spaces, or a label's noun, can stand before it (a quick look)."""
    if not (colon == end or text.startswith(_LABEL_NOUN_LEADS, end) or text[end:colon].isspace()):
        return False
    return _LABEL_ANSWER(text, end) is not None


_LABEL_NOUN_LEADS = (" status", " alert", " update", " notice", " school")


def _label_answer(text: str, mention: Mention) -> Note | None:
    """What an answer to a status written as a field's label says of it (see _LABEL_ANSWER):
    "negated" for one that says no, "hedged" for one that says nothing is decided. A day
    between a statement and the colon ("Opening at 10 AM TODAY: OPEN", "No classes TODAY:
    OPEN") heads an answer of its own, which says nothing of the status before it; after a
    status's noun ("Closure tomorrow: open", "Closure tomorrow: no decision yet") the day is
    the label's."""
    found = _LABEL_ANSWER(text, mention.end)
    if found is None:
        return None
    if found.group("no") is None:
        return "hedged"
    if len(found.group("gap")) < _BLANKED_GAP or text.endswith(
        _NOTICE_HEADS, mention.start, mention.end
    ):
        return "negated"
    return None


def _either_hint(text: str) -> bool:
    """Whether ``text`` can hold an answer left open (see :data:`_ANSWERED_EITHER`)."""
    return "/n" in text or " or no" in text


def _open_after(context: _Context, clause: _Clause, mention: Mention) -> bool:
    """Whether the words after a status in its clause leave it open (see :func:`_dropped`).

    "Closing possible", "closure to be determined"; a condition right after it
    ("Closed tomorrow should the storm arrive", "assuming it snows"); "not" and a
    word that leaves it unsettled after a status "not" cannot deny ("No school
    tomorrow not confirmed").
    """
    bits = context.bits
    after = _words_after(context.text, mention.end, clause.end)
    return (
        _hedged_after(after)
        or bool(bits & _CONDITIONAL and _condition_opens(after))
        or (not mention.negatable and bool(bits & _NEGATION) and _denied_after(after) == "hedged")
        # (A notice last: a watch is noted only when nothing else leaves the status open.)
        or (
            bool(after)
            and (
                after[0] in _NOTICE_NOUNS
                or after[0] in _NOTICE_JOINED
                # (After a length, "report" is the staff's verb: "2 hour delay report at 10".)
                or (after[0] in _REPORT_NOUNS and mention.delay is None and mention.early is None)
            )
            and context.text.endswith(_NOTICE_HEADS, mention.start, mention.end)
            and _notice(
                after,
                dated="  " in context.text[mention.end : clause.end],
                watched=lambda: context.watched.append(
                    (mention, mention.dropped, _watch_dated(context.text, clause, mention))
                ),
            )
        )
    )


def _conditionals(
    text: str,
    clauses: list[_Clause],
    busy: AbstractSet[int],
    *,
    conditional_words: bool,
    trailing_words: bool,
) -> list[bool]:
    """Whether each clause is conditional, or a question.

    "If roads are icy, closed" carries the condition over the comma; "Snow day
    tomorrow?" and "Closed tomorrow (?)" ask rather than state; "Closed tomorrow,
    if the storm hits" and "Closed Friday (tentative)" leave the status before
    the condition or the hedge open (see :func:`_trailing`). ``conditional_words``
    is false when the text has none of the words that open a condition, and
    ``trailing_words`` when it has none of those or of a hedge; ``busy`` holds the
    clauses with a mention.
    """
    if "?" in text:
        asks = [text.startswith(("?", ", ?"), clause.end) for clause in clauses]
    else:
        asks = [False] * len(clauses)
    conditional_words = conditional_words and _ANY_CONDITIONAL.search(text) is not None
    if not conditional_words and not (trailing_words and len(clauses) > 1):
        return asks
    tokens = [words(text, clause.start, clause.end) for clause in clauses]
    result = asks
    if conditional_words:
        result = []
        carry = False
        for clause, clause_tokens, question in zip(clauses, tokens, asks, strict=True):
            conditional, opens = _conditional(text, clause, clause_tokens)
            result.append(question or conditional or (carry and not clause.strong))
            carry = opens or (carry and not clause.strong)
    if trailing_words and len(clauses) > 1:
        for target in _trailing(text, clauses, tokens, busy):
            result[target] = True
    return result


def _settle(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917 - the text's parts, one pass
    text: str,
    clauses: list[_Clause],
    mentions: list[Mention],
    homes: list[int],
    bits: int,
    nouns: tuple[list[int], list[int]],
    rare: int,
) -> tuple[set[Note], bool, bool]:
    """Decide every mention; return the notes, ``offices_open`` and ``says_open``.

    ``homes`` holds the clause of each mention; ``bits`` are the kinds of word the
    text holds (the union of :func:`_facts` bits over its words, below
    :data:`_OWN_BITS`), ``nouns`` where the words with a scope noun's run start
    and end (see :class:`_Context`), and ``rare`` the text's rare bits (see
    :func:`_answers`).
    """
    notes: set[Note] = set()
    offices_open = False
    says_open = False
    if not mentions:
        return notes, offices_open, says_open
    if (
        _FAST_PATH
        and not bits & (_ANY_SCOPE | _QUALIFIERS | _CONDITIONAL | _HEDGE_CLAUSE)
        and "?" not in text
    ):
        return _settle_plain(text, clauses, mentions, homes, bits, nouns, rare)
    context = _Context(text, bits, nouns)
    busy = set(homes)
    conditionals = (
        _conditionals(
            text,
            clauses,
            busy,
            conditional_words=bool(bits & _CONDITIONAL),
            trailing_words=bool(bits & (_CONDITIONAL | _HEDGE_CLAUSE)),
        )
        if bits & (_CONDITIONAL | _HEDGE_CLAUSE) or "?" in text
        else None
    )
    any_scope = bits & _ANY_SCOPE
    qualifiers = bits & _QUALIFIERS
    # (What the text holds for a field's answer, read once, when a status is first looked at
    # for one: see _qualify_possible.)
    answers: _Answers | None = None
    noun_starts, noun_ends = nouns
    last_clause = len(clauses) - 1
    named = False  # a mention is about the school because a noun is in its name
    previous_clause = -1
    previous_end = 0
    previous_negated = False
    notice_time = -1  # where a status's report notice's own time starts (see _notice_time)
    for position, mention in enumerate(mentions):
        index = homes[position]
        clause = clauses[index]
        if index != previous_clause:
            previous_clause = index
            previous_end = clause.start
            # "No closings, delays or cancellations": the "no" covers a list across commas.
            previous_negated = (
                previous_negated and not clause.strong and _listed(text, mentions, position)
            )
            context.conditional = conditionals is not None and conditionals[index]
        if mention.kind == "revoke":
            # A word that calls a status off (see revoke.pair_revocations): settled already.
            previous_end = mention.end
            previous_negated = False
            continue
        scope: Scope | None = None
        extra: Scope | None = None
        if (
            any_scope
            and mention.scope_rule != "none"
            and noun_ends
            and noun_ends[-1] > previous_end
        ):
            # (A noun after the status or in its window ends after the window starts: with
            # none, _scope_of finds nothing.)
            scope, extra = _scope_of(context, clause, mention, previous_end)
            named = named or mention.named
        if (
            (
                qualifiers
                or context.conditional
                # (A colon in the two characters after the status, as _FIELD_MARKS, or more;
                # or after a label's noun, as _LABEL_ANSWER reads it.)
                or (
                    bits & _COLON
                    and text.find(":", mention.end, mention.end + _LABEL_REACH) >= 0
                    and _field_colon(text, mention.end)
                )
            )
            and (
                context.conditional
                or _qualify_possible(
                    text,
                    bits,
                    clause,
                    mention,
                    previous_end,
                    (answers := _answers(text, bits, rare)) if answers is None else answers,
                )
            )
        ) or (
            # ("Closure report by 5:30 a.m.": maybe a notice, see _open_after.)
            rare & _REPORT_RARE
            and text.startswith(_REPORT_LEAD, mention.end)
            and _report_notice(text, mention)
        ):
            _qualify(context, clause, mention, previous_end)  # (a field's answer: "Delay: --")
            notice_time = _notice_time(text, mention, notice_time)
        if mention.start == notice_time:
            mention.dropped = mention.dropped or "hedged"  # (see _notice_time)
        if (
            scope is None
            and any_scope
            and (mention.kind in _LABELED_KINDS or mention.needs_school_noun)
        ):
            # A scope noun in the clause or a clause beside it (see _Context).
            low = clauses[index - 1].start if index else clause.start
            if index > 1 and _WORD.search(text, low, clauses[index - 1].end) is None:
                low = clauses[index - 2].start  # a day alone before it (see _label_scope)
            high = clauses[index + 1].end if index < last_clause else clause.end
            noun = bisect_right(noun_ends, low)
            if noun < len(noun_starts) and noun_starts[noun] < high:
                scope, extra = _label_scope(text, clauses, index, mention, busy)
                if mention.kind == "ambiguous" and scope == "school":
                    mention.kind = "closed"  # "Cancelled (all classes)"
                    mention.note = None
        # "No closings or delays": the "no" covers both.
        if (
            previous_negated
            and mention.negatable
            and set(words(text, previous_end, mention.start)) <= _JOINERS
        ):
            mention.dropped = "negated"
        previous_negated = mention.dropped == "negated"
        previous_end = mention.end
        if mention.revoked:
            _apply_scope(mention, scope)  # called off: what it was about adds no note
            continue
        if extra is not None and mention.dropped is None:
            # "Schools and offices closed": the second noun's news, as its own status says it
            # (a status denied or hedged says nothing of it).
            if mention.kind == "open":
                offices_open = offices_open or extra == "office"
                if extra not in ("office", "activities"):
                    notes.add(SCOPE_NOTES[extra])
            elif extra != "office" or _closes(mention):
                notes.add(SCOPE_NOTES[extra])
        if mention.kind == "open":
            outcome = _open_outcome(mention, scope)
            offices_open = offices_open or outcome == "office"
            says_open = says_open or outcome == "school"
            if outcome == "partial":
                # "Closed. Lincoln Elementary open.": part of the program has a status of its
                # own, so a status beside it may not be all there is (see parse_status).
                mention.narrowed = "open"
            mention.elsewhere = outcome not in (None, "school")  # "offices open" (see partial)
            # "Buses open" or "staff open" names what the news is about; "activities open" is
            # no news of activities cancelled.
            if outcome not in (None, "office", "school", "activities"):
                notes.add(SCOPE_NOTES[outcome])
            continue
        if scope is None and mention.dropped is None and mention.kind != "note":
            continue  # a status about the school, standing: nothing to note (see _apply_scope)
        note = _apply_scope(mention, scope)
        if note is not None:
            notes.add(note)
    if context.watched:
        _read_watched(context.watched, mentions, notes)
    if named:
        _demote_names(mentions, notes)
    return notes, offices_open, says_open


def _settle_plain(  # noqa: PLR0913, PLR0917 - as _settle
    text: str,
    clauses: list[_Clause],
    mentions: list[Mention],
    homes: list[int],
    bits: int,
    nouns: tuple[list[int], list[int]],
    rare: int,
) -> tuple[set[Note], bool, bool]:
    """:func:`_settle` of a text with no scope noun, no qualifying word and no condition.

    Then no noun moves a mention away from the school, no clause is conditional
    and only a field answered after a colon or a dash ("Delay: --") can
    qualify a mention: what is left is the lists that a "no" covers, the notes
    and the "open" mentions, read as :func:`_settle` reads them.
    """
    notes: set[Note] = set()
    says_open = False
    colon = bits & _COLON
    context: _Context | None = None
    previous_clause = -1
    previous_end = 0
    previous_negated = False
    notice_time = -1  # (as in _settle)
    for position, mention in enumerate(mentions):
        index = homes[position]
        if index != previous_clause:
            clause = clauses[index]
            previous_clause = index
            previous_end = clause.start
            previous_negated = (
                previous_negated and not clause.strong and _listed(text, mentions, position)
            )
        if mention.kind == "revoke":
            previous_end = mention.end
            previous_negated = False
            continue
        if (
            colon
            and text.find(":", mention.end, mention.end + _LABEL_REACH) >= 0
            and _field_colon(text, mention.end)
            and _qualify_possible(
                text, bits, clauses[index], mention, previous_end, _answers(text, bits, rare)
            )
        ) or (
            rare & _REPORT_RARE
            and text.startswith(_REPORT_LEAD, mention.end)
            and _report_notice(text, mention)
        ):
            if context is None:
                context = _Context(text, bits, nouns)
            _qualify(context, clauses[index], mention, previous_end)
            notice_time = _notice_time(text, mention, notice_time)
        if mention.start == notice_time:
            mention.dropped = mention.dropped or "hedged"  # (see _notice_time)
        if (
            previous_negated
            and mention.negatable
            and set(words(text, previous_end, mention.start)) <= _JOINERS
        ):
            mention.dropped = "negated"
        previous_negated = mention.dropped == "negated"
        previous_end = mention.end
        if mention.revoked:
            continue  # called off: what it was about adds no note
        if mention.kind == "open":
            says_open = says_open or mention.dropped is None  # (see _open_outcome)
            continue
        if mention.dropped is None and mention.kind != "note":
            continue  # a status about the school, standing: nothing to note
        note = _apply_scope(mention, None)
        if note is not None:
            notes.add(note)
    return notes, False, says_open


# The gap between two items of a list of statuses: a comma, a joining word, or both.
_LIST_GAP = re.compile(r"\s*(?P<comma>,)?\s*(?P<joiner>(?:or|and|nor)\s+)?", re.ASCII)


def _listed(text: str, mentions: list[Mention], position: int) -> bool:
    """Whether the mention at ``position`` is an item of a list that runs on from the one
    before it: the items are parted by commas, and a joining word comes before the last.

    "No closings, delays or cancellations" is one list; "No delays, closed today" is not.
    """
    comma_first = True
    for later in range(position, len(mentions)):
        gap = _LIST_GAP.fullmatch(text, mentions[later - 1].end, mentions[later].start)
        if gap is None or (comma_first and gap.group("comma") is None):
            return False
        if gap.group("joiner") is not None:
            return True
        comma_first = False
    return False


def _demote_names(mentions: list[Mention], notes: set[Note]) -> None:
    """Make a status named after a school part of the program when others are.

    "Lincoln Elementary closed; middle school 2 hour delay": a listing that gives
    parts of the program their own statuses names schools within it, not itself.
    """
    if not any(mention.named for mention in mentions) or not any(
        mention.narrowed is not None and mention.dropped is None for mention in mentions
    ):
        return
    for mention in mentions:
        if mention.named and mention.kind != "note":
            note = _apply_scope(mention, "partial")
            if note is not None:
                notes.add(note)


# Words a label or a restriction may hold besides its nouns: "all students", "AM kindergarten only".
_LABEL_FILLERS = frozenset({"all", "the", "our", "any", "only", "for", "students", "student"})
# A grade or a span of grades: "6-12", "k-5", "3rd", "third".
_GRADE_SPAN = re.compile(
    r"(?:k|pk|tk|\d{1,2}(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth"
    r"|ninth|tenth|eleventh|twelfth)(?:-(?:k|\d{1,2}(?:st|nd|rd|th)?))?",
    re.ASCII,
)


def _phrase_scope(tokens: list[str]) -> Scope | None:
    """The scope of a clause that is only a noun phrase ("AM kindergarten", "grades 6-12")."""
    kept = [token for token in tokens if token not in _LABEL_FILLERS]
    if not 1 <= len(kept) <= 2:  # noqa: PLR2004 - a one- or two-word noun phrase
        return None
    if " ".join(kept) in SCOPES:
        return SCOPES[" ".join(kept)]
    for token in kept:  # (one or two: a loop costs less than all())
        if not (token in SCOPES or token in MODIFIERS or _GRADE_SPAN.fullmatch(token)):
            return None
    return _noun_phrase_scope(kept[0], kept[1] if len(kept) > 1 else None)


def _label_phrase_scope(tokens: list[str]) -> tuple[Scope | None, Scope | None]:
    """The scope a label gives the status after it ("AM Kindergarten - No School"), and a
    second scope for a note.

    A label that ends with a scope noun is about what that noun names, as the
    words before a status in its own clause are ("District offices - Closed",
    "Albany and Corvallis offices - Closed" are about the offices, as "District
    offices: Closed" is, and "Schools and offices - Closed" notes the offices;
    see :func:`_scope_before`); any other label is read as a noun phrase (see
    :func:`_phrase_scope`).
    """
    kept = [
        token
        for index, token in enumerate(tokens)
        if token not in _LABEL_FILLERS
        # (A count after a word for all of them is all of them: "All three campuses - closed".)
        and not (token in _COUNTS and index and tokens[index - 1] in _ALL_OF)
    ]
    if kept and (
        kept[-1] in SCOPES
        or " ".join(kept[-2:]) in SCOPES
        # (A center of a program: "Kindergarten Center - closed", as "Kindergarten Center:
        # closed" is read.)
        or _program_center(kept)
    ):
        scope, extra = _scope_before(kept, label=True)
        # (A second "school" only says a school's name decided it: "Lincoln Elementary".)
        return scope, None if extra == "school" else extra
    return _phrase_scope(tokens), None


def _program_center(kept: list[str]) -> bool:
    """Whether a label's words end with a center of a program: "Kindergarten Center", "Early
    Childhood Center" (see :func:`_label_phrase_scope`)."""
    return (
        len(kept) > 1
        and kept[-1] in _INSTITUTIONS
        and (kept[-2] in SCOPES or " ".join(kept[-3:-1]) in SCOPES)
    )


_NO_SCOPE: tuple[None, None] = (None, None)


def _label_scope(  # noqa: PLR0911 - one return per place a label or a restriction can be
    text: str, clauses: list[_Clause], index: int, mention: Mention, busy: set[int]
) -> tuple[Scope | None, Scope | None]:
    """The scope a label or a restriction beside a status gives it, and a second scope for a
    note (see :func:`_label_phrase_scope`).

    "AM kindergarten: no school" and "AM Kindergarten - No School" label the
    status; "No school - AM kindergarten only" and "2 hour delay (elementary
    only)" restrict it. The label or restriction is a noun phrase alone in its
    clause, or before a colon.
    """
    clause = clauses[index]
    before = text[clause.start : mention.start]
    if (
        before
        and not before.isspace()
        and _worded(before)
        # (Verbs alone before it leave the label its own: "Elementary School - will be
        # closed today", "High school - will have a 2 hour delay".)
        and not (index > 0 and _NAME_VERBS.issuperset(before.split()))
    ):  # words before it
        if mention.scope_rule == "after" and before.rstrip().endswith(":"):
            return _label_phrase_scope(words(before, _name_heading_end(before)))
        return _NO_SCOPE
    if index > 0 and not clause.strong and index - 1 not in busy:
        label = _label_clause(text, clauses, index, busy)
        tokens = words(text, label.start, label.end)
        cut = _name_heading_end(text[label.start : label.end])
        if cut:
            # "Update: Elementary School - Closed": the label's name starts after its
            # heading's mark (see _NAME_HEADING_MARK).
            tokens = words(text, label.start + cut, label.end)
        # A dash sets a label off ("District offices - Closed"); after a comma the clause
        # before is a label only if it is a noun phrase ("AM kindergarten, no school"), and
        # an "open" is labeled by a dash alone ("Offices - Open"; not "Essential personnel
        # Tuesday, normal operations Wednesday").
        if "-" in text[label.end : clause.start]:
            scopes = _label_phrase_scope(tokens)
            if scopes[0] is not None:
                return scopes
        elif mention.kind == "open":
            return _NO_SCOPE
        else:
            scope = _phrase_scope(tokens) or (
                # "Kindergarten Center, closed": a program's center (see _label_phrase_scope)
                _label_phrase_scope(tokens)[0] if tokens and tokens[-1] in _INSTITUTIONS else None
            )
            if scope is not None:
                return scope, None
    if mention.kind == "open":
        return _NO_SCOPE  # (a restriction after an "open" says where it is open: none)
    following = index + 1
    if (
        following < len(clauses)
        and following not in busy
        and _WORD.search(text, mention.end, clause.end) is None  # no words after it
    ):
        restriction = words(text, clauses[following].start, clauses[following].end)
        # "Closed today. Kindergarten only." restricts across a sentence mark too.
        if "only" in restriction or (mention.needs_school_noun and not clauses[following].strong):
            return _phrase_scope(restriction), None
    return _NO_SCOPE


def _label_clause(text: str, clauses: list[_Clause], index: int, busy: set[int]) -> _Clause:
    """The clause that can label the status of clause ``index`` (see :func:`_label_scope`): the
    one before it, or the one before that across a day alone in its clause (blanked out of
    ``text``): "Preschool - Wednesday - closed" is labeled as "Preschool - closed" is."""
    label = clauses[index - 1]
    if (
        index > 1
        and not label.strong
        and index - 2 not in busy
        and _WORD.search(text, label.start, label.end) is None
    ):
        return clauses[index - 2]
    return label


def _open_outcome(mention: Mention, scope: Scope | None) -> Scope | None:
    """What an "open" mention says: the school is open, the offices are, or something else is."""
    if mention.dropped is not None:
        return None
    return "school" if scope is None else scope


def _closes(mention: Mention) -> bool:
    """Whether a status about offices says they are closed.

    Offices opening late or early are news about the offices, but not "offices
    closed", and nor are offices closing or opening at a time ("offices close at
    3", "offices open at 7:30").
    """
    return (
        mention.kind in {"closed", "ambiguous"}
        and mention.dismissal is None
        and mention.opens_at is None
    )


def _apply_scope(mention: Mention, scope: Scope | None) -> Note | None:
    """Turn a status about something other than the school into a note; return the note to add."""
    if scope not in (None, "school") and mention.kind != "note":
        if scope == "partial":
            mention.narrowed = mention.kind
        closes = _closes(mention)
        mention.kind = "note"
        mention.note = None if scope == "office" and not closes else SCOPE_NOTES[scope]
    if mention.kind == "note" and mention.note is not None and mention.dropped != "negated":
        return mention.note
    if mention.dropped is not None and mention.kind != "note":
        return mention.dropped
    return None


# Dates ----------------------------------------------------------------------------------


def _date_hedged(text: str, clause: _Clause, group: DateGroup) -> bool:
    """Whether a date hedge is a day's: right before it ("possibly Wednesday", "and likely
    Friday") or after it, at most a word or two of "also" and the like between, but before
    no day of its own ("with Monday possible", "Friday also likely"; not "Thursday possibly
    Friday")."""
    # (A modal before a heading's mark is about what comes before it: in "Wednesday still
    # undecided: tomorrow: closed", Wednesday is undecided, not tomorrow.)
    mark = text.rfind(":", clause.start, group[GROUP_START])
    before = words(text, clause.start if mark < 0 else mark + 1, group[GROUP_START])[-4:]
    if (
        any(token in _DATE_HEDGES for token in before[-2:])
        or any(
            token in _DAY_MODALS
            and (token not in _EXPECTED or NEGATIONS.isdisjoint(before))  # ("not expected Friday")
            for token in before[-3:]
        )
    ):
        return True
    if "not" in before and ("yet" in before or "decided" in before):
        return True  # "Closed today and not yet decided for tomorrow"
    after = _HEDGE_AFTER_DAY.match(text, group[GROUP_END], clause.end)
    return after is not None and _DAY_NEXT.match(text, after.end(), clause.end) is None


# Words that leave a day after them open when they come in the three words before it: "Closed
# Thursday and may close Friday", "Closed today and could be tomorrow as well", "Closed Thursday
# and tentatively Friday" (see _date_hedged).
_DAY_MODALS = frozenset(
    {"may", "might", "could", "tentatively", "unlikely", "undecided", "expected", "anticipated"}
)
_EXPECTED = frozenset({"expected", "anticipated"})  # (a day's hedge unless denied: "not expected")
# A date hedge after a day, with the words that may stand between them (see _date_hedged), and
# a day's name or number right after it, which the hedge leads instead.
_HEDGE_AFTER_DAY = re.compile(
    r"(?:\s+(?:also|too|is|are|as|well|very|quite|seems|looks|still|remains))?"
    r"(?:\s+(?:also|too|is|are|as|well|very|quite|seems|looks|still|remains))?"
    r"\s+(?:possibly|maybe|perhaps|possible|likely|potentially|probably|undecided"
    r"|not (?:yet )?decided|to be decided)\b",
    re.ASCII,
)
_DAY_NEXT = re.compile(
    r"\s+(?:on\s+|the\s+)?(?:\d|mon|tue|wed|thu|fri|sat|sun|tomorrow|today|next|this|jan|feb"
    r"|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    re.ASCII,
)


# After "will", the words that carry a status on to the day named next: "2 hour delay will be
# in effect tomorrow", "Snow day will be Friday". Any other verb ("will reopen Thursday",
# "will update tomorrow") ends the status's words.
_WILL_GOES_ON = re.compile(
    r"(?: (?:also|still|now|then))?(?: (?:be|apply|take place|continue|remain|occur|happen"
    r"|stay|last|extend|run|in effect|in place|effective|observed|implemented|held))+"
    r"(?: (?:on|for|through|thru|until|till|starting|beginning|from))? ",
    re.ASCII,
)


def _region_end(
    text: str,
    start: int,
    end: int,
    groups: list[DateGroup] | tuple[DateGroup, ...] = (),
    stops: Sequence[tuple[int, int]] | None = None,
) -> int:
    """Where the words that can date a status end: at a word such as "reopen" or "due".

    ``stops``, when the caller has them, are where the text's runs of those
    words start and how long each is, in order (see :func:`_chunk_facts`): the
    same words :data:`_STOP` finds, looked up rather than searched for.
    """
    if stops is None or (
        0 < end < len(text) and text[end - 1] in _WORD_CHARS and text[end] in _WORD_CHARS
    ):
        # (An end inside a word cuts it: what is left of it before the end can be a stop.)
        stop = _STOP.search(text, start, end)
        while stop is not None:
            if time_follows(text, stop.start()):  # "closed after 11:30 today"
                stop = _STOP.search(text, stop.end(), end)
                continue
            if not groups or not text.startswith("will", stop.start()):
                break
            goes_on = _WILL_GOES_ON.match(text, stop.end())
            if goes_on is None or not _dated_between(groups, stop.end(), goes_on.end()):
                break
            stop = _STOP.search(text, goes_on.end(), end)
        return end if stop is None else stop.start()
    for position, length in stops:
        if position < start:
            continue
        if position + length > end:
            break
        if time_follows(text, position):
            continue  # "closed after 11:30 today": a time of the day, not the end of the dates
        if groups and text.startswith("will", position):
            goes_on = _WILL_GOES_ON.match(text, position + length)
            if goes_on is not None and _dated_between(groups, position + length, goes_on.end()):
                start = goes_on.end()  # "2 hour delay will be in effect tomorrow"
                continue
        return position
    return end


def _dated_between(groups: Sequence[DateGroup], low: int, high: int) -> bool:
    """Whether a date group starts after ``low``, and at or before ``high``."""
    for group in groups:  # noqa: SIM110 - (a loop costs less than a generator, per call)
        if low < group[0] <= high:  # (its start)
            return True
    return False


def _after_cause(
    text: str,
    stop: int,
    bound: int,
    groups: list[DateGroup] | tuple[DateGroup, ...],
    stops: Sequence[tuple[int, int]] | None = None,
) -> list[DateGroup]:
    """The days named after a cause, for a status that names none before it.

    "No school due to snow tomorrow", "2 hour delay due to fog Thursday": the day
    after the cause is the status's. A possessive ("due to Monday's storm") dates
    the cause, not the status.
    """
    if not text.startswith(_CAUSE_WORDS, stop):
        return []
    end = _region_end(text, stop + 1, bound, groups, stops)
    return [
        group
        for group in groups
        if stop <= group[GROUP_START] < end and not text.startswith("'s", group[ATOM_END] - 2)
    ]


def _assign_in_clause(  # noqa: PLR0913, PLR0917 - the clause's parts, and the assignment
    text: str,
    clause: _Clause,
    members: Sequence[int],
    mentions: list[Mention],
    groups: list[DateGroup] | tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
    stops: Sequence[tuple[int, int]] | None = None,
) -> None:
    """Give each mention of one clause (``members``) the clause's date groups that are its.

    ``stops`` are where the words that end a status's words are (see :func:`_region_end`).
    A mention that gets none gets no entry in ``assigned``.
    """
    if not groups or not members:
        return
    # (A group's start and end are its first two fields, g[0] and g[1], read by index here: a
    # named tuple's field is read slower, and these are read for every group and mention.)
    last = len(members) - 1
    if not last and _FAST_PATH and groups[-1][1] <= mentions[members[0]].start:
        # One mention after every date ("Tuesday Morning: Closed"): its words end after the
        # dates do, and the dates from the clause's start are its own, as read below.
        low = clause.start
        chosen = [g for g in groups if low <= g[0]]
        if chosen:
            assigned[members[0]] = chosen
        return
    prefix = groups[0][0] < mentions[members[0]].start
    for position, index in enumerate(members):
        mention = mentions[index]
        if prefix and position < last:
            low = mentions[members[position - 1]].end if position else clause.start
            chosen = [g for g in groups if low <= g[0] and g[1] <= mention.start]
            if chosen:
                assigned[index] = chosen
            continue
        if prefix:
            low = mentions[members[position - 1]].end if position else clause.start
            bound = clause.end
            high = _region_end(text, mention.end, bound, groups, stops)
            chosen = [
                g
                for g in groups
                if low <= g[0] < high and (g[1] <= mention.start or g[0] >= mention.end)
            ]
        else:
            bound = mentions[members[position + 1]].start if position < last else clause.end
            high = _region_end(text, mention.end, bound, groups, stops)
            end = mention.end
            chosen = [g for g in groups if end <= g[0] < high]
        if (
            groups[-1][0] >= high  # (groups are in order: a day after the cause can be one)
            and mention.kind in _STATUS_KINDS
            and text.startswith(_CAUSE_WORDS, high)
        ):
            # A cause after the status's words (see _after_cause).
            chosen = _cause_dated(text, mention, high, bound, groups, chosen=chosen, stops=stops)
        if chosen:
            assigned[index] = chosen


def _cause_dated(  # noqa: PLR0913 - the assignment's state, passed through
    text: str,
    mention: Mention,
    stop: int,
    bound: int,
    groups: list[DateGroup] | tuple[DateGroup, ...],
    *,
    chosen: list[DateGroup],
    stops: Sequence[tuple[int, int]] | None = None,
) -> list[DateGroup]:
    """The status's days once a cause follows it; a judgment call when the cause names a day.

    A status with no day of its own takes the cause's ("No school due to snow
    tomorrow"). One with its own day keeps it, but a day in the cause ("Closed
    today due to snow Wednesday") leaves the reading less than certain.
    """
    after = _after_cause(text, stop, bound, groups, stops)
    if after:
        mention.strength = min(mention.strength, JUDGMENT)
    return chosen or after


def _pure_dates(
    text: str, clause: _Clause, groups: list[DateGroup], *, details: bool = False
) -> bool:
    """Whether a clause holds only dates, filler words, date hedges ("possibly Wednesday"),
    parts of the day ("Wednesday morning"), school nouns ("for students") and a cause
    ("Wednesday due to snow"); with ``details``, the times and lengths of a status that
    names no day of its own too ("Early dismissal - Wednesday at 1:00", "Delayed -
    Wednesday 2 hours"). (A day that restates or adds to a status's own days brings no
    time or length of its own: "Delayed Thursday 2 hours, Friday 3 hours".)"""
    if not groups:
        return False
    # A label before the days, with a colon, says nothing of them: "UPDATE: Thursday - Closed".
    start = text.rfind(":", clause.start, groups[0][GROUP_START]) + 1 or clause.start
    remainder = text[start : clause.end]
    for group in reversed(groups):
        local_start, local_end = group[GROUP_START] - start, group[GROUP_END] - start
        remainder = remainder[:local_start] + " " + remainder[local_end:]
    after_for = False  # (a school noun is the status's after "for" only: see below)
    for token in words(remainder):
        if token in _CAUSE_OPENERS_WORDS:
            return True  # "Closed - Wednesday due to snow": the rest is the cause
        if token in FILLERS:
            after_for = after_for or token in _FOR
        elif not (
            token in _DATE_HEDGES
            or token in _DAY_PARTS
            or (details and (token in _DETAIL_WORDS or _DETAIL_NUMBER(token) is not None))
            # "Closed - Wednesday for students"; but "Closed today. School tomorrow." says
            # school is held tomorrow, so a school noun with no "for" before it is no filler.
            or (after_for and SCOPES.get(token) == "school")
        ):
            return False
    return True


# The words that open a cause, which a clause of bare dates can end with (see _pure_dates):
# "due to snow", "because of the ice", "per the superintendent".
_CAUSE_OPENERS_WORDS = frozenset({"due", "because", "owing", "per"})
# The words of a time or a length that a clause of bare dates can hold (see _pure_dates): "at
# 1:00 pm", "2 hours", "two-hour", "90 min", "noon".
_DETAIL_WORDS = frozenset(
    [
        "at", "by", "noon", "midday", "hour", "hours", "hr", "hrs", "h", "minute", "minutes",
        "min", "mins", "m", "a", "p", "one", "two", "three", "four", "half", "an", "one-hour",
        "two-hour", "three-hour", "half-hour", "ninety", "sixty", "thirty", "forty-five",
    ]
)  # fmt: skip
_DETAIL_NUMBER = re.compile(
    r"\d{1,3}(?:am|pm|a|p|hrs?|h|mins?|m|-hours?|-hrs?|-minutes?)?", re.ASCII
).fullmatch


_FOR = frozenset({"for"})


def _held_day(text: str, clause: _Clause, groups: list[DateGroup]) -> _Opening | None:
    """The days a clause of their own says school is held on, as an opening, if it does.

    "School Friday", "Classes tomorrow", "Friday: classes", "There will be school
    Friday", "We will have school Friday", "Friday school as usual", "Students report
    Friday", "Friday is back on": school nouns and the words of school held, and the
    days. The day is no status's (whatever the status: a delay or an early dismissal on
    a day school is said to be held as usual is no surer), and a status that names it
    too loses it, as a correction (after a word that marks an update, a replacement:
    "Update: there will be school Friday"). A clause with any other word ("School
    possibly Friday", "No school Friday", "School Friday at 10") is none.
    """
    days = [group for group in groups if _school_day_group(group)]
    if not days:
        return None
    start = text.rfind(":", clause.start, groups[0][GROUP_START]) + 1 or clause.start
    remainder = text[start : clause.end]
    for group in reversed(groups):
        local_start, local_end = group[GROUP_START] - start, group[GROUP_END] - start
        remainder = remainder[:local_start] + " " + remainder[local_end:]
    tokens = words(remainder)
    sentence = max([text.rfind(mark, 0, start) for mark in _OPENING_SENTENCE_MARKS]) + 1
    if _NARROWING_WORDS.issuperset(tokens):
        # "Closed today through Friday. Update: now only through tomorrow.": an update that
        # ends the status's days on the range's last day.
        last = groups[-1]
        if (
            last[GROUP_OPEN_START] in _RANGE_ENDS or "range" in last[GROUP_LINKS]
        ) and not _RETRACTIONS.isdisjoint(words(text, sentence, start)):
            return (last[GROUP_START], _NARROWING, (last,))
        return None
    held = False
    for token in tokens:
        if token in _HELD_DAY_SIGNS:
            held = True
        elif token not in _HELD_DAY_WORDS:
            return None
    if not held:
        return None
    marked = not _RETRACTIONS.isdisjoint(words(text, sentence, start))
    return (groups[0][GROUP_START], _DENIALS | (_OPEN_MARKED if marked else 0), tuple(days))


# The words that may stand beside an update's range end alone (see _held_day).
_NARROWING_WORDS = frozenset({"now", "only", "just"})


# The words that say school is held on a clause's days (see _held_day), and the words that
# may stand beside them: "There will be school Friday", "Friday is back on", "Classes on
# Friday as normal", "Students should report Friday".
_HELD_DAY_SIGNS = frozenset(
    ["school", "schools", "class", "classes", "students", "student", "session", "back",
     "usual", "normal", "normally"]
)  # fmt: skip
_HELD_DAY_WORDS = frozenset(
    ["there", "will", "be", "we", "have", "is", "are", "a", "an", "the", "on", "for", "all",
     "in", "as", "of", "full", "day", "should", "report", "reports", "attend", "attends",
     "scheduled", "regular", "regularly"]
)  # fmt: skip


# No mention indexes, shared (see _Assignment.hedged).
_NO_INDEXES: frozenset[int] = frozenset()


# The date groups of each mention, and the mentions whose only dates were hedged. A plain tuple,
# read by the field numbers below (see _Status).
type _Assignment = tuple[
    dict[int, list[DateGroup]],  # _ASSIGNED_GROUPS
    frozenset[int],  # _ASSIGNED_HEDGED
]
_ASSIGNED_GROUPS: Final = 0
_ASSIGNED_HEDGED: Final = 1


def _assign_dates(  # noqa: PLR0912, PLR0913, PLR0917 - the text's parts, and where each sits
    text: str,
    clauses: list[_Clause],
    mentions: list[Mention],
    homes: list[int],
    groups: tuple[DateGroup, ...],
    hedges: bool,
    stops: Sequence[tuple[int, int]] | None = None,
    held: list[_Opening] | None = None,
) -> _Assignment:
    """The date groups of each mention (see :data:`_Assignment`); ``held`` gains the days a
    clause of their own says school is held on (see :func:`_held_day`)."""
    assigned: dict[int, list[DateGroup]] = {}
    if not groups or not mentions:
        return (assigned, _NO_INDEXES)
    if len(clauses) == 1:
        # One clause holds every mention and every date: no clause is bare dates.
        clause = clauses[0]
        _assign_in_clause(text, clause, range(len(mentions)), mentions, groups, assigned, stops)
        if not hedges:
            return (assigned, _NO_INDEXES)
        return _hedged_out(assigned, {g for g in groups if _date_hedged(text, clause, g)})
    by_clause_mentions: dict[int, list[int]] = {}
    for index, home in enumerate(homes):
        members = by_clause_mentions.get(home)
        if members is None:
            by_clause_mentions[home] = [index]
        else:
            members.append(index)
    by_clause_groups: dict[int, list[DateGroup]] = {}
    home = 0
    last = len(clauses) - 1
    for group in groups:  # (in order, as _homes finds each group's clause)
        while home < last and clauses[home + 1].start <= group[0]:  # (group[0]: its start)
            home += 1
        clause_groups = by_clause_groups.get(home)
        if clause_groups is None:
            by_clause_groups[home] = [group]
        else:
            clause_groups.append(group)
    hedged: set[DateGroup] = set()
    if hedges:
        hedged = {
            group
            for number, clause_groups in by_clause_groups.items()
            for group in clause_groups
            if _date_hedged(text, clauses[number], group)
        }
    bare = False  # a clause holds dates and no mention
    for number, clause_groups in by_clause_groups.items():
        members = by_clause_mentions.get(number)
        if members:
            _assign_in_clause(
                text, clauses[number], members, mentions, clause_groups, assigned, stops
            )
        else:
            bare = True
    for number, clause_groups in by_clause_groups.items() if bare else ():
        if not by_clause_mentions.get(number):
            _assign_bare(
                text, clauses, number, clause_groups, by_clause_mentions, mentions, assigned,
                hedged, dated=by_clause_groups, held=held,
            )  # fmt: skip
    if not hedged:
        return (assigned, _NO_INDEXES)
    return _hedged_out(assigned, hedged)


def _assign_bare(  # noqa: PLR0913, PLR0917 - the clause, and the assignment it extends
    text: str,
    clauses: list[_Clause],
    number: int,
    clause_groups: list[DateGroup],
    by_clause_mentions: dict[int, list[int]],
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    hedged: set[DateGroup],
    *,
    dated: Container[int] = frozenset(),
    held: list[_Opening] | None = None,
) -> None:
    """Give the dates of a clause that holds no mention to the mention they belong to, if any.

    A status beside it that names no day takes them ("Tuesday - closed", "closed -
    Tuesday"), or one a clause that says where or what else comes between, when
    the dates head a sentence or end the text ("(Tomorrow) All locations - no
    classes", "Closed - no extended care; through April 24": see
    :func:`_across_scope`; ``dated`` holds the numbers of the clauses with dates);
    a day slot's are the slot's ("Wednesday - Closed, Thursday - Open"); a dated
    status beside it is restated or added to ("Closed tomorrow. Jan. 22."); else
    a side note beside it takes them ("Closed; offices open - Wednesday"). A clause that
    says school is held on its days ("Closed today. School tomorrow.") gives them to no
    status: ``held`` gains them (see :func:`_held_day`).
    """
    if not _pure_dates(text, clauses[number], clause_groups):
        # "Early dismissal - Wednesday at 1:00": the day, and the time, of a delay or an
        # early dismissal that names no day of its own; or of a side note ("Closed;
        # offices open. 3/11 at 1:00"). A closure or a remote day has no time to take:
        # "Closed. Wednesday at 1:00." could be a closing time, so the day is no one's.
        if _pure_dates(text, clauses[number], clause_groups, details=True):
            target = _neighbour(number, clauses, by_clause_mentions, mentions, assigned)
            if target is None:
                target = _side_neighbour(number, by_clause_mentions, mentions, assigned)
            if target is not None and mentions[target].kind in _TIMED_OR_SIDE:
                assigned.setdefault(target, []).extend(clause_groups)
        elif held is not None:
            opening = _held_day(text, clauses[number], clause_groups)
            if opening is not None:
                held.append(opening)
        return
    if hedged.isdisjoint(clause_groups) and _clause_hedged(text, clauses[number]):
        # "Closed tomorrow. Friday also possible.": a hedge in a clause of bare dates is
        # every one of its days', whatever adds them ("also", "too", "with").
        hedged.update(clause_groups)
    target = _across_scope(text, clauses, number, by_clause_mentions, dated, mentions, assigned)
    if target is None:
        target = _neighbour(number, clauses, by_clause_mentions, mentions, assigned)
    kept = [group for group in clause_groups if group not in hedged]
    if target is not None:
        # "Closed, possibly Wednesday": hedged dates attach too, and hedge their status.
        assigned.setdefault(target, []).extend(clause_groups)
    elif kept and (slot := _slot_mention(text, number, clauses, by_clause_mentions, mentions)):
        # "Wednesday - Closed, Thursday - Open": a day slot's day is what the slot says.
        assigned.setdefault(slot, []).extend(kept)
    elif kept and (
        # "Closed tomorrow. Through Friday, offices open.": a run that heads a clause of its
        # own is that clause's, and restates no status before it.
        _heads_clause(text, clauses, number, kept)
        or not _restate(text, clauses[number], number, by_clause_mentions, mentions, assigned, kept)
    ):
        # "Closed; offices open - Wednesday": the day is the offices', as in "Closed; offices
        # open Wednesday", and leaves the closure's day unclear. A day that no mention
        # takes is not dropped, for a status that names none to fall on the posting day.
        side = _side_neighbour(number, by_clause_mentions, mentions, assigned)
        if side is not None:
            assigned.setdefault(side, []).extend(kept)


def _heads_clause(text: str, clauses: list[_Clause], number: int, kept: list[DateGroup]) -> bool:
    """Whether a clause of a bare run ("through Friday") heads the clause after it in its
    sentence, a comma between them: "Through Friday, offices open", "through Friday, call the
    office with questions" (see _assign_bare)."""
    following = number + 1
    return (
        following < len(clauses)
        and not clauses[following].strong
        and all(group[GROUP_OPEN_START] is not None for group in kept)
        and "," in text[clauses[number].end : clauses[following].start + 1]
        and bool(words(text, clauses[following].start, clauses[following].end))
    )


def _clause_hedged(text: str, clause: _Clause) -> bool:
    """Whether a clause holds a date hedge anywhere (see _assign_bare)."""
    return not _DATE_HEDGES.isdisjoint(words(text, clause.start, clause.end))


def _listing_day(text: str, mentions: list[Mention], assignment: _Assignment) -> _Assignment:
    """Give the day that ends a listing after a "no ..." note to the status before the note.

    "2 Hour Delay - No AM Pre-K 2/4" and "Closed-No Activities Tuesday, January
    27" state their status, say what else it means, and end with the day: the
    listing's day, the status's as much as the note's. So when the text's one
    date group ends it (but for a cause: "... Friday due to snow") and belongs
    to a note that starts with "no" ("no AM Pre-K", "no in-person classes"),
    or to a status a "no" denies ("Closed - no virtual tomorrow", "2 hr
    delay/no NTI Friday"), and the one status before the note names no day,
    the status takes that day too. So it does for any side note joined to the
    status by a dash alone, as such listings write it: "Closed-Activities
    Canceled Today" is closed today, whenever it is posted. The note must share
    the status's sentence: after a full stop it is a statement of its own ("2
    hour delay. No AM kindergarten tomorrow."). A note of another kind, or
    after another mark, keeps its day to itself: "Closed; concert cancelled
    Monday" leaves the closure's day unclear.
    """
    ((holder, held),) = assignment[_ASSIGNED_GROUPS].items()
    note = mentions[holder]
    # "no virtual", "not virtual": a status the "no" before it denies says what else the
    # status before it means, as a "no ..." note does.
    denied = note.dropped == "negated" and note.kind in _STATUS_KINDS
    says_no = text.startswith("no ", note.start) or (
        denied and _DENIED_BY_NO(text, max(note.start - 4, 0), note.start) is not None
    )
    if len(held) != 1 or not (
        says_no if denied else note.kind in _LISTING_NOTES and (says_no or note.kind == "note")
    ):
        return assignment
    group = held[0]
    rest = text[group[GROUP_END] :].lstrip(" .,;:!-")
    if rest and not rest.startswith(_CAUSE_OPENERS):
        return assignment  # (the day ends the text, or only its cause comes after it)
    statuses = [
        index
        for index, mention in enumerate(mentions)
        if mention.kind in _KIND_OF and mention.dropped is None and not mention.revoked
    ]
    if len(statuses) != 1 or statuses[0] >= holder:
        return assignment
    between = text[mentions[statuses[0]].end : note.start]
    if _SENTENCE_MARKS.intersection(between) or not (says_no or _DASH_JOINED(between)):
        # "2 hour delay. No AM kindergarten tomorrow." is a sentence of its own, and "Closed;
        # concert cancelled Monday" a note of its own.
        return assignment
    groups = {statuses[0]: [group], holder: [group]}
    return (groups, assignment[_ASSIGNED_HEDGED])


# The kinds of a "no ..." phrase that says what else a status means: a note ("no AM Pre-K"),
# or a phrase that could be a closure or remote learning ("no in-person classes").
_LISTING_NOTES = frozenset({"note", "ambiguous"})
# A "no" or a "not" right before a status it denies: the "no " of "closed - no virtual".
_DENIED_BY_NO = re.compile(r"(?<![a-z0-9'/-])not? \Z", re.ASCII).search
_CAUSE_OPENERS = ("due ", "because", "owing ")
_SENTENCE_MARKS = frozenset(".!?")
# A dash alone between a status and a note, before the note's subject: "closed-activities
# canceled today", "closed - evening activities canceled today".
_DASH_JOINED = re.compile(r" ?-+ ?(?:[a-z0-9'/-]+ )*", re.ASCII).fullmatch


def _hedged_out(assigned: dict[int, list[DateGroup]], hedged: set[DateGroup]) -> _Assignment:
    """Take the hedged date groups out of each mention's; note the mentions left with none."""
    hedged_only: set[int] = set()
    if hedged:
        for index, chosen in assigned.items():
            kept = [group for group in chosen if group not in hedged]
            if chosen and (not kept or (len(kept) < len(chosen) and chosen[0] in hedged)):
                # (A hedged day that heads a mention's other days, "Friday not decided yet:
                # Tue. Jan. 20: No classes", leaves which day it is for unclear.)
                hedged_only.add(index)
            chosen[:] = kept
    return (assigned, frozenset(hedged_only))


# Words in a clause of bare dates that add days, not restate them: "Closed today. Also Friday."
# And the marks that end a sentence, but a semicolon, after which a clause of bare dates with
# none of them is no status's ("Closed Thursday. Friday."; but "Closing at noon Wednesday;
# Thursday through Friday").
_FULL_STOP = re.compile(r"\.(?=\s|$)|[!?|]", re.ASCII)
_ADDING = frozenset({"also", "and", "plus", "again", "well", "too"})


def _restate(  # noqa: PLR0912, PLR0913, PLR0917 - the assignment state it reads and extends
    text: str,
    clause: _Clause,
    number: int,
    by_clause: dict[int, list[int]],
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    groups: list[DateGroup],
) -> bool:
    """Join a clause of bare dates to a dated status beside it ("Closed tomorrow. Jan. 22.").

    The clause restates the status's nearest date group, so the two are
    resolved as one group whose kinds of day must agree; with "also" or "and"
    it adds days to it instead. Whether there was such a status.
    """
    before = by_clause.get(number - 1, [])
    after = by_clause.get(number + 1, [])
    if before:
        index, at_end = before[-1], True
    elif after:
        index, at_end = after[0], False
    else:
        return False
    if not _dated_status(index, mentions, assigned):
        return False
    bare = groups[0]
    for group in groups[1:]:
        bare = join_groups(bare, group, "list")
    fillers = set(words(text, clause.start, clause.end))
    own = assigned[index]
    if at_end and bare[GROUP_OPEN_START] is not None:
        # "Closed Wednesday; through Friday" runs on to Friday. "Closed until further
        # notice; through Jan. 30" counts its days from the posting day, as "through Jan. 30"
        # alone does.
        if all(atom[ATOM_KIND] == "further_notice" for atom in own[-1][GROUP_ATOMS]):
            own.append(bare)
        else:
            own[-1] = join_groups(own[-1], (*bare[:4], None), bare[GROUP_OPEN_START])
        return True
    if at_end:
        last = own[-1]
        named = {_day_key(atom) for group in own for atom in group[GROUP_ATOMS]}
        if all(_day_key(atom) in named for atom in bare[GROUP_ATOMS]):
            return True  # "Closed Friday. Friday.": the days named again add nothing
        if (
            fillers.isdisjoint(_ADDING)
            and bare[GROUP_ATOMS][0][ATOM_KIND] in _NAMED_DAYS
            and not restates(last[GROUP_ATOMS][-1], bare[GROUP_ATOMS][0])
            and _FULL_STOP.search(text, last[GROUP_END], clause.start) is not None
        ):
            # "Closed Thursday. Friday.", "Closed Thursday. As for Friday, stay tuned.": a day of
            # a sentence of its own, with no word that adds it, says nothing of the status. It is
            # left out (see _said_again for one the status names already).
            return True
        if (
            text[last[GROUP_END] : clause.start].strip(" -") == ""
            and text.find("-", last[GROUP_END], clause.start) >= 0
        ):
            # "Closed today - Thursday and Friday" names the day again, as a colon does
            # ("Closed today: Thursday and Friday"), unless a word adds the days ("- also
            # Thursday"): the words that join the dates' own list add nothing.
            fillers = set(words(text, clause.start, groups[0][GROUP_START]))
            fillers.update(words(text, groups[-1][GROUP_END], clause.end))
        link: Link = _restating_link(last, bare, fillers)
        own[-1] = join_groups(last, bare, link)
    else:
        link = _restating_link(bare, own[0], fillers)
        own[0] = join_groups(bare, own[0], link)
    return True


def _restating_link(first: DateGroup, second: DateGroup, fillers: set[str]) -> Link:
    if fillers.isdisjoint(_ADDING) and restates(first[GROUP_ATOMS][-1], second[GROUP_ATOMS][0]):
        return "appos"
    return "list"


def _dated_status(
    index: int, mentions: list[Mention], assigned: dict[int, list[DateGroup]]
) -> bool:
    mention = mentions[index]
    return mention.kind in _STATUS_KINDS and mention.dropped is None and bool(assigned.get(index))


def _undated_status(
    index: int, mentions: list[Mention], assigned: dict[int, list[DateGroup]]
) -> bool:
    mention = mentions[index]
    return mention.kind in _STATUS_KINDS and mention.dropped is None and not assigned.get(index)


def _neighbour(
    number: int,
    clauses: list[_Clause],
    by_clause: dict[int, list[int]],
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
) -> int | None:
    """The mention a clause of bare dates belongs to: "Tuesday - closed" or "closed - Tuesday"."""
    following = [i for i in by_clause.get(number + 1, []) if _undated_status(i, mentions, assigned)]
    preceding = [i for i in by_clause.get(number - 1, []) if _undated_status(i, mentions, assigned)]
    if number == 0 and following:
        return following[0]
    if preceding and not clauses[number].strong:
        return preceding[-1]
    if following:
        return following[0]
    return preceding[-1] if preceding else None


def _across_scope(  # noqa: PLR0913, PLR0917 - the clause, and the assignment it reads
    text: str,
    clauses: list[_Clause],
    number: int,
    by_clause: dict[int, list[int]],
    dated: Container[int],
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
) -> int | None:
    """The status a clause of bare dates belongs to across a clause that says where or what else.

    Dates that head the text, or a sentence of it, then a clause that says
    where, then a status ("(Tomorrow) All locations - no classes", "Closed. Friday,
    Lincoln Elementary - 2 hour delay"), give the status its day, as in "Tomorrow
    - closed". So do dates that end the text after a status and a clause that
    says what else, or where ("Closed - no extended care; through April 24"), as
    in "Closed; through April 24". The clause between must hold no mention, no
    date and no word that could qualify a status (a hedge, a condition, a
    negation, an update), but for the "no" that opens a phrase of what else
    ("no extended care"), nor any that moves it from the school's day (a part
    of the day, a modifier, a noun for something else but after that "no", a
    word for part of the district but after "all": "(Tomorrow) Evening -
    closed", "Tomorrow, staff report - closed", "(Tomorrow) North campus -
    closed"), and no sentence mark may part it from the status: "Tomorrow, if
    the roads are icy - closed" and "Tomorrow. All locations. Closed." are not
    read so. Heading dates whose
    clause after the scope holds a mention of another kind are that mention's,
    as a day slot's are ("(Thursday) Lincoln Elementary - Open"). ``None`` when
    the dates are not so placed, or no such mention there names no day.
    """
    last = len(clauses) - 1
    # (A clause's ``strong`` says a sentence mark parts it from the clause before it.)
    if number + 2 <= last and (number == 0 or clauses[number].strong):
        between, holder = number + 1, number + 2
        parted = clauses[between].strong or clauses[holder].strong
    elif number == last and number >= 2:  # noqa: PLR2004 - the status and the clause between
        between, holder = number - 1, number - 2
        parted = clauses[between].strong
    else:
        return None
    if parted or between in by_clause or between in dated:
        return None
    scope = clauses[between]
    said = words(text, scope.start, scope.end)
    # "no extended care" says what else, of whatever noun; "no" alone answers. A word for part
    # of the district says where only after "all": "all locations", "all three campuses", not
    # "north campus" or "some locations".
    what_else = said[:1] == ["no"] and len(said) > 1
    every = said[:1] == ["all"]
    bars = _SCOPE_BARS if every else _SCOPE_BARS | _CARVE
    for word in said[1:] if what_else else said:
        if every and word in _COUNTS:
            continue  # ("all three campuses": every one of them)
        bits = _facts(word)[0]
        if (
            bits & bars
            or word in _COUNT_WORDS  # ("two campuses": some of them, as "some campuses" is)
            or (bits & _OTHER_SCOPE and not what_else and SCOPES.get(word) != "partial")
        ):
            return None  # ("Lincoln Elementary" names a school, as the scope rules read it)
    held = by_clause.get(holder, [])
    statuses = [i for i in held if _undated_status(i, mentions, assigned)]
    if holder < number:
        return statuses[-1] if statuses else None
    if statuses:
        return statuses[0]
    # "(Wednesday) Lincoln - Closed | (Thursday) Lincoln - Open": the slot's day.
    slots = [i for i in held if mentions[i].dropped is None and not assigned.get(i)]
    return slots[0] if slots else None


# The words that keep a clause between bare dates and a status from being the status's scope:
# a word that could qualify a status, a part of the day, or a word that moves a school noun
# elsewhere ("evening"). (A noun for something other than the school bars it too, but after a
# "no": see _across_scope.)
_SCOPE_BARS = _QUALIFIERS | _DATE_HEDGE | _QUALIFYING | _PART_WORD | _MODIFIER


def _slot_mention(
    text: str,
    number: int,
    clauses: list[_Clause],
    by_clause: dict[int, list[int]],
    mentions: list[Mention],
) -> int | None:
    """The mention of another kind that a clause of bare dates heads with a dash, if any.

    "Wednesday - Closed, Thursday - Open" and "Wednesday-Closed-Thursday-Open"
    give each day its slot: Thursday is the day the school is open, not one
    more day of the closure before it. (A status that names no day takes the
    day first: see :func:`_neighbour`.)
    """
    following = by_clause.get(number + 1)
    if not following or number + 1 >= len(clauses):
        return None
    if text[clauses[number].end : clauses[number + 1].start].strip() != "-":
        return None  # (a dash alone joins the day to its slot)
    index = following[0]
    mention = mentions[index]
    if mention.kind in _STATUS_KINDS or mention.dropped is not None:
        return None
    return index


def _side_neighbour(
    number: int,
    by_clause: dict[int, list[int]],
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
) -> int | None:
    """The mention of another kind a clause of bare dates belongs to, when no status's is: the
    last one before it that names no day ("Closed; offices open - Wednesday"), or the first
    one after it."""
    for index in reversed(by_clause.get(number - 1, [])):
        if mentions[index].dropped is None and not assigned.get(index):
            return index
    for index in by_clause.get(number + 1, []):
        if mentions[index].dropped is None and not assigned.get(index):
            return index
    return None


# Resolution -------------------------------------------------------------------------------


def _merge(kinds: set[str]) -> StatusKind | None:
    if kinds <= {"closed", "remote"}:
        return "remote" if "remote" in kinds else "closed"
    if kinds <= {"delayed", "early_dismissal"}:
        return "delayed" if "delayed" in kinds else "early_dismissal"
    if kinds <= {"remote", "delayed"}:
        return "remote"
    return None


def _only(values: list[int | None] | list[time | None]) -> int | time | None:
    distinct = {value for value in values if value is not None}
    return distinct.pop() if len(distinct) == 1 else None


type _Day = tuple[
    StatusKind,  # _DAY_KIND
    int | None,  # _DAY_DELAY
    time | None,  # _DAY_OPENS_AT
    time | None,  # _DAY_DISMISSAL
    int | None,  # _DAY_EARLY
    bool,  # _DAY_STATED
    bool,  # _DAY_FURTHER_NOTICE
]
_DAY_KIND: Final = 0
_DAY_DELAY: Final = 1
_DAY_OPENS_AT: Final = 2
_DAY_DISMISSAL: Final = 3
_DAY_EARLY: Final = 4
_DAY_STATED: Final = 5
_DAY_FURTHER_NOTICE: Final = 6


def _alike(claims: list[_Claim]) -> bool:
    """Whether a day's claims are all one status with the same details, none of them marked
    as replacing another or as replaced (see :func:`_day_status`)."""
    first = claims[0][_CLAIM_STATUS]
    if first[_IS_SUPERSEDING] or first[_IS_SUPERSEDED]:
        return False
    for claim in claims[1:]:
        status = claim[_CLAIM_STATUS]
        if (
            status[_KIND] != first[_KIND]
            or status[_IS_SUPERSEDING]
            or status[_IS_SUPERSEDED]
            or status[_DELAY] != first[_DELAY]
            or status[_OPENS_AT] != first[_OPENS_AT]
            or status[_DISMISSAL] != first[_DISMISSAL]
            or status[_EARLY] != first[_EARLY]
        ):
            return False
    return True


def _day_status(claims: list[_Claim], further_notice: bool) -> tuple[_Day, float] | None:
    claim = claims[0]
    status = claim[_CLAIM_STATUS]
    if len(claims) == 1 or _alike(claims):
        # One claim (the most common day), or claims that all say the same ("Tuesday
        # Morning: Closed | Tuesday Afternoon: Closed"): the status stands as it is.
        stated = claim[_CLAIM_STATED]
        confidence = claim[_CLAIM_CONFIDENCE]
        for other in claims[1:]:
            stated = stated or other[_CLAIM_STATED]
            confidence = max(confidence, other[_CLAIM_CONFIDENCE])
        fields = (
            status[_KIND], status[_DELAY], status[_OPENS_AT], status[_DISMISSAL], status[_EARLY],
            stated, further_notice,
        )  # fmt: skip
        return fields, confidence
    superseding = [c for c in claims if c[_CLAIM_STATUS][_IS_SUPERSEDING]]
    if len({c[_CLAIM_STATUS][_KIND] for c in superseding}) > 1:
        # "Update: 2 hour delay, now closed": the last update wins.
        last = max(c[_CLAIM_STATUS][_POSITION] for c in superseding)
        superseding = [c for c in superseding if c[_CLAIM_STATUS][_POSITION] == last]
    top = superseding or [c for c in claims if not c[_CLAIM_STATUS][_IS_SUPERSEDED]] or claims
    kind = _merge({claim[_CLAIM_STATUS][_KIND] for claim in top})
    if kind is None:
        return None
    delay = _only([c[_CLAIM_STATUS][_DELAY] for c in top])
    opens = _only([c[_CLAIM_STATUS][_OPENS_AT] for c in top])
    dismissal = _only([c[_CLAIM_STATUS][_DISMISSAL] for c in top])
    early = _only([c[_CLAIM_STATUS][_EARLY] for c in top])
    day = (
        kind,
        delay if isinstance(delay, int) else None,
        opens if isinstance(opens, time) else None,
        dismissal if isinstance(dismissal, time) else None,
        early if isinstance(early, int) else None,
        any(claim[_CLAIM_STATED] for claim in top),
        further_notice,
    )
    confidence = max(claim[_CLAIM_CONFIDENCE] for claim in top)
    if len(top) < len(claims):
        confidence = min(confidence, JUDGMENT)
    return day, confidence


# The bits of the words that some steps after the dates are read need: a weekend day (see
# _weekend_programs), a part of the day (_part_days), a colon (_share_headings).
_TAIL_WORDS = _WEEKEND | _PART_WORD | _COLON
_NO_NARROWED: frozenset[str] = frozenset()  # (no status about part of the program)


type _WeatherFields = tuple[
    tuple[str, ...], bool, Reason | None, tuple[Reason, ...], tuple[str, ...]
]


def _weather_fields(
    normalized: str, bits: int, weather_runs: list[tuple[int, _Runs]]
) -> _WeatherFields:
    """What the text says of the weather, as the result's fields (see _Analysis.weather)."""
    weather_hints = bits >> _WEATHER_SHIFT & _WEATHER_BITS
    if not bits & _POWER and not (weather_hints and weather_candidate_in(normalized, weather_runs)):
        # ("power" or "blackout": see _text_bits. With neither, and no run that can start a
        # term or a cause, find_weather finds nothing: see weather.candidate_in.)
        return _NO_WEATHER
    weather = find_weather(
        normalized, hints=weather_hints, runs=weather_runs, names=bool(bits & _NAME_KIND)
    )
    if weather is _NO_FINDINGS:
        return _NO_WEATHER
    if (
        weather.reasons
        and bits & _MAKE_UP
        and _MADE_UP_FOR_WEATHER(normalized) is not None
        and _CAUSE_SAID(normalized) is None
    ):
        # "Closed - snow make-up day": a day that makes up a snow day, not one weather caused.
        return (weather.terms, bool(weather.terms), None, (), weather.other_causes)
    return (
        weather.terms,
        bool(weather.terms),
        weather.reasons[0] if weather.reasons else None,
        weather.reasons,
        weather.other_causes,
    )


# A day that makes up one weather took ("snow make-up day", "snow day makeup"), and the words
# that say what caused a status ("due to snow"), which keep the reason.
_MADE_UP_FOR_WEATHER = re.compile(
    r"\b(?:snow|ice|icy|weather|storm|cold|flood|hurricane)(?:\s+days?)?\s+make[-\s]?ups?\b",
    re.ASCII,
).search
_CAUSE_SAID = re.compile(r"\b(?:due|because|owing|caused)\b", re.ASCII).search


def _without_mentions(  # noqa: PLR0913, PLR0917 - what the text's reading found
    normalized: str,
    bits: int,
    hints: int,
    groups: tuple[DateGroup, ...],
    months: int,
    weather_runs: list[tuple[int, _Runs]],
) -> _Analysis:
    """The analysis of a text with no status phrase (see :func:`_analyse_normalized`).

    Nothing is settled or dated: only the text's days that no pattern reads, and
    its weather, count. (With no status, weekday names can come in any order,
    as :func:`~snowlight.classify.dates.weekdays_out_of_order` reads the days of
    statuses; a weekend program needs a closure; no closure is limited to part of
    a day.)
    """
    if (hints & UNREADABLE_HINTS or bits & _DOT_PAIR) and unreadable_possible(normalized, hints):
        unreadable = find_unreadable(
            normalized, groups, _protected(groups, []), None, hints, months=months
        )
    else:
        unreadable = bool(hints & MONTH_WORD) and months > sum(
            atom[ATOM_NAMED] for group in groups for atom in group[GROUP_ATOMS]
        )
    notes: set[Note] = {"unreadable_date"} if unreadable else set()
    if normalized:
        notes.add("unrecognized")
    weather_fields = _weather_fields(normalized, bits, weather_runs)
    frozen = frozenset(notes) if notes else _NO_NOTES
    ordered = tuple(sorted(notes)) if notes else ()
    confidence = _unstated_confidence(
        normalized, frozen, ambiguous=False, says_open=False, offices_open=False
    )
    result = _new(
        ParsedStatus,
        (
            "other", (), None, None, None, None, False, False, (), *weather_fields, confidence,
            False, False, ordered,
        ),
    )  # fmt: skip
    return (
        normalized, (), frozen, False, False, False, False, False, weather_fields, None, None,
        ordered, (), (), result, None, groups if bits & _DIGITS else (), (), None,
    )  # fmt: skip


# What reading a text's stretches between spaces gives (see _raw_analysis): the facts of each
# stretch, in order, and the union of their bits.
type _Prepared = tuple[list[_ChunkFacts], int]


def _analyse_normalized(  # noqa: PLR0912, PLR0915 - one pass
    normalized: str, prepared: _Prepared | None = None
) -> _Analysis:
    if prepared is None:
        facts = list(map(_chunk_lookup, normalized.split(" ")))
        bits = 0
        for stretch in facts:  # (a loop costs less than reduce, per stretch)
            bits |= stretch[0]
    else:
        facts, bits = prepared
    # Where each scan can start, and which rules can start there (see _chunk_facts): the
    # status phrases and the date scan run by run, each with its start mask (see
    # mentions.mentions_at), the weather scan by the stretch that holds them, where it starts
    # (see text.Pieces).
    phrase_runs: list[tuple[int, int]] = []
    date_runs: list[tuple[int, int]] = []
    weather_runs: list[tuple[int, _Runs]] = []
    # What only some stretches hold (see _chunk_facts): where the words with a scope noun's
    # run start and end (see _Context); where each run that ends a status's words starts, and
    # its length (see _region_end); each stretch with a clause mark (see _clauses_at); the
    # stretches with a word of _NOTED (see _noted_words); and how many month names there are.
    noun_starts: list[int] = []
    noun_ends: list[int] = []
    stops: list[tuple[int, int]] = []
    separators: _Separators = []
    noted: list[tuple[int, str]] = []
    months = 0
    position = 0
    for _bits, width, phrased, dated, weathered, rare, _chunk in facts:
        if phrased:
            phrase_runs.append((position, phrased))
        if dated:
            date_runs.append((position, dated))
        if weathered:
            weather_runs.append((position, weathered))
        if rare is not None:
            nouns, marks, noted_chunk, rarer = rare
            if nouns:
                for low, high in nouns:
                    noun_starts.append(position + low)
                    noun_ends.append(position + high)
            if marks is not None:
                separators.append((position, width - 1, marks))
            if noted_chunk is not None:
                noted.append((position, noted_chunk))
            if rarer is not None:
                stop_runs, month_count, more_phrased, more_dated = rarer
                for offset, length in stop_runs:
                    stops.append((position + offset, length))
                months += month_count
                for offset, mask in more_phrased:
                    phrase_runs.append((position + offset, mask))
                for offset, mask in more_dated:
                    date_runs.append((position + offset, mask))
        position += width
    hints = bits >> _DATE_SHIFT & HINT_BITS
    flags = bits & _OWN_BITS  # the kinds of word the text holds (one small number: see there)
    rare_bits = bits >> _RARE_SHIFT  # the gate's kinds of word, and the rare words' (as small)
    # (As find_date_groups and find_mentions read them, called directly: see there.)
    groups = date_groups_at(normalized, date_runs) if hints & DATE_START else ()
    # A time needs a digit or "noon"; a length before "early" needs "early".
    clocks = flags & (_DIGITS | _NOON)
    rules = bits >> _RULE_SHIFT & (RULE_BITS if clocks else _CLOCKLESS_RULES)
    mentions = found = (
        mentions_at(normalized, rules, phrase_runs, flags & _INSTITUTION) if rules else []
    )
    # Whether a count in words or figures comes before a noun of schools or places (see
    # _COUNTED and _COUNT_SCHOOLS), and whether the text can promise an update (see
    # _update_promised).
    counted = promised = False
    if mentions:
        if rare_bits & _PREFIXED_RARE:
            _prefixed_statuses(normalized, mentions)  # "Non-closed", "Post-closure update"
        # "Payroll delayed", "Dismissal delayed", "School pictures cancelled": a status word
        # about something besides the school's day is a side note (see classify.subjects).
        settle_subjects(normalized, mentions)
        if rare_bits & _MID_RARE:  # (one test for the rare words: most texts have none)
            if rare_bits & _CAUSE_RARE:
                _caused_statuses(normalized, mentions)
            if rare_bits & _POLICY_RARE and _POLICY_HINT(normalized) is not None:
                _policies(normalized, mentions)  # "Any closure tomorrow will be an eLearning day"
            if rare_bits & _HEADING_RARE and _HEADING_HINT(normalized) is not None:
                _headings(normalized, mentions)  # "Closings and delays", "The following schools"
            if rare_bits & _COUNT_WORD_RARE:
                counted = _COUNTED(normalized) is not None
            if rare_bits & _PROMISE_RARE:
                promised = _PROMISE_HINT(normalized) is not None
            if (
                rare_bits & _COUNTED_RARE  # (most texts hold no noun of places)
                and flags & _DIGITS
                and not counted
                and _COUNT_SCHOOLS(normalized) is not None
            ):
                counted = True  # "Classes cancelled at 2 schools": a count in figures (carved)
        if "," in normalized and (
            (normalized[:2] in _POLICY_LEAD_STARTS and normalized.startswith(_POLICY_LEADS))
            or (". " in normalized and _POLICY_INNER(normalized) is not None)
        ):
            _policies(normalized, mentions)  # "On a 2 hour delay, buses run 2 hours late"
    if not mentions and _FAST_PATH:
        return _without_mentions(normalized, bits, hints, groups, months, weather_runs)
    # One status with nothing that qualifies it: settling changes nothing, and its dates
    # are assigned as within its own clause (with no dates, the clauses are not needed).
    if len(mentions) == 1:
        lone = (
            _lone_status(normalized, mentions, flags, noted, rare_bits, counted)
            if _FAST_PATH
            else False
        )
    else:
        _closing_times(mentions)
        lone = False  # (see _lone_status)
    clauses: list[_Clause] | None = None
    home: _Clause | None = None  # the lone status's clause
    revoked_by: dict[int, int] = _NO_REVOKED
    held: list[_Opening] | None = None  # the days a clause says school is held on (_held_day)
    if lone is None or (lone and groups):
        clauses = _split(normalized, groups, mentions, separators)
        home = clauses[_home(clauses, mentions[0].start)]
        if not lone:
            lone = _quiet_clause(normalized, home, mentions[0], noted)
        if lone and groups:
            lone = _dates_beside(clauses, mentions[0], groups)
    if lone and flags & _SUPERSEDING and _change_cues(normalized, mentions[0].end):
        lone = False  # "2 hr delay - now a full day": a change after it (see _changes)
    if not mentions:
        # Nothing to settle or date: only the text's days, weather and unread days count.
        notes: set[Note] = set()
        offices_open = says_open = False
        assignment = _NO_ASSIGNMENT
    elif lone:
        notes = set()
        offices_open = says_open = False
        assignment = _NO_ASSIGNMENT
        if groups and home is not None:  # (a lone status with dates splits the text above)
            lone_groups: dict[int, list[DateGroup]] = {}
            _assign_in_clause(normalized, home, (0,), mentions, groups, lone_groups, stops)
            assignment = (lone_groups, _NO_INDEXES)
    else:
        if clauses is None:
            clauses = _split(normalized, groups, mentions, separators)
        masked = (
            _without_dates(normalized, groups, parts=bool(flags & _PART_WORD))
            if groups
            else normalized
        )
        if rules & _REVOKING_RULES and may_revoke(mentions):  # (rules hold every revoking one)
            # "2 hour delay cancelled": the words that call a status off, and what they call off.
            mentions, revoked_by = pair_revocations(masked, clauses, mentions, groups)
        homes = [0] * len(mentions) if len(clauses) == 1 else _homes(clauses, mentions)
        held = []
        notes, offices_open, says_open = _settle(
            masked, clauses, mentions, homes, flags, (noun_starts, noun_ends), rare_bits
        )
        if (
            says_open
            or (rare_bits & _OPTION_RARE and any(mention.kind == "remote" for mention in mentions))
        ) and _remote_option(normalized, mentions):
            notes.add("hedged")  # "Open; virtual option available": see _remote_option
        if flags & _NEGATION and not groups:
            _parallel_no(normalized, mentions, notes)
        assignment = _assign_dates(
            normalized, clauses, mentions, homes, groups, bool(flags & _DATE_HEDGE), stops, held
        )
        if (
            len(groups) == 1
            and len(assignment[0]) == 1
            and ("no " in normalized or "-" in normalized or "not " in normalized)
        ):
            assignment = _listing_day(normalized, mentions, assignment)
        if rare_bits & _PROMISE_RARE and len(groups) > 1 and ": " in normalized:
            # "UPDATE 1/21: closure extended through Friday 1/23": the update's date.
            _update_dates(normalized, assignment[0])
        if flags & _SUPERSEDING:
            # "2 hour delay is now a full day": a status changed into nothing read.
            _changes(normalized, masked, mentions, groups, assignment[0], notes)
        if rare_bits & _TO_RARE and (
            " to " in normalized
            or " into " in normalized
            or "ed for " in normalized
            or "ed with " in normalized
            or " favor of " in normalized
            or " favour of " in normalized
        ):
            # "Closure cut to a 2 hour delay": two statuses no change rule orders.
            _unordered_changes(normalized, mentions, assignment[0], notes)
    # "All schools closed except Lincoln Elementary", "Closed north of Route 9", "North campus
    # closed": statuses for part of the district (see snowlight.classify.partial). An
    # exception for a day ("Closed all week except Wednesday") leaves the days unread.
    days_left_out = False
    if (flags & _CARVE or counted) and mentions:
        limited, days_left_out = carved(normalized, mentions, groups)
        for index in limited:
            mention = mentions[index]
            if mention.kind == "open":
                says_open = False  # "Open except Lincoln Elementary": not every school is
                mention.narrowed = "open"
                notes.add("partial_program")
            else:
                notes.add(_apply_scope(mention, "partial") or "partial_program")
        if limited:
            # "Lincoln Elementary closed. All other schools on a 2 hour delay.": the school
            # named is one of the district's too.
            _demote_names(mentions, notes)
    # (A full stop between two digits, "1.21", is the one form of an unread day with no hint.)
    if (hints & UNREADABLE_HINTS or flags & _DOT_PAIR) and unreadable_possible(normalized, hints):
        unreadable = find_unreadable(
            normalized, groups, _protected(groups, found), None, hints, months=months
        )
    elif months and hints & MONTH_WORD:
        # Only a month name can be a day the patterns do not read: one that no date holds.
        unreadable = months > sum(
            [atom[ATOM_NAMED] for group in groups for atom in group[GROUP_ATOMS]]
        )
    else:
        unreadable = False
    # A day left out of a run, a day number misread or a day still to come, or a year alone
    # (see _misread_day). (One test of the rare bits for the last three: most texts have none.)
    if not unreadable and (
        days_left_out
        or (
            rare_bits & _MISREAD_OR_YEAR_RARE
            and mentions
            and _misread_day(normalized, mentions, groups, flags, rare_bits)
        )
    ):
        unreadable = True
    # Two weekdays or more can be out of order, or place one another (see _two_weekdays).
    weekdays = False
    if groups and (len(groups) > 1 or len(groups[0][2]) > 1):  # (a group's atoms: its third)
        weekdays = _two_weekdays(groups)
    # The weekdays that head a closings page's slots, whatever the slot says ("Thursday: Open",
    # "Thursday Evening: No Evening Activities"): days in the text's order as much as the
    # statuses' own (see _weekday_headings). With one weekday they only name it again.
    headings = (
        _weekday_headings(normalized, groups)
        if weekdays and flags & _COLON and len(groups) > 1
        else _NO_HEADINGS
    )
    if (
        not unreadable
        and weekdays
        and weekdays_out_of_order(_with_headings(_status_groups(mentions, assignment), headings))
    ):
        unreadable = True
    assigned, hedged = assignment
    parts = _NO_PARTS
    if unreadable:
        # A day the text names but the parser cannot read: any status could be for that day.
        notes.add("unreadable_date")
        offices_open = says_open = False
    elif flags & _TAIL_WORDS:  # (a weekend day, a part of the day, or a colon)
        if flags & _COLON and flags & _PART_WORD and " afternoon" in normalized:
            _afternoon_slot_days(normalized, mentions, assigned)
        if flags & _WEEKEND:
            _weekend_programs(normalized, mentions, assigned, notes)
        if flags & _PART_WORD and (flags & _PART_SURE or _PART_HINT.search(normalized) is not None):
            parts = _part_days(
                normalized,
                mentions,
                assignment,
                groups,
                notes,
                bool(clocks and rare_bits & _LEADING_RARE),
            )
            if parts[_PARTS_UNCLEAR]:
                # "Closed tomorrow morning, open in the afternoon": unclear, but no school
                # running as normal either.
                says_open = False
        if not lone and len(mentions) > 1 and groups and flags & _COLON:
            _share_headings(normalized, mentions, assignment, groups, parts)
    bounds, reopenings, taken, ambiguous, unclear_dated = parts
    # "2 hour delay for elementary. 1 hour delay.": the length depends on the school.
    narrowed: AbstractSet[str] = _NO_NARROWED
    for mention in mentions:
        if mention.dropped is not None:
            continue
        if mention.revoked:
            notes.add("revoked")  # called off, whatever it was about
            continue
        if mention.narrowed is not None:
            narrowed = {*narrowed, mention.narrowed}
        if mention.kind == "ambiguous":
            ambiguous = True
    statuses: list[_Status] = []
    # (Most statuses stand as their words say: with nothing bounded, hedged, taken, narrowed or
    # called off in the text, a closure or a remote day that is neither dropped, called off nor
    # the rest of the posting day has no detail to read, and goes in as it is.)
    # (No part of a day read means nothing bounded or taken: see _part_days. As statements, the
    # tests cost less than as one expression.)
    plain = False
    if parts is _NO_PARTS and not hedged and not narrowed and not revoked_by:
        plain = _FAST_PATH
    # The days a status denied names besides today, which a status naming none is for ("No
    # closure tomorrow; 2 hour delay instead"); () when those of a status only possible, or two
    # denied statuses' days, leave it unclear ("Possible closure Friday. 2 hour delay").
    dropped_days: tuple[DateGroup, ...] | None = None
    for index, mention in enumerate(() if unreadable else mentions):
        kind = _KIND_OF.get(mention.kind)
        if kind is None:
            if not mention.revoked or mention.kind != "ambiguous":
                continue
            kind = "closed"  # a closing called off ("Closing rescinded") is a closure called off
        elif (
            plain
            and kind in _UNTIMED
            and mention.dropped is None
            and not mention.revoked
            and not mention.today
        ):
            own = assigned.get(index, ())
            plain_fields: _Status = (
                kind, mention.start, mention.strength, mention.delay, mention.opens_at,
                mention.dismissal, mention.early, mention.superseding, mention.superseded,
                _restated(normalized, own) if len(own) > 1 else tuple(own), False, False, None,
            )  # fmt: skip
            statuses.append(plain_fields)
            continue
        if mention.dropped is not None or index in taken or index in hedged:
            if index in hedged:
                notes.add("hedged")
            if index not in taken and dropped_days != ():
                own = assigned.get(index, ())
                if own and not _today_only(own):
                    dropped_days = (
                        tuple(own) if dropped_days is None and mention.dropped == "negated" else ()
                    )
            continue
        if bounds:
            bound = bounds.get(index)
            if bound is not None:
                reopening = reopenings.get(index)
                statuses += _part_statuses(
                    normalized,
                    mention,
                    bound,
                    assigned.get(index, ()),
                    None if reopening is None else mentions[reopening],
                    narrowed,
                    notes,
                )
                continue
        if kind in _TIMED and _may_harvest(mention, normalized, clocks):
            harvest_details(mention, normalized, _detail_end(normalized, mentions, index))
        own = assigned.get(index, ())
        strength = mention.strength
        if kind == "delayed" and len(own) == 1 and own[0][GROUP_OPEN_START] == "until":
            # (Both readings below need one group that opens with "until".)
            if _delayed_until_day(normalized, mention, own):
                # "School delayed until Monday": no school before Monday, not a late start.
                kind = "closed"
                strength = min(strength, JUDGMENT)
            elif _later_today(normalized, own[0]):
                # "Delayed until this afternoon", "Opening delayed until noon today": the
                # school opens later today, so the delay is today's, not the days before it.
                own = [(*own[0][:GROUP_OPEN_START], None)]
        if narrowed and kind in narrowed:
            mention.delay = mention.opens_at = mention.dismissal = mention.early = None
        if mention.revoked and revoked_by.get(index) in assigned:
            # "Cancelled tomorrow's delay": the date sits with the word that calls it off.
            own = sorted([*own, *assigned[revoked_by[index]]], key=_group_start)
        if mention.today:
            # "Closed for the rest of the day": the posting day, whenever it was posted.
            rest = _rest_of_today(normalized, mention, own)
            if rest is not None:
                statuses += rest
                continue
        if kind == "early_dismissal":
            if (
                own
                and normalized.startswith(_CLOSURE_VERBS, mention.start)
                and "early" not in normalized[mention.start : mention.end]
                and _is_run(own)
            ):
                # "Closing at 1:00 PM today through Friday": see _first_of_run. ("Closing
                # early Wednesday thru Friday" closes early each day.)
                own, strength = _first_of_run(normalized, own), min(strength, JUDGMENT)
                notes.add("ambiguous")
                if not own:
                    continue
            if "day" in normalized and _several_days(own):
                whole = _all_day(normalized, mention, own)
                if whole is not None:
                    own, closed = whole  # "Closing at 11:30 Wednesday and all day Thursday"
                    fields: _Status = (
                        "closed", mention.start, mention.strength, None, None, None, None,
                        mention.superseding, mention.superseded, _restated(normalized, closed),
                        False, False, None,
                    )  # fmt: skip
                    statuses.append(fields)
        status_groups = _restated(normalized, own) if len(own) > 1 else tuple(own)
        statuses.append(
            (
                kind,
                mention.start,
                strength,
                mention.delay,
                mention.opens_at,
                mention.dismissal,
                mention.early,
                mention.superseding,
                mention.superseded,
                status_groups,
                False,
                mention.revoked,
                None,
            )
        )
    openings: tuple[_Opening, ...] = ()
    # (Most texts hold one status, a day at most and nothing the steps below read: those
    # steps change nothing then, so one test of what each of them needs comes first.)
    if statuses and (
        len(statuses) > 1
        or len(groups) > 1
        or (notes and "negated" in notes)
        or narrowed
        or says_open
        or held
        or unclear_dated
        or dropped_days is not None
        or bits & _LATE_STEP_BITS
        or statuses[0][_IS_SUPERSEDED]
        or (groups and (groups[0][3] or "not " in normalized or rare_bits & _CONTINUE_RARE))
    ):
        if (
            statuses
            and len(groups) > 1
            and ("thr" in normalized or "til" in normalized or "week" in normalized)
            and _late_run(groups)
        ):  # (an open start needs "thr" or "til" before it, and a week "week": see dates)
            # "Closed tomorrow. Closed through Friday.": a run with no first day of its own after a
            # day a status names starts on that day, not on the posting day.
            statuses = _anchored_runs(mentions, assigned, statuses)
        if statuses and groups and rare_bits & _CONTINUE_RARE:
            # "Will close at 5 p.m. today and remain closed through Friday": see
            # _continued_closures.
            statuses = _continued_closures(normalized, groups, statuses, notes)
        if narrowed and statuses:
            # "Closed. Lincoln Elementary open.", "Closed - high school open", "Closed. Lincoln
            # Elementary on a 2 hour delay.": part of the district has a status of its own beside
            # the district's, which is then no status of the whole district (see _partly_otherwise).
            kept = _partly_otherwise(normalized, mentions, assigned, statuses)
            if len(kept) < len(statuses):
                notes.add("partial_program")
                statuses = kept
        if (
            statuses
            and flags & _OPENING
            and rare_bits & _WITHDRAWAL_RARE  # (one of its words: see _text_bits)
            and _WITHDRAWAL_CUES.search(normalized) is not None
        ):
            # "Closed tomorrow. Update: posted in error.", "Disregard Friday": see _withdrawals.
            statuses, withdrawn = _withdrawals(normalized, mentions, groups, statuses, notes)
            if withdrawn:
                held = [*(held or ()), *withdrawn]
        if statuses and groups:
            denied: tuple[_Opening, ...] = ()
            if "not " in normalized:
                # "Closed today and not tomorrow": the day after "not" is not the status's.
                statuses, denied = _without_denied_days(
                    normalized, statuses, notes, groups, assigned
                )
            if rare_bits & _OR_RARE and statuses and (" or" in normalized or "/or" in normalized):
                # "Closed tomorrow or Friday": one day or the other, not both.
                statuses = _without_alternative_days(normalized, statuses, groups, notes)
            if (
                rare_bits & _ONLY_RARE  # ("only" or "just" in the text: see _text_bits)
                and statuses
                and _only_near(normalized, groups, statuses)
            ):
                # "Closed today and tomorrow. Update: closed today only.": see _only_days.
                before = statuses
                statuses = _only_days(normalized, statuses, notes)
                if statuses and _only_elsewhere(normalized, statuses, groups, assigned):
                    notes.add(
                        "ambiguous"
                    )  # "Closed Thursday and Friday. Correction - only Thursday"
                    statuses = []
                elif statuses is before and _only_unread(normalized, statuses, groups):
                    notes.add(
                        "ambiguous"
                    )  # "Closed today and tomorrow. The only day closed is today"
                    statuses = []
            # "Closed Thursday and Friday. Open Friday.": see _Opening. (Every opening holds "open",
            # "resum", "assess" or a word of _RETURN_HINT, or is an "open" that settling read as
            # the school's: "on time" and the like; every denial is a status negated or a day
            # after "not".)
            if statuses and (says_open or flags & _OPENING or denied or "negated" in notes):
                denials = "negated" in notes
                openings = (
                    _openings(normalized, mentions, assignment, groups, statuses, denials=denials)
                    + denied
                )
            if held and statuses:
                openings += tuple(held)  # "Closed Thursday and Friday. School Friday."
        if statuses and clauses is not None:
            for group in groups:  # (a loop costs less than any(), per text)
                if not group[3]:
                    continue  # one day: no list (a group's links are its fourth field)
                if _carried_elsewhere(
                    normalized, clauses, mentions, statuses, groups, revoked_by, openings
                ):
                    # "Closed today, tomorrow and Friday open": the last days could be the open
                    # word's.
                    statuses = []
                    notes.add("ambiguous")
                    offices_open = says_open = False
                break
        if statuses:
            if says_open:
                statuses = _retracted(normalized, mentions, assigned, statuses, notes)
            if dropped_days and not unclear_dated and statuses:
                statuses = _lent_days(statuses, dropped_days)
            elif (unclear_dated or dropped_days is not None) and statuses:
                # "Closed tomorrow morning. No school.": the text names a day for a closure it
                # leaves unclear, so a status that names no day could be for that day as much as
                # any; so does one that names a day for a status denied or only possible ("No
                # closure tomorrow; 2 hour delay instead", "Possible closure Friday. 2 hour delay").
                kept = [status for status in statuses if _names_days(status)]
                if len(kept) < len(statuses):
                    notes.add("undated")
                    statuses = kept
            if statuses and statuses[0][_IS_SUPERSEDED] and _all_superseded(statuses):
                statuses = _past_reports(statuses, notes)
            if len(statuses) > 1:
                statuses, left_out = _fold_undated(statuses)
                if left_out:
                    notes.add("undated")
    doubts = (
        _doubts(normalized, mentions, assignment)
        if ambiguous and statuses and not unreadable
        else ()
    )
    if notes and "hedged" in notes and statuses and clauses is not None and not unreadable:
        # "Closed Monday and Tuesday. Tuesday's closure may be lifted.": a day a status only
        # possible names is no day of the statuses for sure (see _hedged_doubts).
        doubts += _hedged_doubts(normalized, mentions, assignment, clauses, groups, statuses)
    side_days = (
        _hints(normalized, mentions, assigned) if len(mentions) > len(statuses) and assigned else ()
    )
    window: tuple[int, int] | None = None
    anchor: tuple[int, int, str | None] | None = None
    named = 0  # date groups the statuses name
    for status in statuses:
        if status[_REVOKED]:
            continue  # called off: it names no day of the school's, and needs none from the post
        status_groups = status[_GROUPS]
        if not status_groups or status_groups[0][GROUP_ATOMS][0][ATOM_KIND] == "further_notice":
            window = _widen(window, status[_KIND], status_groups)  # (else it names its days)
        named += len(status_groups)
    if window is not None and clauses is not None and len(clauses) > 1 and len(groups) > named:
        # "Wednesday Afternoon: UPDATE; Closed": a heading of days that no status takes still
        # names a day, which a status that names none may be for (see _orphan_days).
        orphans = _orphan_days(normalized, clauses, groups, assigned, statuses)
        if orphans:
            side_days = (*side_days, *orphans)
    if named > 1:  # one group: nothing comes before its own weekday
        for status in statuses:
            if status[_GROUPS] and not status[_REVOKED]:
                anchor = _last_weekday(anchor, status[_GROUPS])
    if headings and named:
        # "Wednesday: Closed...... Thursday: Open on time": a day heading after a status's day
        # is a later day, whatever its slot says (posted on a Thursday, closed yesterday).
        anchor = _heading_anchor(anchor, statuses, headings)
    # (Every day a weekday name alone: a first status that names another day, the most common,
    # leaves none, so its first atom is looked at first. See _weekday_lead.)
    lead = None
    if named:
        head = statuses[0]
        head_groups = head[_GROUPS]
        if (
            head[_REVOKED]
            or head[_FLOATING]
            or (head_groups and head_groups[0][GROUP_ATOMS][0][ATOM_KIND] == "weekday")
        ):
            lead = _weekday_lead(statuses, headings)
    if ambiguous:
        notes.add("ambiguous")
    if not mentions and normalized:
        notes.add("unrecognized")
    weather_fields = (
        _weather_fields(normalized, bits, weather_runs)
        if bits & _WEATHER_OR_POWER  # (or "power" or "blackout": see _text_bits)
        else _NO_WEATHER
    )
    # The precision gate (see classify.gate): a sentence that bears on a status and holds a
    # word no rule reads, or a statement no rule read, could say anything of it.
    gated: ParsedStatus | None = None
    unstated: float | None = None  # the confidence of a result of no status, once worked out
    if bits & _ANY_GATE_TEXT:  # (_ANY_GATE_OWN or _ANY_GATE_RARE, in the text's bits)
        if statuses:
            # A sentence that bears on them holds a word no rule reads (see _unread), or a
            # clause says something of them that no rule read (see _unread_statement): a
            # statement's word, a question, "is on", "school day", or a phrase that says the
            # school is open ("open", "on time"; its other words are statements': "regular
            # schedule", "in session") after a status.
            stop: Note | None = None
            if (flags & _NAME_WORD or rare_bits & _UNREAD_RARE) and _unread(
                normalized, mentions, groups
            ):
                stop = "unread_words"
            elif (
                rare_bits & _STATEMENT_RARE
                or (
                    rare_bits & _HELD_RARE
                    and (
                        "?" in normalized
                        or " is on" in normalized
                        or " are on" in normalized
                        or "school day" in normalized
                        or "day of school" in normalized
                        or "have school" in normalized
                        or "have class" in normalized
                        or "be school" in normalized
                        or "be class" in normalized
                    )
                )
                or (
                    len(mentions) > len(statuses)
                    and (flags & _OPENING or "on time" in normalized)
                    and _opens_after(mentions, statuses, assigned)
                )
            ):
                stop = _unread_statement(normalized, mentions, groups, openings, statuses, assigned)
            if stop is not None:
                gated = _gated_result(normalized, notes, weather_fields, stop, ambiguous=ambiguous)
        elif flags & _NAME_WORD or rare_bits & _UNREAD_RARE:
            if notes and not (says_open or offices_open):
                unstated = _unstated_confidence(
                    normalized, notes, ambiguous=ambiguous, says_open=False, offices_open=False
                )
            if (
                says_open or offices_open or (unstated is not None and unstated >= INFERRED)
            ) and _unread(normalized, mentions, groups):
                # (A confident "other" too: "Offices open tomorrow for the parade".)
                notes.add("unread_words")
                offices_open = says_open = False
                unstated = None
    if gated is None and statuses:
        # A later sentence that names a status's day again (see _said_again). (Statuses stand
        # in text order: a day after the first one's start can be said again.)
        stop = (
            _said_again(normalized, mentions, groups, statuses, hedged, openings)
            if len(groups) > 1 and groups[-1][GROUP_START] > statuses[0][_POSITION]
            else None
        )
        if stop is None and (
            promised or rare_bits & _LATE_GATE_RARE or (notes and "negated" in notes)
        ):
            stop = _later_stop(
                normalized,
                mentions,
                groups,
                statuses,
                assigned,
                notes,
                rare_bits,
                promised=promised,
            )
        if stop is not None:
            gated = _gated_result(normalized, notes, weather_fields, stop, ambiguous=ambiguous)
    if notes:
        frozen: frozenset[Note] = frozenset(notes)
        ordered: tuple[Note, ...] = tuple(sorted(notes))
    else:
        frozen, ordered = _NO_NOTES, ()
    result = (
        None
        if statuses
        else _new(
            ParsedStatus,
            (
                "other",
                (),
                None,
                None,
                None,
                None,
                False,
                False,
                (),
                *weather_fields,
                _unstated_confidence(
                    normalized,
                    frozen,
                    ambiguous=ambiguous,
                    says_open=says_open,
                    offices_open=offices_open,
                )
                if unstated is None
                else unstated,
                says_open,
                offices_open,
                ordered,
            ),
        )
    )
    return (
        normalized,
        tuple(statuses),
        frozen,
        bool(mentions),
        ambiguous,
        bool(narrowed),
        offices_open,
        says_open,
        weather_fields,
        window,
        anchor,
        ordered,
        side_days,
        doubts,
        result,
        lead,
        # (A text with no digit has no day number for a template to change: see _shared_analysis.
        # One atom at most, the most common, holds one date at most.)
        groups if flags & _DIGITS else (),  # (see _ONE_DATE)
        openings,
        gated,
    )


def _open_run(group: DateGroup) -> bool:
    """Whether ``group`` is a run with no first day of its own: "through Friday", "until
    Monday", "the rest of the week", "all week" (counted from the posting day alone)."""
    return group[GROUP_OPEN_START] is not None or group[GROUP_ATOMS][0][ATOM_KIND] == "week"


def _late_run(groups: tuple[DateGroup, ...]) -> bool:
    """Whether a group after the text's first is a run with no first day (see _open_run)."""
    for group in groups[1:]:
        if group[GROUP_OPEN_START] is not None or group[GROUP_ATOMS][0][ATOM_KIND] == "week":
            return True
    return False


_ANCHOR_KINDS = _STATUS_KINDS | {"ambiguous"}
_ANCHOR_ATOMS = frozenset({"explicit", "weekday", "relative"})  # (the kinds that name a day)


def _anchored_runs(
    mentions: list[Mention], assigned: dict[int, list[DateGroup]], statuses: list[_Status]
) -> list[_Status]:
    """The statuses, each whose days start with a run with no first day of its own ("Closed
    through Friday") led by the first day a status of its kind named before it ("Closed
    tomorrow. Closed through Friday.", "Closed tomorrow. Closed for the rest of the week."):
    the run starts on that day, as a bare "Closed tomorrow. Through Friday." does (see
    _restate), and the text, which says nothing of the posting day, says no school runs on it
    no more than before.

    After a day a status of another kind named ("Wednesday will be an eLearning day. Closed
    the rest of the week."), the run may start on that day or on the posting day: the day is
    kept beside the status (its _LED) and the run's days are unclear when it comes later (see
    _led_later). "All week" and "this week" name the posting week whatever comes before them
    ("NTI day Thursday. Closed all week."), unless the day before is of a later week."""
    anchored: list[_Status] = []
    for status in statuses:
        own = status[_GROUPS]
        if own and _open_run(own[0]):
            start = own[0][GROUP_START]
            anchor: DateAtom | None = None
            kind = ""
            for index, days in assigned.items():
                mention = mentions[index]
                if (
                    days
                    and mention.kind in _ANCHOR_KINDS
                    and mention.dropped is None
                    and not mention.revoked
                    and days[0][GROUP_END] <= start
                    and (anchor is None or days[0][GROUP_START] < anchor[ATOM_START])
                ):
                    # (A run of its own, "Closed thru Friday", starts on the posting day too.)
                    anchor = None if _open_run(days[0]) else days[0][GROUP_ATOMS][0]
                    kind = mention.kind
            if anchor is not None and anchor[ATOM_KIND] in _ANCHOR_ATOMS:
                # (Its first day alone: "Closed today through Friday. Update: closed through
                # tomorrow" runs from today.)
                led: DateGroup = (anchor[ATOM_START], anchor[ATOM_END], (anchor,), (), None)
                if kind == status[_KIND] and not _whole_week(own[0]):
                    status = _with_groups(status, (led, *own))  # noqa: PLW2901 - the status led
                else:
                    status = (*status[:_LED], (led, False))  # noqa: PLW2901 - see _led_later
        anchored.append(status)
    return anchored


# A closure at a time of the day, and the words that say a status after it continues it:
# "will close at 5 p.m. today and remain closed through Friday".
_CLOSING_AT = re.compile(
    r"\bclos(?:e|es|ing)(?: (?:early|down))?(?P<day>(?: [a-z0-9.,]+){0,2}?)"
    r" at (?:\d{1,2}(?::\d\d)?(?: ?[ap]m)?|noon)\b",
    re.ASCII,
)
_CONTINUING = re.compile(r"\b(?:remain|remains|stay|stays|continue to be|continues to be) $")
_CONTINUING_REACH = 22  # (how far before a status its continuing words can start)
_CLOSING_DAY_GAPS = frozenset({"", "on"})  # (between a closing's time and its day)


def _continued_closures(
    text: str, groups: tuple[DateGroup, ...], statuses: list[_Status], notes: set[Note]
) -> list[_Status]:
    """The statuses, each closure that continues one that starts at a time of a day before
    it in its sentence ("will close at 5 p.m. today and remain closed through Friday", "will
    close at 2 pm Thursday and stay closed Friday") going on from the school day after that
    day: on that day school runs until the time, as an early dismissal or a full day (see
    _LED). That day is no day of the closure's, and a closure left with no day of its own
    ("will close at 5 p.m. today and remain closed") has none anyone can tell."""
    continued: list[_Status] = []
    for status in statuses:
        position = status[_POSITION]
        if (
            status[_KIND] == "closed"
            and not status[_REVOKED]
            and _CONTINUING.search(text, max(0, position - _CONTINUING_REACH), position)
        ):
            start = max([text.rfind(mark, 0, position) for mark in _POLICY_MARKS]) + 1
            closing = None
            for closing in _CLOSING_AT.finditer(text, start, position):  # noqa: B007 - the last
                pass
            day = None if closing is None else _closing_day(text, closing, groups, position)
            if day is not None and _SENTENCE_END.search(text, day[GROUP_END], position) is None:
                # (Its day, and one written between the closing's words: "will close today at
                # 4 p.m., Wed., Dec. 10".)
                first = closing.start() if closing is not None else day[GROUP_START]
                own = tuple(
                    [
                        group
                        for group in status[_GROUPS]
                        if not first <= group[GROUP_START] <= day[GROUP_START]
                    ]
                )
                if not own:
                    notes.add("unreadable_date")
                status = (*_with_groups(status, own)[:_LED], (day, True))  # noqa: PLW2901
        continued.append(status)
    return continued


def _closing_day(
    text: str, closing: re.Match[str], groups: tuple[DateGroup, ...], position: int
) -> DateGroup | None:
    """The day a closure at a time is on (see _continued_closures): the date right after its
    time ("close at 5 p.m. today", "close at 4:30 p.m. on Wednesday, September 25"), or else
    one between its words ("close Thursday at 2 pm"), before the status at ``position``."""
    inside = None
    for group in groups:
        if closing.start("day") <= group[GROUP_START] < closing.end("day"):
            inside = group
        elif closing.end() <= group[GROUP_START] < position:
            gap = text[closing.end() : group[GROUP_START]].strip(" ,")
            return group if gap in _CLOSING_DAY_GAPS else inside
    return inside


def _whole_week(group: DateGroup) -> bool:
    """Whether ``group`` is "all week" or "this week": the posting week, not the rest of it."""
    atom = group[GROUP_ATOMS][0]
    return (
        group[GROUP_OPEN_START] is None
        and atom[ATOM_KIND] == "week"
        and not atom[ATOM_REST_OF_WEEK]
    )


def _led_later(calendar: Calendar, led: DateGroup, run: DateGroup, default: date | None) -> bool:
    """Whether the day a status named before a run with no first day of its own (``led``: see
    _anchored_runs) leaves the run's days unclear.

    After a status of another kind, the run starts on the posting day or on that day: when
    that day comes later ("Wednesday will be an eLearning day; closed the rest of the week",
    posted on a Tuesday), the text does not say which, and the days between are no status's
    for sure. "All week" or "this week" is the posting week, whatever day comes before it,
    unless that day is of a later week ("Closed 1/27. Closed this week.")."""
    resolved = calendar.resolve(led, default)
    if resolved.flags & _LED_UNTOLD or not resolved.dates:
        return bool(resolved.flags & _LED_UNTOLD)  # (a day no one can tell leads no run either)
    first = min(resolved.dates)
    if _whole_week(run):
        return first > calendar.week_end()
    alone = calendar.resolve(run, default).dates
    return bool(alone) and first > min(alone)


def _later_stop(  # noqa: PLR0913, PLR0917 - the text's parts, as the gate reads them
    text: str,
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    statuses: list[_Status],
    assigned: dict[int, list[DateGroup]],
    notes: set[Note],
    rare: int,
    *,
    promised: bool,
) -> Note | None:
    """What stops the statuses a text holds, past a day said again (see _analyse_normalized): a
    promise of an update after statuses for several days (see _update_promised), a test or an
    old post ("This is a test. Closed tomorrow.", "ARCHIVE: closed tomorrow"), a status of a
    kind stated, then denied with no day of its own ("Closed tomorrow. Update: not closed."),
    or a correction that moves a status's day or time (see _corrected). ``rare`` are the text's
    rare bits, and ``promised`` whether it can promise an update."""
    if promised and groups and _update_promised(text, mentions, statuses):
        return "unread_words"
    if rare & _UNREAD_RARE and _TEST_MESSAGE(text) is not None:
        return "unread_words"
    if "negated" in notes and _denied_later(text, mentions, assigned, statuses):
        return "conflict"
    if rare & _CORRECTION_RARE and _corrected(text, statuses, groups):
        return "ambiguous"
    return None


def _corrected(text: str, statuses: list[_Status], groups: tuple[DateGroup, ...]) -> bool:
    """Whether a correction moves a status's day or time and the status still holds the old
    one: a later sentence that a correction's words lead names another day ("Closed Thursday.
    Correction: Friday.", "... Correction: closed Friday.", "... date changed to Friday",
    "... Update: closure moved to Friday"), a move from a day to another ("Closure moved from
    Thursday to Friday"), or a bare new time ("Early dismissal at 1:00. Correction: 12:30.").
    The new day or time may replace the old or join it: no status is sure. (A correction that
    denies the old day, "Correction: closed Friday, not Thursday", leaves no status holding
    it.)"""
    for found in _CORRECTION_CUE.finditer(text):
        cue = found.start()
        # (Its sentence, or the part of it after a bracket, a dash or a comma: "Closed Thursday
        # (correction: Friday)", "Closed Thursday - now Friday".)
        start = max([text.rfind(mark, 0, cue) for mark in _CORRECTION_MARKS]) + 1
        if text.startswith(_LEADING_CUES, cue) and any(
            start < group[GROUP_END] and text[group[GROUP_END] : cue].isspace() for group in groups
        ):
            start = cue  # "Closed Thursday [correction: Friday]", its brackets dropped
        if not _about_status(text, start, cue, groups):
            continue  # "Food pantry moved to Thursday": something else's day
        if found.group("move") is not None:
            for status in statuses:
                for group in status[_GROUPS]:
                    if group[GROUP_START] == found.end() and "range" in group[GROUP_LINKS]:
                        return True  # "moved from Thursday to Friday": the old day held
            continue
        if found.group("clock") is not None:
            # (A change in the status's own sentence is a change's: "Opening at 8 AM changed
            # to 10 AM" opens at 10, see _changes; so is one a status already took, "Early
            # dismissal at 1 PM - now 12:30".)
            new = _clock_minutes(found.group("clock"))
            if any(
                status[_KIND] in _TIMED
                and status[_POSITION] < start
                and new not in _status_minutes(status)
                for status in statuses
            ):
                return True
            continue
        if _moved_day(text, found.end(), start, statuses, groups):
            return True
    return False


def _clock_minutes(clock: str) -> int | None:
    """The minutes after midnight a correction's bare clock names, read in a school day's
    hours ("12:30", "1:15 pm", "2": the afternoon); None when it names none."""
    found = _BARE_CLOCK.search(clock)
    if found is None:
        return None
    hour = int(found.group(1)) % 12
    if found.group(3) == "p" or (found.group(3) is None and hour < _MORNING_HOURS):
        hour += 12
    return hour * 60 + int(found.group(2) or 0)


def _status_minutes(status: _Status) -> tuple[int, ...]:
    """The times of the day a status holds, in minutes after midnight (see _clock_minutes)."""
    return tuple(
        [
            clock.hour * 60 + clock.minute
            for clock in (status[_OPENS_AT], status[_DISMISSAL])
            if clock
        ]
    )


_BARE_CLOCK = re.compile(r"(\d{1,2})(?::(\d\d))?\s*(?:([ap])\.?m)?", re.ASCII)
_MORNING_HOURS = 7  # (a bare hour below it is an afternoon's: "1:00" is 1 p.m.)


def _moved_day(
    text: str, end: int, start: int, statuses: list[_Status], groups: tuple[DateGroup, ...]
) -> bool:
    """Whether the days of a correction's sentence (from ``start``, its cue ending at ``end``)
    are new ones beside old ones a status still holds (see :func:`_corrected`): "Correction:
    Friday", "Update: closed Friday instead". A sentence about an old day alone ("Open
    Friday", "Friday was listed by mistake") keeps or withdraws it, and one that keeps only
    some ("Correction: closed today only") is read by _only_days."""
    if "only" in text[start:end] or text.find("only", end) >= 0:
        return False
    ended = _SENTENCE_END.search(text, end)
    high = len(text) if ended is None else ended.start()
    if not _ADDED_DAY.isdisjoint(words(text, start, high)) or "as well" in text[start:high]:
        return False  # "Now closed Friday too": a day added, not moved
    new_keys = {
        _day_key(atom)
        for group in groups
        if start <= group[GROUP_START] < high
        for atom in group[GROUP_ATOMS]
    }
    if not new_keys:
        return False
    for status in statuses:
        for group in status[_GROUPS]:
            old_keys = {_day_key(atom) for atom in group[GROUP_ATOMS] if atom[ATOM_START] < start}
            if old_keys - new_keys and new_keys - old_keys:
                return True
    return False


def _about_status(text: str, start: int, cue: int, groups: tuple[DateGroup, ...]) -> bool:
    """Whether a correction's words at ``cue`` are about a status: the nearest word before them
    in their sentence (from ``start``), past days, times and a correction's own leads, is a
    status's word, or there is none ("Update: closure moved to Friday", "Correction: Friday";
    not "Food pantry moved to Thursday", "Finals at 8:00 a.m. rescheduled to 1 p.m.")."""
    for found in reversed(list(_WORD.finditer(text, start, cue))):
        word = found.group()
        if (
            word in _CORRECTION_LEADS
            or word[0].isdigit()
            or any(group[GROUP_START] <= found.start() < group[GROUP_END] for group in groups)
        ):
            continue
        if word == "day":
            # "Snow day moved to Friday"; not "Soup Day postponed until Feb. 27".
            before = words(text, start, found.start())[-1:]
            return bool(before) and before[0] in _STATUS_DAY_WORDS
        return word in _STATUS_HEADS
    return True


# The words before "day" that make it a status's day (see _about_status).
_STATUS_DAY_WORDS = frozenset(
    {"snow", "nti", "ami", "elearning", "e-learning", "learning", "virtual", "remote", "weather",
     "cold", "calamity", "ice", "flexible", "instructional", "instruction", "inclement", "storm",
     "closure", "closing", "school", "digital", "online", "distance", "flex"}
)  # fmt: skip
# Where a correction's part of a sentence starts (see _corrected).
_CORRECTION_MARKS = (".", ";", "!", "?", "|", "(", "[", ",", " -")  # (as _POLICY_MARKS, and more)
# The cues that lead the new day, which a day right before them is the old one of (see
# _corrected); "instead" follows the new day ("closed Friday instead").
_LEADING_CUES = ("correct", "errat", "revis", "now", "updated", "change")
# Words that add a day to a status's days rather than move it: "Now closed Friday too".
_ADDED_DAY = frozenset({"also", "too", "additionally", "plus"})
# The words of a status a correction can be about (see _about_status).
_STATUS_HEADS = frozenset(
    {"closed", "closure", "closing", "delay", "delayed", "dismissal", "release", "opening",
     "open", "school", "schools", "classes", "elearning", "e-learning", "learning", "day",
     "start", "nti", "remote", "virtual", "late"}
)  # fmt: skip
# The words a correction of a status's day can follow in its sentence when no status does:
# "Update: make that Friday", "The date has been changed to Friday".
_CORRECTION_LEADS = frozenset(
    {"update", "updated", "correction", "date", "the", "it", "this", "that", "has", "have",
     "been", "was", "is", "will", "be", "we", "sorry", "please", "note", "status", "now",
     "and", "but", "at", "a", "m", "p", "am", "pm", "noon", "on", "for", "to", "from"}
)  # fmt: skip
# The words that lead a correction of a day (see _corrected), a move from a day ("moved from"),
# and a bare new time after one ("Correction: 12:30").
_CORRECTION_CUE = re.compile(
    r"\b(?:correction|corrected|correcting|make\s+that|should\s+(?:be|read|say|have\s+said)"
    r"|date\s+change[ds]?|changed\s+to|moved\s+to|rescheduled\s+(?:to|for)|instead|typo|meant"
    r"|oops|errat(?:um|a)|revised|revision|change(?=\s*:)|updated\s+to|shifted\s+to"
    r"|(?:correct|updated)\s+date|change\s+of\s+date"
    r"|pushed\s+(?:back\s+)?to|postponed\s+(?:to|until|till)|now\s+on"
    r"|now(?=\s+(?:closed\s+|delayed\s+|to\s+)?(?:mon|tue|wed|thu|fri|sat|sun|tomorrow|\d"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)))\b(?P<clock>\s*(?:[:-]|to\b)?\s*\d{1,2}(?::\d\d)?\s*(?:[ap]\.?m\b\.?)?(?=\s*(?:[.;!?|]|$)))?"
    r"|\b(?:moved|rescheduled|changed|postponed|switched|shifted|pushed)\s+(?:back\s+)?"
    r"(?P<move>from\s+)",
    re.ASCII,
)


def _remote_option(text: str, mentions: list[Mention]) -> bool:
    """Leave out a remote day after the school says it is open that the text offers as an
    option to some students, not the district's day: "Open, virtual option available", "Open as
    scheduled; eLearning available for those unable to attend", "Open with an optional virtual
    day", "Open; remote learning for students in quarantine". Whether one was left out."""
    opened = False
    found = False
    # (Beside a closure, a delay or an early dismissal, a remote option is the status's own:
    # "Closed for in-person classes; check Canvas for remote learning class options".)
    alone = all(
        mention.kind not in _OTHER_THAN_REMOTE or mention.dropped is not None
        for mention in mentions
    )
    for mention in mentions:
        if mention.kind == "open" and mention.dropped is None:
            opened = True
        elif opened and mention.kind == "remote" and mention.dropped is None:
            ended = _SENTENCE_END.search(text, mention.end)
            low = max([text.rfind(mark, 0, mention.start) for mark in _OPTION_MARKS]) + 1
            said = words(text, low, len(text) if ended is None else ended.start())
            if not _OPTION_WORDS.isdisjoint(said):
                mention.dropped = "hedged"
                found = True
        elif (
            alone
            and mention.kind == "remote"
            and mention.dropped is None
            and "day" not in text[mention.start : mention.end]
            and _offered(text, mention)
        ):
            mention.dropped = "hedged"
            found = True
    return found


def _offered(text: str, mention: Mention) -> bool:
    """Whether the words right after a remote mention, to the next mark, offer it to some
    students only, with no word that the school is open before it: "Remote learning available
    for students who cannot get to school", "Virtual option for students who cannot travel
    safely", "Remote learning for students unable to travel", "Remote learning option available
    today" (not "eLearning day - students unable to log in will not be marked absent")."""
    marks = [found for mark in _OFFER_MARKS if (found := text.find(mark, mention.end)) >= 0]
    return _offers(words(text, mention.end, min(marks) if marks else len(text)))


def _offers(said: list[str]) -> bool:
    """Whether words offer something to some students only (see :func:`_offered`)."""
    return not _OFFER_WORDS.isdisjoint(said) or ("who" in said and not _OFFER_WHO.isdisjoint(said))


_OFFER_MARKS = (",", ";", ".", "!", "?", "|", ":", " - ")
_OTHER_THAN_REMOTE = frozenset({"closed", "delayed", "early_dismissal"})
_OFFER_WORDS = frozenset(
    {"option", "options", "optional", "unable", "cannot", "quarantine", "quarantined",
     "isolating", "isolation", "choose", "chooses", "opt"}
)  # fmt: skip
_OFFER_WHO = frozenset({"students", "student", "those", "families", "anyone", "kids"})
# A word of an option to some students anywhere in a text, as a quick look (see _offered).
_OPTION_HINT = re.compile(r"option|unable|cannot|quarantin|isolat|choose|\bopt\b|\bwho\b").search


_OPTION_MARKS = (",", ";", ".", "!", "?", "|", ":")
# Words that make a remote day one some students may take: an option, for those who need it.
_OPTION_WORDS = frozenset(
    {"option", "options", "optional", "available", "availability", "unable", "quarantine",
     "quarantined", "isolating", "isolation", "choose", "chooses", "choice", "opt", "who"}
)  # fmt: skip


_UPDATE_HEADS = ("update", "updated", "update on", "updated on", "updated:", "update:")


def _update_dates(text: str, assigned: dict[int, list[DateGroup]]) -> None:
    """Take from a status's days the date of an update's heading before it, when the status
    names days of its own after the heading: "UPDATE 1/21: closure extended through Friday 1/23"
    is an update written on the 21st about Friday ("Update 1/22: closed", with no other day,
    keeps it)."""
    for own in assigned.values():
        if len(own) < 2:  # noqa: PLR2004 - the heading's date and a day of the status's own
            continue
        first = own[0]
        if text.startswith(":", first[GROUP_END]) and text[: first[GROUP_START]].rstrip(
            " -"
        ).endswith(_UPDATE_HEADS):
            del own[0]


def _gated_result(
    text: str, notes: set[Note], weather: _WeatherFields, stop: Note, *, ambiguous: bool
) -> ParsedStatus:
    """What a text gives when the precision gate stops a confident result (see classify.gate):
    ``other``, no surer than a hedge, with its notes and the gate's, ``stop``: ``conflict`` for
    a statement that school is held or open beside the statuses, else ``unread_words``."""
    gated_notes = frozenset({*notes, stop})
    return _new(
        ParsedStatus,
        (
            "other", (), None, None, None, None, False, False, (), *weather,
            _unstated_confidence(
                text, gated_notes, ambiguous=ambiguous, says_open=False, offices_open=False
            ),
            False, False, tuple(sorted(gated_notes)),
        ),
    )  # fmt: skip


_NOTE_MARKS = ",;:.!?|()"
# What each kind of phrase is to the precision gate (see classify.gate.unread_sentence): a side
# note, a phrase that says a place is open, or else a status phrase.
_SPAN_KINDS = {"note": NOTE_SPAN, "open": OPEN_SPAN}
# The status phrases whose subject the rules read before them, whatever it is: a side note's
# ("Payroll delayed"), or a word that alone leaves its status unclear ("Payroll postponed").
_SIDE_KINDS_READ = frozenset({"note", "ambiguous"})


# A cause that follows the words of its clause ("Liberal leave Tuesday due to school delays"),
# up to the next mark: group 1 is the cause's words. And the words that start a clause of their
# own inside it ("Closed today due to weather and will have a 2 hour delay tomorrow").
_TRAILING_CAUSE = re.compile(
    r"(?:due\s+to|because\s+of|owing\s+to)\s+([^,;:.!?|()\[\]]*)", re.ASCII
)
_CAUSE_RESTART = re.compile(
    r"\band\s+(?:will|we|there|all|school|schools|classes|students)\b", re.ASCII
)


def _prefixed_statuses(text: str, mentions: list[Mention]) -> None:
    """Read a status word joined to a prefix that makes it something else ("Non-closed",
    "Post-closure update", "Pre-delay schedule", "Anti-closure") as no statement of the
    status: an ambiguous mention in its place."""
    for index, mention in enumerate(mentions):
        start = mention.start
        if (
            start > 2  # noqa: PLR2004 - the shortest prefix and its hyphen
            and text[start - 1] == "-"
            and text.endswith(_STATUS_PREFIXES, 0, start)
            and mention.kind in _STATUS_KINDS
        ):
            mentions[index] = Mention(start, mention.end, "ambiguous", CERTAIN, note="ambiguous")


def _policies(text: str, mentions: list[Mention]) -> None:
    """Hedge the statuses of a sentence that states a rule for statuses to come, not a status:
    "Any closure tomorrow will be an eLearning day", "Our next snow day will be an NTI day",
    "Future closures will be remote learning days", "Snow days will be remote learning days",
    "Any delay will be 2 hours", "On early release days, dismissal is at 1:00". Such a
    sentence is a condition ("if school closes, ..."), whatever day it names."""
    for policy in _POLICY.finditer(text):
        found = _SENTENCE_END.search(text, policy.end())
        if policy.group("asked") is not None:
            found = None  # "What does a 2 hour delay mean? School starts at 10.": the answer too
        high = len(text) if found is None else found.start()
        low = max([text.rfind(mark, 0, policy.start()) for mark in _POLICY_MARKS]) + 1
        if not NEGATIONS.isdisjoint(words(text, low, policy.start())):
            continue  # "No schools have reported any closings": none, not a rule
        for mention in mentions:
            if low <= mention.start < high and mention.kind in _POLICY_KINDS:
                mention.dropped = "hedged"


# A rule for statuses to come (see _policies): a status noun after "any", "next", "future",
# "every" or "each", as in any closure, our next snow day or any weather-related closures;
# status days after "on", as in on early release days; or status nouns for many days that
# are said to be something to come: snow days that will be NTI days, all closures that are.
_STATUS_NOUNS = (
    r"(?:snow\s+days?|closures?|closings?|cancell?ations?|delays?|late\s+starts?"
    r"|delayed\s+(?:starts?|openings?)"
    r"|early\s+(?:dismissals?|releases?)|(?:nti|ami|e-?learning|remote(?:\s+learning)?|virtual"
    r"|inclement\s+weather|weather)\s+days?)"
)
# The kinds of day a rule can be for, with a length before a delay ("2 hour delay days").
_POLICY_DAYS = (
    r"(?:(?:\d+(?:\.\d+)?|one|two|three|ninety)[\s-]*(?:hours?|hrs?|minutes?|mins?)[\s-]+)?"
    r"(?:snow|delay(?:ed)?(?:\s+(?:start|opening))?|late\s+start|early\s+(?:dismissal|release)"
    r"|nti|ami|e-?learning|remote(?:\s+learning)?|virtual(?:\s+learning)?|closure"
    r"|(?:inclement|bad|severe|cold)\s+weather|weather|flex(?:ible)?(?:\s+instruction)?)\s+days"
)
_POLICY = re.compile(
    r"\b(?:(?:any|next|future|every|each)\s+(?:[a-z0-9][a-z0-9-]*\s+){0,2}"
    + _STATUS_NOUNS
    + r"\b|on\s+"
    + _POLICY_DAYS
    + r"\b|(?:"
    + _POLICY_DAYS
    + r"|closures|closings|delays|late\s+starts|early\s+(?:dismissals|releases))"
    r"(?:\s+this\s+(?:winter|year|season|semester|week))?"
    r"\s+(?:will\s+(?:all\s+)?(?:be|begin|start|end|run)|are(?:\s+to\s+be)?"
    r"|(?:begin|start|end|run)\s+at)(?=\s)"
    r"|"
    + _POLICY_DAYS
    + r"\s*:(?!\s*(?:\d|mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct"
    r"|nov|dec|today|tomorrow|this|next))"
    r")"
    # A sentence that opens with a status as a case: "On a 2 hour delay, buses run 2 hours
    # late", "During a delay, breakfast is not served", "In the event of a closure, ...".
    r"|(?:^|(?<=[.;!?|] ))(?:on|for|during|with|in\s+case\s+of|in\s+the\s+event\s+of)\s+an?\s+"
    r"(?:(?:\d+(?:\.\d+)?|one|two|three|ninety)[\s-]*(?:hours?|hrs?|minutes?|mins?)[\s-]+)?"
    r"(?:closure|closing|delay|delayed\s+(?:start|opening)|late\s+start|early\s+(?:dismissal"
    r"|release)|snow\s+day|(?:nti|ami|e-?learning|remote|virtual)\s+day)\s*,"
    # What a status means, as a page of answers says: "A 2 hour delay means school starts at
    # 10:00", "What does a 2 hour delay mean?".
    r"|(?P<asked>\bwhat\s+(?:does|do|is)\s+(?:an?\s+|the\s+)?(?:[a-z0-9-]+\s+){0,3}?)?"
    r"\b(?:delays?|closures?|closings?|starts?|releases?|dismissals?|days?|learning)\s+"
    r"(?(asked)mean|means)\b",
    re.ASCII,
)
_POLICY_HINT = re.compile(
    r"\b(?:any|next|future|every|each)\s|\bdays\b|closures|closings|delays|starts|dismissals"
    r"|releases|\bmeans?\b",
    re.ASCII,
).search
# A sentence that can open with a status as a case (see _POLICY): a quick look before it.
_POLICY_LEADS = ("on a", "for a", "during a", "with a", "in case of", "in the event of")
_POLICY_LEAD_STARTS = frozenset(lead[:2] for lead in _POLICY_LEADS)  # (a look with no call)
_POLICY_INNER = re.compile(r"[.;!?|] (?:on|for|during|with) an? ", re.ASCII).search
_POLICY_MARKS = ".;!?|"
_POLICY_KINDS = frozenset({"closed", "delayed", "remote", "early_dismissal", "ambiguous", "open"})


def _headings(text: str, mentions: list[Mention]) -> None:
    """Make ambiguous the status words of a heading, which names a page or a list, not a status:
    "Closings and delays", "School Closings & Delays", "Snow day procedures", "NTI day
    information", "AMI packets", and a list's header with no subject of its own ("The
    following schools are closed today:")."""
    marked: list[tuple[int, int]] = (
        [match.span() for match in _STATUS_LIST.finditer(text)]
        if _LIST_HINT(text) is not None
        else []
    )
    following = _FOLLOWING.search(text) if "following" in text else None
    if following is not None:
        marked.append((following.start(), len(text)))  # (the list's entries follow it)
    joined: Mention | None = None  # the heading's status word after a join, if any
    for mention in reversed(mentions):
        if mention.kind not in _POLICY_KINDS or mention.dropped is not None:
            joined = None
            continue
        following = _NEXT_NOUN(text, mention.end)
        linked = (
            (following is not None and following.group(1) in _LINKED_NOUNS)
            or text[mention.start : mention.end].rpartition(" ")[2] in _LINKED_NOUNS
        ) and not _LINK_WORDS.isdisjoint(words(text, 0, mention.start))
        if (
            (following is not None and following.group(1) in _HEADING_NOUNS)
            or (
                # "eLearning day plans", "NTI day plans": plans for such days, not one
                following is not None
                and following.group(1) == "plans"
                and text.endswith(_DAY_KIND_ENDS, mention.start, mention.end)
            )
            or any(low <= mention.start < high for low, high in marked)
            or (
                # "Delay and closure information", "Delay/closure policy": a status word joined
                # to the heading's.
                joined is not None
                and " ".join(text[mention.end : joined.start].split()) in _HEADING_JOINS
            )
        ):
            mention.dropped = "ambiguous"
            joined = mention
        elif linked:
            # "Click here for the 2 hour delay schedule": a link to a status's page. Beside a
            # status of its kind that the text states ("2 hour delay today. Click here for the
            # delay schedule.") it is that status's page, and says nothing of its own.
            if _stated_beside(mentions, mention):
                _quiet(mention)
            else:
                mention.dropped = "ambiguous"
            joined = mention
        else:
            joined = None


def _stated_beside(mentions: list[Mention], mention: Mention) -> bool:
    """Whether another of ``mentions`` states a status of ``mention``'s kind."""
    return any(
        other is not mention and other.kind == mention.kind and other.dropped is None
        for other in mentions
    )


def _quiet(mention: Mention) -> None:
    """Make ``mention`` a side note that adds nothing to the text's notes (see _apply_scope)."""
    mention.kind = "note"
    mention.note = None
    mention.scope_rule = "none"
    mention.needs_school_noun = False
    mention.negatable = False
    mention.revokes = None
    mention.delay = mention.opens_at = mention.dismissal = mention.early = None


# What joins two status words in a heading: "Delay and closure information".
_HEADING_JOINS = frozenset({"and", "&", "/", ",", "or", "and/or", "and / or", "&amp;"})
# Status nouns listed together, as a page's heading lists them: "closings and delays".
_STATUS_LIST = re.compile(
    r"\b(?:closings|closures|cancell?ations|delays|dismissals)\s*(?:and|&|/|,|\+)\s*"
    r"(?:closings|closures|delays|cancell?ations|dismissals|early\s+(?:dismissals|releases))\b",
    re.ASCII,
)
# What every match of _STATUS_LIST holds (a quick test before it is looked for).
_LIST_HINT = re.compile(r"(?:ings|ures|ations|lays|sals)\s*(?:and|&|/|,|\+)", re.ASCII).search
# A list's header: "the following schools are closed".
_FOLLOWING = re.compile(r"\bthe\s+following\b", re.ASCII)
# The nouns after a status word that make it a heading's: "snow day procedures".
_HEADING_NOUNS = frozenset(
    {"procedures", "procedure", "information", "info", "packets", "packet", "guidelines",
     "policy", "policies", "faq", "faqs", "resources", "guide", "reminders", "tips", "options",
     "expectations", "instructions"}
)  # fmt: skip
# The nouns after a status word that make it a heading's when a link points to it: "Click here
# for the 2 hour delay schedule" (not "Delay Schedule" alone, which slots of a closings page
# hold as a status).
_LINKED_NOUNS = frozenset({"schedule", "schedules", "plan", "calendar", "bell"})
_DAY_KIND_ENDS = (" day", " days", "learning")  # (the status words "plans" can follow)
_LINK_WORDS = frozenset({"click", "here", "link", "see", "view", "download", "visit", "find"})
_NEXT_NOUN = re.compile(r" ([a-z]+)\b", re.ASCII).match
_HEADING_HINT = re.compile(
    r"following|procedure|information|\binfo\b|packet|guideline|polic|faq|plans|click"
    r"|resources|guide|reminders|tips|options|expectations|instructions"
    r"|(?:ings|ures|ations|lays|sals)\s*(?:and|&|/|,|\+)",
    re.ASCII,
).search


def _partly_otherwise(
    text: str,
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    statuses: list[_Status],
) -> list[_Status]:
    """The statuses that no part of the district has another status beside, on their days.

    A school, a level or a site open, or on a status of another kind, beside a status of
    the district ("Closed. Lincoln Elementary open.", "Closed - high school open", "All
    locations are open, with the exception of the Kubaze Center. The Kubaze Center is
    closed.", "Closed. Lincoln Elementary on a 2 hour delay.") leaves the district no one
    status: the status is left out, unless the part's days are plainly others ("Closed today;
    Lincoln Elementary open tomorrow"). A part of the same kind restates it ("Closed.
    Preschool closed too."), and a building open for a service is none ("Lincoln Elementary
    open as a warming center").
    """
    parts: list[tuple[str, list[DateAtom] | None]] = []  # each part's kind, and its days
    for index, mention in enumerate(mentions):
        kind = mention.narrowed
        if kind is None or mention.dropped is not None or mention.revoked:
            continue
        found = _CLAUSE_END.search(text, mention.end)
        high = len(text) if found is None else found.start()
        low = max([text.rfind(mark, 0, mention.start) for mark in _NOTE_MARKS]) + 1
        clause = words(text, low, high)
        if not _SERVICE_OPEN.isdisjoint(clause):
            continue  # "open as a warming center", "Elementary band and orchestra canceled"
        if (
            _SITE_WORDS.isdisjoint(clause)
            and _GRADE_BAND.search(text, low, high) is None
            and not any(map(_slashed_levels, clause))  # ("Closed; Middle/High School open")
        ):
            continue  # a program, not a school or a site: "AM preschool cancelled"
        own = assigned.get(index)
        days = [atom for group in own for atom in group[GROUP_ATOMS]] if own else None
        parts.append((kind, days))
    if not parts:
        return statuses
    for status in statuses:
        atoms = [atom for group in status[_GROUPS] for atom in group[GROUP_ATOMS]]
        if not status[_REVOKED] and not all(
            kind == status[_KIND] or (days is not None and _days_apart(days, atoms))
            for kind, days in parts
        ):
            # (No one status for the district: none of its statuses stands, of whatever kind.
            # "2 hour delay. Lincoln Elementary closed. All other schools 2 hours late.")
            return [status for status in statuses if status[_REVOKED]]
    return statuses


def _days_apart(first: list[DateAtom], second: list[DateAtom]) -> bool:
    """Whether two lists of days are plainly different days: named alike, and none the same."""
    kinds = {atom[ATOM_KIND] for atom in first} | {atom[ATOM_KIND] for atom in second}
    return (
        bool(second)
        and len(kinds) == 1
        and {_day_key(atom) for atom in first}.isdisjoint([_day_key(atom) for atom in second])
    )


# Words that name a school, a level or a site, in the clause of a status about part of the
# district: "Lincoln Elementary is closed", "high school virtual", "Portland campus closed",
# "remote learning grades 7-12" (see _partly_otherwise). A program ("AM preschool cancelled",
# "Morning classes are canceled") is none: its status says what else the day holds.
_SITE_WORDS = frozenset(
    {"elementary", "elem", "middle", "high", "junior", "intermediate", "primary", "secondary",
     "campus", "campuses", "center", "centre", "centers", "academy", "location", "locations",
     "site", "sites", "grade", "grades", "magnet", "upper", "lower",
     # The levels abbreviated: "Closed; HS open" (see SCOPES).
     "es", "ms", "hs", "jh", "jhs", "shs", "ms/hs", "jh/hs", "jr/sr"}
)  # fmt: skip
_GRADE_BAND = re.compile(r"\b(?:pre-?k|pk|tk|k|\d{1,2})\s*-\s*(?:k|\d{1,2})\b", re.ASCII)
_SCHOOL_PARTS = ("school", "partial")  # (the scopes of the school's day and part of it)
# Words beside a status about part of the district that make it a service's or an activity's,
# not a school's (see _partly_otherwise): "open as a warming center", "open for staff", "open
# for meal pickup", "Elementary band and orchestra are canceled".
_SERVICE_OPEN = frozenset(
    [word for word, scope in SCOPES.items() if " " not in word and scope not in _SCHOOL_PARTS]
    + ["warming", "cooling", "shelter", "shelters", "meal", "meals", "pickup", "pick-up",
       "distribution", "voting", "polling", "testing", "clinic", "vaccine", "vaccination",
       "pantry", "employees", "teachers"]
)  # fmt: skip


def _caused_statuses(text: str, mentions: list[Mention]) -> None:
    """Make a status phrase inside a cause that follows its clause's words ambiguous: it says
    why, not what the listing's status is ("Liberal leave Tuesday due to school delays",
    "Closed Tuesday due to a training day that will now be virtual"). A cause about
    something besides the school ("due to bus delays", "due to road closures") is left to
    the scopes (see _settle), and so is a clause that starts again inside it ("due to
    weather and will have a 2 hour delay tomorrow")."""
    last = mentions[-1].start  # (the mentions are in text order)
    for word in _CAUSE_OPENING_WORDS:
        if 0 <= text.find(word) < last:
            break
    else:
        return  # no cause opens before the last phrase ("Closed today due to snow"): a quick look
    for cause in _TRAILING_CAUSE.finditer(text):
        opener = cause.start()
        if opener < 2 or text[opener - 1] != " " or not text[opener - 2].isalnum():  # noqa: PLR2004
            continue  # (no words of its clause before it: "Due to snow, closed")
        low, high = cause.span(1)
        for index, mention in enumerate(mentions):
            if (
                low <= mention.start < high
                and mention.kind in _STATUS_KINDS
                and mention.dropped is None
                and _CAUSE_RESTART.search(text, low, mention.start) is None
                and all(
                    SCOPES.get(word, "school") in _SCHOOL_SCOPES for word in words(text, low, high)
                )
            ):
                mentions[index] = Mention(
                    mention.start,
                    mention.end,
                    "ambiguous",
                    CERTAIN,
                    note="ambiguous",
                    scope_rule="none",
                )


def _opens_after(
    mentions: list[Mention],
    statuses: list[_Status],
    assigned: dict[int, list[DateGroup]],
) -> bool:
    """Whether a phrase that can say the school is open, with no day of its own, follows a
    status ("Closed tomorrow, school is open", "Closed. School on time."): see
    _unread_statement."""
    for index, mention in enumerate(mentions):
        if (
            mention.kind == "open"
            and index not in assigned
            and not mention.elsewhere
            and mention.narrowed is None
            and mention.dropped is None
            and not mention.revoked
        ):
            first = min(
                [status[_POSITION] for status in statuses if not status[_REVOKED]], default=-1
            )
            if 0 <= first < mention.start:
                return True
    return False


def _unread(text: str, mentions: list[Mention], groups: tuple[DateGroup, ...]) -> bool:
    """Whether a sentence of the text that bears on a status holds a word no rule reads (see
    classify.gate): the status phrases, the side notes and the days are read whole, and the
    sentences with a status phrase (but a side note) or a day bear on a status."""
    spans = [(group[GROUP_START], group[GROUP_END], DAY_SPAN) for group in groups]
    low = 0
    for mention in mentions:
        start = mention.start
        if mention.kind in _SIDE_KINDS_READ:
            # A side note's words before it in its clause are its subject ("Payroll delayed
            # until Friday", "Report cards delayed"): the rule that read the note read them.
            start = max(low, *[text.rfind(mark, low, start) + 1 for mark in _NOTE_MARKS])
        kind = _SPAN_KINDS.get(mention.kind, STATUS_SPAN)
        if kind == OPEN_SPAN and (
            mention.superseding or _dated_clause(text, start, mention.end, groups)
        ):
            # An update that opens, or a place open on a day: its subject must be read, as it
            # can open the school ("Update: Kubaze open tomorrow", "Hotspots open Friday").
            kind = STATUS_SPAN
        spans.append((start, mention.end, kind))
        low = max(low, mention.end)
    spans.sort()
    if names_read(text, spans):
        return False  # every word no rule reads is a name's, ended by its noun (the most common)
    anchors = sorted(
        [mention.start for mention in mentions if mention.kind != "note"]
        + [group[GROUP_START] for group in groups]
    )
    return unread_sentence(text, spans, anchors)


def _dated_clause(text: str, start: int, end: int, groups: tuple[DateGroup, ...]) -> bool:
    """Whether a date group stands in the clause of the words at ``start``-``end``."""
    low = max([text.rfind(mark, 0, start) for mark in _NOTE_MARKS]) + 1
    high = min(
        [place for place in (text.find(mark, end) for mark in _NOTE_MARKS) if place >= 0],
        default=len(text),
    )
    for group in groups:  # noqa: SIM110 - (a loop costs less than a generator)
        if low <= group[GROUP_START] < high:
            return True
    return False


def _unread_statement(  # noqa: PLR0911, PLR0912, PLR0913, PLR0917 - the text's parts, one return per form
    text: str,
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    openings: tuple[_Opening, ...],
    statuses: list[_Status],
    assigned: dict[int, list[DateGroup]],
) -> Note | None:
    """The note of a clause of the text that says something of the statuses that no rule
    read, if one does: ``conflict`` for one that says the school, its classes or students
    are held or open (it disagrees with them), else ``unread_words``.

    A clause with no status phrase or side note of its own, and no opening, return, held
    day, withdrawal or denial the parser read in it, that names no school day but the
    statuses' own, and that only hedges ("Closed today and tomorrow, possible", "...,
    decision tonight", "..., hopefully not"), only says school is held ("Closed tomorrow,
    classes will be held", "... - still on", "..., is a school day", "Friday: school as
    usual", "Closed Friday. School will run Friday.") or only corrects ("..., disregard"):
    the parser left the statuses standing beside it, so it did not read it. So is a clause
    whose one phrase says the school is open with no day of its own, after a status in its
    sentence ("Closed tomorrow, school is on", "..., in session") or in a later sentence
    that names the school or starts with it, beside statuses for no day or today, the day
    it is for ("Closed today. Classes on time.", "Closed. Open on time."); a clause that
    offers another status ("Closed tomorrow, or delayed") and a question asked of the
    status after a mark ("Closed tomorrow - ?"). A clause about another day ("Closed today.
    Tomorrow TBD.", "Closed tomorrow, possibly Wednesday"), or with any other word ("Closed
    tomorrow, more snow expected", "Closed. Schedule changed."), is left to the rules that
    read it.
    """
    live = [status for status in statuses if not status[_REVOKED]]
    if not live:
        return None  # (a status called off: "2 hour delay cancelled, regular schedule")
    if _ASKED_AFTER_MARK.search(text) is not None:
        return "unread_words"  # "Closed tomorrow - ?"
    own = {
        _day_key(atom)
        for status in statuses
        for group in status[_GROUPS]
        for atom in group[GROUP_ATOMS]
    }
    effects = sorted([at for at, _mode, _days in openings])
    first = min(status[_POSITION] for status in live)  # where the first status stands
    low = 0
    heading: list[DateGroup] = []  # the days of a clause of days alone just before
    begins = True  # whether the next clause begins a sentence
    for mark in chain(_STATEMENT_MARK.finditer(text), (None,)):
        high = len(text) if mark is None else mark.start()
        start, end = low, high
        low = high if mark is None else mark.end()
        sentence, begins = begins, mark is not None and text[high] in _STATEMENT_SENTENCE_MARKS
        before, heading = heading, []
        found = bisect_right(effects, start - 1)
        if found < len(effects) and effects[found] < end:
            continue  # a statement read there: an opening, a return, a withdrawal
        inside = [mention for mention in mentions if start <= mention.start < end]
        days = [group for group in groups if group[GROUP_START] < end and group[GROUP_END] > start]
        tokens = words(_without_dates(text, tuple(days)) if days else text, start, end)
        if days and not tokens and not inside:
            heading = days  # "(Tomorrow) To be announced": the clause after it is that day's
            continue
        days += before
        if inside:
            if (
                "either" in tokens
                and "or" in tokens
                and any(mention.kind in _STATUS_KINDS for mention in inside)
            ):
                return "unread_words"  # "Either a delay or a closure tomorrow": one of them
            if ("or" in tokens or "instead" in tokens) and any(
                mention.kind in _STATUS_KINDS
                and ("instead" in tokens or "or" in words(text, start, mention.start))
                and any(
                    other.kind in _STATUS_KINDS
                    and other.kind != mention.kind
                    and other.dropped is None
                    and other.start < mention.start
                    for other in mentions
                )
                for mention in inside
            ):
                # "Closed tomorrow, or delayed", "Closed tomorrow or delayed": another status
                # offered; "No school tomorrow; 2 hour delay instead": one in place of another.
                return "unread_words"
            if (
                start > first
                and not days
                and (
                    _SENTENCE_END.search(text, first, start) is None  # (the status's sentence)
                    or not _HELD_SUBJECTS.isdisjoint(tokens)
                    or (
                        sentence
                        and (
                            "open" in tokens
                            or _UPDATE_LEAD.issuperset(words(text, start, inside[0].start))
                        )
                    )
                )
                and all(
                    _open_alone(text, mention) and mentions.index(mention) not in assigned
                    for mention in inside
                )
                and _held_clause(
                    text,
                    inside,
                    start,
                    end,
                    sentence=sentence and (mark is None or text[high] in _STATEMENT_SENTENCE_MARKS),
                )
            ):
                # "Closed tomorrow, school is open": school open after the status, with no day
                # of its own; or in a sentence after it that names the school or its classes,
                # or starts with the open phrase (after an update's word, if any), whatever
                # day the statuses name ("Closed today. Classes on time.", "Closed tomorrow.
                # School will be in session.", "Closed. Open on time.", "2 hour delay tomorrow.
                # Regular schedule.", "Closed tomorrow. Open."): it is for no day, so it could be
                # for theirs. (A later clause's subject can be something else, cut off by a
                # mark: "Closed. Board of Ed. mtg. will be held as scheduled.", "Office (Kubaze)
                # open regular hours")
                return "conflict" if not _SAID_HELD.isdisjoint(tokens) else "unread_words"
            if (
                not UNVERIFIED.isdisjoint(tokens)
                and any(
                    mention.dropped is None for mention in inside if mention.kind in _STATUS_KINDS
                )
                and _ANSWERING_HEARSAY.isdisjoint(words(text, 0, end))
            ):
                return "unread_words"  # hearsay: "Closed tomorrow per unconfirmed reports"
            continue  # a status phrase or a side note: the rules read the clause
        if any(
            not own.issuperset(_day_key(atom) for atom in group[GROUP_ATOMS])
            and _school_day_group(group)
            for group in days
        ):
            continue  # about another day: "Tomorrow TBD", "possibly Wednesday"
        if tokens:
            stop = _bare_statement(tokens)
            if stop is not None:
                return stop
    return None


def _said_again(  # noqa: PLR0912, PLR0913, PLR0917 - the text's parts; one pass per day
    text: str,
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    statuses: list[_Status],
    hedged: AbstractSet[int],
    openings: tuple[_Opening, ...],
) -> Note | None:
    """The note of a later sentence that names a status's day again and says something of it
    that no rule read, if one does: ``hedged`` when a status only possible stands in it, else
    ``unread_words``.

    Once a status names its days, a sentence after it that names one of them again either
    restates the status ("Closed Thursday and Friday. Friday closed too."), says what else
    the day holds ("Friday's practice is cancelled": a side note), or says the day is not
    settled: "Friday might be virtual", "Friday will be evaluated tomorrow", "A decision about
    Friday will be made tomorrow", "Tomorrow is up in the air", "As for Friday, stay tuned",
    "Buses will run Friday". The rules read the first two (a status phrase or a side note in
    it); any other such sentence is read whole only when its words but the days are words that
    add or repeat days ("Closed Monday. Monday, January 26.", "... Friday as well."). Its
    clause alone counts when the status stands in its sentence before it ("Closed Thursday and
    Friday; Friday might be virtual", "Closed today and tomorrow, tomorrow TBD"). A sentence
    where the rules read an opening, a return, a held day, a withdrawal or a denial is theirs
    ("Closed Thursday and Friday. May reopen Friday.", "... Not closed Friday.").
    """
    # (The statuses are few, and their days: plain loops, with nothing made that no day needs.)
    positions = [status[_POSITION] for status in statuses if not status[_REVOKED]]
    if not positions:
        return None
    positions.sort()
    first = positions[0]  # where the first status stands
    earlier: list[tuple[int, tuple[object, ...]]] | None = None  # (where, which day) of theirs
    for group in groups:
        start = group[GROUP_START]
        if start <= first:
            continue
        # The rest of the day's sentence after it. A status there is read in it ("Monday
        # evening: closed"), as any status phrase the rules read in its clause is (below).
        # (Looked at first: a closings page's slots each hold one.)
        found = _SENTENCE_END.search(text, group[GROUP_END])
        high = len(text) if found is None else found.start()
        after = bisect_left(positions, start)
        if after < len(positions) and positions[after] < high:
            continue
        if earlier is None:
            earlier = [
                (atom[ATOM_START], atom[2:9])  # (as _day_key)
                for status in statuses
                if not status[_REVOKED]
                for own in status[_GROUPS]
                for atom in own[GROUP_ATOMS]
            ]
        named = False  # whether the group names a day the statuses name before it
        for atom in group[GROUP_ATOMS]:
            if atom[ATOM_EVENING]:
                continue  # ("tonight" is no school day)
            key = atom[2:9]
            for at, day in earlier:
                if at < start and day == key:
                    named = True
                    break
            if named:
                break
        if not named:
            continue
        # The clause the day stands in.
        mark = _LAST_MARK_SAID(text, first, start)
        low = first if mark is None else mark.end() - (mark.group("dash") is not None)
        doubt = False
        for index, mention in enumerate(mentions):
            if low <= mention.start < high:
                if mention.kind == "revoke":
                    continue  # a word that calls off nothing here: "... may be lifted"
                if mention.dropped not in _DOUBTED_DROPS and index not in hedged:
                    break  # a status phrase, a side note or a denial: the rules read it
                doubt = True
        else:
            if (
                any(low <= at < high for at, _mode, _days in openings)
                or _reopening_cue(text, group)
                or (_SLOT_PART(text, group[GROUP_END]) is not None and len(_SLOT_PARTS(text)) > 1)
            ):
                # An opening, a return or a denial read there, or a return dismissed; or a slot
                # of part of the day in a listing of such slots ("Tuesday Morning: Closed |
                # Tuesday Afternoon: No Services"), which says what that part holds.
                continue
            inside = tuple(
                other for other in groups if other[GROUP_START] < high and other[GROUP_END] > low
            )
            tokens = words(_without_dates(text, inside), low, high)
            for token in tokens:
                if not (
                    token in _SAID_AGAIN_WORDS
                    or token[0].isdigit()
                    or (not doubt and (noun_word(token) or inert_word(token)))
                ):
                    if doubt or not _closure_restated(tokens, statuses):
                        return "hedged" if doubt else "unread_words"
                    break
    return None


# A post that says it is a test, or an old post's label (see the gate stage of
# _analyse_normalized): "This is a test.", "Test message", "Closed tomorrow (test)", "ARCHIVE:".
_TEST_MESSAGE = re.compile(
    r"\b(?:this\s+is\s+(?:only\s+|just\s+)?a\s+test|(?:only|just)\s+a\s+test"
    r"|test(?:ing)?\s+(?:message|post|alert|notification|entry|only|purposes))\b"
    r"|(?:^|[,;:.|]\s|\s-\s)(?:test|testing)\s*(?:$|[,;:.|!])"
    r"|^(?:archived?|old|previous|draft|sample|example)\s*:",
    re.ASCII,
).search


def _without_alternative_days(
    text: str, statuses: list[_Status], groups: tuple[DateGroup, ...], notes: set[Note]
) -> list[_Status]:
    """The statuses, less each with a day that is one of two alternatives: "Closed tomorrow or
    Friday", "2 hour delay Thursday or Friday", "Closed today, Thursday or Friday", "Closed
    tomorrow (Thursday) or Friday" (note ``ambiguous``).

    Days joined by "or" are one day or another, so neither is the status's for sure, and the
    text says no status for sure: every status is left out. After "no" or "not" they are
    every day ("No school today, Thursday or Friday", "Closed - no classes today or
    tomorrow": no school on any of them), and "until further notice" is no day to choose.
    """
    pairs = [
        (left[ATOM_START], right[ATOM_START])
        for left, right in pairwise(
            sorted(
                [
                    atom
                    for group in groups
                    for atom in group[GROUP_ATOMS]
                    if atom[ATOM_KIND] != "further_notice"
                ]
            )
        )
        if " ".join(text[left[ATOM_END] : right[ATOM_START]].replace(")", " ").split()).replace(
            " ,", ","
        )
        in _ALTERNATIVE_GAPS
    ]
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            if _OR_NUMBER(text, atom[ATOM_END]) is not None:
                pairs.append((atom[ATOM_START], atom[ATOM_START]))  # "Jan. 22 or 23"
    for status in statuses:
        if status[_REVOKED]:
            continue
        starts = {atom[ATOM_START] for group in status[_GROUPS] for atom in group[GROUP_ATOMS]}
        for left, right in pairs:
            if (
                (left in starts or right in starts)
                and not text.startswith("no ", status[_POSITION])
                and _NO_HELD.isdisjoint(words(text, status[_POSITION], left))
            ):
                notes.add("ambiguous")
                return []
    return statuses


# What joins two days that are one or the other: "tomorrow or Friday", "Thursday, or Friday",
# "Thursday and/or Friday"; and a day number after a date and "or" ("Jan. 22 or 23").
_ALTERNATIVE_GAPS = frozenset({"or", ", or", ",or", "and/or", "and / or", "or/and"})
_OR_NUMBER = re.compile(r"[\s,]*(?:or|and/or|and / or)\s+(?:the\s+)?\d", re.ASCII).match


def _denied_later(
    text: str,
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    statuses: list[_Status],
) -> bool:
    """Whether a status of the school's is denied, with no day of its own, after a status of its
    kind that stands: "Closed tomorrow. Update: not closed.", "2 hour delay tomorrow. No longer
    delayed.". The denial is about the status before it, which the text then both states and
    denies (as "Closed tomorrow. Tomorrow is not closed." does: see _without_denied_days). A
    denial with a length or a time of its own denies only that ("2 hour delay. Not a 3 hour
    delay."), one of another kind none ("Closed tomorrow. Not delayed."), and one that names
    part of the program or something else only that ("No AM preschool or Head Start")."""
    for index, mention in enumerate(mentions):
        if (
            mention.dropped != "negated"
            or index in assigned
            or mention.revoked
            or mention.elsewhere
            or mention.narrowed is not None
            or mention.delay is not None
            or mention.opens_at is not None
            or mention.dismissal is not None
            or any(
                SCOPES.get(word, "school") != "school"
                for word in words(text, mention.start, mention.end)
            )
        ):
            continue
        kind = _KIND_OF.get(mention.kind)
        for status in statuses:
            if status[_KIND] == kind and not status[_REVOKED] and status[_POSITION] < mention.start:
                return True
    return False


def _update_promised(text: str, mentions: list[Mention], statuses: list[_Status]) -> bool:
    """Whether a clause after statuses that name several days, with no status phrase of its
    own, promises an update or more to come: "Closed today and tomorrow, will update tonight",
    "Closed Thursday and Friday, update at 5am", "..., stay tuned". The days after the first
    can still change, so none is sure (see _said_again for one that names such a day)."""
    days = 0
    first = len(text)
    for status in statuses:
        if status[_REVOKED]:
            continue
        first = min(first, status[_POSITION])
        for group in status[_GROUPS]:
            # (A day named two ways is one: "today, Wednesday, Dec 17". "Through Friday" runs
            # from the posting day.)
            days += 1 + (group[GROUP_OPEN_START] is not None)
            for link in group[GROUP_LINKS]:
                days += link in _RUN_LINKS
    if days < 2:  # noqa: PLR2004 - one day: an update is about the days after it
        return False
    for promise in _UPDATE_PROMISE.finditer(text, first):
        low = max(text.rfind(mark, 0, promise.start()) + 1 for mark in _PROMISE_MARKS)
        found = _CLAUSE_END.search(text, promise.end())
        high = len(text) if found is None else found.start()
        if all(not low <= mention.start < high for mention in mentions):
            return True
    return False


# A promise of an update, or of more to come: "stay tuned", "check back", "will update", "we will
# advise", "will notify", "update at 5am" (its time dropped with the stamps: see
# text.normalize), "updates to follow", "more info later".
_UPDATE_PROMISE = re.compile(
    r"\b(?:stay\s+tuned|check\s+back|update\s+at\b|(?:will|we'll|to)\s+(?:update|advise|notify|let\s+"
    r"(?:you|families|everyone|parents)\s+know)|updates?\s+(?:will\s+(?:follow|come)|to\s+"
    r"(?:follow|come)|(?:at|by)\s+\d|tonight|later|soon|tomorrow|this\s+(?:evening|afternoon))"
    r"|more\s+(?:info(?:rmation)?|details|updates)\s+(?:to\s+(?:follow|come)|later|tonight"
    r"|tomorrow|soon))\b",
    re.ASCII,
)
_CLAUSE_END = re.compile(r"[,;:.!?|()]", re.ASCII)
# What every promise of _UPDATE_PROMISE holds (a quick test before it is looked for).
_PROMISE_HINT = re.compile(r"tuned|back|updat|advise|notify|know|more ", re.ASCII).search
_PROMISE_MARKS = (",", ";", ":", ".", "!", "?", "|", "(", ")", " -")
_RUN_LINKS = frozenset({"list", "range", "until", "first"})


def _closure_restated(tokens: list[str], statuses: list[_Status]) -> bool:
    """Whether the words of a sentence deny that school is held, beside closures only, which
    it restates: "Closed tomorrow. School will not run tomorrow." (see _said_again)."""
    found = set(tokens)
    return (
        not _NO_HELD.isdisjoint(found)
        and found <= _HELD_STATEMENT | _NO_HELD
        and not (_HELD_VERBS.isdisjoint(found) and HELD_SIGNS.isdisjoint(found))
        and all(status[_KIND] == "closed" for status in statuses if not status[_REVOKED])
    )


def _reopening_cue(text: str, group: DateGroup) -> bool:
    """Whether a word of a reopening, a return or a decision leads the day (see _reopened_on),
    read by the rules for openings whether it opens the school's day or not ("Staff return
    Friday", "Classes resume Friday", "will reassess Thursday")."""
    start = group[GROUP_START]
    low = max(0, start - _REOPEN_REACH)
    return _REOPENED_DAY.search(text, low, start) is not None or (
        _RETURN_HINT(text, low, start) is not None
        and _RETURNED_DAY.search(text, low, start) is not None
    )


# The ways a status phrase is dropped that leave its day in doubt (see _said_again): only
# possible, or unclear. (One negated, or an activity's, is read: "Friday: not open".)
_DOUBTED_DROPS = frozenset({"hedged", "ambiguous"})
# The last mark before a day that ends a clause (",", "(", "[", " -") or a sentence (". ", ";",
# "!", "?", "|"): the clause starts after it (at the dash of " -").
_LAST_MARK_SAID = re.compile(r"(?s:.*)(?:[,(\[;!?|]|\. |(?P<dash> )-)", re.ASCII).match
# The words of a sentence that names a status's day again and only adds or repeats days ("Closed
# Monday. Monday, January 26.", "Closed Thursday and Friday. Friday as well."), says who or what
# else the day holds none of ("Closed Sunday; No Sunday Service", "... No home delivered meal
# services Monday": with the nouns of who or what is affected, see gate.noun_word), names the
# day the listing is for ("(For Thu. Dec 1st)") or when it was written ("Updated this morning
# Feb. 5"): see _said_again.
_SAID_AGAIN_WORDS = frozenset(
    {"also", "too", "and", "again", "as", "well", "plus", "both", "no", "or", "for", "on", "of",
     "the", "a", "an", "all", "at", "in", "first", "second", "third", "updated", "posted", "last",
     "am", "pm", "will", "be", "is", "are", "was", "were", "been", "to", "with", "by", "from",
     "this", "that", "these", "those", "their", "our", "your", "we", "you", "they", "it", "its",
     "there", "here", "any", "some", "each", "every", "other", "who", "which"}
)  # fmt: skip
# A day heading a slot of part of the day ("Tuesday Afternoon:"), and every such heading.
_SLOT_PART = re.compile(r"\s+(?:morning|afternoon|evening|night|am|pm)\s*:", re.ASCII).match
_SLOT_PARTS = re.compile(r"\s(?:morning|afternoon|evening|night|am|pm)\s*:", re.ASCII).findall


def _held_clause(
    text: str, inside: list[Mention], start: int, end: int, *, sentence: bool = False
) -> bool:
    """Whether a clause of phrases that say the school is open says only that the school is
    held: "school is open", "classes are in session", "on time" (see _unread_statement). A
    bare "open" alone in its clause is left to the rules ("Closed - - open"), unless the clause
    is a whole ``sentence`` ("Closed tomorrow. Open.")."""
    rest = set(words(_masked_mentions(text, inside, start, end)))
    return rest <= _HELD_STATEMENT and bool(
        rest or sentence or any(" " in text[mention.start : mention.end] for mention in inside)
    )


def _open_alone(text: str, mention: Mention) -> bool:
    """Whether a phrase says the school is open, held or in session, and no more: not about
    something else ("offices open"), part of the school, or denied (see _unread_statement)."""
    return (
        mention.kind == "open"
        and not mention.elsewhere
        and mention.narrowed is None
        and mention.dropped is None
        and not mention.revoked
        and _about_school(text, mention.start, mention.end)
    )


def _bare_statement(tokens: list[str]) -> Note | None:
    """The note of a clause whose words (its days left out) only hedge, hold school or correct,
    if they do (see _unread_statement): ``conflict`` for one that holds school, else
    ``unread_words``."""
    words_of = set(tokens)
    if _hedge_only(tokens) or (
        not _DECISIONS.isdisjoint(words_of)
        and _DECIDED.isdisjoint(words_of)
        and "final" not in words_of  # ("Final decision": this one)
        and all(word in _PENDING_DECISION or _DIGIT.search(word) is not None for word in words_of)
        and ("made" not in words_of or "will" in words_of or "be" in words_of)
    ):
        return "unread_words"  # "possible", "TBD", "decision tonight", "no decision yet"
    if (
        not HELD_SIGNS.isdisjoint(words_of)
        or ("school" in words_of and "day" in words_of)
        or (tokens[-1] == "on" and len(tokens) > 1)  # "school is on", "classes are on"
        or (
            not _HELD_SUBJECTS.isdisjoint(words_of)
            and (
                not _HELD_VERBS.isdisjoint(words_of)
                or "have" in words_of
                or ("there" in words_of and "be" in words_of)
            )
        )
    ):  # (the last: "school will run Friday", "classes operating", "we will have school",
        # "there will be school")
        if not words_of <= _HELD_STATEMENT or not _NO_HELD.isdisjoint(words_of):
            return None
        # "Classes will be held" disagrees with the statuses; "as planned" or "still on" may
        # say the status itself holds.
        return "conflict" if not _SAID_HELD.isdisjoint(words_of) else "unread_words"
    if not HOPE_SIGNS.isdisjoint(words_of):
        read = words_of <= _HOPE_STATEMENT
    elif not CORRECTION_SIGNS.isdisjoint(words_of) or not _STALE_SIGNS.isdisjoint(words_of):
        read = words_of <= _CORRECTION_STATEMENT | _STALE_SIGNS
    elif not _NOT_SO.isdisjoint(words_of) and not _TRUE.isdisjoint(words_of):
        read = words_of <= _CORRECTION_STATEMENT | _NOT_SO | _TRUE  # "- not true", "isn't so"
    else:
        read = words_of <= _EITHER_STATEMENT  # "Closed today, tomorrow either", "- or not"
    return "unread_words" if read else None


# A correction that denies what was said: "Closed tomorrow -- not true", "... is not correct".
_NOT_SO = frozenset(["not", "isn't", "wasn't", "no", "nope"])
_TRUE = TRUTH_SIGNS


# A question asked right after a mark: "Closed tomorrow - ?", "Closed today, tomorrow (?)".
_ASKED_AFTER_MARK = re.compile(r"(?:^|[,;:|(\[]|\s-+)\s*\?", re.ASCII)
# The marks that end a sentence, and those that end a clause, for the statements read in
# clauses (see _unread_statement).
_STATEMENT_SENTENCE_MARKS = frozenset(".;!?|")
_STATEMENT_MARK = re.compile(r"[,;!?|]|\.(?=\s|$)|\s-+(?=\s|$)| but\b| however\b", re.ASCII)
# The words of a clause that says school is held, or a day runs as usual ("classes will be
# held", "still on", "school as usual", "is a school day", "regular schedule"), and those of
# one that hopes, promises an update or corrects (see _bare_statement).
_HELD_STATEMENT = HELD_SIGNS | frozenset(
    ["school", "schools", "class", "classes", "students", "student", "day", "days", "will",
     "be", "is", "are", "a", "an", "the", "as", "on", "in", "at", "for", "all", "we", "have",
     "there", "go", "goes", "going", "per", "time", "hours", "full", "open", "and", "also",
     "too", "of", "our", "we're", "we'll", "kids", "children", "to", "should", "may", "can",
     "report", "reports", "run", "runs", "running", "operate", "operates", "operating",
     "start", "starts", "begin", "begins", "business", "update", "updated", "change",
     "plans", "correction", "corrected"]
)  # fmt: skip
# The words that can lead a sentence that says school is open or held after a status: an
# update's ("Update: open on time", "Change of plans: school is on").
_UPDATE_LEAD = frozenset(["update", "updated", "updates", "correction", "change", "of", "plans"])
_EITHER_STATEMENT = EITHER_SIGNS | frozenset(["not", "maybe", "way", "else"])
_NO_HELD = frozenset(["no", "not", "never", "nor", "without", "won't", "wont", "cannot", "can't"])
_PENDING_DECISION = _DECISIONS | _DECISION_WORDS | {"yet", "still", "not"}
_HOPE_STATEMENT = HOPE_SIGNS | frozenset(["we", "not", "so", "to", "be", "are", "is", "it"])
_CORRECTION_STATEMENT = CORRECTION_SIGNS | frozenset(
    [
        "school",
        "schools",
        "day",
        "date",
        "listing",
        "status",
        "district",
        "info",
        "information",
        "this",
        "that",
        "please",
        "just",
        "posted",
        "in",
        "was",
        "is",
        "it",
        "the",
        "post",
        "message",
        "previous",
        "earlier",
        "above",
        "never",
        "mind",
        "a",
        "an",
        "all",
        "no",
        "wait",
        "update",
        "updated",
        "correction",
        "corrected",
        "notice",
        "case",
        "longer",
        "plans",
        "change",
        "changed",
        "changes",
        "of",
        "have",
        "has",
    ]
)


def _without_denied_days(
    text: str,
    statuses: list[_Status],
    notes: set[Note],
    groups: tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
) -> tuple[list[_Status], tuple[_Opening, ...]]:
    """The statuses without the days a "not" right before them denies, and those denials.

    "Closed today and not tomorrow", "Closed today not tomorrow" and "No school
    Thursday and Friday not Monday" name the days the status is not for after
    the "not": those days are left out. A status left with no day of its own
    names none it can be read for, so it is left out too, as ambiguous ("No
    school not Monday"). Each such day denies the status's kind on it to the
    other statuses too, as an opening for that kind does (see :data:`_Opening`):
    "Closed today and tomorrow. Closed today but not tomorrow." is not closed
    tomorrow, and "Closed Monday through Friday, not Wednesday" not on Wednesday.
    A day after "not" that no status takes denies every kind of status on it
    ("Closed today and tomorrow. Update: not tomorrow").
    """
    kept: list[_Status] = []
    denied: list[_Opening] = []
    for status in statuses:
        own = status[_GROUPS]
        if not own or not any(_denied_day(text, group) for group in own):
            kept.append(status)
            continue
        left: list[DateGroup] = []
        for group in own:
            if not _denied_day(text, group):
                left.append(group)
            elif _school_day_group(group):
                marked = status[_IS_SUPERSEDING] or _marked_before(text, group[GROUP_START])
                bit = _DENIED_BITS.get(status[_KIND], 0) | (_OPEN_MARKED if marked else 0)
                denied.append((group[GROUP_START], bit, (group,)))
        if left:
            kept.append(_with_groups(status, tuple(left)))
        else:
            notes.add("ambiguous")
    taken = {group[GROUP_START] for own in assigned.values() for group in own}
    for group in groups:
        start = group[GROUP_START]
        if start not in taken and _denied_day(text, group) and _school_day_group(group):
            mode = _DENIALS | (_OPEN_MARKED if _marked_before(text, start) else 0)
            denied.append((start, mode, (group,)))
    return kept, tuple(denied)


def _marked_before(text: str, position: int) -> bool:
    """Whether a word that marks an update comes before ``position`` in its sentence ("Update:
    not tomorrow")."""
    sentence = max([text.rfind(mark, 0, position) for mark in _OPENING_SENTENCE_MARKS]) + 1
    return not _RETRACTIONS.isdisjoint(words(text, sentence, position))


def _denied_day(text: str, group: DateGroup) -> bool:
    """Whether "not" comes right before a date group: "not tomorrow", "not on Monday"."""
    return text.endswith(_DENIED_DAY, 0, group[GROUP_START])


_DENIED_DAY = (
    "not ", "not on ", "not for ", "not be ", "not be on ", "n't be ", "n't be on ", "wont be ",
)  # fmt: skip


def _only_days(text: str, statuses: list[_Status], notes: set[Note]) -> list[_Status]:
    """The statuses, with what "only" beside a status's days says of the other days.

    "Closed today only", "only on Thursday" and "only closed today" name the
    one day a status is for. An update or a correction that says so ("Closed
    today and tomorrow. Update: closed today only.") replaces every status of
    its kind before it: their other days are left with a status the text
    marks as replaced (see _schedule). With no such mark, another day of the
    same kind of status is a contradiction ("Closed today only, Thursday and
    Friday", "Closed Wednesday only; Thursday and Friday"), and so is one
    beside the update's own day: the text says no status for sure. A later
    update of the same kind replaces the "only" in turn.
    """
    index = 0
    while index < len(statuses):
        status = statuses[index]
        index += 1
        if status[_REVOKED] or status[_IS_SUPERSEDED] or not status[_GROUPS]:
            continue  # (a status replaced already restricts nothing)
        restricted = _only_restricted(text, status)
        if restricted is None:
            continue
        days, extra = restricted
        if extra:
            notes.add("ambiguous")  # "Closed today only, Thursday and Friday"
            return []
        kind, position = status[_KIND], status[_POSITION]
        kept: list[_Status] = []
        for other in statuses:
            if (
                other is status
                or other[_KIND] != kind
                or other[_REVOKED]
                or other[_IS_SUPERSEDED]
                or all(
                    _day_key(atom) in days
                    for group in other[_GROUPS]
                    for atom in group[GROUP_ATOMS]
                )
                or (other[_POSITION] > position and other[_IS_SUPERSEDING])
            ):
                kept.append(other)  # (no other day, or a later update of its own)
            elif status[_IS_SUPERSEDING] and other[_POSITION] < position:
                kept.append((*other[:_IS_SUPERSEDED], True, *other[_GROUPS:]))  # replaced
            else:
                notes.add("ambiguous")  # "Closed Monday. Closed today only."
                return []
        statuses = kept  # (in the same order: ``index`` still counts it)
    return statuses


def _only_unread(text: str, statuses: list[_Status], groups: tuple[DateGroup, ...]) -> bool:
    """Whether an "only" that restricted nothing stands in a sentence after the statuses' first
    that names one of their days, beside statuses for several days: "Closed today and
    tomorrow. Update: the only day closed is today" says the days are fewer, in a way no
    rule read."""
    keys = {
        _day_key(atom)
        for status in statuses
        if not status[_REVOKED]
        for group in status[_GROUPS]
        for atom in group[GROUP_ATOMS]
    }
    if len(keys) < 2:  # noqa: PLR2004 - one day: nothing for "only" to leave out
        return False
    first = min(status[_POSITION] for status in statuses)
    found = _SENTENCE_END.search(text, first)
    if found is None:
        return False
    for only in _ONLY_WORD.finditer(text, found.end()):
        low = max([text.rfind(mark, 0, only.start()) for mark in _POLICY_MARKS]) + 1
        end = _SENTENCE_END.search(text, only.end())
        high = len(text) if end is None else end.start()
        for group in groups:
            if low <= group[GROUP_START] < high and not keys.isdisjoint(
                [_day_key(atom) for atom in group[GROUP_ATOMS]]
            ):
                return True
    return False


_ONLY_WORD = re.compile(r"\bonly\b", re.ASCII)


def _only_near(text: str, groups: tuple[DateGroup, ...], statuses: list[_Status]) -> bool:
    """Whether "only" or "just" stands right beside a day or right before a status (a quick
    look before :func:`_only_days`): "today only", "only on Thursday", "only closed today".
    "Essential personnel only" and "online services only" touch none."""
    before: set[int] = {status[_POSITION] for status in statuses}  # where a word can lead
    after: set[int] = set()  # where a word can follow
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            before.add(atom[ATOM_START])
            after.add(atom[ATOM_END])
    for word in ("only", "just"):
        index = text.find(word)
        while index >= 0:
            end = index + 4  # (both words are four letters long)
            if index - 1 in after or not before.isdisjoint((end + 1, end + 4, end + 5)):
                return True  # "today only", "only today", "only on today", "only for today"
            index = text.find(word, end)
    return False


def _only_elsewhere(
    text: str,
    statuses: list[_Status],
    groups: tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
) -> bool:
    """Whether "only" restricts a day that no status or other word takes, while a status
    names another day ("Closed Thursday and Friday. Correction - only Thursday"): which
    status it restricts cannot be told, and it contradicts each that names another day."""
    taken = {group[GROUP_START] for own in assigned.values() for group in own}
    for group in groups:
        start = group[GROUP_START]
        if start in taken or not (_only_before(text, start) or _only_after(text, group[GROUP_END])):
            continue
        days = {_day_key(atom) for atom in group[GROUP_ATOMS]}
        if any(
            _day_key(atom) not in days
            for status in statuses
            if not status[_REVOKED] and not status[_IS_SUPERSEDED]
            for own in status[_GROUPS]
            for atom in own[GROUP_ATOMS]
        ):
            return True
    return False


def _only_restricted(text: str, status: _Status) -> tuple[set[tuple[object, ...]], bool] | None:
    """The days "only" restricts a status to (see :func:`_only_days`), as :func:`_day_key`
    gives them, and whether the status names another day too; ``None`` when no "only"
    restricts it. "Only" ("just") right before a date group, or before the status ("only
    closed today"), restricts it to the group's days up to the end of the sentence ("only
    today, Thursday and Friday"; "Closed only today. Tomorrow and Friday as well" names two
    more); right after a group, to its days from the start of the sentence ("Closed today,
    tomorrow and Friday only"); right after or before one day of a group ("today only,
    Thursday and Friday", "Thursday and Friday. Correction: only Thursday"), to that day
    and the names of it beside it ("today only (Wednesday)"). "Only if" opens a condition,
    and "not only" adds days."""
    position = status[_POSITION]
    before_status = text.endswith("only ", 0, position) and _only_before(text, position)
    days: set[tuple[object, ...]] = set()
    named: list[DateAtom] = []
    for group in status[_GROUPS]:
        atoms = group[GROUP_ATOMS]
        named.extend(atoms)
        start, end = group[GROUP_START], group[GROUP_END]
        if before_status or _only_before(text, start):
            low = position if before_status else start
            days.update(
                _day_key(atom)
                for atom in atoms
                if not _SENTENCE_END.search(text, *sorted((low, atom[ATOM_START])))
            )
            continue
        if _only_after(text, end):
            days.update(
                _day_key(atom)
                for atom in atoms
                if not _SENTENCE_END.search(text, atom[ATOM_END], end)
            )
            continue
        links = group[GROUP_LINKS]
        last = len(atoms) - 1
        index = 0
        while index <= last:
            if (index < last and _only_after(text, atoms[index][ATOM_END])) or (
                index and _only_before(text, atoms[index][ATOM_START])
            ):
                days.add(_day_key(atoms[index]))
                while index < last and links[index] == "appos":
                    index += 1  # "today only (Wednesday)": the same day named again
                    days.add(_day_key(atoms[index]))
            index += 1
    if not days:
        return None
    return days, any(_day_key(atom) not in days for atom in named)


def _only_after(text: str, end: int) -> bool:
    """Whether "only" follows ``end`` as a word of its own, and opens no condition."""
    return (
        text.startswith(" only", end)
        and not text[end + 5 : end + 6].isalnum()
        and not text.startswith(_ONLY_CONDITIONS, end + 5)
    )


def _only_before(text: str, start: int) -> bool:
    """Whether "only" ("only on", "just") comes right before ``start``, but not "not only"."""
    for lead in _ONLY_LEADS:
        if text.endswith(lead, 0, start):
            before = start - len(lead)
            return (before == 0 or not text[before - 1].isalnum()) and not text.endswith(
                "not ", 0, before
            )
    return False


_ONLY_LEADS = ("only ", "only on ", "only for ", "just ", "just on ", "just for ")
_ONLY_CONDITIONS = (" if", " when", " unless", " in case", " should", " until")
# The links that make a group of days several days: a list, a range or a run.
_SEVERAL_LINKS = frozenset({"list", "range", "until", "first"})
# The links that can join two names of one day (see dates.Link).
_RESTATING_LINKS = frozenset({"appos", "lead"})
# Words after the last day of a list, in its clause, that leave the list its days (see
# _list_carried): words that restate or add to it ("too", "as well", "again", "only"), the
# words that join them, who it is for ("for all students", "all schools", "district-wide"),
# what it closes too ("and all evening activities") and a reason for it ("snow", "inclement
# weather"). It lists what may stand there, not what may not: any other word could make the
# last days its own subject ("Closed today, tomorrow under review", "... Thursday and Friday
# not affected", "... students return", "... stay tuned"), and no list of such words is ever
# whole. A cause ends the words read ("... due to the ice storm"), as does what the status
# takes in ("... including evening activities").
_LIST_STANDS = frozenset(
    [
        "and", "for", "the", "our", "all", "of", "with", "a", "an", "both", "each", "every",
        "entire", "whole", "too", "also", "as", "well", "again", "only", "plus", "either",
        "districtwide", "district-wide", "systemwide", "system-wide", "countywide",
        "county-wide", "wide", "everyone", "locations", "sites", "this", "week",
    ]
    + [word for word, scope in SCOPES.items() if scope == "school"]  # "for students"
)  # fmt: skip
# "In" and "at" leave a list its days ("at all schools", "in the district"), but not before
# a word that says students attend ("Closed today, tomorrow students in class", "... in
# school", "- in session"): see _carrying_words and _usual_words.
_ATTENDING = frozenset({"in", "at"})
_ATTENDED = frozenset({"school", "class", "classes", "session"})
# Reasons for a status ("Closed today and tomorrow, inclement weather"), which can name its
# days too ("snow days"): see weather.
_REASON_WORDS = frozenset(
    [
        "snow", "snowy", "snowfall", "snowstorm", "ice", "icy", "sleet", "freezing", "rain",
        "storm", "storms", "winter", "wintry", "weather", "inclement", "cold", "extreme",
        "bitter", "frigid", "wind", "chill", "chills", "windchill", "subzero", "sub-zero",
        "temperatures", "temps", "flood", "flooding", "hurricane", "tropical", "heat", "power",
        "outage", "outages", "severe", "blizzard", "hazardous", "dangerous", "road", "roads",
        "conditions", "fog", "tornado", "holiday", "break", "vacation",
    ]
)  # fmt: skip
# Words that a day's number can follow ("AMI today and tomorrow, days 3 and 4"), and that
# can stand before "day" ("Closed today and tomorrow all day"), as a reason can ("... snow
# days").
_NUMBERED_DAYS = frozenset({"day", "days"})
_WHOLE_DAY_WORDS = frozenset({"all", "full", "entire", "whole"})
_OPEN_WORDS = frozenset(["open", "opens", "opened", "opening"])
_PART_WORDS = frozenset(
    [
        "morning", "mornings", "afternoon", "afternoons", "evening", "evenings", "night",
        "nights", "nite", "nites",
    ]
)  # fmt: skip
# What a part of the day can be the time of, besides the school day: "Closed today and
# tomorrow and all evening activities" closes the activities too.
_PART_EVENTS = frozenset(
    [
        "activities", "activity", "events", "event", "programs", "program", "practices",
        "practice", "games", "game", "meetings", "meeting", "classes", "class",
    ]
)  # fmt: skip
# The words that join such events to a list's status, a few words before them: "Closed today
# and tomorrow and all evening activities". With none, the events are the last days' own
# subject: "Closed today, Thursday and Friday games postponed" (see _carrying_words).
_EVENTS_JOINED = frozenset({"and", "all", "plus"})
# Words that say a day runs as usual ("Closed today, Thursday and Friday normal"), but for
# one of its details ("2 hour delay today and tomorrow with regular dismissal").
_USUAL_WORDS = frozenset(
    ["normal", "normally", "regular", "regularly", "usual", "usually", "scheduled", "standard"]
)
_USUAL_DETAILS = frozenset(
    [
        "dismissal", "dismissals", "release", "bus", "buses", "busses", "routes", "route",
        "transportation", "time", "times", "hours", "start", "lunch", "pickup",
    ]
)  # fmt: skip
# Statuses that, after a mark, add to one another rather than take its days: "Closed today
# and tomorrow - NTI days" is two days of remote learning.
_COMBINED_KINDS = frozenset({"closed", "remote"})


def _carried_elsewhere(  # noqa: PLR0913, PLR0917 - the text's parts, read as they are
    text: str,
    clauses: list[_Clause],
    mentions: list[Mention],
    statuses: list[_Status],
    groups: tuple[DateGroup, ...],
    revoked_by: dict[int, int],
    openings: tuple[_Opening, ...],
) -> bool:
    """Whether a status's list of days could end with days that are another word's.

    "Closed today, tomorrow and Friday open" can be closed today and open
    tomorrow and Friday as much as closed all three days, and so can a list
    of days followed in its sentence by a status of another kind that names
    no day of its own ("Closed today, Thursday and Friday 2 hour delay", "NTI
    today, Thursday and Friday closed", "Closed Monday through Wednesday,
    Thursday - 2 hour delay"), or by a status of its own kind denied ("...
    Thursday and Friday not closed", "... - no closings"), or in its clause by
    any word but those that leave a list its days ("Closed today, tomorrow under
    review", "... Thursday and Friday not affected", "... students return": see
    :func:`_carrying_words`), or in a clause after a mark by a word that says
    the day runs as usual or is held ("... - normal", "... - in session"). So
    can a list led by a part of today ("Closed this afternoon, Thursday and
    Friday"). Such a text says no status for sure. A status of the same kind
    restates the list's ("No school today and tomorrow - snow days"), a remote
    day after a mark adds to a closure ("Closed today and tomorrow - NTI days"),
    and a side note, an open office, a status that replaces another and a word
    that calls one off claim no school day.
    A list led by a relative day ("Closed today, Thursday and Friday", which
    could name today again) is no list for sure when the text says school is
    open on one of its days anywhere ("... Open Friday.", "... Friday: regular
    schedule").
    """
    revokers = revoked_by.values() if revoked_by else ()
    for status in statuses:
        if status[_REVOKED]:
            continue
        for group in status[_GROUPS]:
            links = group[GROUP_LINKS]
            if not links or _SEVERAL_LINKS.isdisjoint(links):
                continue  # one day, or one day named two ways
            atoms = group[GROUP_ATOMS]
            if (
                links[0] in _RESTATING_LINKS
                and atoms[0][ATOM_KIND] == "relative"
                and text.startswith("this ", atoms[0][ATOM_START])
            ):
                return True  # "Closed this afternoon, Thursday and Friday"
            if links[0] == "lead" and openings and _opened_in_list(group, openings):
                return True  # "Closed today, Thursday and Friday. Open Friday."
            if _list_carried(text, clauses, mentions, status, group, groups, revokers):
                return True
    return False


def _list_carried(  # noqa: PLR0911, PLR0912, PLR0913, PLR0917 - as _carried_elsewhere, one list
    text: str,
    clauses: list[_Clause],
    mentions: list[Mention],
    status: _Status,
    group: DateGroup,
    groups: tuple[DateGroup, ...],
    revokers: Container[int],
) -> bool:
    """:func:`_carried_elsewhere` for one ``status`` and one of its lists of days."""
    end = group[GROUP_END]
    size = len(text)
    if end >= size - 1:
        return False  # nothing after the list ("Closed today and tomorrow")
    home = _home(clauses, group[GROUP_START])
    clause_end = clauses[home].end
    count = len(clauses)
    stop = home + 1
    while stop < count and not clauses[stop].strong:
        stop += 1
    sentence_end = clauses[stop].start if stop < count else size
    # The next day named after the list in its sentence: the words and statuses from its
    # clause on are that day's ("..., 2 hour delay Monday").
    limit = sentence_end
    words_end = clause_end  # where the words after the list in its clause end
    for other in groups:
        if other[GROUP_START] >= end:
            if other[GROUP_START] < sentence_end:
                limit = clauses[_home(clauses, other[GROUP_START])].start
                words_end = min(words_end, other[GROUP_START])
                denial = text.rfind("not ", end, other[GROUP_START])
                if denial >= 0 and _denied_day(text, other):
                    words_end = min(words_end, denial)  # "... Thursday and Friday not Monday"
            break
    # A list with no "and" before its last day, or led by a relative day ("Closed today,
    # tomorrow", "Closed today, Thursday and Friday"), may end before the mark after it: the
    # first clause after the mark is read as its own clause's words are (see _loose_list).
    loose = _loose_list(text, group)
    loose_end = -1
    if loose and "?" in text[end : sentence_end + 1]:
        return True  # "Closed today, Thursday and Friday - ?"
    if loose and home + 1 < stop:
        # A clause that names a school day of its own is that day's ("..., Friday under
        # review"); one that names an evening ("- decision tonight") may be the list's.
        first = clauses[home + 1]
        if not any(
            first.start <= other[GROUP_START] < first.end and _school_day_group(other)
            for other in groups
        ):
            tokens = words(
                _masked_mentions(_without_dates(text, groups), mentions, first.start, first.end)
            )
            if not _LISTING_CLOSERS.issuperset(tokens) and _carrying_words(
                tokens, status[_KIND], dated=False, subject=False
            ):
                return True
            loose_end = first.end
    if _status_after(clauses, mentions, status, revokers, (end, clause_end, limit, loose_end)):
        return True
    # The words up to the end of the list's clause, or to the next day named in it: "Closed
    # today, tomorrow decision tonight" makes "tomorrow" the decision's.
    evening = group[GROUP_ATOMS][-1][ATOM_EVENING]  # "... tomorrow night games postponed"
    if _clause_carries(text, mentions, status, (end, words_end, clause_end), evening=evening):
        return True
    if limit < clause_end:
        return False  # (a day named in the list's own clause: the rest is that day's)
    # After a mark, in the list's sentence, up to the clause of the next day named: a clause
    # that says the day runs as usual ("Closed today, Thursday and Friday - normal"). (After
    # a loose list, the first clause with any word its own clause could not hold carries
    # it, but for the words that only close a listing: "Closed today, tomorrow - decision
    # tonight", "Closed today, Thursday and Friday, classes will be held", "- stay tuned".)
    later = home + 1
    while later < stop and clauses[later].start < limit:
        clause = clauses[later]
        tokens = words(_masked_mentions(text, mentions, clause.start, clause.end))
        if _usual_words(tokens):
            return True
        later += 1
    return False


def _loose_list(text: str, group: DateGroup) -> bool:
    """Whether a list of days could end before a mark after it: one led by a relative day
    ("Closed today, Thursday and Friday", which could name today again), or one with no
    "and", "or" or "&" before its last day ("Closed today, tomorrow", "Closed Monday,
    Tuesday, Wednesday": the mark after it could go on with another item)."""
    links = group[GROUP_LINKS]
    atoms = group[GROUP_ATOMS]
    if atoms[-1][ATOM_EVENING]:
        return False  # ("Closed today, tomorrow night - games postponed": no school day)
    if links[0] == "lead":
        return True
    if links[-1] != "list":
        return False  # (a range ends where it says)
    between = text[atoms[-2][ATOM_END] : atoms[-1][ATOM_START]]
    return "&" not in between and _LIST_JOINS.isdisjoint(words(between))


_LIST_JOINS = frozenset({"and", "or", "plus", "nor"})
# Words that close a listing without a word on its days ("- stay tuned", "- check back"), the
# words a status after the mark leaves of itself ("- NTI days") and an open office's ("-
# offices open"): after a loose list, they leave it its days (see _list_carried).
_LISTING_CLOSERS = frozenset(
    {"stay", "tuned", "check", "back", "day", "days", "office", "offices", "district", "central",
     "administrative", "admin", "administration"}
)  # fmt: skip


def _clause_carries(
    text: str,
    mentions: list[Mention],
    status: _Status,
    places: tuple[int, int, int],
    *,
    evening: bool = False,
) -> bool:
    """Whether the words after a list of days in its clause could take its last days (see
    :func:`_carrying_words`). ``places`` are where the list ends, where the words end (the
    clause's end, or the next day named in it) and where the clause ends. A list that heads
    its status has the status's subject between them: "Thursday and Friday: Lincoln County
    Schools closed". A list that ends with an evening is followed by what is held then
    ("Closed today, tomorrow night games postponed")."""
    end, words_end, clause_end = places
    kind = status[_KIND]
    start = end
    position = status[_POSITION]
    if end <= position < words_end:
        subject = words(_masked_mentions(text, mentions, end, position))
        if _carrying_words(subject, kind, dated=False, subject=True):
            return True
        start = next(mention.end for mention in mentions if mention.start == position)
    tokens = words(_masked_mentions(text, mentions, start, words_end))
    return _carrying_words(
        tokens, kind, dated=words_end < clause_end, subject=False, evening=evening
    )


def _status_after(
    clauses: list[_Clause],
    mentions: list[Mention],
    status: _Status,
    revokers: Container[int],
    places: tuple[int, int, int, int],
) -> bool:
    """Whether a status of another kind after a list of days, or one of its kind denied,
    could take its days (see :func:`_list_carried`). ``places`` are where the list ends,
    where its clause ends, where the clause of the next day named after it starts (or its
    sentence ends), and, for a loose list (see :func:`_loose_list`), where the first clause
    after its mark ends (-1 otherwise): there a side note could take its last days too
    ("Closed today, tomorrow no activities", "Closed today, Thursday and Friday - buses
    not running"; an open office takes none: "... - offices open")."""
    end, clause_end, limit, loose_end = places
    kind = status[_KIND]
    elsewhere = -1  # where the clause of an open office or the like ends ("offices open")
    for index, mention in enumerate(mentions):
        start = mention.start
        if start < end or start == status[_POSITION]:
            continue
        if start >= limit and start >= loose_end:
            break
        if start < loose_end and (
            mention.kind == "note"
            or (mention.dropped is not None and mention.dropped in _SCOPE_DROPS)
        ):
            return True
        if start >= limit:
            continue  # (only a side note there: see above)
        if mention.elsewhere:
            elsewhere = clauses[_home(clauses, start)].end
            continue
        if mention.dropped == "negated" and mention.kind in {kind, "ambiguous"}:
            return True  # "Closed today, Thursday and Friday not closed", "... - no closings"
        if (
            mention.kind in {"note", "revoke"}
            or mention.superseding
            or index in revokers
            or mention.kind == kind
            or (mention.kind == "open" and start < elsewhere)
            or (
                start >= clause_end
                # After a mark, a remote day adds to a closure, and a status word that does
                # not say what it is about says nothing of the days ("- no in-person classes").
                and ({kind, mention.kind} <= _COMBINED_KINDS or mention.kind == "ambiguous")
            )
            or (mention.dropped is not None and mention.dropped in _SCOPE_DROPS)
        ):
            continue
        return True
    return False


def _carrying_words(
    tokens: list[str], kind: StatusKind, *, dated: bool, subject: bool, evening: bool = False
) -> bool:
    """Whether words after a list of days, in its clause, could take its last days (see
    :func:`_list_carried`): any word but those that leave a list its days (see
    :data:`_LIST_STANDS` and :func:`_detail_stands`), the time or the length of a late start
    or an early dismissal ("Delayed Thursday and Friday by 2 1/2 hours", "Early dismissal
    today and tomorrow at 1:00"), and, when ``dated`` (the words run up to the next day the
    clause names), a return on that day ("Closed today and tomorrow reopening Friday"). "In"
    or "at" stands but before a word that says students attend ("... students in class").
    A cause, or what the status takes in, ends the words read ("... Friday due to the
    storm", "... including evening activities"; "as per usual" is no cause). A school's
    name stands there too ("Closed today and tomorrow for Oak Ridge Elementary"), and, as
    the ``subject`` of a status the list heads, one in words the parser reads ("Thursday
    and Friday: Lincoln County Schools closed"; see :func:`_school_name_end`)."""
    timed = kind in _TIMED_KINDS
    position = 0
    count = len(tokens)
    while position < count:
        token = tokens[position]
        position += 1
        if token in _LIST_STANDS or token in _REASON_WORDS:
            continue
        if token in _PART_EVENTS and (
            evening or not _EVENTS_JOINED.isdisjoint(tokens[max(0, position - 4) : position - 1])
        ):
            continue  # "... and all evening activities", but not "... Friday games postponed"
        if token in _CARRYING_ENDS:
            # ("As per usual" is no cause: the days run as usual; nor is "due to be decided".)
            return (token in _PER and position < count and tokens[position] in _USUAL_WORDS) or (
                tokens[position : position + 1] == ["to"]
                and tokens[position + 1 : position + 2] in _DUE_VERBS
            )
        if token in _ATTENDING:
            if position < count and tokens[position] in _ATTENDED:
                return True  # "Closed today, tomorrow students in class"
            continue  # "at all schools", "at 1:00 pm"
        if timed and (
            token in _DETAIL_WORDS or token in _TIMED_STANDS or _DETAIL_NUMBER(token) is not None
        ):
            continue  # "by 2 1/2 hours", "at 1:00 pm", "until 10"
        if dated and token in _RETURN_WORDS:
            continue  # "reopening Friday", "students return Monday"
        if _detail_stands(tokens, position - 1, kind):
            continue
        named = _school_name_end(tokens, position - 1, subject=subject)
        if named < position:
            return True
        position = named  # "Lincoln County Schools"
    return False


def _school_name_end(tokens: list[str], start: int, *, subject: bool) -> int:
    """Where a school's name that starts at ``start`` ends, or ``start`` when none does: words
    that nothing in the parser reads (see :func:`_role`), then the words that end a school's
    name ("Oak Ridge Elementary"). After a list a word the parser reads is no name's
    ("Closed today, tomorrow reopen schools"); as the ``subject`` of a status after the list,
    any word that can be a name's is ("Thursday and Friday: Lincoln County Schools
    closed": see :func:`_name_word`)."""
    index = start
    count = len(tokens)
    while index < count and (
        (_name_word(tokens[index]) if subject else _role(tokens[index]) == "n")
        or (index > start and tokens[index] in _NAME_JOINERS)
    ):
        index += 1
    end = index
    while end < count and tokens[end] in _INSTITUTION_WORDS:
        end += 1
    return end if index > start and end > index else start


def _detail_stands(tokens: list[str], position: int, kind: StatusKind) -> bool:
    """Whether a word after a list of days leaves it its days as a detail of the words beside
    it (see :func:`_carrying_words`): a part of the day that a status of ``kind`` is for ("2
    hour delay Thursday and Friday morning") or that an event is in ("... and all evening
    activities"), a usual detail ("with normal dismissal"), a day's number ("days 3 and 4"),
    "all day" and the days of a reason ("snow days")."""
    token = tokens[position]
    following = tokens[position + 1] if position + 1 < len(tokens) else ""
    before = tokens[position - 1] if position else ""
    if token in _PART_WORDS:
        return token in _PART_FITS.get(kind, ()) or following in _PART_EVENTS
    if token in _USUAL_WORDS:
        return following in _USUAL_DETAILS
    if token in _USUAL_DETAILS:
        return before in _USUAL_WORDS
    if token in _NUMBERED_DAYS:
        return following.isdigit() or before in _WHOLE_DAY_WORDS or before in _REASON_WORDS
    if token.isdigit():
        return before in _NUMBERED_DAYS or (
            before == "and" and position > 1 and tokens[position - 2].isdigit()
        )
    return False


def _usual_words(tokens: list[str]) -> bool:
    """Whether a clause after a list of days, in its sentence, says a day runs as usual (see
    :func:`_list_carried`): an open word or a word that says school is held or untouched
    ("- in session", "- not affected", "- students in class"), or a word of
    :data:`_USUAL_WORDS` but before a detail it is about ("- regular dismissal"). A cause, or
    what the status takes in, ends the words read ("- as per usual" is no cause)."""
    last = len(tokens) - 1
    for position, token in enumerate(tokens):
        if token in _CARRYING_ENDS:
            # ("- as per usual" is no cause: the days run as usual.)
            return token in _PER and position < last and tokens[position + 1] in _USUAL_WORDS
        if token in _USUAL_WORDS:
            if position == last or tokens[position + 1] not in _USUAL_DETAILS:
                return True
        elif (
            token in _OPEN_WORDS
            or token in _HELD_WORDS
            or (token in _ATTENDING and position < last and tokens[position + 1] in _ATTENDED)
            or (token in _BACK and _back_to_school(tokens, position))
        ):
            return True  # "- open", "- in session", "- students in class", "- students back"
    return False


def _back_to_school(tokens: list[str], position: int) -> bool:
    """Whether the "back" at ``position`` says students return ("students back", "we'll be
    back", "back to school", "back in class"), not "check back" or "call back"."""
    return (position > 0 and tokens[position - 1] in _BACK_SUBJECTS) or (
        position + 2 < len(tokens)
        and tokens[position + 1] in _BACK_TO
        and tokens[position + 2] in _ATTENDED
    )


_BACK = frozenset({"back"})
_BACK_TO = _ATTENDING | {"to"}  # "back to school", "back in class"
_BACK_SUBJECTS = frozenset(
    {"students", "kids", "children", "everyone", "we", "classes", "school", "be", "are", "is"}
)


# Words that say a school day is held, or that nothing changes it: "- in session", "- classes
# resume", "- students return", "- not affected".
_HELD_WORDS = frozenset(
    {
        "session", "resume", "resumes", "reopen", "reopens", "return", "returns", "returning",
        "affected", "impacted", "unaffected", "unchanged",
    }
)  # fmt: skip


_CARRYING_ENDS = _CAUSE_OPENERS_WORDS | {"including", "includes", "include"}
_PER = frozenset({"per"})  # (the cause opener that "as per usual" holds)
# What "due to" can lead besides a cause: "Closed today, tomorrow due to be decided tonight",
# "... due to reopen".
_DUE_VERBS = (["be"], ["reopen"], ["open"], ["resume"], ["return"])
# The kinds of status with a time or a length of their own, which words after their list of
# days can give (see _carrying_words).
_TIMED_KINDS = frozenset({"delayed", "early_dismissal"})
# The words of such a time or length besides _DETAIL_WORDS: "2 1/2 hours", "until 10", "2
# hours late", "1 hour early".
_TIMED_STANDS = frozenset(
    {"1/2", "1/4", "3/4", "am", "pm", "until", "till", "til", "o'clock", "oclock", "late", "early"}
)
# Words of a return to school on a day named after them: "Closed today and tomorrow
# reopening Friday", "Closed Thursday and Friday, students return Monday".
_RETURN_WORDS = frozenset(
    {
        "reopen", "reopens", "reopening", "re-open", "re-opens", "re-opening", "resume",
        "resumes", "resuming", "return", "returns", "returning", "back", "will", "we",
        "students", "classes", "school", "schools", "on",
    }
)  # fmt: skip
# The part of the day each kind of status is for: "2 hour delay Thursday and Friday morning".
_PART_FITS: dict[str, frozenset[str]] = {
    "delayed": frozenset(["morning", "mornings"]),
    "early_dismissal": frozenset(["afternoon", "afternoons"]),
}


# The notes of a status about something besides the school's day (see mentions.SCOPE_NOTES).
_SCOPE_DROPS: frozenset[Note | None] = frozenset(SCOPE_NOTES.values())


def _masked_mentions(text: str, mentions: list[Mention], start: int, end: int) -> str:
    """``text[start:end]`` with every mention in it blanked out."""
    pieces: list[str] = []
    position = start
    for mention in mentions:
        if mention.end <= position or mention.start >= end:
            continue
        pieces.append(text[position : max(position, mention.start)])
        position = max(position, min(mention.end, end))
    pieces.append(text[position:end])
    return " ".join(pieces)


def _one_date(groups: tuple[DateGroup, ...]) -> bool:
    """Whether the date groups hold one date with a day number at most (see _ONE_DATE)."""
    if len(groups) < 2 and (not groups or len(groups[0][GROUP_ATOMS]) < 2):  # noqa: PLR2004
        return True  # one atom at most (the most common case)
    found = 0
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            if atom[ATOM_KIND] == "explicit":
                found += 1
    return found <= 1


# Part of a day --------------------------------------------------------------------------
#
# "Closed this afternoon", "closed Wednesday PM" and "closed after 11:30" close the school for
# the rest of a day that has begun: an early dismissal. "Closed tomorrow morning" closes it for
# the start of a day: a late start when the text says when school opens ("closed tomorrow until
# 10", "closed Wednesday AM, reopening at 11"), and otherwise nothing anyone can act on, so it
# is unclear, and so is every status in the text that names no day. "Closed AM kindergarten" is
# part of the program; "closed after 5 PM", the evening. See snowlight.classify.dayparts.

# The words a closure's bound can hold (a cheap test before reading any closure's bounds).
_PART_HINT = re.compile(
    r"\b(?:am|pm|mornings?|afternoons?|after|before|from|starting|beginning|as of|effective"
    r"|until|till|til|at)\b",
    re.ASCII,
)
# The runs of letters and digits those words are, as :func:`_facts` reads a text's words: a
# text with none of them has no match of _PART_HINT, so it is not searched, and one with any
# of them but "as" (which must come before "of") has one.
_PART_RUNS = frozenset(
    {
        "am", "pm", "morning", "mornings", "afternoon", "afternoons", "after", "before", "from",
        "starting", "beginning", "as", "effective", "until", "till", "til",
    }
)  # fmt: skip


# The closures limited to part of a day, by mention, and what else that decides. A plain tuple,
# read by the field numbers below (see _Status).
type _Parts = tuple[
    dict[int, Bound | Split],  # _PARTS_BOUNDS
    # A morning closure's late start, from the delay after it: "closed tomorrow morning,
    # opening at 11" (closure -> delay).
    dict[int, int],  # _PARTS_REOPENING
    # The statuses another one took over: the delays a morning closure took its opening
    # from, and the afternoon slots of a remote learning day (see _remote_afternoon).
    frozenset[int],  # _PARTS_TAKEN
    bool,  # _PARTS_UNCLEAR: a closure (or one of its days) was left unclear
    bool,  # _PARTS_UNCLEAR_DATED: and it named its days
]
_PARTS_BOUNDS: Final = 0
_PARTS_REOPENING: Final = 1
_PARTS_TAKEN: Final = 2
_PARTS_UNCLEAR: Final = 3
_PARTS_UNCLEAR_DATED: Final = 4


_NO_PARTS: _Parts = ({}, {}, frozenset(), False, False)


def _part_days(  # noqa: PLR0912, PLR0913, PLR0917 - one pass over the closures, then their bounds
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    groups: tuple[DateGroup, ...],
    notes: set[Note],
    leading: bool,
) -> _Parts:
    """Read which closures are limited to part of a day, and settle those that state nothing.

    A closure of part of the program, of the evening, or of a morning with no
    opening time is dropped here with its note; the rest are turned into their
    statuses by :func:`_part_statuses`.
    """
    found: dict[int, tuple[Bound | Split, list[DateGroup]]] = {}
    whole: list[int] = []  # the dated closures of whole days
    for index, mention in enumerate(mentions):
        if (
            mention.kind != "closed"
            or mention.dropped is not None
            or mention.revoked
            or index in assignment[_ASSIGNED_HEDGED]
        ):
            continue
        own = assignment[_ASSIGNED_GROUPS].get(index, ())
        if not may_bound(text, mention.start, mention.end, own, leading):
            if own:
                whole.append(index)
            continue  # (closure_bounds would find nothing: see there)
        own = sorted(own, key=_group_start)
        bound = closure_bounds(text, mention.start, mention.end, own, leading)
        if bound is not None:
            found[index] = (bound, own)
        elif own:
            whole.append(index)
    if not found:
        return _NO_PARTS
    _whole_days(text, found, groups)
    if whole:
        _whole_day_slots(text, found, [assignment[_ASSIGNED_GROUPS][index] for index in whole])
    bounds: dict[int, Bound | Split] = {}
    reopening: dict[int, int] = {}
    unclear = unclear_dated = False
    for index, (bound, own) in found.items():
        if isinstance(bound, Split):
            if _noted_pieces(bound, notes):
                unclear = unclear_dated = True
            bounds[index] = bound
            continue
        if bound.part == "morning" and bound.opens_at is None:
            later = _morning_start(text, mentions, assignment, groups, index, bound, own)
            if later == _WHOLE_DAY:
                continue  # "Tuesday Morning: Closed": the day's slot, so the whole day
            if later is not None:
                reopening[index] = later  # "closed tomorrow morning, opening at 11"
                bounds[index] = bound
                continue
        if bound.part == "afternoon" or bound.opens_at is not None:
            bounds[index] = bound  # an early dismissal, or a late start ("until 10")
        elif _drop_part(mentions[index], bound, notes):
            unclear = True
            unclear_dated = unclear_dated or bool(own)
    # "... Remote Learning Day | Tuesday Afternoon: Closed": the remote day's afternoon.
    remote_afternoons = frozenset(
        [
            index
            for index, bound in bounds.items()
            if bound == _AFTERNOON and _remote_afternoon(text, mentions, assignment, index, found)
        ]
    )
    return (
        {index: bound for index, bound in bounds.items() if index not in remote_afternoons},
        reopening,
        frozenset(reopening.values()) | remote_afternoons,
        unclear,
        unclear_dated,
    )


_MORNING = Bound("morning")
_AFTERNOON = Bound("afternoon")


def _remote_afternoon(
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    index: int,
    found: dict[int, tuple[Bound | Split, list[DateGroup]]],
) -> bool:
    """Whether an afternoon slot's closure is the afternoon of a remote learning day.

    "Thursday Morning: Remote Learning Day | Thursday Afternoon: Closed": the
    morning slot states the day's status, a remote learning day, and the
    afternoon slot's "Closed" says the buildings stay shut after it. It adds
    nothing to the day, as "Thursday Morning: 2 hour delay | Thursday Afternoon:
    Closed" is a delay. The closure must be the slot's alone, with no time or
    other bound of its own ("Thursday Afternoon: Closing at 1:00" is not), and
    a remote status must hold that day and no other.
    """
    mention = mentions[index]
    own = found[index][1]
    if (
        len(own) != 1
        or own[0][GROUP_END] >= mention.start
        or not slot_heading(text, own[0], "afternoon")
        or own_bound(text, mention.start, mention.end) is not None
    ):
        return False
    day = _day_key(own[0][GROUP_ATOMS][0])
    for other, remote in enumerate(mentions):
        if (
            remote.kind != "remote"
            or remote.dropped is not None
            or remote.revoked
            or other in assignment[_ASSIGNED_HEDGED]
        ):
            continue
        days = [
            atom
            for group in assignment[_ASSIGNED_GROUPS].get(other, ())
            for atom in group[GROUP_ATOMS]
        ]
        if days and all(_day_key(atom) == day and not atom[ATOM_EVENING] for atom in days):
            return True
    return False


_WHOLE_DAY = -1  # (see _morning_start)


def _morning_start(  # noqa: PLR0913, PLR0917 - the closure, and the text around it
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    groups: Sequence[DateGroup],
    index: int,
    bound: Bound,
    own: Sequence[DateGroup],
) -> int | None:
    """What says when school starts after a morning closure with no opening time of its own.

    The delay that gives the opening ("closed tomorrow morning, opening at 11",
    "Tuesday Morning: Closed | Tuesday Afternoon: Opening At Noon"), or
    :data:`_WHOLE_DAY` for a closings page's morning slot, which closes the
    whole day ("Tuesday Morning: Closed"), or ``None``: nothing does.
    """
    later = _reopening(text, mentions, assignment[_ASSIGNED_GROUPS], index)
    if later is not None or not _slot_day(text, mentions[index], bound, own):
        return later
    later = _slot_opening(mentions, assignment, index, own[0])
    if later is None and not _slot_opens(text, groups, own[0]):
        return _WHOLE_DAY
    return later


def _slot_day(text: str, mention: Mention, bound: Bound, own: Sequence[DateGroup]) -> bool:
    """Whether a morning closure is a closings page's morning slot: "Tuesday Morning: Closed".

    The slot heading must be the closure's only day and the only thing that
    bounds it: "Tuesday Morning: Closed AM" still says the morning.
    """
    return (
        bound == _MORNING
        and len(own) == 1
        and own[0][GROUP_END] < mention.start
        and slot_heading(text, own[0])
        and own_bound(text, mention.start, mention.end) is None
    )


def _slot_opening(
    mentions: list[Mention], assignment: _Assignment, index: int, heading: DateGroup
) -> int | None:
    """A late start for the day of a morning slot's closure, in another slot of that day.

    "Tuesday Morning: Closed | Tuesday Afternoon: Opening At Noon" opens Tuesday
    at noon: the morning slot is closed until the afternoon one opens.
    """
    day = _day_key(heading[GROUP_ATOMS][0])
    for other, mention in enumerate(mentions):
        if (
            other == index
            or mention.kind != "delayed"
            or mention.dropped is not None
            or mention.revoked
            or other in assignment[_ASSIGNED_HEDGED]
        ):
            continue
        days = [
            atom
            for group in assignment[_ASSIGNED_GROUPS].get(other, ())
            for atom in group[GROUP_ATOMS]
        ]
        if days and all(_day_key(atom) == day and not atom[ATOM_EVENING] for atom in days):
            return other
    return None


# Words that open the school later in the day: "Tuesday Afternoon: Open", "... Reopening".
_OPENS_LATER = re.compile(
    r"\b(?:re-?)?open(?:s|ed|ing)?\b(?!\s+house)|\bresum(?:e|es|ed|ing)\b|\bin\s+session\b",
    re.ASCII,
)


def _slot_opens(text: str, groups: Sequence[DateGroup], heading: DateGroup) -> bool:
    """Whether another entry for a morning slot's day opens the school with no time to act on.

    "Tuesday Morning: Closed | Tuesday Afternoon: Open" closes the morning
    only, and says nothing of when school starts: that stays unclear.
    """
    day = _day_key(heading[GROUP_ATOMS][0])
    for group in groups:
        if (
            group[GROUP_START] == heading[ATOM_START]
            or len(group[GROUP_ATOMS]) != 1
            or _day_key(group[GROUP_ATOMS][0]) != day
            or not _heading(text, group)
        ):
            continue
        if _OPENS_LATER.search(text, group[GROUP_END], _entry_end(text, groups, group)) is not None:
            return True
    return False


def _noted_pieces(split: Split, notes: set[Note]) -> bool:
    """Note the pieces of a split closure that state no status; whether a morning is among them."""
    left_open = False
    for piece, _groups in split.pieces:
        if piece is None or piece.part == "afternoon" or piece.opens_at is not None:
            continue
        if piece.part == "morning":
            notes.add("ambiguous")  # "closed Wednesday morning and Thursday"
            left_open = True
        else:
            notes.add("partial_program" if piece.part == "program" else "activities_cancelled")
    return left_open


def _drop_part(mention: Mention, bound: Bound, notes: set[Note]) -> bool:
    """Drop a closure that states no school day status; whether it was left unclear."""
    if bound.part == "program":
        _apply_scope(mention, "partial")  # "closed AM kindergarten"
        notes.add("partial_program")
        return False
    if bound.part == "evening":
        mention.dropped = "activities_cancelled"  # "closed after 5 PM"
        notes.add("activities_cancelled")
        return False
    mention.dropped = "ambiguous"  # "closed tomorrow morning", "closed from 8 to noon"
    notes.add("ambiguous")
    return True


# "Saturday school", "Sunday classes": a program on a day with no school, not the school day.
_WEEKEND_PROGRAM = re.compile(
    r"\b(?:satur|sun)day\s+(?:school|classes|class|academy|program|session)\b", re.ASCII
)


def _weekend_programs(
    text: str, mentions: list[Mention], assigned: dict[int, list[DateGroup]], notes: set[Note]
) -> None:
    """Drop a closure of a weekend program: "Saturday school cancelled" is no school day's."""
    ends = {
        match.start() + match.group().index("day") + 3 for match in _WEEKEND_PROGRAM.finditer(text)
    }
    if not ends:
        return
    for index, mention in enumerate(mentions):
        if mention.kind != "closed" or mention.dropped is not None:
            continue
        own = [atom[ATOM_END] for group in assigned.get(index, ()) for atom in group[GROUP_ATOMS]]
        if own and all(end in ends for end in own):  # (with a school day too, it stands)
            mention.dropped = "activities_cancelled"
            notes.add("activities_cancelled")


# Words that take back what came before: "Closed. Update: open", "Closed. Just kidding, open",
# "2 hour delay changed to open on time".
_RETRACTIONS = frozenset(
    {
        "update", "updated", "correction", "corrected", "kidding", "jk", "nevermind", "never",
        "disregard", "scratch", "now", "instead", "revised", "changed", "switched", "became",
        "becomes", "turned", "replaced", "reduced", "downgraded", "lowered", "scaled",
    }
)  # fmt: skip


def _retracted(
    text: str,
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    statuses: list[_Status],
    notes: set[Note],
) -> list[_Status]:
    """Drop the statuses an update to open replaces: "Closed. Update: open."

    The school opening, after a word that takes back what came before it,
    replaces the statuses before it: for its days if it names any, else for all
    of theirs. The buildings or a service opening ("Update: buildings open
    today", "Update: open today for meal pickup") replaces nothing, as offices
    opening does not (see :func:`_about_school`).
    """
    opening = [
        index
        for index, mention in enumerate(mentions)
        if mention.kind == "open"
        and mention.dropped is None
        and not mention.revoked
        and _about_school(text, mention.start, mention.end)
    ]
    last = opening[-1] if opening else 0
    opened = mentions[last]
    before = [i for i in range(last) if mentions[i].kind in _STATUS_KINDS]
    if not before or _RETRACTIONS.isdisjoint(words(text, mentions[before[-1]].end, opened.start)):
        return statuses  # (no opening: nothing before the first mention)
    days = {_day_key(atom) for group in assigned.get(last, ()) for atom in group[GROUP_ATOMS]}
    kept = [
        status
        for status in statuses
        if status[_POSITION] >= opened.start
        or (
            bool(days)
            and not {_day_key(atom) for group in status[_GROUPS] for atom in group[GROUP_ATOMS]}
            <= days
        )
    ]
    if len(kept) < len(statuses):
        notes.add("superseded")
    return kept


# Withdrawals ----------------------------------------------------------------------------
#
# A post can say that it, or part of it, was wrong: "Closed tomorrow is false", "Ignore posts
# saying we are closed tomorrow", "Closed today, tomorrow and Friday. Update: disregard
# Friday", "... Friday was posted in error", "Closed tomorrow. Update: posted in error." A
# status the withdrawal is about (after "disregard" or "ignore" in its sentence, before "in
# error" or "is false") stands no more, and nor do its days for the statuses before it. A
# sentence that withdraws with no status of its own withdraws the days it names from the
# statuses before it ("Update: Friday removed"), or, naming none, leaves unclear what it
# withdraws ("Closed tomorrow. Disregard the previous message." could be about this post or an
# earlier one): the statuses before it are no status for sure.

_WITHDRAWAL_CUES = re.compile(
    r"\b(?:(?P<object>disregard|ignore)"
    r"|(?P<removed>removed)"
    r"|in\s+error|by\s+mistake|mistakenly|(?:is|are|was|were)\s+(?:false|fake|untrue"
    r"|not\s+true|incorrect|wrong|a\s+mistake|an\s+error)"
    r"|false\s+(?:alarm|report|reports|information|info|rumou?rs?|posts?)|fake\s+news"
    # "Update: this has been rescinded", "The above is withdrawn", "This announcement has been
    # retracted": the post itself, no status of the sentence's own.
    r"|(?:this|that|the\s+above|(?:this|that|the\s+(?:above|previous|earlier))\s+(?:post"
    r"|message|announcement|notice|alert|update))\s+(?:has\s+been|have\s+been|is|was|are"
    r"|were|is\s+now|has\s+now\s+been)\s+(?:rescinded|withdrawn|retracted|revoked"
    r"|cancell?ed))\b",
    re.ASCII,
)
# The words a withdrawal holds, which the text's words are checked for first (see _word_bits).
_WITHDRAWAL_WORDS = frozenset(
    {"disregard", "ignore", "error", "false", "fake", "untrue", "true", "incorrect", "wrong",
     "removed", "mistake", "mistakenly", "rescinded", "withdrawn", "retracted", "revoked"}
)  # fmt: skip
_NEGATED_CUE = frozenset({"not", "don't", "dont", "never"})  # "do not ignore warnings"


def _withdrawals(  # noqa: PLR0912 - one pass over the cues, one branch per kind of cue
    text: str,
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    statuses: list[_Status],
    notes: set[Note],
) -> tuple[list[_Status], tuple[_Opening, ...]]:
    """The statuses left once the text's withdrawals are read, and the days they withdraw from
    the statuses before them, as openings for any kind of status (see above)."""
    withdrawn_at: set[int] = set()  # the statuses withdrawn, by where they stand
    days: list[_Opening] = []
    unclear_before = -1  # the statuses before here are no status for sure
    for cue in _WITHDRAWAL_CUES.finditer(text):
        start = cue.start()
        if not _NEGATED_CUE.isdisjoint(words(text, max(0, start - 8), start)[-2:]):
            continue
        low = max([text.rfind(mark, 0, start) for mark in _OPENING_SENTENCE_MARKS]) + 1
        ends = [text.find(mark, cue.end()) for mark in _OPENING_SENTENCE_MARKS]
        high = min([place for place in ends if place >= 0], default=len(text))
        inside = [m for m in mentions if low <= m.start < high]
        own = [m for m in inside if m.kind in _STATUS_KINDS]
        if not own and any(m.kind == "open" for m in inside):
            continue  # "Closed. Disregard, school is open.": an update to open (see _retracted)
        if not own:
            named = tuple(g for g in groups if low <= g[GROUP_START] < high)
            if named:
                days.append((start, _DENIALS | _OPEN_MARKED, named))
            elif cue.lastgroup != "removed":
                unclear_before = max(unclear_before, low)
            continue
        if cue.lastgroup == "removed":
            continue  # ("2 hour delay while snow is removed")
        if cue.lastgroup == "object":
            colon = text.find(":", cue.end(), high)
            low, high = cue.end(), colon if colon >= 0 else high  # "Ignore posts saying ..."
        else:
            high = start  # "Closed tomorrow is false"
        taken = [status for status in statuses if low <= status[_POSITION] < high]
        if taken and not any(status[_GROUPS] for status in taken) and low > 0:
            # "Closed tomorrow. Update: the closure notice was a mistake.": a status of its
            # sentence with no day of its own is the one posted before, of its kind.
            kinds = {status[_KIND] for status in taken}
            taken += [
                other for other in statuses if other[_POSITION] < low and other[_KIND] in kinds
            ]
        for status in taken:
            withdrawn_at.add(status[_POSITION])
            if status[_GROUPS]:
                days.append((status[_POSITION], _DENIALS | _OPEN_MARKED, status[_GROUPS]))
    if not withdrawn_at and unclear_before < 0:
        return statuses, tuple(days)
    kept = [
        status
        for status in statuses
        if status[_POSITION] not in withdrawn_at and status[_POSITION] >= unclear_before
    ]
    if withdrawn_at:
        notes.add("revoked")
    if unclear_before >= 0 and len(kept) + len(withdrawn_at) < len(statuses):
        notes.add("ambiguous")
    return kept, tuple(days)


# Openings -------------------------------------------------------------------------------
#
# A statement that school is open on a day a closure or a remote day names too says that day
# is neither: "Closed Thursday and Friday. Open Friday.", "Closed today and tomorrow. Update:
# tomorrow is a regular day", "Closed Thursday and Friday. We will reopen Friday.". After the
# status it takes the day from it, as a correction (when no word marks it as an update, the
# status's other days are a judgment call, and a status left with no day says nothing for
# sure). Before the status ("Open tomorrow. Closed tomorrow.") the two say opposite things of
# the day, which gets no status, unless the status is the update ("Open tomorrow. Update:
# closed tomorrow."). A school that reopens on a day is open from that day on; one that may
# reopen ("may reopen Friday", "reopening Friday if roads clear") leaves those days in doubt,
# and so does a decision to come on a day ("will reassess Thursday") for the days after it, and
# for the day itself when it is what the decision is about ("will reassess Friday tomorrow",
# "will reassess tomorrow's status tonight") or the last day a status names ("Closed Thursday
# and Friday; will reassess Friday.").
# The days are compared on the calendar (see _open_days): "Closed Thursday. Open tomorrow."
# posted on a Wednesday names one day twice.
# A status denied on a day ("Closed tomorrow. Update: tomorrow is not closed", "Closed
# Thursday and Friday. No closure Friday", "Closed today and tomorrow. Closed today but not
# tomorrow", "... Update: not tomorrow") says the same of that day, for that kind of status
# only (see _DENIED_BITS): a closure denied leaves a remote day standing, and a delay of
# another length denied ("not a 3 hour delay") denies no delay.

_OPEN_MARKED = 1  # after a word that marks an update: "Update: open Friday"
_OPEN_HEDGED = 2  # only possible: "may reopen Friday"
_OPEN_ONWARD = 4  # school reopens on the day: it is open from then on
_OPEN_AFTER = 8  # a decision on the day: the days after it are in doubt ("reassess Thursday")
_OPEN_ENDS = 256  # onward from the last day, not the first: an update ends a range (_held_day)
# A decision on the day, as _OPEN_AFTER, that bears on the day itself when no status's day
# comes after it: "Closed Thursday and Friday; will reassess Friday" (see _opened_targets).
_OPEN_LAST = 512
# A decision about the group's first day itself, made at the time its other words name:
# "will reassess Friday tomorrow", "will reassess tomorrow tonight", "reassess tomorrow's
# status" (see _reassessed_day).
_OPEN_FIRST = 1024
# A denial of a kind of status on the day, by the kind it denies: it bears on that kind only.
_DENIED_BITS: dict[str, int] = {"closed": 16, "remote": 32, "delayed": 64, "early_dismissal": 128}
_DENIALS = 16 | 32 | 64 | 128
# An update that ends a range ("Update: now only through tomorrow"), as an opening: it replaces
# every status's days after the range's last day (see _held_day).
_NARROWING = _DENIALS | _OPEN_MARKED | _OPEN_ONWARD | _OPEN_AFTER | _OPEN_ENDS
# The statuses an opening says the day is not: a late start or an early dismissal opens the
# school too ("2 hour delay tomorrow. Open tomorrow at 10.").
_OPENED_KINDS = frozenset({"closed", "remote"})
# What an opening does to a status's day (see _opening_effect).
_REPLACED = 1  # an update after it opens the day
_CORRECTED = 2  # an opening after it, with no word that marks it as an update
_DOUBTED = 4  # a reopening that is only possible, or a decision to come
_CONTRADICTED = 8  # an opening before it, with no word that marks the status as an update
_SCHOOL_SCOPES = frozenset({"school", "partial"})
# Words that make an "open" another place's or service's, just before it ("Shelter open
# tomorrow", "Buildings open Thursday") or as what it is open for ("Open tomorrow for meal
# pickup", "Schools open as warming centers"): a scope noun of anything but the school day
# (see lexicon.SCOPES), the buildings, which open while school is closed or held remotely,
# and the services a closed school's buildings hold.
_NOT_SCHOOL_WORDS = frozenset(
    [word for word, scope in SCOPES.items() if " " not in word and scope not in _SCHOOL_SCOPES]
    + ["building", "buildings", "campus", "campuses", "facility", "facilities", "doors"]
    + ["shelter", "shelters", "center", "centers", "centre", "centres", "site", "sites"]
    + ["meal", "meals", "pickup", "pick-up", "distribution", "warming", "cooling", "voting"]
    + ["polling", "polls", "testing", "clinic", "clinics", "vaccine", "vaccination"]
    + ["portal", "portals", "assignments", "lunches", "breakfast", "breakfasts", "pantry"]
)  # fmt: skip
# A day right after "reopen" or "resume" ("We will reopen Friday", "Classes resume on
# Monday", "reopening Friday") or a return to school ("Students return Friday", "we will be
# back Friday", "back to school Monday"), after "reassess" ("will reassess Thursday",
# "reassess the situation on Thursday"), or after an "open" that took no day ("Possibly open
# Friday") or a school day held ("Classes will be held Friday", "regular classes Friday").
_REOPENED_DAY = re.compile(
    r"\b(?:(?P<reopen>re-?open(?:s|ing)?|resum(?:e|es|ing))|(?P<open>open(?:s|ing)?)"
    r"|(?P<reassess>re-?assess(?:es|ing)?)"
    r"(?:\s+(?:the\s+)?(?:situation|conditions|weather|roads|plans?))?)"
    r"(?:\s+(?:on|by|as\s+of))?\s*$",
    re.ASCII,
)
# The same of a return to school, read as a reopening, or a school day held, read as an open
# day: kept apart from _REOPENED_DAY, so that only a text with a word of _RETURN_HINT before
# the day pays for it.
_RETURNED_DAY = re.compile(
    r"\b(?:(?P<reopen>return(?:s|ing)?"
    r"(?:\s+to\s+(?:school|class(?:es)?|campus|in-person(?:\s+[a-z]+)?))?"
    r"|(?:be|are|is|come|comes|coming|students|kids|children|everyone)\s+back"
    r"(?:\s+(?:to|in)\s+(?:school|class(?:es)?|session|campus))?"
    r"|back\s+(?:to|in)\s+(?:school|class(?:es)?|session|campus))"
    r"|(?P<open>(?:classes|class|school)\s+(?:will\s+be\s+|is\s+|are\s+)?held"
    r"|(?:regular|normal|usual)\s+class(?:es)?))"
    r"(?:\s+(?:on|by|as\s+of))?\s*$",
    re.ASCII,
)
# The words _RETURNED_DAY can find before a day (see _openings and _word_bits).
_RETURN_HINT = re.compile(r"return|back|held|regular|normal|usual", re.ASCII).search
_REOPEN_REACH = 64
# Words just before "reopen" or "resume" that make it no school reopening: a denial ("will
# not reopen Friday"), or something besides the school's day ("activities resume Friday",
# "bus routes will resume", "Power should be back Friday"; see also _NOT_SCHOOL_WORDS). A
# "no" denies it right before it only ("No school will be held Friday", but not "No school
# today - back to school Friday").
_NOT_REOPENING = frozenset(
    ["not", "won't", "wont", "cannot", "can't", "never", "service", "services", "lunch",
     "breakfast", "care", "construction", "power", "heat", "heating", "electricity", "water",
     "internet", "wifi", "phone", "phones", "lights"]
)  # fmt: skip
_REOPEN_LOOKBACK = 3  # the words before "reopen" read for a denial or a subject
# Words that make a reopening only possible: a condition, before it in its clause or after
# its day ("if roads clear we will reopen Friday", "reopening Friday if roads clear"), or a
# hedge before it ("may reopen Friday", "hope to reopen Friday").
_REOPEN_CONDITIONS = CONDITIONALS | CONDITIONS_ANYWHERE | frozenset(["pending"])
_REOPEN_HEDGES = (
    HEDGES
    | _REOPEN_CONDITIONS
    | frozenset(
        ["hope", "hopes", "hoping", "hopeful", "hopefully", "plan", "plans", "planning", "aim",
         "goal", "target", "tentatively"]
    )
)  # fmt: skip
_OPENING_CLAUSE_MARKS = ",;:.!?|"
_OPENING_SENTENCE_MARKS = ";.!?|"


def _openings(  # noqa: PLR0913 - the text's parts, and whether it denies a status
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    groups: tuple[DateGroup, ...],
    statuses: list[_Status],
    *,
    denials: bool,
) -> tuple[_Opening, ...]:
    """The text's statements that school is open on days it names (see :data:`_Opening`).

    An "open" about something besides the school ("offices open Friday"), about
    part of it ("Lincoln Elementary open Friday"), about its buildings ("buildings
    open Friday") or denied is none. A day right after "reopen", "resume" or a
    return to school is one ("We will reopen Friday", "Classes resume Friday",
    "Students return Friday", "back to school Friday"), and so, as a hedge, is
    one after "reassess", and one after an "open" that took no day or a school
    day held ("Classes will be held Friday").
    A status that names no day is for a day the posting time gives, which an
    opening can name too ("Closed. Open tomorrow." posted in the evening).
    With ``denials`` (a status was denied), a status the school's own denied on
    days it names ("tomorrow is not closed", "no closure Friday") is one for its
    kind of status (see :data:`_DENIED_BITS`).
    """
    # (A list's "in" costs less than any() over a generator.)
    opened = True in [
        status[_KIND] in _OPENED_KINDS and not status[_REVOKED] for status in statuses
    ]
    if not groups or not (opened or denials):
        return ()
    assigned, hedged = assignment
    found: list[_Opening] = []
    for index, mention in enumerate(mentions):
        if index not in assigned:
            continue
        if mention.kind != "open":
            if denials and mention.dropped == "negated":
                denial = _denial(text, mention, assigned[index])
                if denial is not None:
                    found.append(denial)
            continue
        if not opened or mention.revoked or mention.elsewhere or mention.narrowed is not None:
            continue
        if mention.dropped is not None and mention.dropped != "hedged":
            continue  # "not open Friday", "open Friday for staff"
        days = tuple(group for group in assigned[index] if _school_day_group(group))
        if not days or not _about_school(text, mention.start, mention.end):
            continue  # "Buildings open Friday", "Shelter open tomorrow"
        mode = _OPEN_MARKED if mention.superseding else 0
        if mention.dropped is not None or index in hedged:
            mode |= _OPEN_HEDGED
        found.append((mention.start, mode, days))
    if opened and (
        "open" in text or "resum" in text or "assess" in text or _RETURN_HINT(text) is not None
    ):
        _reopenings(text, mentions, assigned, groups, found)
    return tuple(found)


def _reopenings(
    text: str,
    mentions: list[Mention],
    assigned: dict[int, list[DateGroup]],
    groups: tuple[DateGroup, ...],
    found: list[_Opening],
) -> None:
    """Add to ``found`` the days a reopening, a return or a decision leads (see
    :func:`_reopened_on`) that no "open" took. (A day can follow "reopen" and head a status
    too: "School will reopen Monday - Monday: Closed". An "open" that took it is read by
    :func:`_openings`.)"""
    owners = {group[GROUP_START]: index for index, own in assigned.items() for group in own}
    for group in groups:
        owner = owners.get(group[GROUP_START])
        if (
            (owner is None or mentions[owner].kind != "open")
            and group[GROUP_OPEN_START] is None  # ("Delayed opening until Monday")
            and _school_day_group(group)
        ):
            reopened = _reopened_on(text, group)
            if reopened is not None:
                if reopened & _OPEN_FIRST:
                    first = group[GROUP_ATOMS][0]
                    group = (first[ATOM_START], first[ATOM_END], (first,), (), None)  # noqa: PLW2901
                found.append((group[GROUP_START], reopened, (group,)))


def _denial(text: str, mention: Mention, own: list[DateGroup]) -> _Opening | None:
    """A status of the school's denied on days it names, as an opening for its kind of status
    (see :func:`_openings`): "tomorrow is not closed", "no closure Friday", "Update: no delay
    tomorrow". One about something else ("No activities cancelled today", "No buses
    delayed") or part of the program, or a late start or an early dismissal at a time or of a
    length of its own ("not a 3 hour delay"), denies no status of the school's."""
    bit = _DENIED_BITS.get(mention.kind)
    if (
        bit is None
        or mention.revoked
        or mention.narrowed is not None
        or mention.delay is not None
        or mention.opens_at is not None
        or mention.dismissal is not None
        or (
            text.startswith("no ", mention.start)  # "No activities cancelled today"
            and SCOPES.get(text[mention.start + 3 : mention.end].partition(" ")[0], "school")
            != "school"
        )
    ):
        return None
    days = tuple(group for group in own if _school_day_group(group))
    return (
        (mention.start, bit | (_OPEN_MARKED if mention.superseding else 0), days) if days else None
    )


def _school_day_group(group: DateGroup) -> bool:
    """Whether a date group names a school day: a day, not only an evening."""
    for atom in group[GROUP_ATOMS]:  # (a loop costs less than any(), per call)
        if atom[ATOM_KIND] in _DAY_ATOMS and not atom[ATOM_EVENING]:
            return True
    return False


def _about_school(text: str, start: int, end: int) -> bool:
    """Whether the "open" at ``start``-``end`` is the school's: no other place or service
    just before it in its clause, nor as what it is open for after it (see
    :data:`_NOT_SCHOOL_WORDS`)."""
    clause = max([text.rfind(mark, 0, start) for mark in _OPENING_CLAUSE_MARKS]) + 1
    before = words(text, clause, start)[-_REOPEN_LOOKBACK:]
    if not _NOT_SCHOOL_WORDS.isdisjoint(before):
        # The buildings open for students, or with classes held, are the school open:
        # "Update: all buildings open tomorrow for students", "... buildings will be open
        # tomorrow and classes will be held"; and so are the school and its buildings
        # together ("School and campus open").
        if _BUILDINGS.isdisjoint(before) or not _NOT_SCHOOL_WORDS.isdisjoint(
            [word for word in before if word not in _BUILDINGS]
        ):
            return False
        if any(
            word in _SCHOOL_SUBJECTS and "and" in before[max(0, index - 1) : index + 2]
            for index, word in enumerate(before)
        ):
            return True
        ends = [text.find(mark, end) for mark in _OPENING_SENTENCE_MARKS]
        high = min([place for place in ends if place >= 0], default=len(text))
        return _STUDENTS_COME.search(text, end, high) is not None
    ends = [text.find(mark, end) for mark in _OPENING_CLAUSE_MARKS]
    after = words(text, end, min([place for place in ends if place >= 0], default=len(text)))
    return not any(
        word in _PURPOSE_WORDS
        and (
            not _NOT_SCHOOL_WORDS.isdisjoint(after[index + 1 : index + 3])
            or (
                after[index + 1 : index + 2]
                and after[index + 1] in _IN_NEED
                and (
                    after[index + 2 : index + 3] == ["needing"]
                    or after[index + 2 : index + 4] in _WHO_NEED
                )
            )
        )
        for index, word in enumerate(after)
    )


_PURPOSE_WORDS = frozenset(["for", "as"])
_SCHOOL_SUBJECTS = frozenset(["school", "schools", "class", "classes"])
_BUILDINGS = frozenset(
    ["building", "buildings", "campus", "campuses", "facility", "facilities", "doors"]
)
# What makes the buildings open the school open (see _about_school): students come, or classes
# are held. ("For students who need meals" is a service: see _IN_NEED.)
_STUDENTS_COME = re.compile(
    r"\bfor\s+(?:all\s+)?(?:students|classes|instruction|learning)\b"
    r"(?!\s+(?:who|needing|in\s+need))"
    r"|\b(?:classes|class|school)\s+(?:will\s+be\s+|is\s+|are\s+)?(?:held|in\s+session)\b",
    re.ASCII,
)
# Who a service is open for, when the school is not: "Open Friday for students who need
# meals", "... for families needing a warm place".
_IN_NEED = frozenset(
    ["students", "student", "families", "family", "those", "anyone", "kids", "children"]
)
_WHO_NEED = (["who", "need"], ["who", "needs"])


def _reopened_on(text: str, group: DateGroup) -> int | None:
    """How a day that "reopen", "resume", a return, "reassess", "open" or a school day held
    leads reads (``_OPEN_*``), if it does."""
    start = group[GROUP_START]
    low = max(0, start - _REOPEN_REACH)
    match = (
        _REOPENED_DAY.search(text, low, start)
        if text.find("open", low, start) >= 0
        or text.find("resum", low, start) >= 0
        or text.find("assess", low, start) >= 0
        else None
    )  # (with no word that can lead the day, the pattern need not look)
    if match is None:
        if _RETURN_HINT(text, low, start) is None:
            return None
        match = _RETURNED_DAY.search(text, low, start)  # "Students return Friday"
        if match is None:
            return None
    verb = match.start()
    sentence = max([text.rfind(mark, 0, verb) for mark in _OPENING_SENTENCE_MARKS]) + 1
    clause = max([text.rfind(mark, 0, verb) for mark in _OPENING_CLAUSE_MARKS]) + 1
    before = words(text, clause, verb)
    if (
        not _NOT_REOPENING.isdisjoint(before[-_REOPEN_LOOKBACK:])
        or before[-1:] == ["no"]
        or not _about_school(text, verb, group[GROUP_END])
    ):
        return None  # "will not reopen Friday", "activities resume Friday", "buildings open"
    ends = [text.find(mark, group[GROUP_END]) for mark in _OPENING_SENTENCE_MARKS]
    end = min([position for position in ends if position >= 0], default=len(text))
    asked = text.startswith("?", end)  # "Reopen Friday?"
    verb_kind = match.lastgroup  # "reopen", "open" or "reassess"
    if verb_kind == "reassess":
        if _reassessed_day(text, group):
            mode = _OPEN_HEDGED | _OPEN_FIRST
        else:
            mode = _OPEN_HEDGED | _OPEN_ONWARD | _OPEN_AFTER
            if _ENDS_HERE(text, group[GROUP_END]) is not None:
                mode |= _OPEN_LAST  # "will reassess Friday.": nothing says when, or for what
    else:
        mode = 0 if verb_kind == "open" else _OPEN_ONWARD
        if (
            asked
            or not _REOPEN_HEDGES.isdisjoint(before)
            or not _REOPEN_CONDITIONS.isdisjoint(words(text, group[GROUP_END], end))
        ):
            mode |= _OPEN_HEDGED  # "may reopen Friday", "reopening Friday if roads clear"
    if not _RETRACTIONS.isdisjoint(words(text, sentence, verb)):
        mode |= _OPEN_MARKED  # "Update: school will reopen tomorrow"
    return mode


def _reassessed_day(text: str, group: DateGroup) -> bool:
    """Whether the day a reassessment leads is what is reassessed, not when: a time for the
    decision follows it ("will reassess Friday tomorrow", "reassess tomorrow tonight", "...
    tomorrow at 5 am"), or its status does ("reassess tomorrow's status", "reassess Friday's
    closure"). (A part of the day is when: "will reassess tomorrow afternoon".)"""
    atoms = group[GROUP_ATOMS]
    first = atoms[0]
    if text.startswith("'s", first[ATOM_END]) or text[first[ATOM_START] : first[ATOM_END]].endswith(
        "'s"
    ):
        return True
    if len(atoms) > 1 and atoms[1][ATOM_KIND] == "relative" and first[ATOM_KIND] != "relative":
        return True  # "Friday tomorrow"
    if len(atoms) > 1 and atoms[1][ATOM_EVENING] and not first[ATOM_EVENING]:
        return True  # "tomorrow tonight"
    return _DECISION_TIME.match(text, group[GROUP_END]) is not None


# The end of a clause right after a day.
_ENDS_HERE = re.compile(r"\s*(?:[.,;:!?|)]|$)", re.ASCII).match
# A time for a decision, or a status's noun, after the day a reassessment leads.
_DECISION_TIME = re.compile(
    r"\s*(?:'s\b|(?:status|closure|closing|schedule|plans?)\b|(?:tonight|this\s+evening|later"
    r"|overnight|at\s+\d|by\s+\d|in\s+the\s+(?:morning|evening))\b)",
    re.ASCII,
)


def _opened_in_list(group: DateGroup, openings: tuple[_Opening, ...]) -> bool:
    """Whether an opening names a day of ``group`` as it names it (see _carried_elsewhere)."""
    named = {_day_key(atom) for atom in group[GROUP_ATOMS]}
    return any(
        _day_key(atom) in named
        for _position, _mode, opened in openings
        for own in opened
        for atom in own[GROUP_ATOMS]
    )


def _opening_effect(position: int, mode: int, status: _Status) -> int:
    """What an opening at ``position`` that reads as ``mode`` does to a status on its day (a
    denial, to a status of the kind it denies only)."""
    if status[_REVOKED] or (
        not mode & _DENIED_BITS.get(status[_KIND], 0)
        if mode & _DENIALS
        else status[_KIND] not in _OPENED_KINDS
    ):
        return 0
    if mode & _OPEN_HEDGED:
        return _DOUBTED
    if position > status[_POSITION]:
        return _REPLACED if mode & _OPEN_MARKED else _CORRECTED
    if status[_IS_SUPERSEDING] and not mode & _OPEN_MARKED:
        return 0  # "Open tomorrow. Update: closed tomorrow."
    return _CONTRADICTED  # ("Update: open today, Today: Closed": which is the update?)


def _opened_dates(
    groups: tuple[DateGroup, ...], calendar: Calendar, default: date | None
) -> set[date]:
    """The days of an opening; none when one of them cannot be told."""
    days: set[date] = set()
    for group in groups:
        resolved = calendar.resolve(group, default)
        if resolved.flags & _UNTOLD_OPENING:
            return set()
        days |= resolved.dates
    return days


_UNTOLD_OPENING = MISMATCH | INVALID | UNCLEAR | RECURRING


def _open_days(
    openings: tuple[_Opening, ...],
    calendar: Calendar,
    default: date | None,
    by_day: dict[date, list[_Claim]],
    notes: set[Note],
) -> None:
    """Take from ``by_day`` the closures and remote days the text's openings open.

    A status that loses a day to an opening with no word that marks it as an
    update, or to a hedged one, keeps its other days as a judgment call (see
    :data:`_Opening`).
    """
    effects = 0
    touched: set[int] = set()  # where the statuses that lost a day so stand
    for position, mode, groups in openings:
        days = _opened_dates(groups, calendar, default)
        if days and not mode & _OPEN_ONWARD and _plain_weekdays(groups):
            # "No school Monday through Wednesday, not Tuesday" seen on a Wednesday: the
            # Tuesday is the one of the closure's own week, not the one ahead.
            days = {
                day - _ONE_WEEK if day not in by_day and day - _ONE_WEEK in by_day else day
                for day in days
            }
        if days:
            for day in _opened_targets(days, mode, by_day):
                effects |= _take_opened(by_day, day, position, mode, touched)
    if not effects:
        return
    if touched:
        for day, claims in by_day.items():
            by_day[day] = [
                (claim[0], claim[1], min(claim[2], JUDGMENT))
                if claim[_CLAIM_STATUS][_POSITION] in touched
                else claim
                for claim in claims
            ]
    # A correction that leaves nothing standing says nothing for sure: "Closed Friday. Open
    # Friday." (and "Open tomorrow. Closed tomorrow." contradicts itself).
    emptied = bool(effects & _CORRECTED) and not by_day
    if effects & _REPLACED or (effects & _CORRECTED and not emptied):
        notes.add("superseded")
    if effects & _DOUBTED:
        notes.add("hedged")
    if effects & _CONTRADICTED or emptied:
        notes.add("conflict")


def _plain_weekdays(groups: tuple[DateGroup, ...]) -> bool:
    """Whether an opening's days are weekday names alone, with no "next" or date beside them."""
    return all(
        atom[ATOM_KIND] == "weekday" and atom[ATOM_MODIFIER] is None and atom[ATOM_DAY] is None
        for group in groups
        for atom in group[GROUP_ATOMS]
    )


def _opened_targets(days: set[date], mode: int, by_day: dict[date, list[_Claim]]) -> list[date]:
    """The days with claims an opening on ``days`` that reads as ``mode`` bears on."""
    if not mode & _OPEN_ONWARD:
        return [day for day in days if day in by_day]
    first = max(days) if mode & _OPEN_ENDS else min(days)
    after = bool(mode & _OPEN_AFTER) and not (
        mode & _OPEN_LAST and not any(day > first for day in by_day)
    )
    return [day for day in by_day if day > first or (day == first and not after)]


def _take_opened(
    by_day: dict[date, list[_Claim]], day: date, position: int, mode: int, touched: set[int]
) -> int:
    """Take from ``day``'s claims those an opening opens (see :func:`_opening_effect`).

    Return what it did to them; ``touched`` gains where each status that lost the
    day to a correction or a hedge stands.
    """
    effects = 0
    kept: list[_Claim] = []
    for claim in by_day[day]:
        status = claim[_CLAIM_STATUS]
        effect = _opening_effect(position, mode, status)
        if not effect:
            kept.append(claim)
            continue
        effects |= effect
        if effect & (_CORRECTED | _DOUBTED):
            touched.add(status[_POSITION])
    if kept:
        by_day[day] = kept
    else:
        del by_day[day]
    return effects


def _opened_single(
    analysis: _Analysis, status: _Status, result: ParsedStatus, calendar: Calendar
) -> ParsedStatus:
    """:func:`_single_result` with the days the text's openings open taken out (see
    :func:`_open_days`)."""
    by_day: dict[date, list[_Claim]] = {
        day: [(status, result.dates_stated, result.confidence)] for day in result.dates
    }
    notes: set[Note] = set(result.notes)
    default = _frame(analysis, calendar)[_FRAME_DEFAULT]
    _open_days(analysis[_OPENINGS], calendar, default, by_day, notes)
    if len(by_day) == len(result.dates):
        return result
    ordered = tuple(sorted(notes))
    if not by_day:
        return _unstated(analysis, notes, ordered)
    confidence = min(claims[0][_CLAIM_CONFIDENCE] for claims in by_day.values())
    if "conflict" in notes:
        confidence = min(confidence, WEAK)
    return _dated_result(
        status, tuple(sorted(by_day)), confidence, result.dates_stated,
        result.until_further_notice, analysis[_NARROWED], frozenset(notes), ordered,
        analysis[_WEATHER], analysis[_OFFICES_OPEN],
    )  # fmt: skip


# Changes --------------------------------------------------------------------------------
#
# A status the text says has changed into another ("2 hour delay is now a closing", "delay
# changed to a closure", "2 hr delay turned into an e-learning day") no longer holds: the one
# named after the change replaces it (see _supersedes and _day_status), and what it said of
# its own (a delay's length) goes with it. When nothing after the change reads as a status
# ("2 hour delay has been changed", "delay is now a full day"), or what comes after it is
# unclear ("2 hour delay. Update: closings") or only possible ("2 hour delay. Update:
# possible closure"), the old status no longer holds and the new one is unknown: neither
# stands. A new length or time ("2 hour delay - now 3 hours", "opening at 10 changed to 11")
# or a new day ("2 hour delay Wednesday moved to Thursday") is the status's, as a judgment
# call.

# Words after a status that say it changed. The strong ones say so whatever follows them;
# "now" and "update" only lead on to a new status or a new length.
_CHANGE_AFTER = re.compile(
    r"\b(?:(?P<strong>(?:(?:has|have|had)\s+(?:now\s+)?(?:been\s+)?|(?:is|are|was|were)\s+"
    r"(?:now\s+)?(?:being\s+)?|will\s+(?:now\s+)?be\s+)?"
    r"(?:chang(?:ed|ing)|switch(?:ed|ing)|convert(?:ed|ing)|upgrad(?:ed|ing)|mov(?:ed|ing)"
    r"|bec[ao]me|becomes|becoming|turn(?:ed|s|ing)\s+(?:in)?to|replaced\s+(?:with|by)"
    r"|(?:reduced|downgrad(?:ed|ing)|lowered)\s+to|scaled\s+(?:back|down)\s+to"
    r"|now\s+an?)\b)"
    r"|now\b|updated?\b)",
    re.ASCII,
)
# The words that may stand between a status and the words of its change: "2 hour delay for
# tomorrow has now been changed", "2 hour delay. UPDATE: ...", "Delay until 10 AM is now ...".
_CHANGE_LINKS = frozenset(
    {
        "is", "are", "was", "were", "has", "have", "had", "been", "being", "will", "be", "now",
        "the", "for", "on", "update", "updated", "also", "just", "officially",
        "today", "tomorrow", "tonight", "until", "till", "at", "of", "am", "pm", "a", "p", "m",
        "hour", "hours", "hr", "hrs", "minute", "minutes", "min", "mins",
    }
)  # fmt: skip
_CHANGE_LINK_NUMBER = re.compile(r"\d{1,2}(?::\d{2})?(?:[ap]m?)?", re.ASCII)
# What leads from the words of a change to a day it moves the status to: "changed to
# Wednesday", "moved to Jan. 22".
_TO_DAY = re.compile(r"\s*(?:[:-]\s*)?(?:(?:to|for|on|until|till)\s+)?", re.ASCII)
# A new length right after the words of a change: "now 3 hours", "changed to a 3 hour".
_NEW_LENGTH = re.compile(
    rf"\s*(?:[:-]\s*)?(?:to\s+)?(?:an?\s+)?(?P<dur>{DURATION})(?![a-z0-9])"
    r"(?!\s+(?:ago|earlier|before|after|later|past)\b)",
    re.ASCII,
)
# A new time right after the words of a change: "changed to 11:30", "now 12:30 PM".
_NEW_CLOCK = re.compile(
    rf"\s*(?:[:-]\s*)?(?:to\s+)?(?:at\s+)?(?P<clock>{CLOCK_STRICT})(?![a-z0-9:])", re.ASCII
)
# "Early" after an early dismissal's new length: "now 2 hours early".
_EARLY_AFTER = re.compile(r"\s*-?\s*early\b", re.ASCII)
# A change followed by "from" names the status before it as the new one: "2 hour delay
# (changed from a closure)".
_CHANGED_FROM = re.compile(r"\s*from\b", re.ASCII)


def _change_linked(text: str, start: int, end: int) -> bool:
    """Whether only filler words, dates (blanked out), times and marks stand between a status
    and the words of its change, so the change is the status's."""
    for token in words(text, start, end):
        if token not in _CHANGE_LINKS and _CHANGE_LINK_NUMBER.fullmatch(token) is None:
            return False
    return True


def _changed_days(
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
    status: int,
    after: int,
) -> bool:
    """Whether what came after a status's change speaks of the status's days: it names no
    day of its own, or one of the status's ("Closed today. Update: possible closure tomorrow"
    leaves today's closure).

    The days of the mention ``after`` are its own and those named between the
    dates of the mentions before it and the mention after it (a status left
    unclear or only possible may hold none of its own).
    """
    low = mentions[after - 1].end
    for index in range(after):
        for group in assigned.get(index, ()):
            low = max(low, group[GROUP_END])
    high = mentions[after + 1].start if after + 1 < len(mentions) else 1 << 30
    later = {
        _day_key(atom)
        for group in chain(
            assigned.get(after, ()), (g for g in groups if low <= g[GROUP_START] < high)
        )
        for atom in group[GROUP_ATOMS]
    }
    if not later:
        return True
    own = {_day_key(atom) for group in assigned.get(status, ()) for atom in group[GROUP_ATOMS]}
    return not own.isdisjoint(later)


def _unclear_change(mentions: list[Mention], start: int) -> int | None:
    """The mention from ``start`` on that changes the status before it into one left unclear
    ("Update: closings") or only possible ("Update: possible closure"), up to the next status
    that stands; ``None`` when there is none."""
    for index in range(start, len(mentions)):
        later = mentions[index]
        if later.revoked:
            continue
        if later.dropped is None and later.kind in _LABELED_KINDS:
            return None  # a status that stands: what comes after it is about it
        if later.superseding and (
            (later.kind == "ambiguous" and later.dropped is None)
            or (later.kind in _STATUS_KINDS and later.dropped == "hedged")
        ):
            return index
    return None


def _change_cues(text: str, start: int = 0) -> list[re.Match[str]]:
    """The words of a change from ``start`` on that can change a status on their own: the
    strong ones, "now" or "update" before a new length, and "now" before a new time (see
    :data:`_CHANGE_AFTER`). ("Updated 7:15 AM" says when the listing was written.)"""
    return [
        cue
        for cue in _CHANGE_AFTER.finditer(text, start)
        if cue.group("strong") is not None
        or _NEW_LENGTH.match(text, cue.end()) is not None
        or (cue.group() == "now" and _NEW_CLOCK.match(text, cue.end()) is not None)
    ]


def _changes(  # noqa: PLR0912, PLR0913, PLR0917 - the text's parts, its notes; per change
    text: str,
    masked: str,
    mentions: list[Mention],
    groups: tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
    notes: set[Note],
) -> None:
    """Drop each status a change replaces with nothing read, noting why, in place.

    ``masked`` is the text with its date groups blanked out (see
    :func:`_without_dates`). A status the words after it change ("is now",
    "changed to", "became", "turned into", "replaced with", "now", "update") is
    left to the status named after them, which replaces it on its days (see
    :func:`_day_status`). When the change leads to one that is unclear
    (``ambiguous``) or only possible (``hedged``), or to nothing that reads as
    a status, the status changed is dropped. A new length, time or day after
    the words of a change is the status's, as a judgment call.
    """
    cues = _change_cues(masked)
    if not cues and not any([mention.superseding for mention in mentions]):  # noqa: C419
        return  # (most texts with such a word: "(updated 5:43 AM)")
    starts = {group[GROUP_START]: group for group in groups}
    for index, mention in enumerate(mentions):
        # "Opening at 8 AM changed to 10 AM": a regular start time changed to a late one.
        opening = mention.kind == "ambiguous" and mention.opens_at is not None
        if (
            (mention.kind not in _STATUS_KINDS and not opening)
            or mention.dropped is not None
            or mention.revoked
        ):
            continue
        following = next(
            (
                later
                for later in range(index + 1, len(mentions))
                if mentions[later].start >= mention.end
            ),
            len(mentions),
        )
        unclear = _unclear_change(mentions, following)
        if unclear is not None and _changed_days(mentions, groups, assigned, index, unclear):
            # "2 hour delay. Update: closings", "2 hour delay. Update: possible closure".
            mention.dropped = "hedged" if mentions[unclear].dropped else "ambiguous"
            notes.update((mention.dropped, "superseded"))
            continue
        limit = mentions[following].start if following < len(mentions) else len(masked)
        cue = next((c for c in cues if mention.end <= c.start() and c.end() <= limit), None)
        if (
            cue is None
            or _CHANGED_FROM.match(masked, cue.end()) is not None  # "(changed from a closure)"
            or not _change_linked(masked, mention.end, cue.start())
        ):
            continue
        strong = cue.group("strong") is not None
        after = mentions[following] if following < len(mentions) else None
        if (
            after is not None
            and after.kind in _LABELED_KINDS
            and after.dropped is None
            and not after.revoked
        ):
            if strong and not after.superseded:
                after.superseding = True  # "2 hour delay has been changed. Schools closed."
            continue  # the status named after the change replaces this one
        if opening:
            if _later_opening(masked, mention, cue.end(), limit):
                notes.add("superseded")
            continue
        detail = _new_detail(masked, mention, cue.end(), limit)
        if detail is not None:
            if detail:
                mention.strength = min(mention.strength, JUDGMENT)
                notes.add("superseded")
            else:
                mention.dropped = "ambiguous"  # "early dismissal at 1 PM - now 5:00 PM"
                notes.update(("ambiguous", "superseded"))
            continue
        # (Only a strong change can lead to a day: "now" and "update" are cues only before a
        # length or a time, which the status has no place for: "Closed - now 2 hours".)
        lead = _TO_DAY.match(text, cue.end()) if strong else None
        if lead is not None and lead.end() in starts:
            # "Closure changed to Thursday": the same status, on the day after the change
            # ("2 hour delay Wednesday has been moved to Thursday" is no delay Wednesday).
            own = assigned.get(index)
            if own and own[0][GROUP_START] < cue.start():
                moved = [group for group in own if group[GROUP_START] >= cue.end()]
                assigned[index] = moved or [starts[lead.end()]]
                mention.strength = min(mention.strength, JUDGMENT)
                notes.add("superseded")
            continue
        mention.dropped = "ambiguous"  # "2 hour delay is now a full day"
        notes.update(("ambiguous", "superseded"))


def _unordered_changes(
    text: str, mentions: list[Mention], assigned: dict[int, list[DateGroup]], notes: set[Note]
) -> None:
    """Leave unclear two statuses of different kinds that a verb no change rule reads links
    with "to" or "into": "Closure cut to a 2 hour delay", "Closure tomorrow shifted to a 2
    hour delay", "Closed today, amended to a 2 hour delay", "2 hour delay escalated to a
    closure". The second has no day of its own and stands in the first's sentence; the text
    may say one replaced the other, or that the two are alternatives, so neither stands (note
    ``ambiguous``). A verb the change rules read orders them ("changed to", "switched to",
    "reduced to": see _changes), and the second is then the one that holds; two statuses that
    merge into the second are the second ("Closed - shifted to virtual learning" is a remote
    day: see _merge).
    """
    previous: Mention | None = None
    dated = False  # whether the previous status names a day of its own
    for index, mention in enumerate(mentions):
        if mention.kind not in _STATUS_KINDS or mention.dropped is not None or mention.revoked:
            continue
        if (
            previous is not None
            and previous.kind != mention.kind
            and not mention.superseding
            and not mention.superseded
            and not previous.superseded
            and not assigned.get(index)
            and _SENTENCE_MARK_SEARCH(text, previous.end, mention.start) is None
            and _CHANGED_TO_END(text[previous.end : mention.start]) is not None
            and _changed_to(text, previous.end, mention.start)
        ):
            if _merge({previous.kind, mention.kind}) != mention.kind:
                previous.dropped = mention.dropped = "ambiguous"
                notes.add("ambiguous")
            elif previous.superseding or (dated and previous.kind != "closed"):
                # "Update: closed, shifted to remote learning", "2 hour delay tomorrow modified
                # to remote learning": an update of the first, on its days. (A remote day joins
                # a closure on its days as it is: see _fold_undated.)
                mention.superseding = True
        previous = mention
        dated = bool(assigned.get(index))


# The end of the words between two statuses that make the second what the first was changed
# to: "cut to a", "amended to", "developing into a".
_CHANGED_TO_END = re.compile(
    r"(?:\b(?:to|into)|\b(?:[a-z]+ed|set|put)(?:\s+(?:over|aside|off|out|up|down|back|away))?"
    r"\s+(?:for|with|in\s+favou?r\s+of))\s+(?:(?:a|an|the)\s+)?$",
    re.ASCII,
).search
_SENTENCE_MARK_SEARCH = re.compile(r"[.;!?|]", re.ASCII).search


def _changed_to(text: str, low: int, start: int) -> bool:
    """Whether the "to" or "into" right before a status at ``start`` (after ``low``) says what
    something was changed to: not a verb's own "to" ("Learning Center to open at 10", "set to
    close at noon"), and not "prior to", "due to" or "next to" (see _NOT_CHANGED_TO)."""
    found = words(text, low, start)
    while found and found[-1] in _ARTICLES:
        found.pop()
    return (
        _TO_VERB(text, start) is None and (len(found) < 2 or found[-2] not in _NOT_CHANGED_TO)  # noqa: PLR2004 - "to", the word before
    )


_ARTICLES = frozenset({"a", "an", "the"})
# A status word that is a verb after "to": "to open at 10", "to close at noon", "to start late".
_TO_VERB = re.compile(
    r"(?:re)?open\b|close\b|dismiss\b|release\b|start\b|begin\b|delay\b|cancel\b|resume\b"
    r"|shut\b|end\b",
    re.ASCII,
).match
# Words before "to" that make it no change's: "prior to", "due to", "up to", "next to".
_NOT_CHANGED_TO = frozenset(
    {"prior", "due", "next", "according", "owing", "close", "closer", "adjacent", "related",
     "subject", "thanks", "compared", "similar", "addition", "regard", "respect", "listen",
     "attention", "welcome"}
)  # fmt: skip


def _later_opening(text: str, mention: Mention, start: int, limit: int) -> bool:
    """Read a regular opening time that a change makes late as a delayed opening, in place.

    "Opening at 8 AM changed to 10 AM": the school opens at 10, later than any
    regular school day starts (see snowlight.classify.mentions), as a judgment
    call. ``False``, and nothing changed, when no such time follows the words
    of the change at ``start``.
    """
    clock = _NEW_CLOCK.match(text, start)
    if clock is None:
        return False
    opens = late_opening(clock.group("clock"))
    if opens is None:
        return False
    mention.kind, mention.note, mention.opens_at = "delayed", None, opens
    mention.strength = min(mention.strength, JUDGMENT)
    mention.end = max(mention.end, min(clock.end(), limit))
    return True


def _new_detail(text: str, mention: Mention, start: int, limit: int) -> bool | None:
    """Read a new length or time for a timed status, that the words of a change end at
    ``start``, in place; ``None`` when there is none.

    "2 hour delay - now 3 hours", "Opening at 10 AM changed to 11 AM", "early
    dismissal at 1 PM - now 12:30", "early dismissal - now 2 hours early". The
    detail then ends the status's words, so no detail before it is read for it
    (see harvest_details). ``False`` when the new time is one no school day
    could start or end early at, or an early dismissal's new length is not said
    to be early.
    """
    length = _NEW_LENGTH.match(text, start) if mention.kind in _TIMED else None
    minutes = None if length is None else _duration_minutes(length.group("dur"))
    if length is not None and minutes is not None:
        if mention.kind == "delayed":
            mention.delay, mention.opens_at = minutes, None
            end = length.end()
        else:
            early = _EARLY_AFTER.match(text, length.end())
            if early is None:
                return False  # "early dismissal at 1 - now 2 hours": a length of what?
            mention.early, mention.dismissal = minutes, None
            end = early.end()
        mention.end = max(mention.end, min(end, limit))
        return True
    clock = _NEW_CLOCK.match(text, start) if mention.kind in _TIMED else None
    if clock is None:
        return None
    if mention.kind == "delayed":
        opens = school_opening(clock.group("clock"))
        if opens is None:
            return False
        mention.opens_at, mention.delay = opens, None
    else:
        dismissal = school_dismissal(clock.group("clock"))
        if dismissal is None:
            return False
        mention.dismissal, mention.early = dismissal, None
    mention.end = max(mention.end, min(clock.end(), limit))
    return True


def _day_key(atom: DateAtom) -> tuple[object, ...]:
    """What a date atom names, apart from where it is and whether it is an evening.

    Its kind, weekday, month, day, year, offset and modifier: the fields in that order.
    """
    return atom[2:9]


def _whole_days(
    text: str, found: dict[int, tuple[Bound | Split, list[DateGroup]]], groups: Sequence[DateGroup]
) -> None:
    """Drop the bounds of closures that, taken together, close whole days.

    Closings pages often split a day into parts: "Monday Morning: Closed......
    Monday Afternoon: Closed" closes Monday all day. So does a morning heading
    beside an evening one for the same day ("Monday Morning: Closed......
    Monday Evening: No activities"): the morning is the school day there, the
    evening what comes after it.
    """
    parts: dict[tuple[tuple[object, ...], ...], set[str]] = defaultdict(set)
    keys: dict[int, tuple[tuple[object, ...], ...]] = {}
    for index, (bound, own) in found.items():
        if isinstance(bound, Split) or bound.dismissal is not None or bound.opens_at is not None:
            continue
        named = [_day_key(atom) for group in own for atom in group[GROUP_ATOMS]]
        key = tuple(named) if len(named) < 2 else tuple(sorted(named, key=repr))  # noqa: PLR2004
        keys[index] = key
        parts[key].add(bound.part)
        if bound.part == "morning" and len(own) == 1 and _heading(text, own[0]):
            parts[key].add("heading")
    evenings = {
        (_day_key(group[GROUP_ATOMS][0]),)
        for group in groups
        if len(group[GROUP_ATOMS]) == 1
        and group[GROUP_ATOMS][0][ATOM_EVENING]
        and _heading(text, group)
    }
    for index, key in keys.items():
        held = parts[key]
        if {"morning", "afternoon"} <= held or (
            "heading" in held and "morning" in held and key in evenings
        ):
            del found[index]


def _afternoon_slot_days(
    text: str, mentions: list[Mention], assigned: dict[int, list[DateGroup]]
) -> None:
    """Take an afternoon slot heading out of a status that names its own days by name or date.

    "Thursday Afternoon: Closed Friday" closes Friday: written in Thursday's
    afternoon slot, after that day's school has begun, it names the day it is
    for, as "Thursday Evening: Closed Friday" does. A morning slot is the
    school day's own ("Tuesday Morning: Closed Wednesday" disagrees with
    itself). A word for today or tomorrow in the status ("Tuesday Afternoon:
    Closed today") could count from the slot's day or from the posting time,
    so there the heading stays, and the two must agree. So it does before a
    run with no first day ("Tuesday Afternoon: Closed through Friday"), which
    the heading starts.
    """
    for index, groups in assigned.items():
        if len(groups) < 2 or mentions[index].kind not in _STATUS_KINDS:  # noqa: PLR2004
            continue
        start = mentions[index].start
        heading = min(groups, key=_group_start)
        if heading[GROUP_END] >= start or not slot_heading(text, heading, "afternoon"):
            continue
        own = [group for group in groups if group is not heading]
        if all(group[GROUP_OPEN_START] is None for group in own) and all(
            atom[ATOM_KIND] in _NAMED_DAY_KINDS and not atom[ATOM_EVENING]
            for group in own
            for atom in group[GROUP_ATOMS]
        ):
            groups.remove(heading)


_NAMED_DAY_KINDS = frozenset({"weekday", "explicit"})


def _whole_day_slots(
    text: str,
    found: dict[int, tuple[Bound | Split, list[DateGroup]]],
    whole: list[list[DateGroup]],
) -> None:
    """Drop the bounds of afternoon slots whose day another closure closes whole.

    "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed": the morning
    slot closes Tuesday, and the afternoon slot's "Closed" is that closure
    again, not an early dismissal beside it. ``whole`` holds the date groups of
    each closure of whole days.
    """
    days = {
        _day_key(atom)
        for groups in whole
        for group in groups
        for atom in group[GROUP_ATOMS]
        if not atom[ATOM_EVENING]
    }
    for index, (bound, own) in list(found.items()):
        if (
            bound == _AFTERNOON
            and len(own) == 1
            and _day_key(own[0][GROUP_ATOMS][0]) in days
            and slot_heading(text, own[0], "afternoon")
        ):
            del found[index]


def _reopening(
    text: str, mentions: list[Mention], assigned: dict[int, list[DateGroup]], index: int
) -> int | None:
    """The late start right after a morning closure, naming no day of its own, if any.

    "Closed tomorrow morning, opening at 11:00" and "closed Wednesday AM; 2 hour
    delay" say when the school opens; "closed tomorrow morning; 2 hour delay
    Thursday" does not, and neither does the opening of one site ("This morning:
    Closed: Learning Center to open at 10"): that is the site's, which leaves the
    rest of the morning unclear (see :func:`_site_opening`).
    """
    for later in range(index + 1, len(mentions)):
        mention = mentions[later]
        if mention.kind not in _STATUS_KINDS or mention.dropped is not None:
            continue
        if mention.kind == "delayed" and not mention.revoked and not assigned.get(later):
            if _site_opening(text, mentions[index].end, mention.start):
                mention.dropped = "ambiguous"
                return None
            return later
        return None
    return None


# One site of a school or a district, as a noun before its own opening: "Learning Center to open
# at 10", "Main campus opens at 10" (not "buildings" or "schools": the district's).
_SITE_OPENING_NOUNS = frozenset(
    {"center", "centre", "campus", "building", "site", "annex", "branch", "wing", "office"}
)
# The words a site's opening can put between the site and its time: "to", "will", "is to".
_SITE_OPENING_VERBS = frozenset({"to", "will", "shall", "is", "would", "should"})
_SITE_OPENING_REACH = 40


def _site_opening(text: str, low: int, start: int) -> bool:
    """Whether the words right before an opening, after ``low``, name one site that it is
    the opening of: "Learning Center to open at 10", "Main campus will open at 10"."""
    tokens = words(text, max(low, start - _SITE_OPENING_REACH), start)
    while tokens and tokens[-1] in _SITE_OPENING_VERBS:
        tokens.pop()
    return bool(tokens) and tokens[-1] in _SITE_OPENING_NOUNS


def _part_statuses(  # noqa: PLR0913, PLR0917 - the closure, what bounds it, and the delay after it
    text: str,
    mention: Mention,
    bound: Bound | Split,
    own: Sequence[DateGroup],
    reopening: Mention | None,
    narrowed: AbstractSet[str],
    notes: set[Note],
) -> list[_Status]:
    """The statuses a closure limited to part of a day states, one per bound it holds."""
    pieces = bound.pieces if isinstance(bound, Split) else ((bound, tuple(own)),)
    found: list[_Status] = []
    for piece, held in pieces:
        groups: Sequence[DateGroup] = held
        delay = opens = dismissal = None
        strength = mention.strength
        kind: StatusKind
        if piece is None:
            kind = "closed"
        elif piece.part == "afternoon":
            kind, dismissal = "early_dismissal", piece.dismissal
            if dismissal is None:
                strength = min(strength, JUDGMENT)  # "closed this afternoon": no time given
        elif piece.opens_at is not None:
            kind, opens = "delayed", piece.opens_at  # "closed tomorrow until 10"
        elif piece.part == "morning" and reopening is not None:
            kind, delay, opens = "delayed", reopening.delay, reopening.opens_at
            strength = min(strength, reopening.strength)
        else:
            continue  # noted in _part_days
        if kind in narrowed:
            delay = opens = dismissal = None
        if kind == "early_dismissal" and groups and _is_run(groups):
            # "Closed from noon Wednesday through Friday": see _first_of_run.
            groups, strength = _first_of_run(text, groups), min(strength, JUDGMENT)
            notes.add("ambiguous")
            if not groups:
                continue
        status_groups = _restated(text, list(groups)) if len(groups) > 1 else tuple(groups)
        fields = (
            kind, mention.start, strength, delay, opens, dismissal, None, mention.superseding,
            mention.superseded, status_groups, False, False, None,
        )  # fmt: skip
        found.append(fields)
    return found


# The earliest a regular school day starts, in minutes after midnight: an opening time
# beside a delay that would put it earlier disagrees with the delay (see _closing_times).
_EARLIEST_REGULAR_START = 7 * 60


def _closing_times(mentions: list[Mention]) -> None:
    """Read a closing time as the time of an early dismissal that gives none of its own,
    and an opening time beside a delay as a delayed opening.

    A closing time late in the afternoon is unclear alone ("Closing at 3:00
    PM": when many schools let out anyway; see snowlight.classify.mentions),
    but beside an early dismissal with no time ("Early release. Closing at 3:00
    today.") it is that dismissal's time. So an opening time early in the
    morning is unclear alone ("Opening at 8:00": when many schools open anyway),
    but beside a delay with no time ("2 hour delay, opening at 9:00") it is the
    delayed opening's time, as any opening time there is, unless the delay's
    length puts the regular start before 7:00 a.m. ("2 hour delay, opening at
    7:30"): the time and the length then disagree, so the delay stands with its
    length alone, as a judgment call.
    """
    for mention in mentions:  # (a loop: this runs for every text with more than one status)
        if mention.kind == "ambiguous" and (
            mention.dismissal is not None or mention.opens_at is not None
        ):
            break
    else:
        return  # no closing or opening time left unclear (the common case)
    timeless = delayed = False
    for mention in mentions:
        kind = mention.kind
        if kind == "delayed" and mention.opens_at is None:
            delayed = True  # a delay word ("2 hour delay", "late start"), and no time of its own
        elif kind == "early_dismissal" and mention.dismissal is None and mention.early is None:
            timeless = True
    for mention in mentions:
        if mention.kind == "ambiguous":
            if timeless and mention.dismissal is not None:
                mention.kind = "early_dismissal"
                mention.note = None
            elif delayed and mention.opens_at is not None:
                mention.kind = "delayed"
                mention.note = None
                _check_opening(mentions, mention)


def _check_opening(mentions: list[Mention], opening: Mention) -> None:
    """Leave out an opening time beside a delay whose length it disagrees with, in place.

    "2 hour delay, opening at 7:30" would start school at 5:30 on a regular day:
    the time and the length do not agree, so the start is left untold, and the
    delay is a judgment call (see :func:`_closing_times`).
    """
    longest = max([mention.delay or 0 for mention in mentions if mention.kind == "delayed"])
    opens = opening.opens_at
    if opens is not None and opens.hour * 60 + opens.minute - longest < _EARLIEST_REGULAR_START:
        opening.opens_at = None
        for mention in mentions:
            if mention.kind == "delayed":
                mention.strength = min(mention.strength, JUDGMENT)


def _is_run(groups: Sequence[DateGroup]) -> bool:
    """Whether a status's date groups make a run of days: "today through Friday", "until 1/30"."""
    for group in groups:  # (a loop costs less than any(), per call)
        if (
            group[GROUP_OPEN_START] is not None
            or "range" in group[GROUP_LINKS]
            or "until" in group[GROUP_LINKS]
        ):
            return True
    return False


def _first_of_run(text: str, groups: Sequence[DateGroup]) -> list[DateGroup]:
    """The date groups of a closing at a time that runs over several days, for its first day.

    "Closing at 1:00 PM today through Friday" and "closed from noon Wednesday
    through Thursday" send students home early on the first day. After it the
    words fit a closing at that time each day as well as a closure from then
    on, so the days after the first state nothing anyone can act on. The run
    is kept, joined by the link ``first`` (see :data:`~snowlight.classify.dates.Link`),
    so its end still places its first day ("Saturday through Monday" posted on a
    Monday starts two days before); a run with no first day of its own ("closing
    at noon through Friday") starts where "through Friday" alone would. When the
    run is apart from the first day, nothing is kept.
    """
    ordered = sorted(groups, key=_group_start)
    first = ordered[0]
    if first[GROUP_OPEN_START] is not None:
        return [(*first[:4], "first")]  # "closing at noon through Friday"
    count = 1  # the first day, with the ways it is named again: "today (Tuesday) through Friday"
    while count < len(first[GROUP_ATOMS]) and first[GROUP_LINKS][count - 1] in _RESTATING_LINKS:
        count += 1
    if count < len(first[GROUP_ATOMS]):
        link = first[GROUP_LINKS][count - 1]
        if link in {"range", "until"}:  # the run starts on the first day
            links: tuple[Link, ...] = (
                *first[GROUP_LINKS][: count - 1], "first", *first[GROUP_LINKS][count:]
            )  # fmt: skip
            return [(*first[:3], links, first[4])]
        # Other days listed before the run ("noon Wednesday; Thursday through Friday"): the
        # run could be closed all day, so the first day stands alone.
        atoms = first[GROUP_ATOMS][:count]
        return [
            (
                atoms[0][ATOM_START],
                atoms[-1][ATOM_END],
                atoms,
                first[GROUP_LINKS][: count - 1],
                None,
            )
        ]
    if len(ordered) > 1 and ordered[1][GROUP_OPEN_START] is not None:
        # "Closed Wednesday 12 pm thru Thursday": the run goes on from the first day.
        return [join_groups(first, (*ordered[1][:4], None), "first")]
    if len(ordered) > 1 and _heading(text, first):
        # "Tuesday: Closing at noon today through Friday": the heading names the run's first
        # day again, and the two must agree ("Wednesday: ... Thursday through Friday" do not).
        atom = ordered[1][GROUP_ATOMS][0]
        return [join_groups(first, (atom[ATOM_START], atom[ATOM_END], (atom,), (), None), "appos")]
    # A run apart from the first day, with words between ("Closing at noon Wednesday, then
    # Thursday through Friday"): which days close early is unclear.
    return []


# "All day" before or after a day: "closing at noon Wednesday and all day Thursday".
_ALL_DAY_BEFORE = re.compile(
    r"(?:all[ -]day|the\s+(?:whole|entire)\s+day)(?:\s+on)?\s+\Z", re.ASCII
)
_ALL_DAY_AFTER = re.compile(r"\s+all[ -]day\b", re.ASCII)
# A closure word that opens a timed closing ("closing at noon"), which "all day" closes outright.
_CLOSURE_VERBS = ("clos", "shut")


def _several_days(groups: Sequence[DateGroup]) -> bool:
    return len(groups) > 1 or (len(groups) == 1 and len(groups[0][GROUP_ATOMS]) > 1)


def _all_day(
    text: str, mention: Mention, own: Sequence[DateGroup]
) -> tuple[list[DateGroup], list[DateGroup]] | None:
    """Split a timed closing's days into those closed early and those closed all day.

    "Closing at 11:30 Wednesday and all day Thursday" is an early dismissal
    Wednesday and a closure Thursday. ``None`` when no day, or every day, is
    said to be closed all day.
    """
    if not text.startswith(_CLOSURE_VERBS, mention.start):
        return None
    early: list[DateGroup] = []
    closed: list[DateGroup] = []
    for group in own:
        whole = False  # "all day tomorrow and Friday": both days
        for atom in group[GROUP_ATOMS]:
            single: DateGroup = (atom[ATOM_START], atom[ATOM_END], (atom,), (), None)
            whole = (
                whole
                or _ALL_DAY_BEFORE.search(text, max(0, atom[ATOM_START] - 24), atom[ATOM_START])
                is not None
                or _ALL_DAY_AFTER.match(text, atom[ATOM_END]) is not None
            )
            (closed if whole else early).append(single)
    if (
        not closed
        or not early
        or any(group[GROUP_OPEN_START] or "range" in group[GROUP_LINKS] for group in own)
    ):
        return None
    return early, closed


# Words between "closed for the rest of the day" and a day that add the day: "and tomorrow".
_REST_AND = frozenset({"and", "also", "plus"})


def _rest_of_today(text: str, mention: Mention, own: Sequence[DateGroup]) -> list[_Status] | None:
    """The statuses of "closed for the rest of the day", which is the posting day's.

    It names its day even when posted in the evening. A day after it ("closed
    for the rest of the day and tomorrow") is closed as well; one that restates
    the day ("for the rest of the day today") changes nothing. ``None`` when the
    day it names is left to the status as it stands.
    """
    day = date_atom(mention.end, mention.end, "relative")
    today: DateGroup = (mention.end, mention.end, (day,), (), None)
    status: _Status = (
        "early_dismissal", mention.start, mention.strength, None, None, mention.dismissal,
        mention.early, mention.superseding, mention.superseded, (today,), False, False, None,
    )  # fmt: skip
    if not own:
        return [status]
    between = words(text, mention.end, own[0][GROUP_START])
    if between and set(between) <= _REST_AND and text.startswith(("clos", "shut"), mention.start):
        closed: _Status = (
            "closed", mention.start, mention.strength, None, None, None, None,
            mention.superseding, mention.superseded, _restated(text, list(own)), False, False,
            None,
        )  # fmt: skip
        return [status, closed]
    return None


def _delayed_until_day(text: str, mention: Mention, groups: Sequence[DateGroup]) -> bool:
    """Whether a delay with no length or time runs until a day: "School delayed until Monday".

    Its start is put off to that day, so there is no school before it. A late
    start ("late start until Monday") or a delay with a length ("2 hour delay
    until Friday", "delay of 2 hours until Friday") is a delay on each of the
    days; so is one called off ("delay lifted until Friday").
    """
    return (
        mention.delay is None
        and mention.opens_at is None
        and not mention.revoked
        and len(groups) == 1
        and groups[0][GROUP_OPEN_START] == "until"
        and groups[0][GROUP_START] == mention.end + 1  # "until" right after the status's words
        and groups[0][GROUP_ATOMS][-1][ATOM_KIND] != "further_notice"
        and "delay" in text[mention.start : mention.end]
        # "Delayed until this afternoon": a late start today.
        and not _later_today(text, groups[0])
    )


def _later_today(text: str, group: DateGroup) -> bool:
    """Whether a date group names a later part of the posting day: "this afternoon"."""
    atoms = group[GROUP_ATOMS]
    return (
        len(atoms) == 1
        and atoms[0][ATOM_KIND] == "relative"
        and atoms[0][ATOM_OFFSET] == 0
        and _LATER_TODAY.search(text, group[GROUP_START], group[GROUP_END]) is not None
    )


_LATER_TODAY = re.compile(r"\b(?:afternoon|midday|noon|later)\b", re.ASCII)


def _parallel_no(text: str, mentions: list[Mention], notes: set[Note]) -> None:
    """Make "no school" unclear beside a status another "no" negates: "No school - no delay".

    With a second "no", the pair reads as two answers of no ("no school closing,
    no delay") as much as a closure and a delay denied; with no day named either
    way, the closure is unclear.
    """
    closures = [
        mention
        for mention in mentions
        if mention.kind == "closed"
        and mention.dropped is None
        and text.startswith("no ", mention.start)
    ]
    if closures and any(
        mention.dropped == "negated" and text.startswith("no ", mention.start - 3)
        for mention in mentions
        if mention.start >= 3  # noqa: PLR2004 - the length of "no "
    ):
        for mention in closures:
            mention.dropped = "ambiguous"
        notes.add("ambiguous")


# Kinds of day that a past report names in a form that points forward: "was closed Friday"
# posted on a Tuesday means the Friday before, which the calendar reads as the one after.
_FORWARD_DAYS = frozenset({"weekday", "week"})


def _past_reports(statuses: list[_Status], notes: set[Note]) -> list[_Status]:
    """Keep the statuses of a report of past ones that name their days plainly.

    "School was closed yesterday" and "we were closed today" name their days.
    "School was closed Friday" could be any Friday, which reads like "closed last
    Friday" (``unreadable_date``); "school was closed" names no day at all
    (``undated``). Only a text in which every status is marked as past ("was",
    "were") is a report: beside a status that stands, the past one is the one
    replaced ("Closed tomorrow (was a 2 hour delay)").
    """
    kept: list[_Status] = []
    for status in statuses:
        if not status[_GROUPS]:
            notes.add("undated")
        elif any(
            atom[ATOM_KIND] in _FORWARD_DAYS
            for group in status[_GROUPS]
            for atom in group[GROUP_ATOMS]
        ):
            notes.add("unreadable_date")
        else:
            kept.append(status)
    return kept


def _all_superseded(statuses: list[_Status]) -> bool:
    """Whether every status is marked as replaced (see :func:`_past_reports`)."""
    for status in statuses:  # noqa: SIM110 - (a loop costs less than a generator, per call)
        if not status[_IS_SUPERSEDED]:
            return False
    return True


def _without_dates(text: str, groups: tuple[DateGroup, ...], *, parts: bool = True) -> str:
    """``text`` with each date group blanked out, and the part of the day that ends its phrase
    with it ("Wednesday morning:"): the words left are what settling a status reads.

    Every place stays where it was: each blank is as long as what it covers. ``parts`` is
    false when the text holds no word for a part of the day (see _PART_RUNS).
    """
    pieces: list[str] = []
    last = 0  # where the text not yet taken starts (a blank may reach past the next group)
    for group in groups:
        start = group[GROUP_START]
        end = group[GROUP_END]
        if parts and text.startswith(_DAY_PART_STARTS, end):
            # (_DAY_PART_AFTER, read in place: the word is known by its first two letters,
            # and a mark or the end right after it ends the phrase; a space is left to it.)
            stop = end + _DAY_PART_LENGTHS[text[end + 1 : end + 3]]
            after = text[stop : stop + 1]
            if after in _DAY_PART_MARKS:  # (also "": the end of the text)
                end = stop
            elif after.isspace():
                part = _DAY_PART_AFTER.match(text, end)
                if part is not None:
                    end = part.end()
        start = max(start, last)
        if end > start:
            pieces += (text[last:start], " " * (end - start))
            last = end
    pieces.append(text[last:])
    return "".join(pieces)


def _doubts(text: str, mentions: list[Mention], assignment: _Assignment) -> tuple[_Status, ...]:
    """The doubts of an ambiguous text (see _Analysis.doubts): each bare "cancelled" that
    stands, read as the school cancelled (see :func:`_doubt`)."""
    assigned, hedged = assignment[_ASSIGNED_GROUPS], assignment[_ASSIGNED_HEDGED]
    return tuple(
        [
            _doubt(mention, assigned.get(index, ()))
            for index, mention in enumerate(mentions)
            if mention.revokes == "cancel"
            and mention.kind == "ambiguous"
            and mention.dropped is None
            and index not in hedged
            # "Closings and cancellations": a heading, not a statement.
            and not text.startswith("cancellation", mention.start)
        ]
    )


def _hedged_doubts(  # noqa: PLR0913, PLR0917 - the text's mentions, days and statuses
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    clauses: list[_Clause],
    groups: tuple[DateGroup, ...],
    statuses: list[_Status],
) -> tuple[_Status, ...]:
    """The days the text's statuses that are only possible name, as doubts that leave any
    status on them unsure (see :func:`_doubted`): "Closed Monday and Tuesday. Tuesday's
    closure may be lifted.", "Possible closure tomorrow. Closed today and tomorrow." (a day
    hedged on its own, "possible ... tomorrow", is taken from the status: see _hedged_out)."""
    assigned, hedged = assignment[_ASSIGNED_GROUPS], assignment[_ASSIGNED_HEDGED]
    doubts: list[_Status] = []
    starts = [clause.start for clause in clauses]
    for index, mention in enumerate(mentions):
        if (
            mention.kind not in _STATUS_KINDS
            # ("2 hour delay tomorrow; closing watch in effect": a closing watched for.)
            and not (
                mention.kind == "ambiguous"
                and mention.dropped == "hedged"
                and _watched(text, mention)
            )
        ) or mention.revoked:
            continue
        own: list[DateGroup] | tuple[DateGroup, ...] = assigned.get(index, ())
        if index in hedged:
            clause = clauses[bisect_right(starts, mention.start) - 1]
            own = tuple(
                group
                for group in groups
                if clause.start <= group[GROUP_START] < clause.end
                and _date_hedged(text, clause, group)
            )
        elif mention.dropped != "hedged":
            continue
        if own:
            doubt: _Status = (
                "closed", mention.start, HEDGED, None, None, None, None, False, False,
                tuple(own), True, True, None,
            )  # fmt: skip
            doubts.append(doubt)
        elif index not in hedged and _watched(text, mention):
            # "2 hour delay tomorrow; closure watch in effect", "Closure watch: 2 hour delay
            # tomorrow": a closure that may come, before the delay or after it.
            doubts += _replaced_maybe(mention, statuses, anywhere=True)
        elif index not in hedged and statuses[0][_POSITION] < mention.start:
            clause = clauses[bisect_right(starts, mention.start) - 1]
            tokens = words(text, clause.start, clause.end)
            if _says_possible(tokens) and not (
                # "Remote learning will be possible for some students" or "for students who
                # are quarantined": an option for some, not a status of the district's to come
                # (see _remote_option).
                mention.kind == "remote"
                and (not _SOME_STUDENTS.isdisjoint(tokens) or _offers(tokens))
            ):
                doubts += _replaced_maybe(mention, statuses)
    return tuple(doubts)


def _says_possible(tokens: list[str]) -> bool:
    """Whether a clause says something may come: a word of :data:`_POSSIBLE_WORDS` that is
    no condition's ("if possible", "when possible": "Remote work/class if possible")."""
    previous = ""
    for token in tokens:
        if token in _POSSIBLE_WORDS and previous not in _POSSIBLE_IF:
            return True
        previous = token
    return False


_POSSIBLE_IF = frozenset({"if", "when", "where", "whenever", "wherever", "as"})
# Words beside "possible" that offer a status to some students only, with those of _offers
# (see _hedged_doubts).
_SOME_STUDENTS = frozenset({"some", "those", "individual"})


# The words that make a status one that may come ("Possible closure", "A closure is a
# possibility", "Chance of a closure", "A closure may follow"), not one a rule, a rumor or a
# condition leaves open (see _replaced_maybe).
_POSSIBLE_WORDS = frozenset(
    {
        "possible", "possibly", "potential", "potentially", "likely", "probable", "probably",
        "maybe", "perhaps", "may", "might", "could", "possibility", "possibilities", "chance",
        "chances", "odds", "likelihood", "probability",
    }
)  # fmt: skip


# The kinds of status that can stand on one day together: a late start and an early dismissal.
_ALONGSIDE = frozenset({"delayed", "early_dismissal"})


def _replaced_maybe(
    possible: Mention, statuses: list[_Status], *, anywhere: bool = False
) -> list[_Status]:
    """The doubts that a status only possible and naming no day casts on the statuses before it
    of a kind it would take the place of (see :func:`_hedged_doubts`).

    "2 hour delay tomorrow. Possible closure.", "2 hour delay. A closure is a possibility.":
    the closure, if it comes, is for the delay's day, so the text says nothing sure of that
    day, as "2 hour delay, possibly developing into a closure" and "2 hour delay. Update:
    possible closure" say nothing sure of it (see _changes). A status of the same kind
    ("Closed today. Possible closure.") or one that can stand on the same day ("2 hour delay.
    Possible early dismissal.") is no other status for it, and leaves it as it is. A watch
    casts its doubt on the statuses after it too (``anywhere``: see :data:`_WATCH_NOUNS`).
    """
    kind = possible.kind
    found: list[_Status] = []
    for status in statuses:
        stated = status[_KIND]
        if (
            (anywhere or status[_POSITION] < possible.start)
            and stated != kind
            and not (stated in _ALONGSIDE and kind in _ALONGSIDE)
            and not status[_REVOKED]
        ):
            doubt: _Status = (
                stated, possible.start, HEDGED, None, None, None, None, False, False,
                status[_GROUPS], True, True, None,
            )  # fmt: skip
            found.append(doubt)
    return found


def _doubt(mention: Mention, groups: list[DateGroup] | tuple[()]) -> _Status:
    """A bare "cancelled" read as the school cancelled, with the days it names, if any."""
    return (
        "closed", mention.start, HEDGED, None, None, None, None, False, False, tuple(groups), True,
        False, None,
    )  # fmt: skip


def _may_harvest(mention: Mention, text: str, clocks: int) -> bool:
    """Whether something after a timed status can change its details (see harvest_details).

    A delay with a length and no opening time, or an early dismissal with a
    length and no time, keeps them whatever time follows: a later time only
    ever fills a detail the status lacks, or withdraws a time it has. Only
    another day's length can withdraw its length ("Delayed 2 hours Thursday and
    3 hours Friday"). Otherwise a time needs a clock (``clocks``), and a length
    after an early dismissal the word "early" ("dismissing today 2 hours early").
    """
    if mention.kind == "delayed":
        length, clock = mention.delay, mention.opens_at
    else:
        length, clock = mention.early, mention.dismissal
    if length is not None and clock is None:
        return length_after(text, mention.end)
    return bool(clocks) or (
        mention.kind == "early_dismissal" and text.find("early", mention.end) >= 0
    )


def _hints(
    text: str, mentions: list[Mention], assigned: dict[int, list[DateGroup]]
) -> tuple[DateGroup, ...]:
    """The date groups of side notes that name a school day: "Closed; offices open Monday".

    The new date of a moved event ("Closed; concert rescheduled to Feb. 13") is
    no day of the school's, so it is not one.
    """
    found: list[DateGroup] = []
    for index, mention in enumerate(mentions):
        if mention.kind not in _SIDE_KINDS or index not in assigned:
            continue
        for group in assigned[index]:
            start = group[GROUP_START]
            if text.endswith(_NEW_DATE_TAILS, 0, start) and _NEW_DATE_BEFORE.search(
                text, max(0, start - _NEW_DATE_REACH), start
            ):
                continue
            for atom in group[GROUP_ATOMS]:
                if atom[ATOM_KIND] in _DAY_ATOMS and not atom[ATOM_EVENING]:
                    found.append(group)
                    break
    return tuple(found)


_SIDE_KINDS = frozenset({"open", "note"})


def _orphan_days(
    text: str,
    clauses: list[_Clause],
    groups: tuple[DateGroup, ...],
    assigned: dict[int, list[DateGroup]],
    statuses: list[_Status],
) -> tuple[DateGroup, ...]:
    """The date groups that no mention takes, that name a school day and could be a status's.

    A clause of bare dates, a heading of days set apart from its status by
    other words ("Wednesday Afternoon: UPDATE; Closed", "Wednesday Afternoon:
    Day services, Skills Training classes cancelled") and a day in a clause
    joined to the one beside it by a comma or a dash ("Closed - Wednesday
    staff report", "Weather alert Thursday - Closed") name a day all the
    same: a status that names none is for the
    posting time's day only when that day is among them (see :func:`_frame`),
    as with a side note's day. A day in a sentence of its own, or after a
    semicolon or a bar, is that sentence's ("2 hour delay; students are off
    Friday"), and a day after words that make it the day school is back, a
    day to make up or when the listing was written ("back on Monday", "make-up
    day Friday", "posted Monday") is no rival either.
    """
    taken = [(group[GROUP_START], group[GROUP_END]) for own in assigned.values() for group in own]
    taken += [
        (group[GROUP_START], group[GROUP_END]) for status in statuses for group in status[_GROUPS]
    ]
    found: list[DateGroup] = []
    for group in groups:
        start, end = group[GROUP_START], group[GROUP_END]
        if any(low < end and start < high for low, high in taken):
            continue
        number = _home(clauses, start)
        clause = clauses[number]
        if (
            (clauses[1].strong if number == 0 else clause.strong)
            and _HEADING_AFTER(text, end) is None
            and not _pure_dates(
                text,
                clause,
                [held for held in groups if clause.start <= held[0] < clause.end],
                details=True,
            )
        ):
            continue
        if _ASIDE_DAY_BEFORE.search(text, max(0, start - _ASIDE_REACH), start) is not None:
            continue
        if any(
            atom[ATOM_KIND] in _DAY_ATOMS and not atom[ATOM_EVENING] for atom in group[GROUP_ATOMS]
        ):
            found.append(group)
    return tuple(found)


# What makes a day a heading, after it: a colon, after a part of the day ("Wednesday Afternoon:").
_HEADING_AFTER = re.compile(r" ?(?:(?:morning|afternoon|evening|night|am|pm) ?)?:", re.ASCII).match
# The words before a day that make it no day of a status (see _orphan_days), in its sentence.
_ASIDE_DAY_BEFORE = re.compile(
    r"\b(?:resum(?:e|es|ed|ing)|return(?:s|ed|ing)?|reopen(?:s|ed|ing)?|back\s+(?:in|on|to)"
    r"|make[\s-]?ups?|made[\s-]up|making\s+up|rescheduled|postponed|moved|pushed\s+back)\b"
    r"[^.;!?|]*$"
    # (When the listing was written, or a day past, right before the day: "posted Monday".)
    r"|\b(?:updated?|posted|revised|as\s+of|since|last|was|were)\s*:?\s*(?:on\s+)?$",
    re.ASCII,
)
_ASIDE_REACH = 48
# The words that give a moved event its new date: "rescheduled to", "postponed until".
_NEW_DATE_BEFORE = re.compile(
    r"\b(?:rescheduled|postponed|moved|pushed\s+back|changed)\s+(?:to|until|till|for)\s+(?:the\s+)?$",
    re.ASCII,
)
_NEW_DATE_REACH = 32
# The words right before such a date, in a normalized text (one space between words): a quick
# look before the pattern.
_NEW_DATE_TAILS = ("to ", "until ", "till ", "for ", "the ")


# Words between two days of one status that add the second rather than restate the first.
_ADDING_WORDS = frozenset(
    {"and", "also", "plus", "or", "nor", "well", "through", "thru", "to", "until", "till", "til"}
)


def _restated(text: str, groups: list[DateGroup] | tuple[()]) -> tuple[DateGroup, ...]:
    """Join a status's date groups that name one day in two ways.

    "Closed tomorrow for snow on Thursday" and "Thursday: closed tomorrow" name
    the day twice, so the two must agree (see :meth:`Calendar.resolve`). So do
    a day heading the status and a day in it: "Monday: Closed Monday" is one
    Monday, and "Sunday: Closed Monday" names two days for one closure. With
    "and" or "also" between them the second adds a day instead.
    """
    if len(groups) < 2:  # noqa: PLR2004 - one group or none: nothing to join
        return tuple(groups)
    ordered = sorted(groups, key=_group_start)
    joined = [ordered[0]]
    for group in ordered[1:]:
        last = joined[-1]
        if (
            group[GROUP_OPEN_START] is None
            and (
                restates(last[GROUP_ATOMS][-1], group[GROUP_ATOMS][0])
                or (
                    last[GROUP_ATOMS][-1][ATOM_KIND] in _NAMED_DAYS
                    and group[GROUP_ATOMS][0][ATOM_KIND] in _NAMED_DAYS
                    and _heading(text, last)
                )
            )
            and _ADDING_WORDS.isdisjoint(words(text, last[GROUP_END], group[ATOM_START]))
        ):
            joined[-1] = join_groups(last, group, "appos")
        else:
            joined.append(group)
    return tuple(joined)


# Atom kinds that name one day, which a heading and the status's own day can both be.
_NAMED_DAYS = frozenset({"explicit", "weekday", "relative"})
_HEADING_END = re.compile(r"(?:\s+(?:morning|am|afternoon|pm|evening|night))?\s*:", re.ASCII)
# Heading ends _HEADING_END matches, the most common (a colon, or a part of the day and a
# colon, after a space): a text that starts with one there needs no pattern.
_HEADING_ENDS = (
    ":",
    *(f" {part}{colon}" for part in ("morning", "afternoon", "evening", "am", "pm", "night")
      for colon in (":", " :")),
    " :",
)  # fmt: skip


def _heading(text: str, group: DateGroup) -> bool:
    """Whether the date group heads a status, before a colon: "Monday:", "Monday morning:"."""
    end = group[GROUP_END]
    return text.startswith(_HEADING_ENDS, end) or _HEADING_END.match(text, end) is not None


# Day headings over several statuses -----------------------------------------------------
#
# "Tuesday Morning: Closed-Flexible Instruction Day" and "Monday: Closed, remote learning": a
# day that heads an entry states its day for every status in it, not only the first. So the
# entry is remote learning on that day as the text says it, where "Closed tomorrow. NTI day."
# is remote learning tomorrow by inference (see _fold_undated).


def _entry_heading(text: str, group: DateGroup) -> bool:
    """Whether a school day heads an entry: "Monday:", "Monday Morning:" (see entry_start)."""
    return (
        _heading(text, group)
        and not any(atom[ATOM_EVENING] for atom in group[GROUP_ATOMS])
        and entry_start(text, group[GROUP_START])
    )


def _entry_end(text: str, groups: Sequence[DateGroup], heading: DateGroup) -> int:
    """Where the entry a heading starts ends: at the next date, or a bar between entries."""
    end = len(text)
    for group in groups:  # (a loop costs less than next() over a generator)
        if group[ATOM_START] > heading[ATOM_END]:
            end = group[GROUP_START]
            break
    bar = text.find("|", heading[GROUP_END], end)
    return end if bar < 0 else bar


def _joins_heading(
    mention: Mention, index: int, kind: StatusKind, assignment: _Assignment, parts: _Parts
) -> bool:
    """Whether an undated status under a heading adds to the status the heading dates."""
    joined = _KIND_OF.get(mention.kind)
    return (
        joined is not None
        and _merge({kind, joined}) is not None
        and mention.dropped is None
        and not mention.revoked
        and not mention.superseding
        and not mention.superseded
        and index not in parts[_PARTS_BOUNDS]
        and index not in parts[_PARTS_TAKEN]
        and not assignment[_ASSIGNED_GROUPS].get(index)
    )


def _share_headings(
    text: str,
    mentions: list[Mention],
    assignment: _Assignment,
    groups: Sequence[DateGroup],
    parts: _Parts,
) -> None:
    """Give a heading's day to the undated statuses in its entry that add to the one it dates.

    Only a status of a kind that merges with the dated one ("Closed - NTI day",
    "2 hour delay, early dismissal at 1") takes the day: any other is left to
    :func:`_fold_undated`, which reads it as the text allows.
    """
    assigned = assignment[_ASSIGNED_GROUPS]
    for index, chosen in list(assigned.items()):
        mention = mentions[index]
        kind = _KIND_OF.get(mention.kind)
        if (
            kind is None
            or mention.dropped is not None
            or mention.revoked
            or index in parts[_PARTS_BOUNDS]
            or index in assignment[_ASSIGNED_HEDGED]
        ):
            continue
        if index + 1 == len(mentions):
            continue  # nothing after it to take the day
        for group in chosen:
            if group[GROUP_END] >= mention.start:
                continue
            end = _entry_end(text, groups, group)
            if mentions[index + 1].start >= end or not _entry_heading(text, group):
                continue  # (most entries hold one mention: nothing else in it takes the day)
            for later in range(index + 1, len(mentions)):
                if mentions[later].start >= end:
                    break
                if _joins_heading(mentions[later], later, kind, assignment, parts):
                    assigned[later] = [group]


# Undated statuses beside dated ones -------------------------------------------------------
#
# "Closed Friday. No school.": the second status names no day, but it restates the first.
# The posting time says nothing about it once the text names a day: read from the posting
# time it would close today, which the text never says. So an undated status in a text that
# names a day joins the dated status nearest it of a kind it can restate, or is left out.

# Atom kinds that name a day a school-day status can hold ("tonight" names an evening).
_DAY_ATOMS = frozenset({"explicit", "weekday", "relative", "week"})


def _lent_days(statuses: list[_Status], days: tuple[DateGroup, ...]) -> list[_Status]:
    """The statuses, each that names no day taking the days of a status denied beside it, as
    a reading of the text: "No closure tomorrow; 2 hour delay instead", "Not closing
    tomorrow, but 2 hour delay", "Closed. No distance learning on Friday"."""
    return [
        status
        if status[_REVOKED] or _names_days(status)
        else _with_groups((*status[:2], min(status[_STRENGTH], JUDGMENT), *status[3:]), days)
        for status in statuses
    ]


def _today_only(groups: Sequence[DateGroup]) -> bool:
    """Whether date groups name the posting day only ("today"), the day a status that names
    none is for: "No school delays today; closed" closes that day either way."""
    return all(
        atom[ATOM_KIND] == "relative" and atom[ATOM_OFFSET] == 0
        for group in groups
        for atom in group[GROUP_ATOMS]
    )


def _names_days(status: _Status) -> bool:
    """Whether the status names a day, of any kind ("until further notice" names none)."""
    for group in status[_GROUPS]:
        for atom in group[GROUP_ATOMS]:
            if atom[ATOM_KIND] != "further_notice":
                return True
    return False


def _school_day_named(status: _Status) -> bool:
    """Whether the status names a school day that an undated status can join."""
    for group in status[_GROUPS]:
        for atom in group[GROUP_ATOMS]:
            if atom[ATOM_KIND] in _DAY_ATOMS and not atom[ATOM_EVENING]:
                return True
    return False


def _agree(first: _Status, second: _Status) -> bool:
    """Whether two statuses' details (length, opening, dismissal, early) never disagree.

    A detail one of them leaves out agrees with any. (Compared field by field: this
    runs for every pair of statuses a text's undated ones are weighed against.)
    """
    mine, theirs = first[_DELAY], second[_DELAY]
    if mine is not None and theirs is not None and mine != theirs:
        return False
    mine_time, their_time = first[_OPENS_AT], second[_OPENS_AT]
    if mine_time is not None and their_time is not None and mine_time != their_time:
        return False
    mine_time, their_time = first[_DISMISSAL], second[_DISMISSAL]
    if mine_time is not None and their_time is not None and mine_time != their_time:
        return False
    mine, theirs = first[_EARLY], second[_EARLY]
    return mine is None or theirs is None or mine == theirs


def _restates_status(undated: _Status, dated: _Status) -> bool:
    """Whether an undated status can be the dated one said again: "Closed Friday. No school."

    The kinds must be one ("closed", "no school") or a closure and remote learning
    ("Closed tomorrow. NTI day."), and the details must not disagree ("2 hour delay
    tomorrow. 90 minute delay." is two delays).
    """
    if dated[_IS_SUPERSEDED] or not _school_day_named(dated):
        return False
    if undated[_KIND] != dated[_KIND] and {undated[_KIND], dated[_KIND]} != {"closed", "remote"}:
        return False
    return _agree(undated, dated)


def _adds_to(undated: _Status, dated: _Status) -> bool:
    """Whether joining the undated status changes the dated one it restates.

    It does when it turns a closure into remote learning, gives a detail the
    dated one lacks ("2 hour delay tomorrow. Opening at 10:00.") or runs until
    further notice.
    """
    return (
        _merge({undated[_KIND], dated[_KIND]}) != dated[_KIND]
        or (undated[_DELAY] is not None and dated[_DELAY] is None)
        or (undated[_OPENS_AT] is not None and dated[_OPENS_AT] is None)
        or (undated[_DISMISSAL] is not None and dated[_DISMISSAL] is None)
        or (undated[_EARLY] is not None and dated[_EARLY] is None)
        or bool(undated[_GROUPS])
    )


def _joined(dated: _Status, undated: _Status) -> _Status:
    """The dated status with an undated one that restates it folded in."""
    kind = _merge({undated[_KIND], dated[_KIND]}) or dated[_KIND]
    # A kind taken from the undated status holds for the dated one's days by inference.
    strength = dated[_STRENGTH] if kind == dated[_KIND] else min(dated[_STRENGTH], INFERRED)
    return (
        kind,
        dated[_POSITION],
        strength,
        dated[_DELAY] if dated[_DELAY] is not None else undated[_DELAY],
        dated[_OPENS_AT] if dated[_OPENS_AT] is not None else undated[_OPENS_AT],
        dated[_DISMISSAL] if dated[_DISMISSAL] is not None else undated[_DISMISSAL],
        dated[_EARLY] if dated[_EARLY] is not None else undated[_EARLY],
        dated[_IS_SUPERSEDING],
        dated[_IS_SUPERSEDED],
        dated[_GROUPS] + undated[_GROUPS],
        False,
        False,
        dated[_LED],
    )


# A dated status found for an undated one: where it is, and whether it is the nearest. A plain
# tuple, read by the field numbers below (see _Status).
type _Found = tuple[
    int,  # _FOUND_POSITION
    _Status,  # _FOUND_STATUS
    bool,  # _FOUND_ADJACENT: no other dated status sits between the two
]
_FOUND_POSITION: Final = 0
_FOUND_STATUS: Final = 1
_FOUND_ADJACENT: Final = 2


def _nearest(
    folded: list[_Status | None], dated: list[bool], index: int, step: int, undated: _Status
) -> _Found | None:
    """The nearest dated status the undated one at ``index`` can restate, one way along."""
    adjacent = True
    position = index + step
    while 0 <= position < len(folded):
        other = folded[position]
        if other is not None and dated[position]:
            if not other[_REVOKED] and _restates_status(undated, other):
                return (position, other, adjacent)
            adjacent = False
        position += step
    return None


def _nearest_any(folded: list[_Status | None], dated: list[bool], index: int) -> _Status | None:
    """The nearest dated status that names a school day, before ``index`` first."""
    for positions in (range(index - 1, -1, -1), range(index + 1, len(folded))):
        for position in positions:
            other = folded[position]
            if other is not None and dated[position] and _school_day_named(other):
                return other
    return None


def _fold_undated(statuses: list[_Status]) -> tuple[list[_Status], bool]:
    """Fold each undated status into the dated ones beside it; return whether one was left out.

    A text with no dated status, or no undated one, is returned as it is. An
    update or a replaced status ("2 hour delay tomorrow. Update: now closed.",
    "Closed tomorrow (was a 2 hour delay)") takes the days of the nearest dated
    status, before it first, and the day then weighs the two as usual. Any other
    undated status is dropped as a restatement when a dated status it can
    restate, nearest it before or after, already says all it says ("Closed
    Friday. No school."); joins that status when it is the only one and nothing
    dated sits between them ("Closed tomorrow. NTI day." is remote learning
    tomorrow); and otherwise floats: it states no day ("Closed. 2 hour delay
    tomorrow."), though it can make a named day uncertain (see :func:`_float`).

    A status the text calls off claims no day, so it is never folded, but a
    dated one still dates the status right after it, which replaces it
    ("Tomorrow's delay cancelled. Closed." closes tomorrow), and the update
    after it ("2 hour delay tomorrow cancelled. Update: now closed."). One that
    names no day calls off the nearest status of its kind before it, on that
    status's days (see :func:`_called_off_days`): "Closed tomorrow. Update:
    closure cancelled." states and calls off tomorrow's closure.
    """
    dated = [_names_days(status) for status in statuses]
    if not any(dated):
        return statuses, False
    revoked = [status[_REVOKED] for status in statuses]
    if True in revoked:
        statuses = _called_off_days(statuses, dated)  # (which keeps each status's _REVOKED)
    if all([named or gone for named, gone in zip(dated, revoked, strict=True)]):  # noqa: C419
        return statuses, False
    folded: list[_Status | None] = list(statuses)
    left_out = False
    for index, status in enumerate(statuses):
        if dated[index] or status[_REVOKED]:
            continue
        folded[index] = None
        replaced = statuses[index - 1] if index > 0 else None
        if replaced is not None and replaced[_REVOKED] and dated[index - 1]:
            # "Tomorrow's delay cancelled. Closed.": the replacement takes the days, as a
            # reading of the text rather than a statement of it.
            folded[index] = (
                *status[:2], min(status[_STRENGTH], INFERRED), *status[3:9],
                replaced[_GROUPS] + status[_GROUPS], *status[10:],
            )  # fmt: skip
            dated[index] = True
            continue
        if status[_IS_SUPERSEDING] or status[_IS_SUPERSEDED]:
            days = _nearest_any(folded, dated, index)
            if days is None:
                left_out = True
            else:
                folded[index] = _with_groups(status, days[_GROUPS] + status[_GROUPS])
                dated[index] = True
            continue
        candidates = [
            found
            for found in (
                _nearest(folded, dated, index, -1, status),
                _nearest(folded, dated, index, 1, status),
            )
            if found is not None
        ]
        if not all([_adds_to(status, found[_FOUND_STATUS]) for found in candidates]):  # noqa: C419
            continue  # said already: a restatement
        if len(candidates) == 1 and candidates[0][_FOUND_ADJACENT]:
            found = candidates[0]
            folded[found[_FOUND_POSITION]] = _joined(found[_FOUND_STATUS], status)
            continue
        folded[index] = (*status[:10], True, *status[11:])  # (floating)
    return [status for status in folded if status is not None], left_out


def _called_off_days(statuses: list[_Status], dated: list[bool]) -> list[_Status]:
    """The statuses, each called off with no day of its own taking the days of the nearest
    status of its kind before it that names a day and is not called off (``dated`` is updated
    to match).

    A later sentence that calls off a status of a kind with no day ("Closed tomorrow. Update:
    closure cancelled.", "2 hour delay tomorrow. Delay lifted.") is about the status of that
    kind it follows, on its days: the day then holds the status and its calling off, which
    contradict each other (see :func:`_contradicted`), as "Closed tomorrow. Tomorrow's closure
    cancelled." does. One with no such status before it is left as it is ("Closed tomorrow.
    Delay cancelled.": no delay is stated).
    """
    out = statuses
    for index, status in enumerate(statuses):
        if not status[_REVOKED] or dated[index]:
            continue
        for position in range(index - 1, -1, -1):
            other = statuses[position]
            if other[_KIND] == status[_KIND] and not other[_REVOKED] and dated[position]:
                if out is statuses:
                    out = list(statuses)
                out[index] = _with_groups(status, other[_GROUPS])
                dated[index] = True
                break
    return out


def _two_weekdays(groups: tuple[DateGroup, ...]) -> bool:
    """Whether the date groups name two different weekdays with no day number, or more.

    With fewer, no weekday names can be out of order (see
    :func:`~snowlight.classify.dates.weekdays_out_of_order`), whichever statuses hold them:
    a day named again ("Tuesday Morning: Closed | Tuesday Afternoon: Closed") is the same day.
    """
    seen: int | None = None
    for group in groups:
        for atom in group[2]:  # (a group's atoms; an atom's kind, weekday and day by index)
            weekday = atom[3]
            if atom[2] == "weekday" and atom[5] is None and weekday is not None:
                if seen is None:
                    seen = weekday
                elif weekday != seen:
                    return True
    return False


_NO_HEADINGS: tuple[DateGroup, ...] = ()


def _weekday_headings(text: str, groups: tuple[DateGroup, ...]) -> tuple[DateGroup, ...]:
    """The date groups that head an entry with weekday names alone: "Thursday:", "Thursday
    Evening:", "Monday-Tuesday:" at the start of the text or after a mark.

    A closings page lists a day's slots in date order whatever each says, a status or not
    ("Wednesday: Closed...... Thursday: No First Shift", "Wednesday Morning: Closed |
    Thursday Morning: Open"). So a heading orders the days around it as a status's day does.
    """
    found: list[DateGroup] | None = None
    for group in groups:
        end = group[GROUP_END]
        if (
            (text.startswith(_HEADING_ENDS, end) or _HEADING_END.match(text, end) is not None)
            and _weekdays_alone(group, None)  # (see _heading)
            and entry_start(text, group[GROUP_START])
        ):
            if found is None:
                found = []
            found.append(group)
    return _NO_HEADINGS if found is None else tuple(found)


# The modifiers of a weekday name whose week the posting time alone chooses: none, or "this"
# ("this Tuesday" seen on a Thursday is as unclear as "Tuesday"). "Next" and "coming" look
# ahead.
_UNPLACED_MODIFIERS = (None, "this")


def _weekdays_alone(group: DateGroup, modifiers: tuple[str | None, ...] | None) -> bool:
    """Whether every day in the group is a weekday name with no day number.

    With ``modifiers``, each name's modifier must also be one of them.
    """
    for atom in group[GROUP_ATOMS]:
        if (
            atom[ATOM_KIND] != "weekday"
            or atom[ATOM_DAY] is not None
            or (modifiers is not None and atom[ATOM_MODIFIER] not in modifiers)
        ):
            return False
    return True


def _with_headings(found: list[DateGroup], headings: tuple[DateGroup, ...]) -> list[DateGroup]:
    """The statuses' date groups and the day headings, in text order, each once."""
    if not headings:
        return found
    starts = {group[GROUP_START] for group in found}
    return sorted(
        [*found, *[group for group in headings if group[GROUP_START] not in starts]],
        key=_group_start,
    )


def _heading_anchor(
    anchor: tuple[int, int, str | None] | None,
    statuses: list[_Status],
    headings: tuple[DateGroup, ...],
) -> tuple[int, int, str | None] | None:
    """The last weekday name of the text's days, with its day headings among them.

    A heading counts when it comes after a status's weekday name for another day:
    then the days before it are not after its day (see :func:`_status_days`). One
    that heads the only status ("Thursday: Opening at 10"), or that only names its
    status's day again ("Tuesday Morning: Closed | Tuesday Afternoon: Closed"),
    orders nothing.
    """
    last = _last_weekday(None, headings)
    if last is None or (anchor is not None and last[0] <= anchor[0]):
        return anchor
    for status in statuses:
        if status[_REVOKED]:
            continue
        for group in status[_GROUPS]:
            if group[GROUP_END] <= last[0] and any(
                atom[ATOM_KIND] == "weekday" and atom[ATOM_WEEKDAY] != last[1]
                for atom in group[GROUP_ATOMS]
            ):
                return last
    return anchor


def _weekday_lead(
    statuses: list[_Status], headings: tuple[DateGroup, ...]
) -> tuple[DateGroup, ...] | None:
    """The date groups of a text whose every day is a weekday name alone (see _LEAD).

    That is every day the statuses that stand name, and every day heading. ``None``
    when any is a date, a relative day, a week, "next" or "coming" a weekday, or a
    weekday with a day number: those place the days themselves. ``None`` too when
    the statuses name only evenings ("Sunday Evening: Closed"): no school day to place.
    """
    found: list[DateGroup] = []
    school_day = False  # whether a status names a day, not only an evening
    for status in statuses:
        if status[_REVOKED] or status[_FLOATING]:
            continue  # (a floating status takes no day of its own: see _float)
        groups = status[_GROUPS]
        if not groups:
            return None  # a status that names no day is for a day near the posting time
        for group in groups:
            # (Each day a weekday name alone, of a week the posting time chooses: see
            # _weekdays_alone, written out here, as most texts' first day is no weekday.)
            for atom in group[GROUP_ATOMS]:
                if (
                    atom[ATOM_KIND] != "weekday"
                    or atom[ATOM_DAY] is not None
                    or atom[ATOM_MODIFIER] not in _UNPLACED_MODIFIERS
                ):
                    return None
                if not atom[ATOM_EVENING]:
                    school_day = True
            found.append(group)
    if not school_day:
        return None
    if headings:
        starts = {group[GROUP_START] for group in found}
        for heading in headings:
            if heading[GROUP_START] in starts:
                continue
            if not _weekdays_alone(heading, _UNPLACED_MODIFIERS):
                return None
            found.append(heading)
        found.sort(key=_group_start)
    return tuple(found)


def _status_groups(mentions: list[Mention], assignment: _Assignment) -> list[DateGroup]:
    """The date groups of the statuses that stand, in text order."""
    assigned, hedged = assignment
    found = [
        group
        for index, mention in enumerate(mentions)
        if mention.kind in _STATUS_KINDS
        and mention.dropped is None
        and not mention.revoked  # called off: it states no day for the school
        and index not in hedged
        for group in assigned.get(index, ())
    ]
    return sorted(found, key=_group_start)


_group_start = itemgetter(0)  # (a date group's first field: its start, as a sort key)


def _widen(
    window: tuple[int, int] | None, kind: StatusKind, groups: tuple[DateGroup, ...]
) -> tuple[int, int] | None:
    """The undated cut-offs, widened for a status that names no day (see :data:`_UNDATED`)."""
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            if atom[ATOM_KIND] != "further_notice":
                return window  # the status names its days
    today_until, tomorrow_from = _UNDATED[kind]
    if window is None:
        return today_until, tomorrow_from
    return min(window[0], today_until), max(window[1], tomorrow_from)


def _last_weekday(
    anchor: tuple[int, int, str | None] | None, groups: tuple[DateGroup, ...]
) -> tuple[int, int, str | None] | None:
    """The position, weekday and modifier of the last weekday name so far."""
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            weekday = atom[ATOM_WEEKDAY]
            if atom[ATOM_KIND] == "weekday" and weekday is not None:
                start = atom[ATOM_START]
                if (
                    anchor is None
                    or start > anchor[0]
                    or (start == anchor[0] and weekday > anchor[1])
                ):  # (later in the text, or a later weekday at the same place)
                    anchor = (start, weekday, atom[ATOM_MODIFIER])
    return anchor


def _detail_end(text: str, mentions: list[Mention], index: int) -> int:
    """Where details for a mention can be: up to the next mention or the end of the sentence."""
    end = len(text)
    for later in mentions[index + 1 :]:
        if later.kind in _STATUS_KINDS or later.kind == "ambiguous":
            end = later.start
            break
    sentence = _SENTENCE_END.search(text, mentions[index].end, end)
    return end if sentence is None else sentence.start()


_FAST_PATH = True
# The mention rules but those whose every match holds a clock time (see mentions.CLOCK_RULES).
_CLOCKLESS_RULES = RULE_BITS & ~CLOCK_RULES
# The mention rules for words that can call a status off ("cancelled", "lifted").
_REVOKING_RULES = rule_mask("cancelled") | rule_mask("lifted")
_WEATHER_BITS = WEATHER_START | CAUSE_START
# The bits of a text whose words can start a weather term or a cause (see _weather_fields).
_WEATHER_GATE = _WEATHER_BITS << _WEATHER_SHIFT
_WEATHER_OR_POWER = _WEATHER_GATE | _POWER
_NO_WEATHER: tuple[tuple[str, ...], bool, Reason | None, tuple[Reason, ...], tuple[str, ...]] = (
    (),
    False,
    None,
    (),
    (),
)
# The statuses that can carry a time or a length found after them (see harvest_details).
_TIMED = frozenset({"delayed", "early_dismissal"})
# The mentions a day with a time or a length beside it can belong to (see _assign_dates).
_TIMED_OR_SIDE = _TIMED | {"open", "note"}
_UNTIMED = frozenset({"closed", "remote"})  # (the status kinds with no time to read)
# Words outside a lone status that could change how it is settled.
_QUALIFYING_WORDS = (
    NEGATIONS | HEDGES | HEDGES_AFTER | SUPERSEDING | SUPERSEDED | frozenset(SUPERSEDING_WITH)
    | _ANSWERS_NO | MAKE_UP_WORDS | _CONDITION_WORDS | _HEDGE_CLAUSE_TRIGGERS
    | {"instead", "rather"} | _POSSIBILITIES | _NOTICE_NOUNS
)  # fmt: skip
_SCHOOL_WORDS = frozenset(word for word, scope in SCOPES.items() if scope == "school")


_NO_ASSIGNMENT: _Assignment = ({}, frozenset())
_NO_REVOKED: dict[int, int] = {}  # (shared, and never changed: no status called off)
# The notes of a text that has none, shared: most texts have none, and an analysis is kept
# for each text parsed, so a set of its own for each would only add to what is kept.
_NO_NOTES: frozenset[Note] = frozenset()


def _lone_status(  # noqa: PLR0911, PLR0913, PLR0917 - one return per reason a status isn't alone
    text: str,
    mentions: list[Mention],
    bits: int,
    noted: list[tuple[int, str]],
    rare: int,
    counted: bool,
) -> bool | None:
    """Whether ``text``, whose one mention ``mentions`` holds, is one status with nothing
    that qualifies it.

    Then settling leaves the status as it is: no word outside it negates,
    hedges or replaces it, and no noun moves it away from the school (a school
    noun with no modifier resolves to the school, as no noun does). ``None``
    when that turns on its clause: the only words that could qualify it are
    ones that act within the status's own clause (see :func:`_quiet_clause`).
    """
    mention = mentions[0]  # (the one mention: see _analyse_normalized)
    if mention.kind not in _STATUS_KINDS or mention.dropped:
        return False  # a status negated by its own words ("no school closures") is settled
    if "?" in text:
        return False  # a question hedges the clause before it
    if (
        rare & _REPORT_RARE
        and text.startswith(_REPORT_LEAD, mention.end)
        and _report_notice(text, mention)
    ) or (mention.kind == "remote" and rare & _OPTION_RARE and _OPTION_HINT(text) is not None):
        # "Closure report by 5:30 a.m.": maybe a notice (see _open_after); "Remote learning
        # for students unable to travel": an option (see _remote_option).
        return False
    end = mention.end
    # (Quick looks with no call first: a colon or a dash in the two characters after the
    # status, as _FIELD_MARKS and _DASHED_MARKS start there, or more.)
    if (
        (bits & _COLON and ":" in text[end : end + 2])
        or (bits & (_NEGATION | _ANSWER) and "-" in text[end : end + 2])
    ) and _ANSWERED_NO.match(text, end):
        return False  # a field answered with a blank or a no: "Delay: --", "Closed - not"
    if bits & _ANSWER and (
        (text[-2:] in _FORM_ENDS and _ANSWERED_FORM(text, end) is not None)
        or (
            rare & _ZERO_RARE
            and text[mention.start - 2 : mention.start - 1] in _ZERO_CLOCK_MARKS
            and text.endswith(_ZERO_CLOCKS, 0, mention.start)
        )
        or (
            rare & _EITHER_RARE
            and _either_hint(text)
            and _ANSWERED_EITHER.match(text, end) is not None
        )
    ):
        # "Closed=false", "00:00 delay" (a length of nothing; _dropped wants the time whole), or
        # a field's answer left open: "Closed: yes/no".
        return False
    if rare & _COUNTED_RARE and bits & _DIGITS and _COUNT_SCHOOLS(text) is not None:
        return False  # "4 schools closed": some of the schools
    if not bits & (_QUALIFYING | _OTHER_SCOPE | _MODIFIER) and not counted:
        return True  # no word anywhere in the text could qualify the status
    found = _noted_words(noted, 0, len(text), mention.start, mention.end)
    outside = (
        frozenset(words(text, 0, mention.start)) | frozenset(words(text, mention.end))
        if found is None
        else frozenset(found)
    )
    nouns = outside & _SCOPE_WORDS
    if bits & _OTHER_SCOPE and "/" in text and nouns <= _SCHOOL_WORDS:
        # "Closed for middle/high school": the nouns joined by a slash.
        nouns = nouns.union(*[token.split("/") for token in outside if "/" in token]) & _SCOPE_WORDS
    if nouns and not (
        nouns <= _SCHOOL_WORDS
        and outside.isdisjoint(MODIFIERS)
        and outside.isdisjoint(_SOME_OF)
        and outside.isdisjoint(_COUNTS)
    ):
        return False
    if (
        bits & _OTHER_SCOPE
        and text.startswith(_BAND_LEADS, mention.end)
        and "-" in text
        and _GRADES_AFTER(text, mention.end) is not None
    ):
        return False  # "Closed for K-5": a band of grades, which no word of the scopes is
    if outside.isdisjoint(_QUALIFYING_WORDS):
        return True
    if not outside.isdisjoint(_TEXT_QUALIFIERS):
        return False
    return None


# Words that qualify a status from anywhere: a condition carries over clauses ("If roads are
# icy, closed") and reaches back over them ("Closed tomorrow, if the storm hits"), a hedge
# does ("Closed Friday (tentative)"), so do plans changed ("Closed tomorrow. Plans have
# changed."), and a field's answer can follow the status past a dash ("Closed - No").
_TEXT_QUALIFIERS = _CONDITION_WORDS | _HEDGE_CLAUSE_TRIGGERS | _ANSWERS_NO


def _quiet_clause(
    text: str, clause: _Clause, mention: Mention, noted: list[tuple[int, str]]
) -> bool:
    """Whether the status's own clause holds no word that could qualify it.

    Negations, hedges, words of an update or of a past status, and words of a
    day made up only act on a status in their clause (see :func:`_qualify`).
    ``noted`` are the stretches that hold such words (see :func:`_noted_words`).
    """
    around = _noted_words(noted, clause.start, clause.end, mention.start, mention.end)
    if around is None:
        around = words(text, clause.start, mention.start) + words(text, mention.end, clause.end)
    return _QUALIFYING_WORDS.isdisjoint(around)


def _dates_beside(clauses: list[_Clause], mention: Mention, groups: tuple[DateGroup, ...]) -> bool:
    """Whether every date is in the lone status's own clause, so it is assigned as there.

    Other clauses may hold words ("- winter storm") but no dates.
    """
    if len(clauses) == 1:
        return True
    clause = clauses[_home(clauses, mention.start)]
    low, high = clause.start, clause.end
    for group in groups:  # noqa: SIM110 - (a loop costs less than a generator, per call)
        if group[0] < low or group[1] > high:  # (its start and end)
            return False
    return True


_KIND_OF: dict[str, StatusKind] = {kind: kind for kind in _UNDATED}


class _CacheInfo(NamedTuple):
    """How many analyses a :class:`_TextCache` keeps, and how many it may."""

    currsize: int
    maxsize: int


# Texts a cache remembers having seen once, at most (see _TextCache); a set of strings, which
# the garbage collector never walks.
_MOST_SEEN = 1 << 17


class _TextCache:
    """Analyses by text, each kept from the second time its text comes.

    Most listings of a storm are worded their own way and come once: keeping
    each one's analysis would win nothing, and would leave the heap full of the
    small objects an analysis holds, which the garbage collector walks over and
    over. So the first time a text comes it is only remembered (see
    :data:`_MOST_SEEN`), and its analysis is kept from the second time on: a
    listing polled again, or a phrase many schools use, is analysed twice and
    then found. A text that stands for many (a key with the names or the day
    numbers of a text replaced: see :func:`_raw_analysis`) is kept at once.
    Analyses depend on the text alone, so what is kept changes no result. At
    most ``maxsize`` analyses are kept; the cache starts over when it is full.
    """

    __slots__ = ("_analyse", "_kept", "_maxsize", "_prepared", "_seen", "get")

    def __init__(
        self,
        analyse: Callable[[str], _Analysis],
        maxsize: int,
        prepared: Callable[[str, _Prepared], _Analysis] | None = None,
    ) -> None:
        self._analyse = analyse
        self._prepared = prepared or (lambda text, _prepared: analyse(text))
        self._kept: dict[str, _Analysis] = {}
        self._seen: set[str] = set()
        self._maxsize = maxsize
        self.get = self._kept.get
        """The analysis kept for a text, or ``None``."""

    def __call__(self, text: str) -> _Analysis:
        """The analysis of ``text``: the one kept, or a new one."""
        found = self.get(text)
        return self.fresh(text) if found is None else found

    def fresh(
        self,
        text: str,
        *,
        keep: bool = False,
        prepared: tuple[str, _Prepared] | None = None,
    ) -> _Analysis:
        """A new analysis of ``text``, kept if the text came before (or ``keep`` says to).

        ``prepared`` is a text that reads the same as ``text`` with what the caller
        read of it already: that text is analysed (see :func:`_analyse_normalized`).
        """
        analysis = (
            self._analyse(text) if prepared is None else self._prepared(prepared[0], prepared[1])
        )
        if not keep:
            seen = self._seen
            size = len(seen)
            seen.add(text)  # (one look at the set: the text is new when the set grows)
            if len(seen) > size:
                if size >= _MOST_SEEN:
                    seen.clear()
                    seen.add(text)
                return analysis
        kept = self._kept
        if len(kept) >= self._maxsize:
            kept.clear()  # (a bound on memory: an analysis is the same when made again)
        kept[text] = analysis
        return analysis

    def cache_clear(self) -> None:
        """Forget every analysis kept and every text seen."""
        self._kept.clear()
        self._seen.clear()

    def cache_info(self) -> _CacheInfo:
        return _CacheInfo(len(self._kept), self._maxsize)


def _raw_analysis(text: str) -> _Analysis:
    """The analysis of a raw text; texts that normalize alike share one (see _shared_analysis)."""
    read = _read_stretches(text)
    if read is None:
        return _shared_analysis(normalize(text))
    return _shared_analysis(*read)


class _ReadStretches(dict[str, _ChunkFacts | None]):
    """Each stretch of raw text between spaces, normalized on its own: its facts.

    The facts of the normalized stretch (see :func:`_chunk_facts`), which end with
    it; ``None`` for a stretch normalize does not read on its own (see
    :func:`~snowlight.classify.text.normalize_stretch`). Listings repeat their
    stretches as they repeat words ("Closed", "Wednesday;", "No"), so a listing
    made only of stretches read before is normalized and read with one lookup
    per stretch (see :func:`_read_stretches`).
    """

    def __missing__(self, stretch: str) -> _ChunkFacts | None:
        if stretch.isascii():
            if stretch.isalpha() and stretch.islower():
                # A lowercase word, the most common stretch: normalize_stretch reads it as it
                # is, but for "event" and a word it reads with the words beside it ("zero",
                # an update stamp's verb).
                read = (
                    None
                    if stretch == "event" or NOT_ALONE(stretch) is not None
                    else _chunk_lookup(stretch)
                )
            else:
                lowered = stretch.lower()
                # "Closed" and "CLOSED" read as "closed" does: normalize_stretch reads an ASCII
                # stretch as its lowercase, so the lowercase is read once for all its spellings.
                if lowered != stretch:
                    read = self[lowered]
                else:
                    normalized = normalize_stretch(stretch)
                    read = None if normalized is None else _chunk_lookup(normalized)
        else:
            normalized = normalize_stretch(stretch)
            read = None if normalized is None else _chunk_lookup(normalized)
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; a stretch is read the same when read again
            _AS_WRITTEN.clear()
        self[stretch] = read
        if read is not None and read[6] == stretch:
            _AS_WRITTEN.add(stretch)
        return read


_READ_STRETCHES = _ReadStretches()
_read_stretch = _READ_STRETCHES.__getitem__
# The stretches looked up so far that normalize to themselves, as most do ("closed", "2",
# "tomorrow,"): a text made only of them is its own normalized text (see _read_stretches).
_AS_WRITTEN: set[str] = set()
_all_as_written = _AS_WRITTEN.issuperset


def _read_stretches(text: str) -> tuple[str, list[_ChunkFacts]] | None:
    """``normalize(text)`` and the facts of its stretches, read stretch by stretch.

    ``None`` when normalize does not read each stretch on its own (see
    :func:`~snowlight.classify.text.joined_alone`). A text read here holds no
    stamp that :func:`~snowlight.classify.text.written_at` could find.
    """
    # (An ASCII stretch reads as its lowercase does, so an ASCII text's stretches are looked
    # up lowercase: "Closed" and "CLOSED" are one entry. A lowercase that is not ASCII can hold
    # an ASCII letter, as the Kelvin sign's does, so any other text is looked up as it is.)
    lowered = text.lower() if text.isascii() else text
    stretches = lowered.split(" ")
    read = list(map(_read_stretch, stretches))
    if _all_as_written(stretches):
        normalized = lowered  # (each stretch normalizes to itself: so does the text)
    elif not all(read):
        return None
    else:
        # (A comprehension: the interpreter reads a tuple's item quicker than a getter does.
        # Each stretch's facts end with the stretch normalized: see _chunk_facts.)
        normalized = " ".join([stretch[6] for stretch in read])  # type: ignore[index]
    # (joined_alone, inline: this runs for nearly every text parsed for the first time.)
    if (
        len(text) > MAX_CHARS
        or normalized[-1] == ","
        or "as of" in normalized
        or (" school" in normalized and ("after" in normalized or "before" in normalized))
    ):
        return None
    return normalized, read  # type: ignore[return-value]


def _shared_analysis(normalized: str, facts: list[_ChunkFacts] | None = None) -> _Analysis:
    """The analysis of a normalized text; texts that normalize alike share one.

    So do texts that differ only in their names (see :func:`canonical`), and
    texts that differ only in the month and the day number of their one plain
    date (see :func:`_day_template`). ``facts`` are those of the text's
    stretches between spaces, when the caller has read them.
    """
    # What each stretch between spaces is (see _chunk_facts): read once, for the names and,
    # when the text is analysed as it is, for the analysis.
    chunks: list[str] | None = None
    if facts is None:
        chunks = normalized.split(" ")
        facts = list(map(_chunk_lookup, chunks))
    bits = 0
    for stretch in facts:  # (a loop costs less than reduce, per stretch)
        bits |= stretch[0]
    key = template = normalized
    days = _NO_DAYS
    if bits & _NAME_WORD:
        key = template = canonical(normalized, chunks) if _CANONICAL else normalized
    # (A day number to fix needs a digit, and a month name or a slash before it: see
    # _day_template. The month name "may" gives no bit: see dates.word_hints.)
    if _TEMPLATE and bits & _DIGITS and (bits & _MONTH_NAME or "/" in key or "may" in key):
        template, days = _day_template(key)
    analysis = _NORMALIZED_KEPT.get(template)
    if analysis is not None and (not days or _one_date(analysis[_ONE_DATE])):
        return _with_days(analysis, days) if days else analysis
    # A text with names or day numbers replaced stands for the texts that differ from it
    # only there, so its analysis is kept at once (see _TextCache). The text itself is
    # analysed, with what was read of it, when that stands for its key as well: canonical
    # changes no reading, and a day number put back (see _with_days) finds its date where
    # the key has it, as nothing moved in the text, or as a text with no digit has no day
    # number. Its analysis is then the text's own, with its own days.
    own = key is normalized or len(key) == len(normalized) or not bits & _DIGITS
    analysis = (
        _analyse_normalized(normalized, (facts, bits)) if own else _analyse_normalized(template)
    )
    if days and not _one_date(analysis[_ONE_DATE]):
        # Two dates or more, whose values steps of the analysis compare ("Closed Jan. 21. Never
        # mind, open Jan. 22." is not "Closed Jan. 22. Never mind, open Jan. 22."): it holds
        # for the text's own dates alone, and stands for no other days.
        if not own:
            analysis = _analyse_normalized(key)
        template, days = key, _NO_DAYS
    # (Kept as _TextCache.fresh keeps it.)
    if not days and key is normalized:
        size = len(_NORMALIZED_SEEN)
        _NORMALIZED_SEEN.add(template)  # (one look at the set: see _TextCache.fresh)
        if len(_NORMALIZED_SEEN) > size:
            if size >= _MOST_SEEN:
                _NORMALIZED_SEEN.clear()
                _NORMALIZED_SEEN.add(template)
            return analysis  # (no days: see below)
    if len(_NORMALIZED_KEPT) >= _MOST_KEPT:
        _NORMALIZED_KEPT.clear()  # (a bound on memory: an analysis is the same made again)
    _NORMALIZED_KEPT[template] = analysis
    if own:
        return analysis
    return _with_days(analysis, days) if days else analysis


# Dates by day number ----------------------------------------------------------------------
#
# "Closed Jan. 21 due to snow" and "Closed Jan. 22 due to snow" say the same but for the day.
# Where a plain date's day number stands clear of everything but a mark or a cause, no step
# of the analysis reads its value: the date patterns take any day number (whether the date
# exists is decided when it is resolved), and nothing after it can make the number part of
# a length, a time, a list of days or a count. Such a day is analysed as a fixed number of
# the same width, so the texts share one analysis, and the real day is put back into the
# date before it is resolved. So is the date's month, "Closed Feb. 9" read as "Closed Jan.
# 5": no step of the analysis reads a month's value either, and the month words of one
# width are read alike (see _TEMPLATE_MONTHS).

_TEMPLATE = True
_TEMPLATE_DIGITS = ("", "5", "15")  # by the day number's width
# Each month word or number a plain date's month is analysed as: one of the same width that
# every step of the analysis reads alike ("dec" as "jan", "december" as "february", "12" as
# "10"). "may" (also a hedge: "may close") and "1" (as in "1/2 day") are read as they are.
_TEMPLATE_MONTHS: dict[str, str] = {
    **dict.fromkeys(
        ("jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), "jan"
    ),
    **dict.fromkeys(("june", "july", "sept"), "june"),
    **dict.fromkeys(("march", "april"), "march"),
    **dict.fromkeys(("january", "october"), "january"),
    **dict.fromkeys(("february", "november", "december"), "february"),
    **dict.fromkeys("23456789", "2"),
    **dict.fromkeys(("10", "11", "12"), "10"),
}  # fmt: skip
# A plain date's real month and day, by where its day number ends (see _day_template).
type _RealDates = dict[int, tuple[int, int]]
_NO_DAYS: _RealDates = {}  # (shared, and never changed: no real day to put back)
# A day number after a month name ("jan 21") or a month number ("1/21"), standing clear: the
# text ends after it, or a sentence mark, a comma or a spaced dash that no number follows, or
# a cause ("due to", "because", "owing"). The pattern finds the number after its space or its
# slash (a quick scan); what comes before it is checked then.
_PLAIN_DAY = re.compile(
    r"[ /](?P<day>\d{1,2})"
    r"(?=$|[;.!?|](?:$| )|,(?:$| (?!and\b)[a-z])| -(?:$| [a-z])| (?:due|because|owing)\b)",
    re.ASCII,
)
_MONTH_WORDS = frozenset(MONTHS)
_MONTH_NAME = MONTH_WORD << _DATE_SHIFT  # (a word of _MONTH_WORDS but "may": see _raw_analysis)
_NUMERALS = frozenset("0123456789")
_NOT_BEFORE_MONTH = frozenset("0123456789/.abcdefghijklmnopqrstuvwxyz_")


_find_plain_days = _PLAIN_DAY.finditer


def _day_template(text: str) -> tuple[str, _RealDates]:
    """``text`` with each plain date's month and day number fixed, and every plain date's
    real month and day.

    The real dates are keyed by where their day number ends. The fixed month and number
    have the same width, so every place in the text stays where it was; and as each plain
    date's real month and day are given, an analysis kept for the template can hold any
    texts' dates (see :func:`_raw_analysis`): :func:`_with_days` puts the text's own back
    in every one.
    """
    days: _RealDates = {}
    pieces: list[str] = []
    last = 0
    for match in _find_plain_days(text):
        start, end = match.span(1)  # (the day number)
        before = start - 1
        # Its month: a month name, or a month number and a slash, right before it.
        if text[before] == " ":
            month_start = text.rfind(" ", 0, before) + 1
            words = text[month_start:before]
            if words not in _MONTH_WORDS:
                continue
        else:
            month_start = before  # (the slash)
            low = before - 2  # (a month number has two digits at most)
            while month_start > low and month_start > 0 and text[month_start - 1] in _NUMERALS:
                month_start -= 1
            if month_start == before or (
                month_start and text[month_start - 1] in _NOT_BEFORE_MONTH
            ):
                continue
            words = text[month_start:before]
        digits = text[start:end]
        days[end] = (MONTHS.get(words) or int(words), int(digits))
        month = _TEMPLATE_MONTHS.get(words)
        if month is not None and month != words:
            pieces += (text[last:month_start], month)
            last = before
        fixed = _TEMPLATE_DIGITS[end - start]
        if digits != fixed:
            pieces += (text[last:start], fixed)
            last = end
    if not pieces:
        return text, days or _NO_DAYS
    pieces.append(text[last:])
    return "".join(pieces), days


def _with_days(analysis: _Analysis, days: _RealDates) -> _Analysis:
    """The analysis of a day template (see :func:`_day_template`) with the real dates put back.

    A date whose day number ends at one of the ``days``' places gets that month and day;
    the rest of the analysis is the text's own.
    """
    statuses = analysis[_STATUSES]
    hints = analysis[_HINTS]
    doubts = analysis[_DOUBTS]
    openings = analysis[_OPENINGS]
    if statuses:
        statuses = _statuses_with_days(statuses, days)
    if hints:
        hints = _groups_with_days(hints, days)
    if doubts:
        doubts = _statuses_with_days(doubts, days)
    if openings:
        fixed = tuple(
            [(at, mode, _groups_with_days(groups, days)) for at, mode, groups in openings]
        )
        if any(new[2] is not old[2] for new, old in zip(fixed, openings, strict=True)):
            openings = fixed
    if (
        statuses is analysis[_STATUSES]
        and hints is analysis[_HINTS]
        and doubts is analysis[_DOUBTS]
        and openings is analysis[_OPENINGS]
    ):
        return analysis
    # (A list's items set in place cost less than slices of the tuple put together.)
    fields = list(analysis)
    fields[_STATUSES] = statuses
    fields[_HINTS] = hints
    fields[_DOUBTS] = doubts
    fields[_OPENINGS] = openings
    return tuple(fields)  # type: ignore[return-value]


def _statuses_with_days(statuses: tuple[_Status, ...], days: _RealDates) -> tuple[_Status, ...]:
    found: list[_Status] | None = None
    for index, status in enumerate(statuses):
        groups = status[_GROUPS]
        if groups and groups is not (groups := _groups_with_days(groups, days)):
            if found is None:
                found = list(statuses)
            found[index] = _with_groups(status, groups)
        led = status[_LED]
        if led is not None and (day := _groups_with_days((led[0],), days)[0]) is not led[0]:
            # The day its days go on from is the text's own too ("Remote learning 1/22. Closed
            # through Friday": see _led_frame).
            if found is None:
                found = list(statuses)
            found[index] = (*found[index][:_LED], (day, led[1]))
    return statuses if found is None else tuple(found)


def _groups_with_days(groups: tuple[DateGroup, ...], days: _RealDates) -> tuple[DateGroup, ...]:
    found: list[DateGroup] | None = None
    for index, group in enumerate(groups):
        atoms: list[DateAtom] | None = None
        for position, atom in enumerate(group[GROUP_ATOMS]):
            real = days.get(atom[ATOM_END])
            if real is not None and atom[ATOM_KIND] == "explicit":
                if atoms is None:
                    atoms = list(group[GROUP_ATOMS])
                # (Its month and day. A list's items set in place cost less than slices.)
                fields = list(atom)
                fields[ATOM_MONTH], fields[ATOM_DAY] = real
                atoms[position] = tuple(fields)  # type: ignore[assignment]
        if atoms is not None:
            if found is None:
                found = list(groups)
            fixed = list(group)
            fixed[GROUP_ATOMS] = tuple(atoms)
            found[index] = tuple(fixed)  # type: ignore[assignment]
    return groups if found is None else tuple(found)


# One analysis takes about 1.2 KB, so a full cache of analyses takes some 20 MB.
_MOST_KEPT = 16384
_normalized_analysis = _TextCache(
    _analyse_normalized, maxsize=_MOST_KEPT, prepared=_analyse_normalized
)
"""The analysis of a normalized text (cached per text; see :class:`_TextCache`)."""
# (As large: an entry holds only the raw text and a reference to an analysis the cache above
# mostly holds too, so texts that come again are found by their raw form, not normalized.)
_cached_analysis = _TextCache(_raw_analysis, maxsize=_MOST_KEPT)
"""The analysis of a raw text (cached per text; see :class:`_TextCache`)."""
# The two caches' analyses kept and texts seen, which parse_status and _raw_analysis keep up
# as _TextCache.fresh does, without the calls (a text parsed for the first time is the most
# common case). The dict and the sets are the caches' own: emptying a cache empties them.
_kept_analysis = _cached_analysis.get
_RAW_KEPT = _cached_analysis._kept
_RAW_SEEN = _cached_analysis._seen
_NORMALIZED_KEPT = _normalized_analysis._kept
_NORMALIZED_SEEN = _normalized_analysis._seen


# The days one status applies to, as resolved for one posting time. A plain tuple, read by the
# field numbers below (see _Status).
type _Days = tuple[
    set[date],  # _DAYS_DAYS
    bool,  # _DAYS_STATED
    float,  # _DAYS_CONFIDENCE
    bool,  # _DAYS_UNTIL_NOTICE
]
_DAYS_DAYS: Final = 0
_DAYS_STATED: Final = 1
_DAYS_CONFIDENCE: Final = 2
_DAYS_UNTIL_NOTICE: Final = 3


# What resolving a text's dates needs besides the calendar. A plain tuple, read by the field
# numbers below (see _Status).
type _Frame = tuple[
    # _FRAME_DEFAULT: the day an open start ("through Friday") counts from (None: noon rule)
    date | None,
    date | None,  # _FRAME_UNDATED: the day a status that names no day applies to; None when unclear
    float,  # _FRAME_CEILING: the confidence ceiling for an undated status
    tuple[int, date] | None,  # _FRAME_ANCHOR: the last weekday name in the text
]
_FRAME_DEFAULT: Final = 0
_FRAME_UNDATED: Final = 1
_FRAME_CEILING: Final = 2
_FRAME_ANCHOR: Final = 3


_PLAIN_FRAME: _Frame = (None, None, INFERRED, None)
_UNTOLD = INVALID | UNCLEAR  # (the flags of a day that cannot be told: see _frame)


def _frame(analysis: _Analysis, calendar: Calendar) -> _Frame:
    anchor = analysis[_ANCHOR]
    last = None if anchor is None else (anchor[0], calendar.weekday(anchor[1], anchor[2]))
    window = analysis[_WINDOW]
    if window is None:
        # Every status names its days: only an open start ("through Friday") needs a default,
        # and the calendar works that out when it meets one.
        return _PLAIN_FRAME if last is None else (None, None, INFERRED, last)
    today_until, tomorrow_from = window
    undated = calendar.undated_day(today_until, tomorrow_from)
    if undated is not None and analysis[_HINTS]:
        # "Closed; offices open Monday": the text names a day, if only for a side note. The
        # posting time gives the status's day only when it is among the days named.
        # A weekend day ("Saturday activities cancelled") is no school day's rival. A day
        # that cannot be told ("Closed - no extended care; through 2/30", or a run too long
        # to be one closure) could be the status's as well: it gives none.
        default = calendar.next_school_day(today_until)
        named = [calendar.resolve(group, default) for group in analysis[_HINTS]]
        school_days = {
            day for resolved in named for day in resolved.dates if day.weekday() < _SATURDAY
        }
        if (school_days and undated not in school_days) or any(
            resolved.flags & _UNTOLD for resolved in named
        ):
            undated = None
    ceiling = JUDGMENT if calendar.near_cutoff(today_until, tomorrow_from) else INFERRED
    return (calendar.next_school_day(today_until), undated, ceiling, last)


def _status_days(  # noqa: PLR0912 - one branch per resolution flag
    status: _Status,
    calendar: Calendar,
    frame: _Frame,
    notes: set[Note],
    resolved_days: dict[tuple[object, ...], tuple[set[date], int]] | None = None,
) -> _Days | None:
    """Resolve one status's date groups; ``None`` when every stated date was impossible.

    ``resolved_days``, when given, keeps what each group resolved to, by what it names and
    the days it is resolved from: the statuses of one text often name the same day
    ("Saturday Morning: Closed | Saturday Afternoon: Closed"), which then resolves once.
    (Where a group sits plays no part in what it resolves to.)
    """
    confidence = status[_STRENGTH]
    until_notice = False
    led = status[_LED]
    default, undated, ceiling, anchor = (
        frame if led is None else _led_frame(status, calendar, frame)
    )
    if led is not None and default == _UNTOLD_DAY:
        notes.add("unreadable_date")
        return None
    groups = status[_GROUPS]
    # (After a closure's day, an open start goes on from the next school day: see _led_frame.)
    if len(groups) == 1 and anchor is None and (led is None or not led[1]):  # the most common
        resolved = calendar.resolve(groups[0], default)
        days = resolved.dates
        flags = resolved.flags
    else:
        days = set()
        flags = 0
        for group in groups:
            latest = anchor[1] if anchor is not None and group[GROUP_END] <= anchor[0] else None
            # A run after a day named before it goes on from that day: "Closed Monday, Tuesday
            # and through Friday", "Closed tomorrow and for the rest of the week".
            if (
                (days or (led is not None and led[1]))
                and _open_run(group)
                and (start := max(days) if days else default) is not None
            ):
                group_days, group_flags = _run_days(calendar, group, start, latest, default)
            else:
                group_days, group_flags = _group_days(
                    calendar, group, default, latest, resolved_days
                )
            days |= group_days
            flags |= group_flags  # (what each flag says holds for any group that has it)
    if flags:
        if flags & FURTHER_NOTICE:
            until_notice = True
        if flags & INVALID:
            notes.add("invalid_date")
            confidence = min(confidence, UNSURE)
        if flags & MISMATCH:
            notes.add("date_mismatch")
        if flags & OVERNIGHT:
            notes.add("overnight")
            confidence = min(confidence, JUDGMENT)
        if flags & RECURRING:
            notes.add("recurring")
        if flags & UNCLEAR:
            notes.add("unreadable_date")
        if flags & MISMATCH:
            # "tomorrow (Friday)" posted on a Wednesday, "Thursday 1/23" (a Friday): two
            # names for the day that disagree, and nothing says which one is right.
            return None
    stated = bool(days)
    if not days and groups and not until_notice:
        if flags & EVENING:
            notes.add("activities_cancelled")  # "Closed tonight": the evening, not the school day
        return None
    if not days:
        if undated is None:
            notes.add("undated")
            return None
        days = {undated}
        confidence = min(confidence, ceiling)
    if (
        next(iter(days)).weekday() >= _SATURDAY
        if len(days) == 1
        else all(day.weekday() >= _SATURDAY for day in days)
    ):
        notes.add("weekend")
        confidence = min(confidence, WEAK)
    return (days, stated, confidence, until_notice)


_UNTOLD_DAY = date.min  # (the default start _led_frame gives for days no one can tell)
_LED_UNTOLD = INVALID | UNCLEAR | MISMATCH  # (the flags of a led day no one can tell)


def _led_frame(status: _Status, calendar: Calendar, frame: _Frame) -> _Frame:
    """The frame a status's days are resolved in after the day named before it (its _LED):
    ``frame`` itself to resolve them as they stand; a default start of _UNTOLD_DAY when they
    cannot be told (see _led_later); or, after a closure's day, the school day after it as
    the day an open start and a status that names no day are for, its default and undated
    days alike (see _continued_closures)."""
    led = status[_LED]
    if led is None:
        return frame
    group, after = led
    default, _undated, ceiling, anchor = frame
    if not after:
        if _led_later(calendar, group, status[_GROUPS][0], default):
            return (_UNTOLD_DAY, None, ceiling, anchor)
        return frame
    resolved = calendar.resolve(group, default)
    if resolved.flags & _LED_UNTOLD or not resolved.dates:
        return (_UNTOLD_DAY, None, ceiling, anchor)
    begin = _next_school_day_after(max(resolved.dates))
    return (begin, begin, ceiling, anchor)


def _run_days(
    calendar: Calendar, group: DateGroup, start: date, latest: date | None, default: date | None
) -> tuple[set[date], int]:
    """The days of a run with no first day of its own after a day named before it, ``start``,
    and the flags of resolving it: it goes on from that day ("Closed Monday, Tuesday and
    through Friday", "Closed tomorrow. Closed through Friday": see _anchored_runs). "All
    week" or "this week" after a day of the posting week is that week, from ``default`` as
    alone ("Closed Thursday and all week")."""
    if _whole_week(group) and start <= calendar.week_end():
        resolved = calendar.resolve(group, default, latest)
        return resolved.dates, resolved.flags
    counted = calendar.run_from(start, group)
    if counted is not None:
        return counted.dates, counted.flags
    resolved = calendar.resolve(group, start, latest)
    if resolved.dates and max(resolved.dates) < start:
        # "Closed Friday. Closed through 1/22.": a run that ends before the day it goes on
        # from names no days anyone can tell.
        resolved.flags |= UNCLEAR
    return resolved.dates, resolved.flags


def _group_days(
    calendar: Calendar,
    group: DateGroup,
    start: date | None,
    latest: date | None,
    resolved_days: dict[tuple[object, ...], tuple[set[date], int]] | None,
) -> tuple[set[date], int]:
    """The days one group resolves to, and the flags of resolving it (see :func:`_status_days`)."""
    if resolved_days is None:
        resolved = calendar.resolve(group, start, latest)
        return resolved.dates, resolved.flags
    key = (
        tuple([atom[ATOM_KIND:] for atom in group[GROUP_ATOMS]]),
        group[GROUP_LINKS],
        group[GROUP_OPEN_START],
        start,
        latest,
    )
    found = resolved_days.get(key)
    if found is None:
        resolved = calendar.resolve(group, start, latest)
        found = resolved_days[key] = (resolved.dates, resolved.flags)
    return found


# Every day's claims, and what else bears on the days. A plain tuple, read by the field numbers
# below (see _Status).
type _Claims = tuple[
    dict[date, list[_Claim]],  # _CLAIMS_BY_DAY
    set[date],  # _CLAIMS_FURTHER: the days whose status runs until further notice
    set[date],  # _CLAIMS_UNCERTAIN: the days a floating status makes uncertain
    dict[
        date, list[_Status]
    ],  # _CLAIMS_REVOKED: the statuses called off, by the days they were for
]
_CLAIMS_BY_DAY: Final = 0
_CLAIMS_FURTHER: Final = 1
_CLAIMS_UNCERTAIN: Final = 2
_CLAIMS_REVOKED: Final = 3


def _claims(  # noqa: PLR0912 - one pass over the statuses, the doubts and the openings
    analysis: _Analysis, calendar: Calendar, notes: set[Note]
) -> _Claims:
    """Return every day's claims, and the days the rest of the text bears on."""
    frame = _frame(analysis, calendar)
    by_day: dict[date, list[_Claim]] = defaultdict(list)
    further: set[date] = set()
    floating: list[_Status] = []
    revoked: dict[date, list[_Status]] = defaultdict(list)
    resolved_days: dict[tuple[object, ...], tuple[set[date], int]] | None = (
        {} if _FAST_PATH else None
    )
    for status in analysis[_STATUSES]:
        if status[_FLOATING]:
            floating.append(status)
            continue
        if status[_REVOKED]:
            # Its days, if they can be told, for the check in _contradicted; nothing it
            # finds on the way is news about the status that stands.
            called_off = _status_days(status, calendar, frame, set())
            for day in () if called_off is None else called_off[_DAYS_DAYS]:
                revoked[day].append(status)
            continue
        resolved = _status_days(status, calendar, frame, notes, resolved_days)
        if resolved is None:
            continue
        for day in resolved[_DAYS_DAYS]:
            by_day[day].append((status, resolved[_DAYS_STATED], resolved[_DAYS_CONFIDENCE]))
            if resolved[_DAYS_UNTIL_NOTICE]:
                further.add(day)
        if status[_IS_SUPERSEDING] and resolved[_DAYS_DAYS]:
            _narrowed(status, resolved[_DAYS_DAYS], by_day, notes)
    uncertain: set[date] = set()
    for status in floating:
        unclear = _float(status, frame[_FRAME_UNDATED], by_day, further, notes)
        if unclear is not None:
            uncertain.add(unclear)
    for doubt in analysis[_DOUBTS]:
        if doubt[_REVOKED]:
            _hedged_days(doubt, calendar, frame, by_day, notes)  # (see _hedged_doubts)
        else:
            uncertain |= _doubted(doubt, calendar, frame, by_day, further)
    if analysis[_OPENINGS]:
        # "Closed Thursday and Friday. Open Friday.": see _Opening.
        _open_days(analysis[_OPENINGS], calendar, frame[_FRAME_DEFAULT], by_day, notes)
    return (by_day, further, uncertain, revoked)


def _narrowed(
    update: _Status, days: AbstractSet[date], by_day: dict[date, list[_Claim]], notes: set[Note]
) -> None:
    """Take from ``by_day`` the days after an update's range ends that a status before it
    claims: "Closed today through Friday. Update: closed through tomorrow."

    An update that ends its days with "through" or "until" ("closed through
    tomorrow", "closed today through tomorrow", "closed until Friday") says when
    it ends, so what the text said before it of the later days no longer holds
    (whatever its kind: "Closed through Friday. Update: 2 hour delay through
    tomorrow" says nothing sure of Friday). An update that names days alone
    ("Update: closed tomorrow") may only restate one of them, and leaves the
    others as they are.
    """
    if not any(
        group[GROUP_OPEN_START] in _RANGE_ENDS or "range" in group[GROUP_LINKS]
        for group in update[_GROUPS]
    ):
        return
    end = max(days)
    position = update[_POSITION]
    for day in [day for day in by_day if day > end]:
        kept = [claim for claim in by_day[day] if claim[_CLAIM_STATUS][_POSITION] > position]
        if len(kept) < len(by_day[day]):
            notes.add("superseded")
            if kept:
                by_day[day] = kept
            else:
                del by_day[day]


_RANGE_ENDS = frozenset({"range", "until"})  # (an open range's start: "through", "until")


def _doubted(
    doubt: _Status,
    calendar: Calendar,
    frame: _Frame,
    by_day: dict[date, list[_Claim]],
    further: set[date],
) -> set[date]:
    """The days a bare "cancelled" puts in doubt.

    Read as the school cancelled, it is for the days it names, or else the day a
    closure that names none is for. A day whose status that reading would
    change ("2 hour delay (Lincoln Elementary) cancelled": a delay or a closure)
    could be either, so it gets none. A closure or a remote day reads the same.
    """
    if doubt[_GROUPS]:
        resolved = _status_days(doubt, calendar, frame, set())
        days = set() if resolved is None else resolved[_DAYS_DAYS]
    else:
        day = calendar.undated_day(*_UNDATED["closed"])
        days = set() if day is None else {day}
    doubted: set[date] = set()
    for day in days:
        claims = by_day.get(day)
        if not claims:
            continue
        alone = _day_status(claims, day in further)
        joined = _day_status([*claims, (doubt, False, doubt[_STRENGTH])], day in further)
        if joined is None or alone is None or joined[0] != alone[0]:
            doubted.add(day)
    return doubted


def _hedged_days(
    doubt: _Status,
    calendar: Calendar,
    frame: _Frame,
    by_day: dict[date, list[_Claim]],
    notes: set[Note],
) -> None:
    """Take from ``by_day`` the days a status only possible names (see :func:`_hedged_doubts`).

    "Closed Monday and Tuesday. Tuesday's closure may be lifted.": the day the text says may
    change is no status's for sure, and the statuses that named it keep their other days as a
    judgment call, as a reopening only possible leaves them (see :func:`_open_days`).
    """
    resolved = _status_days(doubt, calendar, frame, set())
    touched: set[int] = set()
    for day in () if resolved is None else resolved[_DAYS_DAYS]:
        claims = by_day.pop(day, None)
        if claims:
            touched.update(claim[_CLAIM_STATUS][_POSITION] for claim in claims)
    if touched:
        notes.add("hedged")
        for day, claims in by_day.items():
            by_day[day] = [
                (claim[0], claim[1], min(claim[2], JUDGMENT))
                if claim[_CLAIM_STATUS][_POSITION] in touched
                else claim
                for claim in claims
            ]


def _contradicted(claims: list[_Claim], revoked: list[_Status] | None) -> bool:
    """Whether the text calls off a status it also states for the day.

    "Closure cancelled. Closed." says both; "2 hour delay cancelled. 3 hour
    delay." replaces one delay with another, and "Delay cancelled. Closed."
    one status with another.
    """
    return bool(revoked) and any(
        claim[_CLAIM_STATUS][_KIND] == called_off[_KIND]
        and _agree(claim[_CLAIM_STATUS], called_off)
        for claim in claims
        for called_off in revoked or ()
    )


def _float(
    status: _Status,
    day: date | None,
    by_day: dict[date, list[_Claim]],
    further: set[date],
    notes: set[Note],
) -> date | None:
    """Return the named day a floating status makes uncertain, if any.

    Read from the posting time alone, the status would be for ``day``. When the
    text names that day for a status the floating one would change ("2 hour
    delay today. Closed."), the day could be either, so it gets no status.
    Otherwise the floating status is left out: nothing says which day it is for.
    """
    claims = by_day.get(day) if day is not None else None
    if day is not None and claims:
        alone = _day_status(claims, day in further)
        joined = _day_status([*claims, (status, False, status[_STRENGTH])], day in further)
        if joined is None or alone is None or joined[0] != alone[0]:
            return day
    notes.add("undated")  # left out: the day the text names reads the same either way
    return None


def _schedule(found: _Claims, notes: set[Note]) -> tuple[list[DatedStatus], list[float]]:
    settled: dict[date, tuple[_Day, float]] = {}
    further = found[_CLAIMS_FURTHER]
    for day, claims in found[_CLAIMS_BY_DAY].items():
        if all(claim[_CLAIM_STATUS][_IS_SUPERSEDED] for claim in claims):
            # "We were closed Monday. Closed again today.": a status the text marks as past
            # or replaced, with nothing standing on its day, is no status for that day.
            notes.add("superseded")
            continue
        outcome = (
            None
            if day in found[_CLAIMS_UNCERTAIN]
            or _contradicted(claims, found[_CLAIMS_REVOKED].get(day))
            else _day_status(claims, day in further)
        )
        if outcome is None:
            notes.add("conflict")
            continue
        if len({c[_CLAIM_STATUS][_KIND] for c in claims}) > 1 and any(
            c[_CLAIM_STATUS][_IS_SUPERSEDED] or c[_CLAIM_STATUS][_IS_SUPERSEDING] for c in claims
        ):
            notes.add("superseded")
        settled[day] = outcome
    by_signature: dict[_Day, list[date]] = defaultdict(list)
    confidence: dict[_Day, float] = {}
    for day in sorted(settled):
        signature, value = settled[day]
        by_signature[signature].append(day)
        confidence[signature] = min(confidence.get(signature, 1.0), value)
    entries = sorted(by_signature.items(), key=lambda item: item[1][0])
    statuses = [
        _new(
            DatedStatus,
            (
                signature[_DAY_KIND],
                tuple(days),
                signature[_DAY_DELAY],
                signature[_DAY_OPENS_AT],
                signature[_DAY_DISMISSAL],
                signature[_DAY_EARLY],
                signature[_DAY_STATED],
                signature[_DAY_FURTHER_NOTICE],
            ),
        )
        for signature, days in entries
    ]
    return statuses, [confidence[signature] for signature, _days in entries]


# Notes that leave a listing with no status because it could not be read with confidence.
_UNSURE_NOTES = frozenset(
    {
        "ambiguous", "hedged", "invalid_date", "unreadable_date", "undated", "date_mismatch",
        "unread_words",
    }
)  # fmt: skip


# The lowest confidence of a result the precision gate can stop (see classify.gate).
CONFIDENT: Final = 0.7

# Notes that leave a stated status standing but say the text holds more than it.
# Notes that leave the status stated not all there is (see parse_status): a status of unclear
# day left out, two day words that disagree, words beside it not placed, or a run of days
# dropped as impossible ("Closed today; closed through April 6" posted on New Year's Eve).
_PARTIAL_NOTES = frozenset({"undated", "date_mismatch", "ambiguous", "invalid_date"})


def _unstated_confidence(
    text: str, notes: AbstractSet[Note], *, ambiguous: bool, says_open: bool, offices_open: bool
) -> float:
    """How sure the parser is of a result that states no status (see :data:`CONFIDENCE_LEVELS`)."""
    if not text:
        return EMPTY
    if "conflict" in notes:
        return CONFLICTING
    if notes & _UNSURE_NOTES or ambiguous:
        return HEDGED
    if says_open or offices_open or not notes <= _NOT_UNDERSTOOD:
        return INFERRED
    return UNKNOWN


# The notes that say nothing understood of a text: a result with only these is unknown.
_NOT_UNDERSTOOD = frozenset({"weekend", "overnight", "date_mismatch", "superseded", "unrecognized"})


_STAMP_LEEWAY = timedelta(hours=1)
_ONE_DAY = timedelta(days=1)


def _as_written(calendar: Calendar, written: Written, tz: str) -> Calendar:
    """The calendar of when a listing says it was written ("Last updated: 01/09/2025 05:13am").

    That is when its "today", "tomorrow" and weekday names were meant, however
    much later the listing was seen: "Closed Friday - Last Updated: 01/09/2025
    05:13am" closes Friday 10 January 2025 even when first seen on the Saturday.
    A stamp without a year is the latest such day up to the day after the posting
    day. A stamp for a day that does not exist, or more than an hour after the
    posting time (a clock in another zone), leaves the posting time as it is.
    """
    month, day, year, hour, minute = written
    today = calendar.today
    try:
        if year is None:
            year = today.year
            if date(year, month, day) > today + _ONE_DAY:
                year -= 1  # "updated Dec 31" seen on Jan 2
        stamped = datetime(year, month, day, hour, minute, tzinfo=zone(tz))
    except ValueError:
        return calendar  # "updated Feb 30 1:00 PM", or Feb 29 in the year before
    posted = datetime.combine(today, time(*divmod(calendar.minutes, 60)), tzinfo=stamped.tzinfo)
    if stamped > posted + _STAMP_LEEWAY:
        return calendar
    return Calendar(stamped, tz)


# The calendar of the last posting time a text was resolved for, with that time and zone: a
# feed's listings are parsed for one posting time, which then needs making and checking once.
# (A Calendar is never changed once made, and depends on the two alone.)
_last_calendar: list[tuple[datetime | None, str | None, Calendar | None]] = [(None, None, None)]


def parse_status(  # noqa: PLR0911, PLR0912, PLR0915 - a kept result, the calendar, each form
    text: str, *, posted_at: datetime, tz: str
) -> ParsedStatus:
    """Return what the closings listing ``text`` says.

    ``posted_at`` is when the listing was published or first seen (a
    timezone-aware datetime); ``tz`` is the school's IANA time zone. Relative
    days ("today", "tomorrow", "Monday") are resolved in that zone from that
    moment, or from the moment the text itself says it was written ("Last
    updated: 01/27/2026 8:13 PM"), when that is no more than an hour after
    it. The function is pure: the same arguments always give the same result,
    and nothing outside them is read.

    A listing longer than :data:`~snowlight.classify.text.MAX_CHARS` is read
    at its start and its end (see :func:`~snowlight.classify.text.within_limit`),
    and noted ``truncated``: a status read there is a judgment call (0.8 at
    most), and a reading of no status is unsure (0.3 at most), as the middle
    is not read.

    Raises ``ValueError`` if ``posted_at`` is naive or ``tz`` is not a known
    time zone.
    """
    if len(text) > MAX_CHARS:
        return _read_in_part(parse_status(within_limit(text), posted_at=posted_at, tz=tz))
    analysis = _kept_analysis(text)
    stamped = True  # whether the text can hold a stamp that says when it was written
    if analysis is None:
        read = _read_stretches(text)  # (as _raw_analysis reads it)
        if read is None:
            normalized, stamped = normalize_stamped(text)
            analysis = _shared_analysis(normalized)
            slot = "{" in text or "[" in text or "%" in text or "<" in text or "_" in text
        else:
            stamped = False
            analysis = _shared_analysis(*read)
            # (A text read stretch by stretch holds no bracket: see text._ALONE_CHARS.)
            slot = "%" in text
        if slot and analysis[_RECOGNIZED] and _template_slot(text):
            analysis = _templated(analysis)  # "Closed {date}": a form never filled in
        # (Kept as _TextCache.fresh keeps it: from the second time the text comes.)
        size = len(_RAW_SEEN)
        _RAW_SEEN.add(text)  # (one look at the set: the text is new when the set grows)
        if len(_RAW_SEEN) == size:
            if len(_RAW_KEPT) >= _MOST_KEPT:
                _RAW_KEPT.clear()  # (a bound on memory: an analysis is the same made again)
            _RAW_KEPT[text] = analysis
        elif size >= _MOST_SEEN:
            _RAW_SEEN.clear()
            _RAW_SEEN.add(text)
    last_posted, last_tz, last = _last_calendar[0]
    result = analysis[_RESULT]
    if last is not None and posted_at is last_posted and tz == last_tz:
        if result is not None:
            return result
        calendar = last  # checked already (see _last_calendar)
    elif result is not None:
        check_moment(posted_at, tz)  # (the same checks as the calendar's, for the same errors)
        return result  # no status: nothing to resolve (see _Analysis.result)
    else:
        calendar = Calendar(posted_at, tz)
        _last_calendar[0] = (posted_at, tz, calendar)
    written = written_at(text) if stamped else None  # (see text.normalize_stamped)
    if written is not None:
        calendar = _as_written(calendar, written, tz)
    lead = analysis[_LEAD]
    if lead is not None and _past_week(lead, analysis[_ANCHOR], calendar):
        # "2-hr delay Tues." seen on a Thursday: most likely the Tuesday just past, which says
        # nothing of today or the days ahead, or else the one a week on. Neither can be told.
        unplaced: set[Note] = {*analysis[_NOTES], "unreadable_date"}
        # (Nor does a slot that says school is open name a day that can be told.)
        return _unstated(analysis, unplaced, tuple(sorted(unplaced)), says_open=False)
    statuses = analysis[_STATUSES]
    single = False
    if len(statuses) == 1 and not analysis[_DOUBTS]:
        single = True
    if single and not statuses[0][_REVOKED]:
        single_result = _single_result(analysis, statuses[0], calendar)
        if (
            analysis[_OPENINGS]
            and single_result.dates
            and (
                single_result.kind in _OPENED_KINDS
                or any(mode & _DENIALS for _at, mode, _days in analysis[_OPENINGS])
            )
        ):
            # "Closed Thursday and Friday. Open Friday.": see _Opening.
            single_result = _opened_single(analysis, statuses[0], single_result, calendar)
        if (
            analysis[_SAYS_OPEN]
            and single_result.dates
            and _all_past(single_result, calendar)
            and _open_now(analysis, calendar)
        ):
            # "Closed yesterday. Open today." (unless the precision gate stops it: see
            # classify.gate)
            return analysis[_GATED] or _open_after_past(analysis)
        if analysis[_GATED] is not None and single_result.confidence >= CONFIDENT:
            return analysis[_GATED]  # (the precision gate: see classify.gate)
        return single_result
    notes: set[Note] = set(analysis[_NOTES])
    schedule: list[DatedStatus] = []
    confidences: list[float] = []
    if statuses and not single:  # (a lone status called off has no day of its own)
        schedule, confidences = _schedule(_claims(analysis, calendar, notes), notes)
    if schedule and "unreadable_date" in notes:
        # A day the parser cannot pin down: any status could be for that day.
        schedule, confidences = [], []
    # Resolving only ever adds notes: the same count means the same notes.
    ordered = (
        analysis[_SORTED_NOTES] if len(notes) == len(analysis[_NOTES]) else tuple(sorted(notes))
    )
    if not schedule:
        # A status the text states that a doubt leaves unclear ("All campuses closed. Remote
        # classes will continue as scheduled. In-person classes may be moved to remote") is no
        # word that school runs as normal; only an opening that takes its days away is.
        unstated = _unstated(
            analysis,
            notes,
            ordered,
            says_open=not (statuses and analysis[_DOUBTS] and not analysis[_OPENINGS]),
        )
        gated = analysis[_GATED]
        return gated if gated is not None and unstated.confidence >= CONFIDENT else unstated
    terms, names_weather, reason, reasons, other_causes = analysis[_WEATHER]
    if len(schedule) == 1:
        primary_index = 0
    else:
        reference = calendar.relative(-1) if calendar.overnight else calendar.today
        primary_index = len(schedule) - 1
        for index, entry in enumerate(schedule):
            if entry.dates[-1] >= reference:
                primary_index = index
                break
    if analysis[_SAYS_OPEN] and primary_index == len(schedule) - 1:
        latest = schedule[-1].dates[-1]
        if latest < (calendar.relative(-1) if calendar.overnight else calendar.today) and (
            _open_now(analysis, calendar)
        ):
            # "Yesterday: closed. Today: open." (unless the precision gate stops it)
            return analysis[_GATED] or _open_after_past(analysis)
    primary = schedule[primary_index]
    confidence = confidences[primary_index]
    if "conflict" in notes:
        confidence = min(confidence, WEAK)
    if analysis[_NARROWED] or not _PARTIAL_NOTES.isdisjoint(notes):
        # Part of the program has its own status, or a status of unclear day was left out,
        # or two day words disagree somewhere, or words beside the status could not be
        # placed: the one stated may not be all there is.
        confidence = min(confidence, JUDGMENT)
    if analysis[_GATED] is not None and confidence >= CONFIDENT:
        return analysis[_GATED]
    return _new(
        ParsedStatus,
        (
            primary.kind,
            primary.dates,
            primary.delay_minutes,
            primary.opens_at,
            primary.dismissal_time,
            primary.dismissal_early_minutes,
            primary.dates_stated,
            primary.until_further_notice,
            tuple(schedule),
            terms,
            names_weather,
            reason,
            reasons,
            other_causes,
            min(confidence, CERTAIN),
            False,
            analysis[_OFFICES_OPEN],
            ordered,
        ),
    )


def _templated(analysis: _Analysis) -> _Analysis:
    """The analysis of a text that holds a template's slot never filled in ("Closed {date}",
    "Closed [DATE]", "2 hour delay on %DATE%", "Closed on <date>"): its status is for a day
    no one wrote, so it states none (note ``unreadable_date``). Normalizing takes the marks out
    of such a slot, so the raw text is looked at for them."""
    notes: set[Note] = {*analysis[_NOTES], "unreadable_date"}
    result = _unstated(analysis, notes, tuple(sorted(notes)), says_open=False)
    return (*analysis[:_RESULT], result, *analysis[_RESULT + 1 :])  # type: ignore[return-value]


# A template's slot for a day or a time, in the raw text: "{date}", "{{date}}", "[DATE]",
# "%DATE%", "<date>", "[Insert date]".
_TEMPLATE_SLOT = re.compile(
    r"\{\{?\s*[a-z_][\w .-]*\}\}?|%[a-z_]+%|[\[<]\s*(?:insert\s+)?(?:date|day|time|weekday|month)"
    r"(?:\s*/\s*time)?\s*[\]>]"
    # A printf slot ("Closed %s") or a blank to fill in ("Closed ___", "_ hour delay").
    r"|(?P<bare>(?<![\w%])%[sd](?!\w)|(?<!\w)_+(?!\w))",
    re.ASCII | re.IGNORECASE,
).finditer
# The words a printf slot or a blank stands after where it is no day's but something to send or
# key in: "Reply %d for details", "Text %s to 12345", "Call ___".
_SLOT_NOT_DAY = re.compile(
    r"\b(?:reply|replies|text|txt|call|dial|press|enter|code|ext|extension|send|type|key|pin"
    r"|number|no|room)\W*\Z",
    re.ASCII | re.IGNORECASE,
)


def _template_slot(text: str) -> bool:
    """Whether the raw text holds a template's slot for a day or a time (see _TEMPLATE_SLOT): a
    named one anywhere, a printf slot or a blank but where it stands for something to send or
    key in."""
    for found in _TEMPLATE_SLOT(text):
        if (
            found.group("bare") is None
            or _SLOT_NOT_DAY.search(text, max(0, found.start() - _SLOT_REACH), found.start())
            is None
        ):
            return True
    return False


_SLOT_REACH = 16  # (how far before a slot its word can start)


def _all_past(result: ParsedStatus, calendar: Calendar) -> bool:
    """Whether every day of a result is before the posting day (the day before, overnight)."""
    return result.dates[-1] < (calendar.relative(-1) if calendar.overnight else calendar.today)


def _open_now(analysis: _Analysis, calendar: Calendar) -> bool:
    """Whether the word that school is open can be for the posting day or after.

    It names no day, or one of the days the text names for something other than
    its statuses (its hints, which hold the open day's) is the posting day or
    after (the day before, overnight): "Closed yesterday. Open today." A school
    open on a day as past as its statuses is history too: "Schools will be open
    on Wednesday, September 25 ... closed on Thursday, September 26" seen in
    October states those days.
    """
    hints = analysis[_HINTS]
    if not hints:
        return True
    reference = calendar.relative(-1) if calendar.overnight else calendar.today
    return any(day >= reference for group in hints for day in calendar.resolve(group).dates)


def _open_after_past(analysis: _Analysis) -> ParsedStatus:
    """The result of a text whose statuses are all past and that says school is open.

    "Yesterday's closure: snow. Today: open", "Closed yesterday. Open today.":
    the past status is history, and the news is that school runs as normal.
    """
    notes: set[Note] = {*analysis[_NOTES], "superseded"}
    return _unstated(analysis, notes, tuple(sorted(notes)))


def _read_in_part(result: ParsedStatus) -> ParsedStatus:
    """The result of a listing too long to read whole, from that of its start and end.

    Whatever its middle says is unknown: a status read is a judgment call, a
    reading of no status is unsure, and nothing says the school runs as normal.
    """
    notes: set[Note] = {*result.notes, "truncated"}
    ceiling = HEDGED if result.kind == "other" else JUDGMENT
    return result._replace(
        confidence=min(result.confidence, ceiling), says_open=False, notes=tuple(sorted(notes))
    )


def _unstated(
    analysis: _Analysis,
    notes: AbstractSet[Note],
    ordered: tuple[Note, ...],
    *,
    says_open: bool = True,
) -> ParsedStatus:
    """The result of a text that states no status for a day it names (kind ``other``).

    ``notes`` are the text's notes with what resolving its days added, and ``ordered`` the
    same in order. ``says_open`` false leaves out the text's word that school is open.
    """
    terms, names_weather, reason, reasons, other_causes = analysis[_WEATHER]
    return _new(
        ParsedStatus,
        (
            "other", (), None, None, None, None, False, False, (), terms, names_weather, reason,
            reasons, other_causes,
            _unstated_confidence(
                analysis[_TEXT], notes, ambiguous=analysis[_AMBIGUOUS],
                says_open=analysis[_SAYS_OPEN], offices_open=analysis[_OFFICES_OPEN],
            ),
            says_open and analysis[_SAYS_OPEN] and "conflict" not in notes,
            analysis[_OFFICES_OPEN], ordered,
        ),
    )  # fmt: skip


# A weekday name stands for its next occurrence (see Calendar.weekday). When that is 5 or 6 days
# after the posting day, the one the name last stood for was a day or two before it: a listing
# still up after the day it was for, most likely ("2-hr delay Tues." seen on a Thursday), not a
# status a week ahead. So is a run of such days that ends there and starts no sooner than 4 days
# on ("Closed Monday through Wednesday" seen on a Thursday): the run just past, not the next. A
# closings page rarely lists a closure for weather days long before it starts; a listing often
# stays up a day or two after it ends. A run that ends on the posting day, seen after school,
# is as much the run just ending as the next when the next starts on the next school day
# ("Closed Mon.-Fri." seen on a Friday evening): neither can be told.
_PAST_LAST_DAY: Final = 5
_PAST_FIRST_DAY: Final = 4
_AFTER_SCHOOL: Final = _UNDATED["closed"][1]  # (when a closure that names no day is tomorrow's)


def _past_week(
    lead: tuple[DateGroup, ...], anchor: tuple[int, int, str | None] | None, calendar: Calendar
) -> bool:
    """Whether a text's days, named by weekday names alone, are most likely the week just past.

    They are when, as the weekday names resolve in the text's order, the last of them
    comes 5 or 6 days after the posting day and none comes sooner than 4 days on:
    "Closed Monday" seen on a Wednesday, "Wednesday: Closed...... Thursday: Opening At
    2:00 PM" seen on a Friday morning, "Closed Monday and Tuesday" seen on a Thursday,
    "Closed Monday through Wednesday" seen on a Thursday. "Closed Friday and Monday"
    seen on a Saturday starts yesterday, "Closed Thursday through Monday" seen on a
    Wednesday starts tomorrow, and "Closed Monday" seen on a Thursday is 4 days on:
    all three stand. A run that ends on the posting day, seen after school, whose
    next run would start on the next school day ("Closed Mon.-Fri." seen on a Friday
    evening: the week ending, or the next) is placed no better, and counts here too.
    An evening names no school day, so it starts no run ("Tuesday Evening:
    Closed...... Wednesday: Closed"); but it is on its day, so it can end one
    ("Monday: Closed...... Tuesday Evening: Open").
    """
    if anchor is None and len(lead) == 1:
        atoms = lead[0][GROUP_ATOMS]
        if (
            len(atoms) == 1
            and lead[0][GROUP_OPEN_START] is None
            and (weekday := atoms[0][ATOM_WEEKDAY]) is not None
        ):
            # "Closed Wednesday" (the most common lead; never an evening: see _weekday_lead).
            return calendar.days_ahead(weekday) >= _PAST_LAST_DAY
    last = None if anchor is None else calendar.weekday(anchor[1], anchor[2])
    starts: list[date] = []  # the days that can start the text's run of days
    ends: list[date] = []  # and those that can end it
    for group in lead:
        before = last if anchor is not None and group[GROUP_END] <= anchor[0] else None
        _lead_days(group, before, calendar, starts, ends)
    if not starts:
        return False
    today = calendar.today
    first, last = min(starts), max(ends)
    if (first - today).days >= _PAST_FIRST_DAY and (last - today).days >= _PAST_LAST_DAY:
        return True
    # "Closed Mon.-Fri." seen on a Friday evening: the week ending, or the next (see above).
    return (
        last == today
        and first < today
        and calendar.minutes >= _AFTER_SCHOOL
        and not calendar.overnight
        and _next_school_day_after(today) == first + _ONE_WEEK
    )


_ONE_WEEK = timedelta(days=7)


def _next_school_day_after(day: date) -> date:
    """The first weekday after ``day``."""
    day += _ONE_DAY_STEP
    while day.weekday() >= _SATURDAY:
        day += _ONE_DAY_STEP
    return day


_ONE_DAY_STEP = timedelta(days=1)


def _lead_days(
    group: DateGroup,
    before: date | None,
    calendar: Calendar,
    starts: list[date],
    ends: list[date],
) -> None:
    """Add the days a group of weekday names stands for (see :func:`_past_week`).

    ``before`` is the day of a weekday named later in the text, which the group's
    days are not after. An evening is on its day all the same, so it can end the
    days named ("Monday: Closed...... Tuesday Evening: Open"); but it is after
    school, so a run that starts with one starts on the next school day ("Tuesday
    Evening: Closed...... Wednesday: Closed").
    """
    atoms = group[GROUP_ATOMS]
    if (
        len(atoms) == 1
        and group[GROUP_OPEN_START] is None
        and (weekday := atoms[0][ATOM_WEEKDAY]) is not None
    ):
        # One weekday name (the most common group), placed as Calendar.resolve places it.
        day = calendar.weekday_by(weekday, atoms[0][ATOM_MODIFIER], before)
        if not atoms[0][ATOM_EVENING]:
            starts.append(day)
        ends.append(day)
        return
    days = calendar.resolve(group, None, before).dates
    if days and group[GROUP_OPEN_START] is not None:
        # "Closed through Wednesday" runs from the posting time to the day it names, whose
        # week the last day closed alone tells: seen on a Thursday, the run ended yesterday,
        # or else runs a week more. "Closed until Monday" seen on a Wednesday closes the rest
        # of the week; "until Wednesday" seen on a Thursday, through a Tuesday 5 days on.
        days = {max(days)}
    starts.extend(days)
    ends.extend(days)
    if any(atom[ATOM_EVENING] for atom in atoms):
        ends.extend(calendar.resolve(_evening_days(group), None, before).dates)


def _evening_days(group: DateGroup) -> DateGroup:
    """The group with each evening read as its day ("Tuesday Evening" as Tuesday).

    An evening states no status for the school day, but it is on that day: where
    a text's days fall in the week, it counts as much as the day does.
    """
    atoms = tuple([(*atom[:ATOM_EVENING], False) for atom in group[GROUP_ATOMS]])
    return (group[GROUP_START], group[GROUP_END], atoms, *group[GROUP_LINKS:])


def _single_result(analysis: _Analysis, status: _Status, calendar: Calendar) -> ParsedStatus:
    """:func:`parse_status` of a text with one status that stands (the most common case).

    With one status there is no other for it to conflict with, restate or
    replace: its days are resolved and the result is made directly. (A status
    marked as past stands here when it names its day plainly: "School was
    closed yesterday"; see :func:`_past_reports`.)
    """
    (
        _text, _statuses, notes, _recognized, _ambiguous, narrowed, offices_open, _says_open,
        weather, window, anchor, ordered, hints, _doubts, _result, _lead, _one, _openings, _gated,
    ) = analysis  # fmt: skip
    if window is None and anchor is None:
        point = _plain_day(status, calendar)
        if point is not None and "unreadable_date" not in notes:
            return _dated_result(
                status, (point,), status[_STRENGTH], True, False, narrowed, notes, ordered, weather,
                offices_open,
            )  # fmt: skip
        frame = _PLAIN_FRAME
    elif window is not None and not status[_GROUPS] and not hints:
        # A status that names no day, and no side note that names one: the posting time's
        # school day (see _frame and _status_days), when it gives a weekday.
        day = calendar.undated_day(*window)
        if day is not None and day.weekday() < _SATURDAY and "unreadable_date" not in notes:
            ceiling = JUDGMENT if calendar.near_cutoff(*window) else INFERRED
            return _dated_result(
                status, (day,), min(status[_STRENGTH], ceiling), False, False, narrowed, notes,
                ordered, weather, offices_open,
            )  # fmt: skip
        frame = _frame(analysis, calendar)
    else:
        frame = _frame(analysis, calendar)
    added: set[Note] = set()
    resolved = _status_days(status, calendar, frame, added)
    if added and not added <= notes:
        notes = notes | added
        ordered = tuple(sorted(notes))
    if resolved is None or "unreadable_date" in notes:
        return _unstated(analysis, notes, ordered)
    days = resolved[_DAYS_DAYS]
    dates = (next(iter(days)),) if len(days) == 1 else tuple(sorted(days))
    return _dated_result(
        status, dates, resolved[_DAYS_CONFIDENCE], resolved[_DAYS_STATED],
        resolved[_DAYS_UNTIL_NOTICE], narrowed, notes, ordered, weather, offices_open,
    )  # fmt: skip


def _dated_result(  # noqa: PLR0913, PLR0917 - the status, its days, and the text's fields
    status: _Status,
    dates: tuple[date, ...],
    confidence: float,
    stated: bool,
    until_notice: bool,
    narrowed: bool,
    notes: frozenset[Note],
    ordered: tuple[Note, ...],
    weather: _WeatherFields,
    offices_open: bool,
) -> ParsedStatus:
    """The result of a text with one status that stands, for its days (see _single_result).

    ``notes`` and ``ordered`` are the text's notes with what resolving the days
    added, when it added any; ``narrowed``, ``weather`` and ``offices_open`` are
    the analysis's (see :class:`_Analysis`). The arguments are positional, as
    this is called once per parse.
    """
    if narrowed or not _PARTIAL_NOTES.isdisjoint(notes):
        confidence = min(confidence, JUDGMENT)  # (see parse_status)
    (
        kind, _position, _strength, delay, opens, dismissal, early, _superseding, _superseded,
        _groups, _floating, _revoked, _led,
    ) = status  # fmt: skip
    terms, names_weather, reason, reasons, other_causes = weather
    entry = _new(DatedStatus, (kind, dates, delay, opens, dismissal, early, stated, until_notice))
    return _new(
        ParsedStatus,
        (
            kind, dates, delay, opens, dismissal, early, stated, until_notice, (entry,), terms,
            names_weather, reason, reasons, other_causes, min(confidence, CERTAIN), False,
            offices_open, ordered,
        ),
    )  # fmt: skip


def _plain_day(status: _Status, calendar: Calendar) -> date | None:  # noqa: PLR0911 - one per form
    """The one school day a status names plainly, resolved directly; ``None`` for any other.

    A lone weekday name ("Closed Wednesday"), a word for a nearby day ("Closed
    today") or a date ("Closed Jan. 21"), with nothing :meth:`Calendar.resolve`
    would flag: no day number beside a weekday or a nearby day, no "next", no
    evening, no "tomorrow" posted overnight, and no date that does not exist or
    that its weekday disagrees with. A weekend day is left to
    :func:`_status_days`, which notes it.
    """
    groups = status[_GROUPS]
    if len(groups) != 1:
        return None
    _start, _end, atoms, _links, open_start = groups[0]
    if len(atoms) != 1 or open_start is not None:
        return None
    (
        _start, _end, kind, weekday, month, day, year, offset, modifier, _rest, _inner, _named,
        evening,
    ) = atoms[0]  # fmt: skip
    if evening or modifier is not None:
        return None
    if kind == "explicit":
        found = calendar.explicit(month, day or 0, year)
        if found is None or (weekday is not None and weekday != found.weekday()):
            return None
        point = found
    elif day is not None:
        return None
    elif kind == "weekday":
        if weekday is None:
            return None
        point = calendar.weekday(weekday, None)
    elif kind == "relative":
        if offset == 1 and calendar.overnight:
            return None
        point = calendar.relative(offset)
    else:
        return None
    return point if point.weekday() < _SATURDAY else None


# Names ---------------------------------------------------------------------------------
#
# "Closed - Lincoln Maple Elementary" and "Closed - Oak Ridge Elementary" say the same: the
# names are words no rule reads. Collapsing such words to one placeholder at the start and
# the end of the text lets listings that differ only in names share one analysis, which is
# the costly part of parsing. The words replaced have no role anywhere in the parser: no
# rule, date, weather or scope reads them, no list holds them and no pattern starts with
# them. At the start and the end they are collapsed only up to a punctuation mark that
# parts them from the rest, so no pattern reaches across; the collapsed words keep their
# place in the order of words, and a number read after them at the end keeps its place in
# the text too, as a window that looks back from it ("returning" before a day) would
# otherwise reach other words. Inside the text a run of such words that begins right after
# a mark is masked letter for letter ("Closed; Maple Bus Garage open"), so every place and
# every count of words stays as it was.

_CANONICAL = True
_PLACEHOLDER = "qq"  # (a word of the mask: see _masked)
# Words kept as they are inside a name: the nouns that end school names.
_INSTITUTION_WORDS = frozenset(
    {
        "school", "schools", "elementary", "middle", "high", "junior", "senior", "academy",
        "district", "districts", "public", "community", "preschool", "center", "centre",
        "montessori", "primary", "intermediate", "secondary", "campus", "institute", "college",
        "prep", "preparatory", "christian", "catholic", "lutheran", "baptist", "county",
        "charter", "isd", "usd", "cusd", "unified", "consolidated", "regional", "parish",
        "township", "magnet", "leadership", "stem", "arts",
    }
)  # fmt: skip
# Substrings that some check reads straight off the text ("grade" near an ordinal) or that
# open a scan ("hour", "noon"): a word holding one is not replaced.
_GATE_WORDS = (
    "grade", "hour", "hr", "min", "noon", "midday", "early", "power", "blackout", "thr", "til",
    "night", "nite",
)  # fmt: skip
_GATES = re.compile(trie(sorted(_GATE_WORDS)), re.ASCII)  # (a trie: see text.one_of)
_ESCAPE = re.compile(r"\\[a-zA-Z]")
_LETTERS = re.compile(r"[a-z]+")
_OPTIONAL_LETTER = re.compile(r"[a-z]\?")


def _strings(value: object) -> Iterator[str]:
    """Every string in a module-level value: word lists, tables, pattern sources."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, re.Pattern):
        yield value.pattern
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, frozenset | set | tuple | list):
        for item in value:
            yield from _strings(item)


def _vocabulary() -> frozenset[str]:
    """Every word run in every list, table and pattern of the parser's modules."""
    found: set[str] = set()
    modules = (
        lexicon_module,
        dates_module,
        dayparts_module,
        mentions_module,
        partial_module,
        revoke_module,
        subjects_module,
        weather_module,
        text_module,
    )
    for module in (*modules, globals()):
        names = module if isinstance(module, dict) else vars(module)
        for name, value in names.items():
            if name.startswith("__") or name in {"_PLACEHOLDER", "_MASK"}:
                continue  # docstrings are prose; the placeholder must stay a name
            for string in _strings(value):
                plain = _ESCAPE.sub(" ", string.lower())
                found.update(_LETTERS.findall(plain))
                # "bags?" reads "bag" too: each word also without a letter a "?" follows
                found.update(_LETTERS.findall(_OPTIONAL_LETTER.sub(" ", plain)))
    return frozenset(found)


_VOCABULARY = _vocabulary()
_SHORTEST_RUN = 3
# Any word that starts with a run of three or more letters some list or pattern holds.
_VOCABULARY_START = re.compile(
    trie(sorted(word for word in _VOCABULARY if len(word) >= _SHORTEST_RUN)), re.ASCII
)
# Where anything the parser reads can start in a word of letters outside the vocabulary: a
# prefix a rule, a date scan or a weather scan starts with, at the word's start, or a part of
# a word some rule needs, or one of _GATES, anywhere in it. (A word the lists hold whole is
# in the vocabulary.) The parts are one trie, which the regex engine searches quickly (see
# text.one_of).
_TRIGGER_START = re.compile(
    "|".join(
        (
            "(?:" + _VOCABULARY_START.pattern + ")",
            "(?:"
            + trie(
                sorted(
                    {
                        *(prefix for group in mentions_module.PREFIX_STARTS for prefix in group),
                        *dates_module.SURE_STARTS,
                        *weather_module.START_PREFIXES,
                        "twenty",
                        "thirty",
                    }
                )
            )
            + ")",
            "(?:" + dates_module.DATE_STARTS.pattern + ")",
            "(?:" + weather_module.ANY_START.pattern + ")",
        )
    ),
    re.ASCII,
).match
_TRIGGER_PART = re.compile(
    trie(sorted({*mentions_module.PART_KEYS, *_GATE_WORDS})), re.ASCII
).search


def _plain_name(token: str) -> bool:
    """Whether ``token`` is a word of letters that nothing in the parser reads, such as a name.

    Then :func:`_facts` finds nothing in it and :func:`_role` makes it a name,
    read here without the scans: it is outside the vocabulary, no rule, date or
    weather scan can start in it or needs a part of it (see :data:`_TRIGGER_START`),
    and it is no day name misspelt.
    """
    return (
        len(token) >= 2  # noqa: PLR2004 - single letters are day letters and units
        and token.isascii()
        and token.isalpha()
        and token not in _VOCABULARY
        and _TRIGGER_START(token) is None
        and _TRIGGER_PART(token) is None
        and not daylike_word(token)
    )


def _role_free(token: str) -> bool:
    """Whether ``token`` is a word with no role anywhere in the parser, such as a name."""
    # (Every word of every list is in the vocabulary, so for a word outside it only what
    # the rules, the date scans and the weather scans make of it can give it bits in
    # _word_bits: those are checked last, being the costly part.)
    return (
        len(token) >= 2  # noqa: PLR2004 - single letters are day letters and units
        and token.isascii()
        and token.isalpha()
        and token not in _VOCABULARY
        and _GATES.search(token) is None
        and _VOCABULARY_START.match(token) is None
        and not _word_bits(token) & _HINTED  # (no rule, date or weather hint)
    )


# The endings of a word the gate or the subjects read apart from a name by its spelling (see
# _role).
_SPELLED_APART = ("ly", "ed")


@lru_cache(maxsize=65536)
def _role(token: str) -> str:
    """How a word takes part in a name: replaced ("n"), kept ("k"), a number ("d"), or not.

    A word the precision gate reads (see classify.gate.word_class: "BPS", "dorm",
    "activites") is never replaced: texts that differ in it read apart. Nor is one the gate
    reads apart by its spelling where a name stands: one ending in "ly", which may be an
    adverb ("Holly - No school" against "Kubaze - No school": see gate.unread_sentence), or in
    "ed", which may be a past participle (see subjects._changed_to). A text's analysis is
    shared only by texts it reads the same as, so none depends on what was parsed before.
    """
    if token in _INSTITUTION_WORDS:
        return "k"
    if token.isdigit():
        return "d"
    if token.endswith(_SPELLED_APART):
        return ""
    if _plain_name(token):
        return "" if word_class(token) or not_name(token) else "n"
    return "n" if _role_free(token) and not word_class(token) and not not_name(token) else ""


def canonical(normalized: str, chunks: list[str] | None = None) -> str:
    """Collapse the name words at the start and the end of a normalized text, and mask the rest.

    Each run of name words (words no part of the parser reads) at the start or
    the end becomes one placeholder word; school nouns stay, and so does a
    number unless it stands clear of the rest of the text. The start and the
    end count only up to a mark that ends a phrase: "Closed - Bakutemi Zorafa
    Elementary" becomes "closed - qq elementary", and "Oak Ridge Elementary: 2
    hour delay" becomes "qq elementary: 2 hour delay". Every other name word
    is masked, each with a placeholder of its own length, so every place in the
    text stays where it was: "Closed; Maple Bus Garage open" becomes "closed;
    qqqqq bus garage open", and "All Maple schools closed" "all qqqqq schools
    closed". A text parses the same either way.

    The words, their places and their roles are read per stretch between spaces
    (see :class:`_RoleTable`): no pass over the whole text is made for them. ``chunks``
    are those stretches (``normalized.split(" ")``), when the caller has them.
    """
    if chunks is None:
        chunks = normalized.split(" ")
    records = list(map(_chunk_roles, chunks))
    if _named_edge(records):
        collapsed = _collapsed_edges(normalized, chunks, records)
        if collapsed is not normalized:
            normalized = collapsed
            chunks = normalized.split(" ")
            records = list(map(_chunk_roles, chunks))
    if any(map(_UNMASKED_NAME, records)):
        return _masked(normalized, chunks, records)
    return normalized


# A word of a stretch between spaces: where it starts and ends in the stretch, and its role.
type _Placed = tuple[int, int, str]
# What a stretch between spaces is to the names: its words (see _Placed), whether one of them
# is a name word not masked yet, and whether one of them is a name word at all.
type _RoleRecord = tuple[tuple[_Placed, ...], bool, bool]


class _RoleTable(dict[str, _RoleRecord]):
    """The words of each stretch between spaces with their :func:`_role`, worked out once."""

    def __missing__(self, chunk: str) -> _RoleRecord:
        record: _RoleRecord
        if chunk.isascii() and chunk.isalnum():  # one word, the most common stretch
            role = _role(chunk)
            # (A word of the mask alone, such as the placeholder, is masked already.)
            name = role == "n"
            record = (((0, len(chunk), role),), name and bool(chunk.strip(_MASK)), name)
        elif (core := _word_before_marks(chunk)) is not None:
            record = self[core]  # the word and a mark after it: "closed,", the same word
        else:
            placed = tuple(
                (match.start(), match.end(), _role(match.group()))
                for match in _WORD.finditer(chunk)
            )
            named = any(role == "n" and chunk[low:high].strip(_MASK) for low, high, role in placed)
            record = (placed, named, any(role == "n" for _low, _high, role in placed))
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the record is the same when worked out again
        self[chunk] = record
        return record


_MASK = "q"
_CHUNK_ROLES = _RoleTable()
_chunk_roles = _CHUNK_ROLES.__getitem__
_UNMASKED_NAME = itemgetter(1)  # (of a _RoleRecord: whether a name word is not masked yet)


def _named_edge(records: list[_RoleRecord]) -> bool:
    """Whether the first or the last word could be part of a name (a quick look at the ends).

    The first word is the text's first; the last is the last word of the last
    stretch between spaces, which must hold one. A number at the end counts
    when the word before it, in the last two stretches, has a role in a name.
    ``records`` are the text's stretches between spaces (see :class:`_RoleTable`).
    """
    for placed, _named, _any in records:
        if placed:
            if placed[0][2] in _NAMED:
                return True
            break
    tail = records[-1][0]
    if not tail:
        return False
    if tail[-1][2] != "d":
        return tail[-1][2] in _NAMED
    if len(tail) > 1:
        return bool(tail[-2][2])  # the word before the number, in its stretch, has a role
    if len(records) < 2:  # noqa: PLR2004 - the last stretch and the one before it
        return False
    before = records[-2][0]
    return bool(before) and bool(before[-1][2])


def _collapsed_edges(  # noqa: PLR0912 - one walk in from each end, then the checks
    normalized: str, chunks: list[str], records: list[_RoleRecord]
) -> str:
    """The text with its name words at the start and the end collapsed (see :func:`canonical`).

    Only the words at the two ends are read: those at the start up to the first
    with no role in a name, and those at the end back to the last such word.
    Returns ``normalized`` itself when nothing changes.
    """
    head: list[_Placed] = []  # the words at the start, and the first with no role
    position = 0
    for chunk, (placed, _named, _any) in zip(chunks, records, strict=True):
        for low, high, role in placed:
            head.append((position + low, position + high, role))
            if not role:
                break
        else:
            position += len(chunk) + 1
            continue
        break
    else:
        return normalized  # names only, or no words: nothing else to read
    tail: list[_Placed] = []  # the last word with no role, and the words after it
    position = len(normalized)
    for chunk, (placed, _named, _any) in zip(reversed(chunks), reversed(records), strict=True):
        position -= len(chunk)
        for low, high, role in reversed(placed):
            tail.append((position + low, position + high, role))
            if not role:
                break
        else:
            position -= 1
            continue
        break
    tail.reverse()
    lead = len(head) - 1
    # (A list's "in" costs less than any() over a generator.)
    if "n" not in [role for _low, _high, role in head[:lead]] and "n" not in [
        role for _low, _high, role in tail[1:]
    ]:
        return normalized
    while lead > 0 and not _parted(normalized, head[lead - 1][1], head[lead][0]):
        lead -= 1
    trail = 1  # (the first word of the end, in ``tail``)
    while trail < len(tail) and not _parted(normalized, tail[trail - 1][1], tail[trail][0]):
        trail += 1
    if "n" not in [role for _low, _high, role in head[:lead]] and "n" not in [
        role for _low, _high, role in tail[trail:]
    ]:
        return normalized
    return _collapsed(normalized, head, lead, tail, trail)


def _masked(text: str, chunks: list[str], records: list[_RoleRecord]) -> str:
    """The text with each name word left after the ends are collapsed masked (see canonical).

    No rule, date or weather scan reads a name word, nor a list holds one (see
    :func:`_role`), so a placeholder of the same length reads as the word did, and
    leaves every place, and every count of words, as it was. ``chunks`` and ``records``
    are the text's stretches between spaces (see :class:`_RoleTable`).
    """
    pieces: list[str] = []
    last = 0
    position = 0
    for chunk, (placed, unmasked, _has_name) in zip(chunks, records, strict=True):
        if unmasked:
            for low, high, role in placed:
                if role == "n":
                    start = position + low
                    pieces += (text[last:start], _MASK * (high - low))
                    last = position + high
        position += len(chunk) + 1
    if not pieces:
        return text
    pieces.append(text[last:])
    return "".join(pieces)


def _collapsed(  # noqa: PLR0912 - one pass over each end, with one branch per role
    text: str, head: list[_Placed], lead: int, tail: list[_Placed], trail: int
) -> str:
    """The text with the name words of ``head[:lead]`` and ``tail[trail:]`` collapsed.

    ``head`` holds the words at the start and the word after ``lead``; ``tail``
    the word before ``trail`` and the words to the end (see :func:`_collapsed_edges`).
    """
    pieces: list[str] = []
    position = 0
    after_name = False
    # A number read as it is after names at the end ("Oak Ridge 1.21") keeps its place, as
    # a window looking back from it (a day after "returning") would reach other words.
    held = _last_held_number(text, tail, trail)
    for index in range(lead):
        start, end, role = head[index]
        if held >= 0:  # (every word at the start comes before a number held at the end)
            if role == "n":
                pieces += (text[position:start], _MASK * (end - start))
                position = end
            continue
        if role == "n":
            gap = text[position:start]
            if not (after_name and gap == " "):  # one placeholder for a run of names
                pieces += (gap, _PLACEHOLDER)
            after_name = True
            position = end
        elif role == "d" and _loose_at_start(text, head, index, lead):
            pieces += (text[position:start], _loose_number(text, start, end))
            after_name = False
            position = end
        else:
            after_name = False
    for index in range(trail, len(tail)):
        start, end, role = tail[index]
        if index < held:
            if role == "n":
                pieces += (text[position:start], _MASK * (end - start))
                position = end
            continue
        if role == "n":
            gap = text[position:start]
            if not (after_name and gap == " "):
                pieces += (gap, _PLACEHOLDER)
            after_name = True
            position = end
        elif role == "d" and _loose_at_end(text, tail, index, trail):
            pieces += (text[position:start], _loose_number(text, start, end))
            after_name = False
            position = end
        else:
            after_name = False
    pieces.append(text[position:])
    return "".join(pieces)


# A year, which the date scans read as a day the parser cannot place ("closed in 2019").
_YEAR = re.compile(r"(?:19|20)\d\d", re.ASCII)


def _loose_number(text: str, start: int, end: int) -> str:
    """What a number standing clear in a name collapses to: one of the same kind to the date
    scans, a day number ("1"), a year ("2000") or another number ("111")."""
    if end - start <= 2:  # noqa: PLR2004 - a day of the month's width
        return "1"
    return "2000" if _YEAR.fullmatch(text, start, end) is not None else "111"


def _last_held_number(text: str, tail: list[_Placed], trail: int) -> int:
    """The index in ``tail`` of the last number at the end that stays as it is, or -1."""
    for index in range(len(tail) - 1, trail - 1, -1):
        if tail[index][2] == "d" and not _loose_at_end(text, tail, index, trail):
            return index
    return -1


class _TokenTable(dict[str, tuple[str, ...]]):
    """The words of each stretch of text between spaces, found the first time it is looked up."""

    def __missing__(self, chunk: str) -> tuple[str, ...]:
        tokens = tuple(_WORD.findall(chunk))
        if len(self) >= _MOST_CHUNKS:
            self.clear()  # a bound on memory; the words are the same when found again
        self[chunk] = tokens
        return tokens


_CHUNK_TOKENS = _TokenTable()
_chunk_tokens = _CHUNK_TOKENS.__getitem__
_NAMED = frozenset({"n", "k"})
# A mark that ends a phrase: a comma, a semicolon, a bar, a spaced dash, a colon or a full
# stop before a space. "1.21" and "10:00" are one date and one time, not two phrases.
# ("[,;|!?]|[.:](?=\s)|(?:^|\s)-+(?=\s|$)", with each branch opening with a character of its
# own: see text.one_of.)
_PARTING = re.compile(one_of(",;|!?") + rf"|\.(?=\s)|:(?=\s)|{DASH_RUN}", re.ASCII)


def _parted(text: str, start: int, end: int) -> bool:
    """Whether a mark that ends a phrase stands between two words."""
    return _PARTING.search(text, start, end) is not None


def _loose_at_start(text: str, head: list[_Placed], index: int, lead: int) -> bool:
    """Whether a number in the name at the start stands clear: "Elementary #12: closed".

    Each neighbour is a word of the name with a plain space between, or the
    text's start. The name's last word may also meet the rest at a comma, a
    colon, a semicolon, a bar or a full stop, but not at a dash, which can join
    numbers ("12 - 14", "2 - hour"). ``head`` holds the words at the start and
    the one after ``lead``.
    """
    start, end = head[index][0], head[index][1]
    if index > 0:
        if text[head[index - 1][1] : start] != " ":
            return False
    elif text[:start].strip():
        return False
    gap = text[end : head[index + 1][0]]
    if index + 1 < lead:
        return gap == " "
    return index == lead - 1 and _HARD_PART.fullmatch(gap) is not None


def _loose_at_end(text: str, tail: list[_Placed], index: int, trail: int) -> bool:
    """Whether a number in the name at the end stands clear: "Closed - Elementary #12", not
    "1.21" or "10:00". Each neighbour is a word of the name with a plain space between, or
    the text's end; the first word of the name at the end never is. ``tail`` holds the word
    before ``trail`` and the words to the end."""
    start, end = tail[index][0], tail[index][1]
    if index == trail or text[tail[index - 1][1] : start] != " ":
        return False
    if index + 1 == len(tail):
        return not text[end:].strip()
    return text[end : tail[index + 1][0]] == " "


# The marks that part a name at the start from the rest when its last word is a number.
_HARD_PART = re.compile(r"\s*(?:[,;:|]|\.(?=\s))\s*", re.ASCII)


# The bits of _word_bits and _facts that come from word lists, for every word the lists hold
# (see _word_list_bits and _run_list_bits): a word no list holds has none of them.
_WORD_LIST_BITS: dict[str, int] = {
    word: bits
    for word in chain(
        NEGATIONS,
        HEDGES,
        HEDGES_AFTER,
        SUPERSEDING,
        SUPERSEDED,
        SUPERSEDING_WITH,
        ("instead", "rather"),
        _QUALIFYING_WORDS,
        _SCOPE_WORDS,
        MODIFIERS,
        _SOME_OF,
        _COUNT_WORDS,
        _DATE_HEDGES,
        _CONDITION_WORDS,
        _HEDGE_CLAUSE_TRIGGERS,
        MAKE_UP_WORDS,
        CARVE_WORDS,
    )
    if (bits := _word_list_bits(word))
}
_RUN_LIST_BITS: dict[str, int] = {
    run: bits
    for run in chain(
        _ANSWER_RUNS, _NOUN_RUNS, NAME_KINDS, REGION_STOPS, INSTITUTION_NOUNS, _PART_RUNS
    )
    if (bits := _run_list_bits(run))
}


def _forget_words() -> None:
    """Empty every cache and table kept by word or by stretch of text, and the text caches.

    For benchmarks and tests that must see every word for the first time; the
    results are the same either way.
    """
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    for cache in (
        _word_bits, _facts, _role, date_start_hint, date_hints,
        dates_module.daylike_word, mentions_module.start_mask, mentions_module.rule_mask,
        weather_start_hint, weather_hints, text_module.duration_minutes, text_module.clock_time,
    ):  # fmt: skip
        cache.cache_clear()
    gate_module.forget_words()
    for table in (
        _CHUNK_FACTS, _CHUNK_SPANS, _CHUNK_ROLES, _CHUNK_TOKENS, _LABEL_SCOPES, _WINDOW_SCOPES,
        _TRIGGERED, _WORDED, _READ_STRETCHES, _AS_WRITTEN, text_module._SPAN_WORDS,
    ):  # fmt: skip
        table.clear()
