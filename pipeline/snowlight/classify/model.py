"""The result of :func:`snowlight.classify.parse_status`.

Everything here is immutable: the records are named tuples, which are cheap to
build (the parser makes one per listing, tens of thousands a run) and cannot be
changed once made. A :class:`ParsedStatus` describes one listing: the
status it states for its first applicable day (``kind``, ``dates`` and the
detail fields), every dated status the text states (``schedule``), the weather
it names, and how sure the parser is.

``confidence`` is a number in ``[0, 1]`` taken from a small fixed scale (see
:data:`CONFIDENCE_LEVELS`), not a probability fitted to data:

* ``0.95``: an explicit status phrase with explicit dates;
* ``0.9``: an explicit status whose day was inferred from the posting time, or a
  listing that clearly states no disruption (activities cancelled, an evening
  closure such as "closed tonight", "closed after 5 PM" or "closing early at
  5:00 PM", offices open, open on time, a weekly schedule, a status called off
  such as "2 hour delay cancelled", a status denied such as "no school
  closures" or "closure not expected", an update to open such as "Closed.
  Update: open.", a program on a weekend day such as "Saturday school
  cancelled", a status for only part of the district such as "All schools
  closed except Lincoln Elementary", "Closed (Lincoln Elementary only)",
  "Closed at some locations", "North campus closed", "Three schools closed",
  "No school for K-5", or a school named open or on another status beside
  the district's ("Closed. Lincoln Elementary open."), note
  ``partial_program``; every status past and the posting day open, such as
  "Closed yesterday. Open today.", note ``superseded`` with ``says_open``);
* ``0.8``: a judgment call: posted close to the cut-off, an overnight
  "tomorrow", a replaced status ("changed to closed", "2 hour delay is now a
  closing", "delay - now 3 hours"), a weaker phrase ("half
  day", a dismissal time with no "early"), part of the program having a status
  of its own, another status in the text left out for an unclear day ("Closed.
  2 hour delay tomorrow."), two day words that disagree elsewhere in the text,
  a day named after the cause ("closed due to snow Wednesday"), words beside
  the status that could not be placed ("No in-person classes; remote learning"),
  a closure for the afternoon with no time given ("closed this afternoon",
  an early dismissal), or a closing at a time that runs over several days
  ("closing at 1 PM today through Friday": an early dismissal on the first
  day, the days after it left out), the days a closure keeps after the text
  says school is open, or may reopen, on another of its days ("Closed Thursday
  and Friday. Open Friday.", "Closed Wednesday through Friday, may reopen
  Friday": Friday is left out), a status beside a status word about
  something else ("Closed today. Payroll delayed.", note ``ambiguous``), a
  delay whose length and opening time disagree ("2 hour delay, opening at
  7:30", the opening time left out), or a
  listing too long to read whole (note ``truncated``: its start and its end
  are read, its middle is not);
* ``0.7``: a status only for a Saturday or Sunday, or a conflict on another day;
* ``0.5``: an impossible date beside a good one (the date given wins);
* ``0.3``: hedged ("possible", "if", a question, "delay may be lifted", a
  decision still to come such as "Closed tomorrow. Decision at 5 AM.",
  "closure unlikely"), ambiguous ("cancelled", "inclement weather day", a
  closing time when many schools let out anyway such as "closing at 3:00 PM",
  an early dismissal before any school day could end such as "early dismissal
  7:00", "Cancelled: 2 hour delay", which could call the delay off or close
  the school, a closure for the morning with no opening time such as "closed
  tomorrow morning", hours that cannot be placed such as "closed from 8 to
  noon", "no school/closings", a day to be made up such as "snow day make-up
  day", a status changed into one that cannot be read, is unclear or is only
  possible such as "2 hour delay has been changed", "2 hour delay is now a full
  day" or "2 hour delay. Update: possible closure", a status word about
  something besides the school's day such as "Payroll delayed", "Graduation
  delayed", "School pictures cancelled", "Lightning delay" or "Lincoln
  delayed", where the name is not known for a school's, a delay of the end of
  the day such as "Dismissal delayed" or "Delayed dismissal due to severe
  weather", classes held in person called off such as "In-person classes
  cancelled", a closure for good such as "Closed permanently" or "Closed for
  renovation"), only impossible dates, a
  day named in a form the parser cannot read ("the 21st", "next week", "2
  weeks"), weekday names that were a day or two before the posting day
  ("Closed Monday" seen on a Wednesday: the Monday just past, or the next; a
  list that runs to the posting day, "Closed Tuesday and Wednesday" seen on a
  Wednesday, is yesterday and today, and stands), a list of days followed by
  words that could take its last days ("Closed today, tomorrow and Friday
  open", "Closed today, Thursday and Friday 2 hour delay", "NTI today,
  Thursday and Friday closed", note ``ambiguous``), a status whose only day
  a "not" denies ("No school not Monday"), a
  year or a span of years or terms ("Closed in 2019", "closed last year",
  "Closed for the summer"),
  an exception for a day ("Closed all week except Wednesday"), a listing too
  long to read whole that states no status in the parts read,
  two names for a day that disagree ("tomorrow (Friday)", "Sunday: Closed
  Monday", "tomorrow, Jan. 22" posted on Jan. 20, "Thursday 1/23" when 1/23 is
  a Friday: either could be the day meant), or no
  day named and a posting time that cannot tell which day: one that fits
  today and tomorrow alike, one days before the next school day (a Friday
  evening or a Saturday), or one that disagrees with a day named for a side
  note ("Closed; offices open Monday"); ``kind`` is ``other``;
* ``0.25``: two statuses conflict for the day, a status the text also calls
  off ("Closure cancelled. Closed."), or a closure on a day the text also says
  school is open, with no word that says which came last ("Open tomorrow.
  Closed tomorrow.", "Closed tomorrow. Open tomorrow."), or a status beside a
  statement that school is held or open on its day ("Closed tomorrow, classes
  will be held", "Closed today. Classes on time."); ``kind`` is ``other``;
* ``0.1``: nothing recognized; ``0.0``: empty text.
"""

