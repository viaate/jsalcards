"""Word lists: who a status is about, and the words that qualify a status.

A listing often mixes the school's status with news about other things: "offices
open", "staff report at 10", "all activities cancelled", "no AM kindergarten",
"buses on snow routes". :data:`SCOPES` maps the nouns that name those things
(one word, or two words joined by a space) to a :data:`Scope`; ``school`` means
the listing's school itself. The parser looks for the noun nearest to a status
word to decide what the status is about.
"""

from typing import Literal

type Scope = Literal[
    "school", "staff", "office", "activities", "partial", "childcare", "transportation"
]

_SCHOOL = (
    "school schools class classes student students campus campuses building buildings "
    "district districts instruction facilities k-12 pk-12 k12"
)
_STAFF = (
    "staff employees employee teachers teacher faculty personnel administrators custodians "
    "paraprofessionals paras 12-month 11-month 10-month"
)
_OFFICE = "office offices administration admin headquarters"
_ACTIVITIES = (
    "activity activities athletics athletic sports sport practice practices game games event "
    "events extracurricular extracurriculars club clubs rehearsal rehearsals meeting meetings "
    "conference conferences trip trips program programs performance performances concert "
    "concerts dance dances tournament tournaments competition competitions scrimmage "
    "scrimmages tryouts match matches contest contests banquet ceremony social socials "
    "fundraiser party parties assembly assemblies celebration festival fair carnival "
    "gym public adult ged after-school afterschool visitor visitors "
    "guest guests spectator spectators volunteer volunteers registration enrollment enrolment "
    # Events a listing can say are held some way: "virtual tour", "remote orientation".
    "tour tours orientation orientations webinar webinars workshop workshops forum forums"
)
# Places and services a listing reports on besides school itself: "Cafeteria closed",
# "Stadium closed", "Fields closed". Each can also name a school ("Stadium Drive
# Elementary"), so a school's name in a label may hold them.
_FACILITIES = (
    "library pool community cafeteria cafeterias kitchen kitchens playground playgrounds "
    "parking stadium stadiums gymnasium gymnasiums gyms auditorium auditoriums fieldhouse "
    "natatorium arena rink concessions fields courts bookstore museum planetarium clinic "
    "pantry dorm dorms dormitory dormitories trails fairgrounds courthouse"
)
FACILITY_NOUNS = frozenset(_FACILITIES.split())
"""Single nouns for places a listing reports on besides school itself (see :data:`SCOPES`)."""
_PARTIAL = (
    "kindergarten kindergarteners kindergartners pre-k prek pre-kindergarten prekindergarten "
    "preschool pre-school ece headstart boces vo-tech votech vocational cte nursery 4k 3k tk pk "
    "k elementary secondary grades grade graders grader lunch breakfast seniors juniors "
    "sophomores freshmen upperclassmen underclassmen "
    # The levels abbreviated, as listings write them: "HS closed; ES open", "Elem. closing
    # 11:40", "MS/HS: remote learning" ("HS" is also Head Start, part of the program too).
    "es elem ms hs jh jhs shs ms/hs jh/hs jr/sr"
)
_CHILDCARE = "daycare childcare latchkey aftercare beforecare before-care after-care sac"
_TRANSPORTATION = (
    "bus buses busses transportation route routes shuttle shuttles road roads street streets "
    "bridge bridges highway highways interstate lane lanes ramp ramps "
    # A road's direction of travel: "NB still closed", "Westbound lanes closed".
    "northbound southbound eastbound westbound nb sb eb wb"
)

