"""The precision gate: the words of a listing that no rule of the parser reads.

A status is reported with confidence (0.7 or more) only when the parser has read
every word of every sentence that bears on it. Each kind of word the grammar
reads is accounted for here: status words and what modifies them, days, dates,
times and lengths, the cause of a closure ("due to ..." to the end of its clause),
the nouns that name who is affected (a school's name too, up to the noun that ends
it: "Maple Ridge Elementary"), filler words, and the words of the statements the
parser reads whole (offices open, activities or games cancelled, meals, a portal,
school opening, reopening or held, hedges, corrections). A word left over is
*unread*. A sentence that names a status or a day, or says school opens or is held,
hedges or corrects, and holds an unread word could mean anything: "Closed today,
tomorrow pending a final call", "No school Friday - parade", "2 hour delay for the
yearbook". The listing is then ``other`` with a low confidence (note
``unread_words``). A sentence that names none of those leaves the result standing
("Stay safe!", "Thank you for your patience.").

The parser's cache of analyses by text shares one analysis among texts that differ
only in their names (see :func:`snowlight.classify.parse.canonical`): a word the gate
reads is never taken for a name there (see ``parse._role``), so a text with a word
read and one with a word unread in its place never share a reading.
"""

import re
from collections.abc import Iterable
from functools import lru_cache

from snowlight.classify.dates import MONTHS, SCHOOL_DAY_WORDS, WEEKDAYS
from snowlight.classify.lexicon import (
    CAUSES,
    CONDITION_OPENERS,
    FACILITY_NOUNS,
    FILLERS,
    HEDGE_CLAUSE_FILLERS,
    HEDGE_CLAUSE_WORDS,
    HEDGES,
    HEDGES_AFTER,
    MAKE_UP_WORDS,
    MODIFIERS,
    NEGATIONS,
    ORDINARY,
    PURPOSES,
    REGION_STOPS,
    SCOPES,
    SUPERSEDING,
    SUPERSEDING_WITH,
    UNSETTLED_AFTER,
)
from snowlight.classify.partial import CARVE_WORDS
from snowlight.classify.weather import ANY_START, NAME_KINDS, TERM_WORDS, term_word

# What a word is to the gate, as bits: read (every listed word); a noun that ends a name (the
# unread words right before it are the name: "Maple Ridge Elementary"); a word whose sentence
# counts even when it names no status or day (an opening, a school held, a hedge, a
# correction); a word that opens a cause (the rest of its clause is the cause); a status
# word; a word read only beside a status word, in its clause ("will remain closed", "remote
# learning will continue"); and a word that can stand inside a name, before the noun that
# ends it ("Kubaze Bus Garage", "Temira Main Campus").
READ = 1
NAME_END = 2
WEIGHTY = 4
CAUSE = 8
STATUS = 16
ATTACHED = 32
INNER = 64
STATEMENT = 128  # a word of a statement on a status of its own (see STATEMENT_WORDS)
PLAIN = 256  # a word of no role but read, and no word that joins or points: it can be a name's