from datetime import date, time
from typing import Literal, NamedTuple

type Kind = Literal["closed", "delayed", "remote", "early_dismissal", "other"]
type StatusKind = Literal["closed", "delayed", "remote", "early_dismissal"]
type Reason = Literal[
    "Winter storm",
    "Ice",
    "Extreme cold",
    "Flooding",
    "Hurricane",
    "Power outage",
    "Heat",
    "Severe storms",
]
type Note = Literal[
    "activities_cancelled",
    "ambiguous",
    "childcare",
    "conflict",
    "date_mismatch",
    "hedged",
    "invalid_date",
    "negated",
    "offices_closed",
    "overnight",
    "partial_program",
    "recurring",
    "revoked",
    "staff",
    "superseded",
    "transportation",
    "truncated",
    "undated",
    "unreadable_date",
    "unread_words",
    "unrecognized",
    "weekend",
]

KINDS: tuple[Kind, ...] = ("closed", "delayed", "remote", "early_dismissal", "other")
STATUS_KINDS: tuple[StatusKind, ...] = ("closed", "delayed", "remote", "early_dismissal")
# In priority order: when a text names several, ``reason`` is the first listed here.
REASONS: tuple[Reason, ...] = (
    "Hurricane",
    "Winter storm",
    "Ice",
    "Extreme cold",
    "Flooding",
    "Severe storms",
    "Heat",
    "Power outage",
)

CERTAIN = 0.95
INFERRED = 0.9
JUDGMENT = 0.8
WEAK = 0.7
UNSURE = 0.5
HEDGED = 0.3
CONFLICTING = 0.25
UNKNOWN = 0.1
EMPTY = 0.0
CONFIDENCE_LEVELS: tuple[float, ...] = (
    CERTAIN,
    INFERRED,
    JUDGMENT,
    WEAK,
    UNSURE,
    HEDGED,
    CONFLICTING,
    UNKNOWN,
    EMPTY,
)