_PAIRS: dict[str, "Scope"] = {
    "high school": "partial",
    "high schools": "partial",
    "middle school": "partial",
    "middle schools": "partial",
    "junior high": "partial",
    "senior high": "partial",
    "elementary school": "partial",
    "elementary schools": "partial",
    "intermediate school": "partial",
    "primary school": "partial",
    "secondary school": "partial",
    "secondary schools": "partial",
    # A private school's divisions: "Upper School: closed", "Lower school open".
    "upper school": "partial",
    "upper schools": "partial",
    "lower school": "partial",
    "lower schools": "partial",
    "early childhood": "partial",
    "early bird": "partial",  # "Early bird classes cancelled": a period before the day
    "early-bird": "partial",
    "zero hour": "partial",  # "Zero hour cancelled" (see text._ZERO), as "zero period"
    "zero-hour": "partial",
    "zero period": "partial",
    "zero-period": "partial",
    "head start": "partial",
    "career center": "partial",
    "career tech": "partial",
    "technical center": "partial",
    "tech center": "partial",
    "day care": "childcare",
    "child care": "childcare",
    "before care": "childcare",
    "after care": "childcare",
    "extended day": "childcare",
    "kids club": "childcare",
    "central office": "office",
    "board office": "office",
    # The building that holds the district's offices: "Administration building closed".
    "administration building": "office",
    "administration buildings": "office",
    "administrative building": "office",
    "administrative buildings": "office",
    "admin building": "office",
    "admin buildings": "office",
    "administration center": "office",
    "administrative center": "office",
    "admin center": "office",
    "service center": "office",
    "open gym": "activities",
    # A college's recreation center: "Campus Rec and all activities cancelled".
    "campus rec": "activities",
    "campus recreation": "activities",
    "parking lot": "activities",
    "parking lots": "activities",
    "parking garage": "activities",
    "field house": "activities",
    "weight room": "activities",
    "open house": "activities",
    "open houses": "activities",
    "dining hall": "activities",
    "dining halls": "activities",
    "residence hall": "activities",
    "residence halls": "activities",
    "concession stand": "activities",
    "concession stands": "activities",
    "food pantry": "activities",
    "food bank": "activities",
    "city hall": "activities",
    "town hall": "activities",
    "village hall": "activities",
    "health center": "activities",
    "fitness center": "activities",
    "rec center": "activities",
    "recreation center": "activities",
    "senior center": "activities",
    "nature center": "activities",
    "aquatic center": "activities",
    "aquatics center": "activities",
    "wellness center": "activities",
    "civic center": "activities",
    "science center": "activities",
    "tennis courts": "activities",
    "swim meet": "activities",
    "track meet": "activities",
    "wrestling meet": "activities",
    "gymnastics meet": "activities",
    "speech meet": "activities",
    "dual meet": "activities",
    "field trip": "activities",
    "field trips": "activities",
    "bus service": "transportation",
}


def _table() -> dict[str, "Scope"]:
    table: dict[str, Scope] = {}
    groups: tuple[tuple[str, Scope], ...] = (
        (_SCHOOL, "school"),
        (_STAFF, "staff"),
        (_OFFICE, "office"),
        (_ACTIVITIES, "activities"),
        (_FACILITIES, "activities"),
        (_PARTIAL, "partial"),
        (_CHILDCARE, "childcare"),
        (_TRANSPORTATION, "transportation"),
    )
    for words, scope in groups:
        for word in words.split():
            table[word] = scope
    table.update(_PAIRS)
    return table


SCOPES: dict[str, Scope] = _table()

MODIFIERS: dict[str, Scope] = {
    # "evening classes", "adult classes": not the school day.
    "evening": "activities",
    "night": "activities",
    "adult": "activities",
    "saturday": "activities",
    "sunday": "activities",
    "weekend": "activities",
    "summer": "activities",
    "enrichment": "activities",
    "continuing": "activities",
    # A program's own classes: "Community ed classes", "ESL classes", "Driver's ed classes".
    # (Not "education" or "Hebrew school": a listing can be the program's own, as a church's
    # "Religious education classes cancelled" is, and "School and religious education classes
    # cancelled" is the school's.)
    "ed": "activities",
    "esl": "activities",
    "ged": "activities",
    "ccd": "activities",
    "ecfe": "activities",
    "dance": "activities",
    "tonight's": "activities",
    "after-school": "activities",
    # "AM kindergarten", "morning classes": part of the school day.
    "am": "partial",
    "pm": "partial",
    "morning": "partial",
    "afternoon": "partial",
    "half-day": "partial",
    "full-day": "partial",
    # "Hybrid students", "hybrid classes": the students of one program, not the district.
    "hybrid": "partial",
    "before-school": "childcare",
}
"""Words that, placed before a school noun, move it to another scope."""

NEGATIONS = frozenset(
    [
        "no",
        "not",
        "never",
        "none",
        "neither",
        "without",
        "nor",
        "won't",
        "wont",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "don't",
        "doesn't",
        "didn't",
        "cannot",
        "can't",
    ]
)