# Words that only join, point or fill: articles, pronouns, prepositions, the forms of "be",
# "have" and "do", and the like.
_FUNCTION = """
a an the and or nor but yet so of on in at to for from by with without into onto off over
per via as than then is are was were be been being am will would shall can could should
must may might do does did done has have had having it its it's this that these those there
here their our ours we us you your they them he she his her all both each every any some
we'll we're we've we'd you'll you're they'll they're there's that's let's it'll
other others another either neither such same also too again well very just only still
even already now currently presently please kindly note notes reminder about after before
during between within throughout up out until till til through thru not no none never
who whom whose which what where how when while because whether if unless except
including includes include included plus etc regarding re least yes current use using
accordingly progress however although amp nbsp
"""
# Ordinary words that say nothing of a status or its days: "as soon as possible", "if
# necessary", "will notify", "as directed", "staff are asked to", "please keep in mind".
_INERT = """
need needs needed take takes taken prior soon possible necessary able unable best cover
covered notify notified require requires required allowed allow allows upon ask asks asked
advice advised ensure reason reasons free get gets keep around option options local access
provide provides provided receive located along multiple general order instructions
communication communications coordinate directed direction review reviewing aware mind
like many most much several few plenty instead individual individually own anyone anything
something nothing everything otherwise directly immediately mandatory taking occur occurs
occurring previous affects affect addition format formats
"""
# Numbers in words: the lengths of a delay ("two hour delay") and counts.
_NUMBERS = """
one two three four five six seven eight nine ten eleven twelve fifteen twenty thirty forty
forty-five fifty sixty ninety hundred half quarter
"""
# Status words, their modifiers, and the lengths and times of a late start or an early
# dismissal: "closed", "2 hour delay", "late start", "early release", "NTI", "e-learning".
_STATUS = """
closed close closes closing closings closure closures shut shuts shutting shutdown shutdowns
indefinately indefinetly indefinitly indefinte indefinatly indefinetely
shuttered cancel cancels canceled cancelled canceling cancelling cancellation
cancellations delay delays delayed delaying late later latest start starts started starting
begin begins beginning began opening openings dismissal dismissals dismiss dismisses
dismissed dismissing release releases released releasing early earlier remote remotely
virtual virtually online nti ami e-learning elearning e-day eday learning learn instruction
instructional flexible fid asynchronous synchronous distance non-traditional nontraditional
traditional digital snow inclement session sessions in-person person home at-home hour
hours hr hrs minute minutes min mins noon midday midnight suspended suspend postponed
postpone rescheduled reschedule modified abbreviated shortened operating operations
operate operates operated running run runs day days full whole entire make-up makeup
indefinite indefinitely
"""
# Words read only beside a status word, in its clause: "will remain closed", "remote learning
# will continue", "moving to remote learning", "fully remote", "closed temporarily".
_ATTACHED = """
remain remains remained remaining continue continues continued continuing proceed
proceeds fully completely entirely partially temporarily officially implement
implementing implemented activate activated observe observing holding pivot pivoting
independent self-directed cyber flex flexibility live alternative alternate methods
designated bag bags packet packets hope hopes hoping hopeful hopefully celebrate
celebrated comprehensive asynchronously non-live
"""
# (Words that change a status, read by the rules for changes wherever they stand: "moved to
# Thursday", "switching to remote learning".)
_CHANGES = """
move moves moved moving switch switches switched switching transition transitions
transitioning transitioned shift shifted shifting
"""
# Days, dates, times of day and how long a status lasts.
_DAYS = """
today tomorrow tonight tonite yesterday morning mornings afternoon afternoons evening
evenings night nights overnight am pm a m p week weeks weekend weekends rest remainder next
this coming beginning starting effective further notice date dates daily all-day eve aft
daytime first second third fourth fifth last final period periods month months mid-day
weekday weekdays mondays tuesdays wednesdays thursdays fridays saturdays sundays ago
semester semesters trimester term terms year years straight row consecutive lunchtime recess
nightly
"""
# Who is affected, beyond the nouns of :data:`~snowlight.classify.lexicon.SCOPES`: people,
# places, and the services and events of the schools, churches, courts and agencies whose
# listings stations carry.
_WHO = """
everyone everybody families family parents parent guardians children child kids youth
civil criminal jail probate juvenile soldiers airmen sailors marines dads moms
grandparents robotics
pupils learners scholars members people locations location sites site branch branches
facility pre-kindergarten care service services mass masses worship liturgy prayer prayers
bible study studies choir ministry ministries faith formation religious education ed ccd
confirmation communion catechism bingo court hearing hearings case cases docket dockets
trial trials jury jurors clerk clerks appointment appointments visit visits patient
patients client clients telehealth outpatient therapy counseling exams exam finals lesson
lessons course courses lab labs training trainings seminar seminars recital recitals
classroom classrooms doors door drop-off drop-offs dropoff pickups arrival departure
transit transport busing drivers driver vehicles crews workers worker employees shift
shifts operations team teams group groups department departments agency agencies council
board government officials coaches tutoring orchestra band choir soccer basketball
football volleyball wrestling hockey swimming track baseball softball cheer leave
liberal polls voting election vans van phones calls snack snacks story trash collection
recycling landfill programming openhouse medical dental clinicals tests exams age wheels
business stops stop toddler toddlers nurse nurses supervisor supervisors management
custodial maintenance principals principal shelters shelter graduation commencement prom
homecoming picture pictures photos yearbook cards books materials devices chromebooks
laptops varsity jv basket log login log-in sign referendum sale sales auction auctions
function functions extension extensions hotline hotlines crisis teleworker teleworkers
sanitation
"""
# Words that can stand inside a name, before the noun that ends it ("Temira Main Campus",
# "North Kubaze Elementary").
_INNER = """
north south east west northeast northwest southeast southwest northern southern eastern
western upper lower central main downtown st saint mt mount fort lake river valley creek
hill hills park new old and learning early child development career technical tech
education family head state jr sr ft nw ne sw se
"""
# Nouns that end a name: the unread words just before one are the name's ("Kubaze Bus
# Garage", "Temira Learning Center", "All Bakuzo schools").
_NAME_ENDS = """
school schools elementary elementaries academy academies district districts county
counties parish parishes center centers centre centres campus campuses office offices
church churches library libraries club clubs program programs building buildings garage
garages hall halls site sites location locations branch branches preschool preschools
daycare daycares college colleges university universities institute institutes charter
township city town village borough area areas region schoolhouse annex ms hs es jhs
care ctr chapel temple parish synagogue mosque clinic clinics hospital court courts
factory studio theater theatre clubhouse camp room rooms zone door complex elem ps
grounds fairgrounds rd ave blvd hwy ln pkwy avenue boulevard parkway
"""
# The words of a cause: "due to", "because of", "owing to", "out of an abundance of
# caution", "as a precaution", "for safety".
_CAUSE_OPENERS = "due because owing caution precaution precautionary"
# The words that open a condition, which hedges its clause's statuses whatever it holds: "if
# conditions improve we will reopen Thursday", "unless otherwise noted", "depending on the
# forecast", "barring more snow".
_CONDITION_OPENERS = """
if unless whether depending dependent contingent provided providing assuming barring
whenever once
"""
_CAUSE_WORDS = """
result results safety concern concerns anticipation response related abundance overabundance
conditions condition roads road travel hazardous dangerous unsafe slick slippery
treacherous poor outage outages power electricity electrical emergency damage damaged
trees tree downed lines temperatures temps warning warnings advisory advisories watch
forecasted expected predicted accumulation accumulations amounts impacts restored ban
state visibility debris inch inches feet foot degrees mph deadly bitter brutal down
emergencies
"""
# Statements the parser reads whole: school opening, reopening or held ("there will be
# school tomorrow", "classes as usual", "students report"), offices open, meals, a portal.
_OPENINGS = """
open opens opened reopen reopens reopened reopening re-open resume resumes resumed
resuming return returns returning returned back held hold holds usual normal normally
regular regularly scheduled schedule schedules report reports reporting attend attends
time times on-time
"""
_SERVICES = """
meal meals breakfast lunch lunches food grab-and-go grab pickup pick-up pick distribution
delivery deliveries delivered served serving available portal assignments packets essential
optional workday telework teleworking limited additional extra reduced special go going
menu menus pizza sandwich sandwiches needing behind reported notices modification
modifications adjustment adjustments disruption disruptions interruption interruptions
unscheduled non-essential nonessential availability drop drops offs carline car-line
"""
# Corrections: "Update:", "Correction:", "disregard", "posted in error", "is false".
_CORRECTIONS = """
update updated updates correction corrections corrected disregard ignore error errors false
jk
fake untrue true incorrect wrong removed mistake mistakenly retract retracted rescind
rescinded revised kidding nevermind mind scratch
"""
# Words that close a listing with no word on its days ("Stay safe!", "More info here").
_CLOSERS = """
stay safe safely warm tuned check checking visit see call contact email website web page
facebook twitter social media app more info information details detail follow thank
thanks patience understanding questions click link below above announcement
announcements message messages alert alerts notification notifications news posted post
sent text phone enjoy careful drive zoom youtube join live stream streamed streaming
recorded fb announce announces announced arrive arrives arriving friendly mail voicemail
video videos www http https com org net edu gov us
"""
# Plans and codes a status is posted with: "Employee Code 2", "Code Red", "Plan B", "Level 3
# remote day", "e-day policy in effect".
_PLANS = """
code codes level levels plan plans phase phases tier protocol protocols policy policies
procedure procedures red orange yellow green blue purple white gray grey black
"""
# Shortened words of listings: "No AM Kdg", "No Trans", "Bd Mtg", "2 Hr Dly", "Elem.".
_SHORT = """
kdg kdgn kinder pgm pgms prog trans transp dly mn elem mod act acts conf appt appts bd mtg
pls spvr empl reg non
mtgs dr opt async virt schd sched ufn svc svcs dept dist info admin govt ext mo mos trnsp
"""
# The words of the prose a district, a church, a court or an agency writes around a status, which
# say nothing of it or of its days: what is said and where ("will be communicated", "check
# Canvas", "posted to Schoology"), health, travel and the roads, work and staff, the storm's
# toll and the cleanup, thanks and courtesy, and the events and services a listing names.
_PROSE = """
hear hears heard communicate communicates communicated communicating broadcast broadcasts
broadcasting channel channels posting postings publicize publicized letter letters radio
listen listening inquire inquiries interview interviews issuance advise advises advising
recommend recommends recommended recommendation encourage encourages encouraged encouraging
talk talking know knowing indicate indicates indicated distribute distributes distributed
consult consults consulted consulting consultation consultations
livestreamed pre-recorded canvas schoology moodle google hangouts seesaw blackboard
cough coughs fever fevers symptom symptoms diagnosis vaccine vaccines vaccination
vaccinations surgery surgeries urgent hygiene telemedicine healthcare sick illness
driving drive-thru traveling travelling traveler travelers motorist motorists commute
commuting commuter commuters traffic truck trucks tow towing mile miles milepost exit
border rides carpool carpools dropped picked leaving waiting
employment job jobs description descriptions designation assigned duty duties contracted
staffed staffers instructor instructors onsite on-site residential swing graveyard benefit
benefits workforce
restore restoring restoration recover recovering recovery cleanup clean cleaning cleaned
cleared clearing removal fallen pole poles unprecedented significant localized tidal
adverse chilly bad clear easily exceed exceeding force nearly approximately total impact
impacted
pleased grateful thankful sincere sincerely loved ones extremely quickly closely
frequently dedicated worked stayed safer help helping supports interest choice choices
circumstance circumstances situation process point far means therefore additionally
according respectively consistent difficult adequate exact active offered based arranged
attended
ballet skating ceramics league leagues lecture lectures sermon sermons soup supper tea ash
deliberative
donut donuts fellowship funeral funerals preview committee committees art computer
computers testing aptitude lottery ticket tickets purchase purchased refund refunds
refunded restaurant restaurants dine dine-in cafe pantries donation
donations partnership partnerships partner partners international compassion conservation
governor federal national private registered eligible younger persons babies friends
division divisions evacuees consumers industry
arrange appear appearance appearances apply applies accept accepted accepting avoid
complete completed completing determine doing dress dressed warmly feed
maintain maintained managed manage participate participating participation permit permits
prioritize prioritizing prohibited reach reached recognize resulted spread slow utilize
utilizing visiting visitation teach teaching taught expanded exhibited experience commence
execute hosted host hosting assessed path calendar rotation deadline deadlines
opportunity opportunities preparation preparations preparedness precautions
continuous blended light hard surface surfaces my mine home homes caregiver caregivers
consisting ending higher losing risk risks works set-over space walk-in walk goes system
systems holidays carefully pre-storm post-storm vary varies varying list lists tax taxes
agile holy automatically developmental disability disabilities absence absences moderate
minor major mild wrap wraparound judgment judgement
"""
_HEDGES_TOO = "tbd tba tbc tentative tentatively possibility unknown"
# A status called off or lifted, and the words that answer hearsay: "Delay lifted", "2 hour delay
# called off", "Delay no longer in effect", "Despite rumors, we are closed today".
_CALLED_OFF = """
lifted lift lifting called calling canx cxl cxld cancelation cancelations revoked revoke
withdrawn withdraw longer ahead happen happening off
"""
_ANSWERING = "despite contrary regardless notwithstanding"
# Who decides, and how far a status reaches: "per the superintendent", "districtwide",
# "District declares an early release".
_WIDE = """
superintendent superintendents president districtwide district-wide countywide county-wide
citywide statewide schoolwide systemwide campuswide parishwide divisionwide wide declare
declares declared declaring announcement
"""