def _clock(value: time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M")


class DatedStatus(NamedTuple):
    """One status the text states, with the local dates it applies to.

    ``delay_minutes`` and ``opens_at`` describe a late start, ``dismissal_time``
    and ``dismissal_early_minutes`` an early dismissal. Each is set only when the
    text gives exactly one value for it. Times are local wall-clock times in the
    school's time zone. ``dates_stated`` is false when the text named no day and
    the dates come from the posting time.
    """

    kind: StatusKind
    dates: tuple[date, ...]
    delay_minutes: int | None = None
    opens_at: time | None = None
    dismissal_time: time | None = None
    dismissal_early_minutes: int | None = None
    dates_stated: bool = True
    until_further_notice: bool = False

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready dict (ISO dates, ``HH:MM`` times)."""
        return {
            "kind": self.kind,
            "dates": [day.isoformat() for day in self.dates],
            "delay_minutes": self.delay_minutes,
            "opens_at": _clock(self.opens_at),
            "dismissal_time": _clock(self.dismissal_time),
            "dismissal_early_minutes": self.dismissal_early_minutes,
            "dates_stated": self.dates_stated,
            "until_further_notice": self.until_further_notice,
        }


class ParsedStatus(NamedTuple):
    """What one closings listing says.

    ``kind`` and the fields after it up to ``until_further_notice`` repeat the
    primary entry of ``schedule``: the first one that covers the posting day or
    a later day (or, when every entry is in the past, the latest one). When the
    text states no usable status, ``kind`` is ``other``, ``dates`` is empty and
    ``schedule`` is empty.

    ``weather_terms`` lists the weather the text names, in order of first
    mention; ``names_weather`` is true when there is at least one. ``reasons``
    are the display labels those terms support and ``reason`` is the first of
    them in :data:`REASONS` order; both are empty when the text names no
    specific hazard. ``other_causes`` lists causes named in the text that are not
    weather (a water main break, a holiday). ``says_open`` is true only when the
    text affirmatively says school runs as normal and states no disruption.
    """

    kind: Kind
    dates: tuple[date, ...]
    delay_minutes: int | None
    opens_at: time | None
    dismissal_time: time | None
    dismissal_early_minutes: int | None
    dates_stated: bool
    until_further_notice: bool
    schedule: tuple[DatedStatus, ...]
    weather_terms: tuple[str, ...]
    names_weather: bool
    reason: Reason | None
    reasons: tuple[Reason, ...]
    other_causes: tuple[str, ...]
    confidence: float
    says_open: bool
    offices_open: bool
    notes: tuple[Note, ...]

    def on(self, day: date) -> DatedStatus | None:
        """Return the status the text states for local date ``day``, if any."""
        for entry in self.schedule:
            if day in entry.dates:
                return entry
        return None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready dict (ISO dates, ``HH:MM`` times)."""
        return {
            "kind": self.kind,
            "dates": [day.isoformat() for day in self.dates],
            "delay_minutes": self.delay_minutes,
            "opens_at": _clock(self.opens_at),
            "dismissal_time": _clock(self.dismissal_time),
            "dismissal_early_minutes": self.dismissal_early_minutes,
            "dates_stated": self.dates_stated,
            "until_further_notice": self.until_further_notice,
            "schedule": [entry.as_dict() for entry in self.schedule],
            "weather_terms": list(self.weather_terms),
            "names_weather": self.names_weather,
            "reason": self.reason,
            "reasons": list(self.reasons),
            "other_causes": list(self.other_causes),
            "confidence": self.confidence,
            "says_open": self.says_open,
            "offices_open": self.offices_open,
            "notes": list(self.notes),
        }