UNVERIFIED = frozenset(
    [
        "rumor",
        "rumors",
        "rumour",
        "rumours",
        "rumored",
        "rumoured",
        "unconfirmed",
        "unverified",
        "unofficial",
        "speculation",
        "hearsay",
        "hoax",
        "draft",
        "drafts",
        "prediction",
        "predictions",
        "projection",
        "projections",
        "projected",
        "hypothetical",
        "theory",
        "theoretically",
        "principle",
        "example",
        "sample",
        "scenario",
    ]
)
"""Words that say a report is hearsay, not the school's word: "Rumor: closed" is no closing.
They hedge a status as :data:`HEDGES` do, before it or just after it ("closed (unverified)")."""

HEDGES = frozenset(
    [
        "possible",
        "possibly",
        "potential",
        "potentially",
        "may",
        "might",
        "could",
        "maybe",
        "perhaps",
        "likely",
        "unlikely",
        "probable",
        "probably",
        "expect",
        "expected",
        "expecting",
        "expects",
        "anticipate",
        "anticipated",
        "anticipating",
        "consider",
        "considering",
        "tentative",
        "tentatively",
        "pending",
        "decision",
        "decide",
        "deciding",
        "monitor",
        "monitoring",
        "evaluate",
        "evaluating",
        "assess",
        "assessing",
        "reassess",
        "reassessing",
        "watching",
        "prepare",
        "prepared",
        "preparing",
        "chance",
        "would",
        "contingency",
        "forecast",
        "forecasted",
        "predicted",
        "predicting",
        "projected",
        *UNVERIFIED,
    ]
)
"""Words that make a following status a possibility rather than a statement."""

HEDGES_AFTER = frozenset(
    [
        "possible",
        "possibly",
        "likely",
        "probable",
        "expected",
        "anticipated",
        "considered",
        "discussed",
        "pending",
        "tentative",
        "may",
        "might",
        "could",
        "forecast",
        "forecasted",
        "unlikely",
        "improbable",
        "doubtful",
        "uncertain",
        "unconfirmed",
        "undecided",
        "undetermined",
        "unknown",
        "unclear",
        "reviewed",
        "evaluated",
        "reevaluated",
        "re-evaluated",
        "reassessed",
        "monitored",
        "tbd",
        "tba",
        "tbc",
        "predicted",
        "projected",
        *UNVERIFIED,
    ]
)
"""Words that make the status just before them a possibility ("closing possible", "closure
being reviewed", "closure unknown", "closure predicted for tomorrow")."""

HEDGE_CLAUSE_WORDS = HEDGES_AFTER | frozenset(
    [
        "tentatively",
        "maybe",
        "perhaps",
        "possibly",
        "probably",
        "potentially",
        "unofficial",
        "preliminary",
        "review",
        "consideration",
        "evaluation",
        "discussion",
        "monitoring",
        "question",
    ]
)
"""Words that, making up a phrase of their own after a status, leave it open: "Closed Friday
(tentative)", "Closed tomorrow - possible", "2 hour delay (TBD)", "Closed tomorrow - under
review", "... - being discussed", "... - still monitoring", "... - in question"."""

HEDGE_CLAUSE_FILLERS = frozenset(
    [
        "is", "are", "be", "at", "this", "time", "for", "now", "still", "currently", "as",
        "of", "yet", "the", "moment", "right", "status", "very", "highly", "all", "only",
        "change", "changes", "under", "being", "in", "will", "overnight", "quickly",
    ]
)  # fmt: skip
"""Words allowed beside :data:`HEDGE_CLAUSE_WORDS` in such a phrase ("tentative at this time",
"may change", "changes possible", "could change overnight")."""

CONDITION_OPENERS = frozenset(
    [
        "depending",
        "dependent",
        "contingent",
        "pending",
        "permitting",
        "provided",
        "providing",
        "assuming",
        "barring",
        "subject",
        "whenever",
    ]
)
"""Words besides :data:`CONDITIONALS` that open a condition: "depending on the forecast",
"pending road conditions", "weather permitting", "barring more snow", "subject to change",
"whenever school is closed"."""

CONDITIONS_ANYWHERE = frozenset(["depending", "dependent", "contingent", "permitting", "whenever"])
"""Words that make every status in their clause conditional wherever they stand ("closed
tomorrow depending on the forecast", "NTI whenever school is closed")."""