def _words(*groups: str | Iterable[str]) -> frozenset[str]:
    """Every word of ``groups``: strings of words, or collections of words or phrases."""
    found: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            found.update(group.split())
        else:
            for word in group:
                found.update(word.split())
    return frozenset(found)


_WEIGHTY_WORDS = _words(
    _OPENINGS, _CORRECTIONS, _HEDGES_TOO, _CALLED_OFF, _ANSWERING, _CONDITION_OPENERS, HEDGES,
    HEDGES_AFTER, HEDGE_CLAUSE_WORDS, CONDITION_OPENERS, SUPERSEDING, SUPERSEDING_WITH,
    "still planned decided determined confirmed previously originally formerly",
) - _words(
    # Words that say nothing of a status in a clause of their own: "staff report at 10",
    # "check back for updates", "we would like to thank", "be prepared", "from 8 to 4".
    "report reports reporting time times on-time back updates would prepare prepared",
    "preparing forecast forecasted should whether",
)  # fmt: skip
_WHO_WORDS = _words(_WHO, SCOPES, MODIFIERS, FACILITY_NOUNS, NAME_KINDS)
_STATUS_WORDS = _words(_STATUS, _OPENINGS)
_ATTACHED_WORDS = _words(_ATTACHED) - _STATUS_WORDS
_READ_WORDS = _words(
    _FUNCTION, _NUMBERS, _STATUS, _ATTACHED, _CHANGES, _DAYS, _NAME_ENDS, _INNER, _CAUSE_OPENERS,
    _CAUSE_WORDS, _SERVICES, _CLOSERS, _PLANS, _SHORT, _INERT, _CALLED_OFF, _WIDE, FILLERS, _PROSE,
    CARVE_WORDS, _CONDITION_OPENERS, _ANSWERING, HEDGE_CLAUSE_FILLERS, NEGATIONS,
    MAKE_UP_WORDS, ORDINARY, PURPOSES, REGION_STOPS, CAUSES, TERM_WORDS, MONTHS, WEEKDAYS,
    SCHOOL_DAY_WORDS, _WEIGHTY_WORDS, _WHO_WORDS, _OPENINGS, _CORRECTIONS, HEDGES,
    HEDGES_AFTER, *(value for value in SUPERSEDING_WITH.values()),
)  # fmt: skip
# The words that make a clause a statement on a status when they stand in it with no status of
# its own (see snowlight.classify.parse._bare_statement): it says school is held, hedges,
# hopes or corrects.
HELD_SIGNS = frozenset(
    ["held", "hold", "holds", "holding", "session", "usual", "normal", "normally", "regular",
     "regularly", "scheduled", "planned", "still", "continue", "continues", "continuing",
     "proceed", "proceeds", "proceeding", "ahead", "schedule", "meet", "meets", "back",
     "resume", "resumes", "resuming", "return", "returns", "returning", "attend", "attends"]
)  # fmt: skip
HOPE_SIGNS = frozenset(["hope", "hopes", "hoping", "hopeful", "hopefully"])
CORRECTION_SIGNS = frozenset(
    ["disregard", "ignore", "false", "error", "wrong", "incorrect", "mistake", "mistakenly",
     "jk", "kidding", "nevermind", "mind", "untrue", "fake", "scratch", "rescinded",
     "retracted", "drill", "drills", "wait", "nvm", "plans"]
)  # fmt: skip
# Words that, denied, correct what was said: "Closed tomorrow -- not true", "Not happening.", "No
# longer.", "Not anymore.".
TRUTH_SIGNS = frozenset(
    ["true", "correct", "accurate", "correctly", "accurately", "happening", "longer", "anymore"]
)
# Words that leave the days beside them open on their own: "Closed today, tomorrow either".
EITHER_SIGNS = frozenset(["either", "neither", "whichever", "or"])
STATEMENT_WORDS = (
    HELD_SIGNS
    | HOPE_SIGNS
    | CORRECTION_SIGNS
    | TRUTH_SIGNS
    | EITHER_SIGNS
    | HEDGE_CLAUSE_WORDS
    | UNSETTLED_AFTER
    | frozenset(["decision", "decisions", "decide", "deciding", "determined", "finalized"])
)
# The plural nouns of who or what is affected that end a name as a school's noun does ("Kubaze
# families", "Lomira hearings", "Tavi Center volunteers").
_GROUPS = """
families parents guardians children kids pupils learners scholars members people locations
sites branches services masses prayers hearings cases dockets trials jurors clerks
appointments visits patients clients exams finals lessons courses labs trainings seminars
recitals classrooms pickups drivers vehicles crews workers employees shifts operations teams
groups departments agencies officials coaches vans stops toddlers nurses supervisors
principals shelters pictures photos cards books materials devices sales auctions functions
extensions hotlines teleworkers volunteers business
"""
_NAME_END_WORDS = _words(_NAME_ENDS, NAME_KINDS, FACILITY_NOUNS, _GROUPS) | frozenset(
    word
    for word in SCOPES
    if " " not in word and len(word) > 3  # noqa: PLR2004
)
_CAUSE_WORDS_OPENING = _words(_CAUSE_OPENERS, CAUSES, _CONDITION_OPENERS)
# Read words that can also be a word of a name ("Dumi Made Elementary", "Lake Like Public
# Schools"): none that joins, points, denies or fills.
_PLAIN_WORDS = _words(_INERT, _PROSE, _CLOSERS, _SERVICES, _PLANS, _SHORT, MAKE_UP_WORDS) - _words(
    _FUNCTION, FILLERS, NEGATIONS, HEDGE_CLAUSE_FILLERS
)
_INNER_WORDS = _words(_INNER) | _WHO_WORDS

_READ_WORDS |= STATEMENT_WORDS  # (read by the rules for statements: see STATEMENT_WORDS)
CLASSES: dict[str, int] = {
    word: (ATTACHED if word in _ATTACHED_WORDS else READ)
    | (NAME_END if word in _NAME_END_WORDS else 0)
    | (WEIGHTY if word in _WEIGHTY_WORDS else 0)
    | (CAUSE if word in _CAUSE_WORDS_OPENING else 0)
    | (STATUS if word in _STATUS_WORDS else 0)
    | (INNER if word in _INNER_WORDS else 0)
    | (STATEMENT if word in STATEMENT_WORDS else 0)
    | (PLAIN if word in _PLAIN_WORDS else 0)
    for word in _READ_WORDS
}
"""Each word the grammar reads, with what it is to the gate (see :data:`READ` and the rest)."""

_JOINS = re.compile(r"[-/']", re.ASCII)
# A district's letter and number ("R-3", "C-4"), or a school's or a district's initials that
# end as such names do ("BPS", "RSD", "PHS", "NLMS"; no vowel): a name's last word.
_NAME_CODE = re.compile(r"[a-z]{1,2}-\d{1,3}|[b-df-hj-np-tv-xz]{0,3}(?:ps|sd|cs|hs|ms)", re.ASCII)
_DIGIT = re.compile(r"\d", re.ASCII)


@lru_cache(maxsize=65536)
def word_class(token: str) -> int:  # noqa: PLR0911 - one return per kind of word
    """What a word token is to the gate: the bits of :data:`CLASSES`, or 0 for an unread word.

    A word with a digit is a date, a time, a length or a number, all read; so is one
    letter alone (an initial, "a.m."). A word joined from parts ("closed-flexible",
    "am/pm", "district's") is read when each part is, and takes their bits. A noun of
    who is affected, a place or a service (see :data:`_NOUN_BITS`) is read in its other
    number too ("emails" as "email"), and so is one of seven letters or more spelt one
    letter off ("activites", "transporation": see :func:`_misspelt_noun`).
    """
    found = CLASSES.get(token)
    if found is not None:
        return found
    if _NAME_CODE.fullmatch(token) is not None:
        return READ | NAME_END  # "Hillsboro R-3", "BPS", "Lincoln HS": a school's name ends
    if (
        len(token) == 1
        or _DIGIT.search(token) is not None
        # (A weather term or a cause starts as one does: the quick test first, for names.)
        or (ANY_START.match(token) is not None and term_word(token))
    ):
        return READ
    if token.endswith(("'s", "s'")):
        base = CLASSES.get(token[:-2] if token.endswith("'s") else token[:-1])
        if base is not None:
            return base
    if token.isalpha():
        return _noun_class(token)
    parts = [part for part in _JOINS.split(token) if part]
    if len(parts) < 2:  # noqa: PLR2004 - a word of one part not listed
        return 0
    bits = READ
    for part in parts:
        part_bits = word_class(part)
        if not part_bits:
            return 0
        bits |= part_bits
    return bits