DENIED_AFTER = frozenset(
    [
        "expected",
        "anticipated",
        "likely",
        "probable",
        "planned",
        "scheduled",
        "forecast",
        "forecasted",
        "predicted",
        "foreseen",
    ]
)
"""Words that, after "not", say the status before them is not coming ("closure not expected")."""

UNSETTLED_AFTER = frozenset(
    [
        "confirmed",
        "decided",
        "determined",
        "official",
        "final",
        "certain",
        "guaranteed",
        "announced",
        "ruled",
        "yet",
        "sure",
        "known",
    ]
)
"""Words that, after "not", leave the status before them open ("delay not yet decided")."""

MAKE_UP_WORDS = frozenset(
    ["make", "makes", "made", "making", "makeup", "makeups", "make-up", "make-ups", "made-up"]
)
"""Words for making up a lost day ("snow day make-up day", "to be made up Feb 16"): a status
in their clause is about a day to be made up, not about the day it names."""

CONDITIONALS = frozenset(["if", "unless", "whether", "should"])
"""Words that make every status in their clause conditional ("should" only opening it)."""

NOT_CONDITIONS = {
    "if": frozenset(["you", "your"]),
    "unless": frozenset(["otherwise", "you"]),
    "should": frozenset(["you", "your", "be", "have", "not"]),
}
"""Words after a conditional word that make it no condition on the status: "if you have
questions", "unless otherwise noted" (it holds), "should be back Thursday"."""

CAUSES = frozenset(["due", "because", "owing"])
"""Words that open a cause phrase ("due to possible flooding"), which hedges nothing."""

SUPERSEDING = frozenset(
    [
        "now",
        "changed",
        "change",
        "updated",
        "update",
        "upgraded",
        "upgrade",
        "switched",
        "switching",
        "converted",
        "moved",
        "revised",
        "correction",
        "instead",
        "became",
        "become",
        "becomes",
        "becoming",
        "changing",
        "converting",
        "upgrading",
    ]
)
"""Words before a status that mark it as replacing an earlier one."""

SUPERSEDING_WITH = {
    "turned": frozenset(["into", "to"]),
    "turns": frozenset(["into", "to"]),
    "turning": frozenset(["into", "to"]),
    "replaced": frozenset(["with", "by"]),
    "reduced": frozenset(["to"]),
    "downgraded": frozenset(["to"]),
    "downgrading": frozenset(["to"]),
    "lowered": frozenset(["to"]),
    "scaled": frozenset(["back", "down"]),
}
"""Words before a status that mark it as replacing an earlier one only with the word after
them: "turned into an e-learning day", "replaced with a closure", "closure reduced to a 2
hour delay", "downgraded to a delay", "scaled back to a delay" ("replaced the delay" names
the status replaced, "turned off" nothing, and "reduced staff" nothing)."""

SUPERSEDED = frozenset(
    ["was", "were", "previously", "originally", "from", "formerly", "replacing", "replaces"]
)
"""Words just before a status that mark it as the one replaced."""

REGION_STOPS = frozenset(
    [
        "due",
        "because",
        "after",
        "following",
        "resume",
        "resumes",
        "resuming",
        "return",
        "returns",
        "returning",
        "reopen",
        "reopens",
        "reopening",
        "back",
        "will",
        "update",
        "updates",
        "decision",
        "reassess",
        "announce",
        "announcement",
        "check",
        "since",
        "when",
        "was",
    ]
)
"""Words after a status past which a date no longer belongs to it."""

FILLERS = frozenset(
    [
        "on",
        "for",
        "the",
        "and",
        "of",
        "this",
        "day",
        "days",
        "starting",
        "beginning",
        "effective",
        "from",
        "is",
        "are",
        "will",
        "be",
        "date",
        "dates",
        "also",
        "again",
        "as",
        "well",
        "through",
        "thru",
        "until",
        "till",
        "all",
        "only",
        "both",
        "next",
        "coming",
    ]
)
"""Words allowed in a clause that holds only dates ("Tuesday and Wednesday")."""

PURPOSES = frozenset(
    [
        "workday",
        "work",
        "development",
        "training",
        "in-service",
        "inservice",
        "day",
        "planning",
        "professional",
        "institute",
        "records",
        "conferences",
        "conference",
        "learning",
    ]
)
"""Words after a staff noun that make "for staff ..." a reason, not an audience."""

ORDINARY = frozenset(["regular", "normal", "usual", "scheduled", "standard"])
"""Words that make a dismissal or start time the normal one, not a change."""