# The bits of a noun of who is affected, a place or a service, and no more: the words read in
# their other number, or spelt one letter off (see word_class). A word with any other bit (a
# status, a day, a hedge, a cause, a correction) is read only as it is listed.
_NOUN_BITS = READ | NAME_END | INNER | PLAIN
_PROSE_WORDS = _words(_PROSE)  # (prose, not nouns of who or where: "awaiting" is no "waiting")
_NOUNS = {
    word: bits
    for word, bits in CLASSES.items()
    if not bits & ~_NOUN_BITS and bits != READ and word not in _PROSE_WORDS
}
_MISSPELT_LENGTH = 7  # the fewest letters of a word read when spelt one letter off


# Words of prose that say a status may still change, or that more is to come about it: an
# update, a notice, a word to hear or know ("Friday: will advise", "Families will be notified
# about Friday", "Friday will be communicated tomorrow", "Friday: don't know yet").
_PENDING_PROSE = _words(
    _CLOSERS,
    """
    notify notified advice advised advise advises advising review reviewing communicate
    communicates communicated communicating hear hears heard know knowing talk talking
    indicate indicates indicated inquire inquiries determine assessed recommend recommends
    recommended recommendation encourage encourages encouraged encouraging consult consults
    consulted consulting consultation consultations broadcast broadcasts broadcasting
    publicize publicized letter letters radio listen listening possible soon necessary
    otherwise option options instead require requires required allowed allow allows ask asks
    asked aware mind point far means therefore choice choices circumstance circumstances
    situation process restore restoring restoration recover recovering recovery cleared
    clearing arrange appear permit permits complete completed completing commence expanded
    calendar rotation deadline deadlines opportunity opportunities preparation preparations
    preparedness precautions set-over
    """,
)


def inert_word(token: str) -> bool:
    """Whether a word is prose that says nothing of a status or of whether it may change
    ("Tickets purchased for today will be refunded automatically"): read, with no role but
    prose's, and no word of an update, a notice or a link to more."""
    return word_class(token) == READ | PLAIN and token not in _PENDING_PROSE


def noun_word(token: str) -> bool:
    """Whether a word is a noun of who or what is affected, a place or a service, and no more
    ("families", "services", "shifts", "activites"): no status, day, hedge, cause or
    statement word, and no word of prose."""
    bits = word_class(token)
    return bool(bits & (NAME_END | INNER)) and not bits & ~_NOUN_BITS


def _deletions(word: str) -> list[str]:
    """The word with each one of its letters left out."""
    return [word[:index] + word[index + 1 :] for index in range(len(word))]


# Each listed noun of seven letters or more with one letter left out, and its bits: a word
# with one letter missing is one of these; one with a letter added or changed, or two
# letters swapped, is one when a letter of it is left out too (see _misspelt_noun).
_NOUN_DELETIONS = {
    short: bits
    for word, bits in _NOUNS.items()
    if len(word) >= _MISSPELT_LENGTH and word.isalpha()
    for short in _deletions(word)
}


# (Every word _misspelt_noun looks up, and their first three letters.)
_NOUN_KEYS = frozenset(_NOUNS) | frozenset(_NOUN_DELETIONS)
_NOUN_KEY_HEADS = frozenset(key[:3] for key in _NOUN_KEYS)


def _noun_class(token: str) -> int:
    """The bits of a word of letters not listed that is a listed noun in its other number,
    or misspelt (see word_class), or 0."""
    other = _NOUNS.get(token[:-1] if token.endswith("s") else token + "s", 0)
    if other or len(token) < _MISSPELT_LENGTH:
        return other
    return _misspelt_noun(token)


def _misspelt_noun(token: str) -> int:
    """The bits of a listed noun of seven letters or more that a word is spelt one letter off
    from: one letter missing ("activites", "transporation"), added ("personnell"), changed
    ("activitiez") or put in another place ("studnets"), or 0."""
    found = _NOUN_DELETIONS.get(token, 0)  # a letter missing
    if found:
        return found
    # (Most words looked at here are names, which no such noun is: a word with a letter left
    # out starts with one of four three letters, which some word looked up must start with.)
    heads = _NOUN_KEY_HEADS
    if (
        token[:3] not in heads
        and token[1:4] not in heads
        and token[0] + token[2:4] not in heads
        and token[:2] + token[3] not in heads
    ):
        return 0
    shorts = _deletions(token)
    if _NOUN_KEYS.isdisjoint(shorts):
        return 0  # (one look for all of them)
    for short in shorts:
        found = _NOUNS.get(short, 0) or _NOUN_DELETIONS.get(short, 0)
        if found:
            return found
    return 0


# What a span is (see unread_sentence): a phrase that says a place is open, a status phrase, a
# side note, a day.
OPEN_SPAN = 3
STATUS_SPAN = 2
NOTE_SPAN = 1
DAY_SPAN = 0


def unread_sentence(  # noqa: PLR0912, PLR0915 - one pass over the words, one branch per kind
    text: str, spans: list[tuple[int, int, int]], anchors: list[int]
) -> bool:
    """Whether a sentence of ``text`` that counts holds a word no rule reads (see above).

    ``spans`` are the stretches the parser's rules read whole, in order: its status
    phrases (:data:`STATUS_SPAN`, which read the words attached to them in their
    clause), its side notes (:data:`NOTE_SPAN`) and its days (:data:`DAY_SPAN`).
    ``anchors`` are where the text's status phrases and days start, in order: a
    sentence that holds one counts, and so does one with a word of :data:`WEIGHTY`.
    A sentence ends at a full stop before a space, a semicolon, "!", "?" or a bar.

    The words no rule reads that stand where a name stands are a name's:

    - right before a noun of :data:`NAME_END`, after any other nouns of who is affected
      ("Kubaze Bus Garage"), the items of a list that such a noun ends among them
      ("Kubaze, Lomira and Tavi campuses"), and those of a list that runs into a side
      note's subject ("Kubaze, Lomira and Tavi campuses closed");
    - a label at the start of a sentence, before a colon or a dash ("Kubaze - Closed",
      "Montessori School of Lomira: 2 hour delay", "Kubaze and Lomira -- Closed"), or a
      list's before a comma, its names joined by "and" or "&" ("Kubaze and Lomira, 2 hour
      delay"; a word alone there may be no name: "Kubaze, closed"); a label that holds
      another word ("Kubaze update: closed") is not a name's;
    - the words after one that opens a name, up to the next word of another kind or mark
      but a list's: "including", "includes", "except", "excluding"; "no" outside a status
      ("2 hour delay, no AM Kubaze"); and "at", "in", "of" or "from" right after a noun of
      who or where is affected ("childcare at Kubaze is open", "School of Lomira").

    A word that ends in "ly" is never a name's in a label, a list or after a word that
    opens one ("Closed tomorrow including Kubaze, allegedly"). A cause or a condition runs
    from the word that opens it to the next mark ("due to a water main break, ...", "if
    conditions improve we will reopen Thursday"). A word of :data:`ATTACHED` is read only
    in a clause with a status word or a noun of who is affected ("remote learning will
    continue", "storm moving north"), a clause being ended by a mark, "but" or "however".
    """
    count = len(anchors)
    index = 0  # the next anchor
    span_count = len(spans)
    span = 0  # the next span, or the one the word is in
    beyond = (len(text) + 1, len(text) + 1, DAY_SPAN)  # (past the last span: no word reaches it)
    span_start, span_end, span_kind = spans[0] if spans else beyond
    unread = weighty = in_cause = False
    pending = False  # unread words that a noun after them can make a name
    doubtful = False  # one of them ends in "ly": only a noun after it makes it a name's
    listed = False  # the pending words go on past a list's joint ("Kubaze, Lomira campuses")
    opened = False  # after a word that opens a name ("including", "at" after a noun)
    denied = False  # ... and the word is "no", or a side note: a day may follow the name
    listy = False  # ... and the word follows a status or a day: only a list is names there
    noted = False  # right after a side note, whose list a joint can go on ("No AM preschool or")
    status = attached = False  # the clause's: a status word, a word read beside one
    label = True  # still before the sentence's first colon, with no status or day read
    label_unread = named = False  # the label's: an unread word, a noun that ends a name
    joined = False  # the pending words are joined by "and" or "&": a list ("Kubaze and Lomira")
    previous = 0  # the bits of the word before (STATUS after a status phrase; none for a joint)
    # Whether every word of the sentence is one no rule reads: such a sentence after a status or
    # a day ("Closed tomorrow. Oops.", "Closed tomorrow. Void.") counts, as one with a status or
    # a weighty word does.
    bare = True
    opening = True  # the next word opens its sentence
    last = 0
    for match in _WORDS.finditer(text):
        start, end = match.span()
        token = text[start:end]
        boundary = token in _CLAUSE_WORDS
        if (pending or opened) and start == last + 1 and last and text[last] in _ADDRESS_MARKS:
            # A web address or a name joined by a full stop ("kubaze.org", "kubaze.edu/news"):
            # its last part ends it ("org").
            if token.partition("/")[0] in _WEB_ENDS:
                pending = doubtful = listed = False
            last = end
            continue
        if (start != last + 1 and last) or boundary:
            gap = text[last:start]
            if pending and "&" in gap:
                joined = True  # ("Kubaze & Lomira")
            if boundary or gap.strip(" &"):
                # A mark: the end of a clause, of a cause, and of a name before it, but a
                # list's joint ("Kubaze, Lomira and Tavi campuses").
                joint = not boundary and gap.strip() in _LIST_JOINTS
                if (
                    pending
                    and not doubtful
                    and (
                        (opened and not joint and (listed or not listy))
                        or (
                            label
                            and (_LABEL_MARK.search(gap) is not None or (joined and gap == ", "))
                        )
                    )
                ):
                    # The names after "including", or a label's: before a colon or a dash, or
                    # a list's before a comma ("Kubaze and Lomira, 2 hour delay").
                    pending = listed = False
                elif pending and joint:
                    listed = True  # (a noun after the list can end its names)
                elif pending or (attached and not status):
                    if label:
                        label_unread = True
                    else:
                        unread = True
                    pending = doubtful = listed = False
                in_cause = status = attached = False
                # (A list goes on past its joint; a comma or a colon after a noun that ends a
                # name opens one: "the central office, Kubaze, open", "these counties: ...".)
                opened = (opened and joint) or (
                    previous & NAME_END != 0 and gap.strip() in _NAME_MARKS
                )
                denied = denied and opened
                if noted and joint:
                    opened = denied = True  # ("No AM preschool, Kubaze or Lomira")
                    listy = False
                noted = False
                previous = 0
                if label and ":" in gap:
                    # A label of names, read with the place it names ("... Campus: Closed").
                    unread = unread or (label_unread and not named)
                    label = label_unread = False
                if _SENTENCE_END.search(gap) is not None:
                    while index < count and anchors[index] < last:
                        weighty = True
                        index += 1
                    if (unread or label_unread) and (weighty or (bare and index > 0)):
                        return True
                    unread = weighty = label_unread = named = False
                    bare = opening = True
                    label = True
                if joint or "," in gap or "(" in gap or "[" in gap:
                    # (A list of names, or names in brackets: "Everett, Tacoma.", "(Northside)",
                    # which the text's normal form opens with a comma.)
                    bare = False
                if boundary:
                    last = end
                    continue
        last = end
        if in_cause:
            bare = opening = False
            continue
        while start >= span_end:
            span += 1
            span_start, span_end, span_kind = spans[span] if span < span_count else beyond
        if span_start <= start:
            # A word a rule read whole: a status phrase, a side note, a day.
            bare = opening = False
            if span_kind >= STATUS_SPAN:
                status = True
            if pending and (
                doubtful
                or (span_kind == DAY_SPAN and not denied)
                or not (
                    (opened and (listed or not listy))
                    or span_kind == OPEN_SPAN
                    or (listed and span_kind == NOTE_SPAN)
                )
            ):
                # (But the names after "including" or "no", those of a place said to be open,
                # "Kubaze and Lomira open", and a list in a side note's subject.)
                unread = True
            pending = doubtful = listed = opened = denied = False
            noted = span_kind == NOTE_SPAN  # (its list can go on: "No AM preschool or Kubaze")
            previous = STATUS if span_kind != NOTE_SPAN else 0  # (a status's or a day's)
            if label:
                unread = unread or label_unread
                label = label_unread = False
            continue
        bits = word_class(token)
        first, opening = opening, False
        if not bits and not_name(token) and (first or not _participle(token)):
            # A word no rule reads that is no name's: unread where a name could stand too. (A
            # past participle only opening its sentence: "Averted school closure", "Expired:
            # closed"; within one it can qualify a noun of who or where: "unplowed roads".)
            if label:
                label_unread = True
            else:
                unread = True
            continue
        if not bits:
            joined = joined and pending
            pending = True
            doubtful = doubtful or token.endswith("ly")
            continue
        if label and token in STALE_LABELS:
            label_unread = True  # "Previous: closed tomorrow", "Old: ...", "Test: ..."
        bare = False
        if pending:
            if bits & NAME_END:
                pending = doubtful = listed = False
            elif (
                bits & INNER
                or bits == READ | PLAIN
                or token in _NAME_JOINTS
                or token in _AUXILIARIES  # (before an "open": "Kubaze will be open")
            ):
                joined = joined or token in _AND
                continue  # (the name goes on: "Temira Main Campus", "School of Kubaze")
            elif opened and not doubtful and (listed or not listy):
                pending = listed = False  # (the names after "including" end)
            elif label:
                label_unread = True
                pending = doubtful = listed = False
            else:
                unread = True
                pending = doubtful = listed = False
        if noted:
            opened = denied = token in _NAME_JOINTS
            noted = listy = False
        elif opened and not (
            bits & (INNER | NAME_END)
            or bits == READ | PLAIN
            or token in _NAME_JOINTS
            or token[0].isdigit()  # (an address: "classes at 200 Kubaze St")
        ):
            opened = denied = False
        if token in _NAME_OPENERS:
            opened = True
            denied = token in NEGATIONS  # ("no": a day may follow the name)
            listy = False
        elif (token in _PLACE_OPENERS and previous & (NAME_END | INNER)) or (
            previous & NAME_END and token in _NAME_PURPOSE_OPENERS
        ):
            opened = True
            listy = False
        elif previous == STATUS and token in _STATUS_PLACE_OPENERS:
            # "Closed in Kubaze, Lomira and Tavi", but not "Friday in doubt": a list of names.
            opened = listy = True
        previous = 0 if token in _NAME_JOINTS else bits
        if bits & ~READ:
            if bits & NAME_END:
                named = True
            if bits & (STATUS | INNER):
                status = True  # (a status word, or who is affected: what an attached word needs)
            if bits & ATTACHED:
                attached = True
            if bits & CAUSE:
                in_cause = True
            if bits & WEIGHTY:
                weighty = True
    if (pending and (doubtful or not opened or (listy and not listed))) or (
        attached and not status
    ):
        unread = True
    if index < count:
        weighty = True
    return (unread or label_unread) and (weighty or (bare and index > 0))


# The marks that end a label of names at a sentence's start: a colon, or a dash with a space
# beside it, or two ("Kubaze - Closed", "Kubaze -- Closed", "Kubaze: Closed").
_LABEL_MARK = re.compile(r":|\s[-/]|[-/]\s|--", re.ASCII)
# The marks that join the items of a list of names: "Kubaze, Lomira and Tavi campuses".
_LIST_JOINTS = frozenset({",", "/", "&", ", &"})
# Words a name holds between its words: "School of Kubaze", "Kubaze and Lomira Campuses"; and
# the one that joins two names in a list, which a comma can end as a label ("Kubaze and
# Lomira, closed": see unread_sentence).
_NAME_JOINTS = frozenset({"and", "or", "of", "the", "&"})
_AND = frozenset({"and"})
# Words after which a name stands: "including Kubaze", "no AM Kubaze"; and those after which
# one stands right after a noun of who or where is affected: "childcare at Kubaze".
_NAME_OPENERS = frozenset(
    {"including", "includes", "include", "except", "excluding", "no", "hurricane", "storm"}
    | {"fort", "ft", "mount", "mt", "saint", "st", "port"}
)
_PLACE_OPENERS = frozenset({"at", "in", "of", "from", "on"})
# ... the one that opens a name right after a status ("Closed in Kubaze and Lomira"), and the
# one that does so right after a noun that ends a name ("Center for Kubaze Studies").
_STATUS_PLACE_OPENERS = frozenset({"in"})
_NAME_PURPOSE_OPENERS = frozenset({"for"})
# The marks after a noun that ends a name that open a name or a list of names.
_NAME_MARKS = frozenset({",", ":"})
# Words between a name and the "open" it is the subject of: "Kubaze will be open".
_AUXILIARIES = frozenset({"will", "be", "is", "are", "remain", "remains", "to"})
# The mark inside a web address or a name, and the ends of a web address: "kubaze.org".
_ADDRESS_MARKS = frozenset({"."})
_WEB_ENDS = frozenset({"com", "org", "net", "edu", "gov", "us", "info"})


# What a stretch between spaces is to names_read: a stretch with no word ("&", "-"), with no
# mark ("&" only: the words beside it join), or with marks; one word alone that no rule reads;
# a noun that ends a name, alone or with marks after it; one word alone that a name can go on
# through ("main", "early"); read words, with or without marks; and anything else, which
# names_read leaves to unread_sentence (a word read only beside a status word, words no rule
# reads beside marks or other words).
_NO_WORD = 0
_MARK = 1
_NAME_WORD = 2
_NAME_END_WORD = 3
_NAME_INNER = 4
_READ_WORDS_ONLY = 5
_UNSURE = 6
_MOST_STRETCHES = 1 << 16  # (a bound on memory: a kind is the same worked out again)


def _stretch_kind(stretch: str) -> int:
    """What a stretch between spaces is to :func:`names_read` (see _NO_WORD and the rest)."""
    tokens = _WORDS.findall(stretch)
    if not tokens:
        return _NO_WORD if not stretch.strip("&") else _MARK
    classes = [word_class(token) for token in tokens]
    if (tokens[0] in STALE_LABELS and stretch.endswith(":")) or any(
        not bits and not_name(token) for token, bits in zip(tokens, classes, strict=True)
    ):
        return _UNSURE  # (a stale label, or a word unread wherever it stands: unread_sentence)
    if any(not bits or bits & ATTACHED for bits in classes):
        return (
            _NAME_WORD
            if len(tokens) == 1 and stretch == tokens[0] and not classes[0]
            else (_UNSURE)
        )
    if len(tokens) == 1 and stretch.startswith(tokens[0]) and classes[0] & NAME_END:
        return _NAME_END_WORD  # ("campus", "campus,": the name ends before the mark)
    if (
        len(tokens) == 1
        and stretch == tokens[0]
        and (classes[0] & INNER or classes[0] == READ | PLAIN)
        and tokens[0] not in _CLAUSE_WORDS
    ):
        return _NAME_INNER
    return _READ_WORDS_ONLY


def names_read(text: str, spans: list[tuple[int, int, int]]) -> bool:
    """Whether every word of ``text`` that no rule reads is a word of a name that a noun of
    :data:`NAME_END` right after it ends ("all Lidama schools remote", "Closed - Kumuka
    campus"), outside ``spans``, and no word is read only beside a status word: then
    :func:`unread_sentence` finds no unread word, which this tells per stretch between
    spaces, with no pass over the words. ``False`` leaves the question to unread_sentence.
    """
    stretches = text.split(" ")
    kinds = list(map(_stretch_kinds, stretches))
    if _UNSURE in kinds:
        return False
    if _NAME_WORD not in kinds:
        return True  # (no word of a name: every word is read)
    # (From the first name word to the noun that ends the last: the stretches before and after
    # hold no name. Where a stretch starts: the lengths before it, and a space after each.)
    first = kinds.index(_NAME_WORD)
    last = len(kinds) - kinds[::-1].index(_NAME_WORD)  # (just past the last name word)
    position = sum(map(len, stretches[:first])) + first
    pending = False  # a name's words, with no noun that ends it yet
    for index in range(first, len(kinds)):
        kind = kinds[index]
        if pending:
            if kind == _NO_WORD:
                pass  # ("Marsh & Manch Campus": no mark)
            elif kind in _NAME_KINDS and not _in_spans(position, spans):
                pending = kind != _NAME_END_WORD
            else:
                return False
        elif kind == _NAME_WORD:
            pending = True
        elif index >= last:
            return True  # (every name ended: no name word after this one)
        position += len(stretches[index]) + 1
    return not pending


_NAME_KINDS = frozenset({_NAME_WORD, _NAME_INNER, _NAME_END_WORD})


def _in_spans(position: int, spans: list[tuple[int, int, int]]) -> bool:
    """Whether ``position`` is inside one of the spans."""
    for low, high, _kind in spans:  # noqa: SIM110 - (a loop costs less than a generator)
        if low <= position < high:
            return True
    return False


class _StretchKinds(dict[str, int]):
    """What each stretch between spaces is to names_read (see _stretch_kind), worked out once."""

    def __missing__(self, stretch: str) -> int:
        if len(self) >= _MOST_STRETCHES:
            self.clear()  # a bound on memory: a kind is the same worked out again
        kind = self[stretch] = _stretch_kind(stretch)
        return kind


_STRETCH_KINDS = _StretchKinds()
_stretch_kinds = _STRETCH_KINDS.__getitem__


def forget_words() -> None:
    """Empty the caches kept by word and by stretch of text (for benchmarks and tests that must
    see every word for the first time; the results are the same either way)."""
    word_class.cache_clear()
    not_name.cache_clear()
    _STRETCH_KINDS.clear()


# Words that end a clause as a mark does.
_CLAUSE_WORDS = frozenset({"but", "however"})
# Read words that, heading a listing as its label, say it is no current status ("Previous:
# closed tomorrow", "Test: closed tomorrow"); a name's label with them ends with its noun
# ("Old Town Elementary: closed").
STALE_LABELS = frozenset(
    {"old", "previous", "prior", "former", "past", "earlier", "test", "testing", "draft",
     "sample", "example", "proposed", "outdated", "expired", "archived", "archive"}
)  # fmt: skip
# The endings of an adverb, which no name has ("apparently", "reportedly", "unofficially",
# "supposedly"), and the past participles that are names ("United", "Sacred Heart", "Blessed
# Sacrament", "Alfred-Almond"): any other word of six letters or more in "-ed" is a verb's.
_ADVERB_ENDINGS = (
    "ally", "edly", "ently", "antly", "ously", "ively", "fully", "ingly", "ably", "ibly",
    "ately", "ictly", "essly", "ward", "wards",
)  # fmt: skip
_NAME_PARTICIPLES = frozenset(
    {"united", "sacred", "blessed", "redeemed", "alfred", "mildred", "wilfred", "winfred",
     "winifred", "manfred", "gifted", "talented"}
)  # fmt: skip
# Words of doubt, of a correction or of a status past, which no school is named ("Iffy: closed
# tomorrow", "Imminent school closure tomorrow").
_NOT_NAME_WORDS = _words(
    """
    nope oops whoops void iffy toss-up anymore anyway premature approval standby think guess
    unsure wobbly dicey borderline pondering mulling weighing shaky murky questionable
    unknowable undecided imminent impending looming threatened feared rumored hypothetical
    supposedly apparently reportedly allegedly purportedly unofficially seemingly presumably
    probably evidently maybe perhaps averted avoided prevented proposed contemplated considered
    outdated expired archived obsolete invalid erroneous mistaken reconsidering reevaluate
    re-evaluate reassess re-assess
    """
)


def _participle(token: str) -> bool:
    """Whether a word is no name's only as a past participle (see _not_name)."""
    return token.endswith("ed") and token not in _NOT_NAME_WORDS


@lru_cache(maxsize=65536)
def not_name(token: str) -> bool:
    """Whether a word no rule reads (see :func:`word_class`) is no name's either, so that it is
    unread wherever it stands, a name's place too ("Apparently school is closed tomorrow",
    "Expired: closed tomorrow", "Averted school closure tomorrow"): a word of doubt, of a
    correction or of a status past ("toss-up", "doubtful-ish" too), an adverb, or a past
    participle of six letters or more."""
    return (
        token in _NOT_NAME_WORDS
        or token.endswith("-ish")
        or (
            token.isalpha()
            and (
                (len(token) > 6 and token.endswith(_ADVERB_ENDINGS))  # noqa: PLR2004
                or (len(token) > 5 and token.endswith("ed") and token not in _NAME_PARTICIPLES)  # noqa: PLR2004
            )
        )
    )


_WORDS = re.compile(r"[a-z0-9]+(?:['/-][a-z0-9]+)*", re.ASCII)
_SENTENCE_END = re.compile(r"[;!?|]|\.(?:\s|\Z)", re.ASCII)
