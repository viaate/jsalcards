"""Word lists behind the name normalizer.

A closings listing and an NCES directory name spell the same school differently:
``"St. Mary's Elem."`` and ``"ST MARYS ELEMENTARY SCHOOL"``, ``"Houston ISD"`` and
``"Houston Independent School District"``, ``"Wentzville R-4"`` and
``"Wentzville R-IV"``. :mod:`snowlight.match.normalize` runs both sides through
the same steps, and these tables drive those steps. Every entry maps to one
canonical spelling, so the direction of an abbreviation never matters: a listing's
``"Elem"`` and a directory's ``"Elementary"`` both become ``"elementary"``.

The abbreviations were chosen from the forms that actually occur in the NCES CCD
and PSS school and district names (``"El Sch"`` in Pennsylvania, ``"H S"`` and
``"J H"`` in Texas, ``"CUSD"`` and ``"CCSD"`` in Illinois, ``"Pblc Schs"`` where CCD
truncates) and in closings lists.
"""

from typing import Final

# Always-on abbreviations: one token becomes one or more canonical tokens.
EXPANSIONS: Final[dict[str, tuple[str, ...]]] = {
    # school levels
    "elem": ("elementary",),
    "elementry": ("elementary",),
    "elemen": ("elementary",),
    "elementar": ("elementary",),
    "ele": ("elementary",),
    "mid": ("middle",),
    "midd": ("middle",),
    "int": ("intermediate",),
    "intrm": ("intermediate",),
    "intrmd": ("intermediate",),
    "intermed": ("intermediate",),
    "pri": ("primary",),
    "prim": ("primary",),
    "kg": ("kindergarten",),
    "kdg": ("kindergarten",),
    "kinder": ("kindergarten",),
    "prek": ("prekindergarten",),
    "prekinder": ("prekindergarten",),
    "prekindergarten": ("prekindergarten",),
    "pk": ("prekindergarten",),
    "preschool": ("prekindergarten",),
    "hs": ("high", "school"),
    "ms": ("middle", "school"),
    "es": ("elementary", "school"),
    "jhs": ("junior", "high", "school"),
    "jshs": ("junior", "senior", "high", "school"),
    "shs": ("senior", "high", "school"),
    "jr": ("junior",),
    "jnr": ("junior",),
    "sr": ("senior",),
    "snr": ("senior",),
    # school nouns
    "sch": ("school",),
    "schl": ("school",),
    "scho": ("school",),
    "schoo": ("school",),
    "schs": ("schools",),
    "schls": ("schools",),
    "acad": ("academy",),
    "academ": ("academy",),
    "acade": ("academy",),
    "prep": ("preparatory",),
    "ctr": ("center",),
    "cntr": ("center",),
    "centre": ("center",),
    "inst": ("institute",),
    "lrng": ("learning",),
    "lrn": ("learning",),
    "alt": ("alternative",),
    "chtr": ("charter",),
    "chartered": ("charter",),
    "chrtr": ("charter",),
    "pcs": ("public", "charter", "school"),
    "voc": ("vocational",),
    "sci": ("science",),
    "cath": ("catholic",),
    "luth": ("lutheran",),
    "sda": ("seventh", "day", "adventist"),
    "univ": ("university",),
    "mlk": ("martin", "luther", "king"),
    # districts
    "dist": ("district",),
    "distr": ("district",),
    "distri": ("district",),
    "distric": ("district",),
    "dst": ("district",),
    "pblc": ("public",),
    "publ": ("public",),
    "pub": ("public",),
    "ind": ("independent",),
    "indep": ("independent",),
    "unif": ("unified",),
    "comm": ("community",),
    # Indiana's NCES names: "North Harrison Com School Corp", "Bartholomew Con
    # School Corp", "Brownstown Cnt Com Sch Corp" ("Con" and "Cnt" are read by
    # context, see snowlight.match.normalize).
    "com": ("community",),
    "cmty": ("community",),
    "cmnty": ("community",),
    "jt": ("joint",),
    "cons": ("consolidated",),
    "coop": ("cooperative",),
    "coopr": ("cooperative",),
    "consol": ("consolidated",),
    "consold": ("consolidated",),
    "reg": ("regional",),
    "regl": ("regional",),
    "rgnl": ("regional",),
    "corp": ("corporation",),
    "dept": ("department",),
    "sd": ("school", "district"),
    "isd": ("independent", "school", "district"),
    "cisd": ("consolidated", "independent", "school", "district"),
    "usd": ("unified", "school", "district"),
    "jusd": ("joint", "unified", "school", "district"),
    "cusd": ("community", "unit", "school", "district"),
    "ccsd": ("community", "consolidated", "school", "district"),
    "chsd": ("community", "high", "school", "district"),
    "ufsd": ("union", "free", "school", "district"),
    "csd": ("central", "school", "district"),
    "esd": ("elementary", "school", "district"),
    "hsd": ("high", "school", "district"),
    "uhsd": ("union", "high", "school", "district"),
    "rsd": ("regional", "school", "district"),
    "msd": ("metropolitan", "school", "district"),
    "psd": ("public", "school", "district"),
    "evsd": ("exempted", "village", "school", "district"),
    "msad": ("school", "administrative", "district"),
    "sad": ("school", "administrative", "district"),
    "rsu": ("regional", "school", "unit"),
    "sau": ("school", "administrative", "unit"),
    "aos": ("alternative", "organizational", "structure"),
    "boe": ("board", "of", "education"),
    # New York City, whose system NCES splits into its geographic districts (see
    # snowlight.match.systems): "NYC Public Schools", "NYC DOE", "NYCDOE".
    "nyc": ("new", "york", "city"),
    "nycdoe": ("new", "york", "city", "department", "of", "education"),
    "nycps": ("new", "york", "city", "public", "schools"),
    # places
    "co": ("county",),
    "cnty": ("county",),
    "twp": ("township",),
    "twsp": ("township",),
    "twnshp": ("township",),
    "boro": ("borough",),
    "vlg": ("village",),
    "vill": ("village",),
    "vil": ("village",),
    "mt": ("mount",),
    "mtn": ("mountain",),
    "ft": ("fort",),
    "pt": ("point",),
    "hts": ("heights",),
    "hgts": ("heights",),
    "spgs": ("springs",),
    "vly": ("valley",),
    "lk": ("lake",),
    "ave": ("avenue",),
    "rd": ("road",),
    "blvd": ("boulevard",),
    "hwy": ("highway",),
}

# Spellings one abbreviation stands for either way, which a listing and a name may
# each spell out differently: NCES's "Mt" is Mount before a name ("Mt. Vernon")
# and Mountain after one ("Eagle Mt-Saginaw ISD", "Blue Mt Christian School"),
# and "Mt. View" is either. A word of a pair meets the other at a little less
# than its full weight (see snowlight.match.index.ALTERNATE_CREDIT).
ALTERNATE_SPELLINGS: Final[dict[str, tuple[str, ...]]] = {
    "mount": ("mountain",),
    "mountain": ("mount",),
}

# Compass directions. A town named for where it lies from another ("East
# Lansing", "West Des Moines", "South Portland", "North Little Rock") is another
# town with its own district, and a school's campus ("Lake Zurich Middle - North
# Campus") is another school: a name that says a direction names only a record
# that says the same one.
DIRECTIONS: Final[frozenset[str]] = frozenset(
    {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"}
)
DIRECTION_ABBREVIATIONS: Final[dict[str, str]] = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "no": "north",
    "so": "south",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}
"""Abbreviated directions. One is read as a direction only where a direction
stands, before a name at the start of it or of a part of it (``"E. Lansing"``,
``"Pontiac-W Holliday"``, ``"MSAD 60 - N. Berwick"``, ``"School of N.
Bennington"``, ``"USD 251 N. Lyon County"``). Between a given name and a surname
the same letter is a middle initial (``"Harry S. Truman"``, ``"Joel E.
Barber"``), and before another initial it is one too (``"E H Gentry"``, ``"W. D.
Hall"``). See :func:`snowlight.match.normalize.expand_directions`."""

# "St" is Saint before a name ("St Marys") and Street after one ("Main St").
SAINT_FORMS: Final[dict[str, tuple[str, str]]] = {
    "st": ("saint", "street"),
    "ste": ("sainte", "street"),
    "sts": ("saints", "streets"),
}

# Tokens that turn a following Roman numeral "i", "v" or "x" into a number
# ("R-I", "District V"); longer numerals ("ii", "iv", "xii") convert anywhere.
NUMBER_CONTEXT: Final[frozenset[str]] = frozenset(
    {"r", "re", "c", "no", "district", "dist", "unit", "sd", "number", "class", "j", "u"}
)

POPE_NAMES: Final[frozenset[str]] = frozenset(
    {"john", "paul", "pius", "leo", "benedict", "gregory", "clement"}
)
"""Popes' names, after which a Roman numeral is the pope's, part of a school's name.

``"ST JOHN XXIII CATHOLIC SCHOOL"`` and ``"PAUL VI CATHOLIC HIGH SCHOOL"`` are named
for popes, not numbered: ``"St. John School"`` and ``"St. Paul School"`` name other
saints, whose schools the numeral tells apart, as a name's word does, never as a
number a listing may leave out."""

_NUMBER_WORDS: Final[tuple[str, ...]] = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty",
)  # fmt: skip
SPELLED_NUMBERS: Final[dict[str, str]] = {
    word: str(value) for value, word in enumerate(_NUMBER_WORDS, start=1)
}
"""District numbers as a list may spell them: South Carolina's ``"Spartanburg District
Seven"``, ``"Anderson School District Five"``, ``"Richland One"`` for NCES's
``"Spartanburg 07"``, ``"Anderson 05"``, ``"Richland 01"``."""
SPELLED_NUMBER_BEFORE: Final[frozenset[str]] = frozenset({"district", "unit", "number"})
"""Words after which a spelled number is a district's number (``"District Seven"``)."""
SPELLED_NUMBER_AFTER: Final[frozenset[str]] = frozenset(
    {"school", "schools", "sch", "schs", "district", "dist", "sd", "public", "ps", "system"}
)
"""Words that may follow a spelled number that ends a name and still leave it the
district's number (``"Richland One Schools"``, ``"Florence One"``), unlike the
``Five`` of ``"Anderson Five Charter School"``, a charter school's own name."""

# Letter prefixes glued to a number that are split off ("R4" -> "r 4", "SD308",
# "RSU13", "MSAD#17" once "#" is gone).
COMPOSITE_PREFIXES: Final[frozenset[str]] = frozenset(
    {"r", "re", "rj", "c", "d", "j", "u", "k", "pk", "sd", "isd", "usd", "cusd", "psd", "no"}
    | {"rsu", "msad", "sad", "sau", "aos"}
)

# Letter prefixes dropped when they stand right before a number: "R-IV", "RE-1",
# "C-2" and "D49" name the number, the letters add nothing a listing repeats.
# The number they prefix is a district's number.
NUMBER_PREFIXES: Final[frozenset[str]] = frozenset({"r", "re", "rj", "c", "d", "j", "u"})

# District codes: a designator and a number that name a district by its legal
# number rather than by a place (Kansas's "USD 320", Maine's "RSU 13" and "MSAD
# 17", New Hampshire's "SAU 16", Colorado's "RE-2", Illinois's "CUSD 300").
DISTRICT_SERIES: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("maine", "school", "administrative", "district"), "sad"),
    (("regional", "school", "unit"), "rsu"),
    (("school", "administrative", "district"), "sad"),
    (("school", "administrative", "unit"), "sau"),
    (("alternative", "organizational", "structure"), "aos"),
)
"""Designators, in canonical words, whose numbers form a series of their own.

Maine numbers its regional school units and its school administrative districts
separately, so ``"RSU 13"`` and ``"MSAD 13"`` are two districts, and the CCD
names a district that is both by both (``"RSU 83/MSAD 13"``). A code of one of
these series is compared as the series and the number together (``"rsu 13"``,
``"sad 13"``): a listing's ``"MSAD 13"`` is ``"RSU 83/MSAD 13"``, never ``"RSU
13"``. ``MSAD`` and ``SAD`` are one series. Longest phrase first."""
DISTRICT_CODE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "unified",
        "independent",
        "school",
        "district",
        "community",
        "unit",
        "consolidated",
        "central",
        "union",
        "free",
        "high",
        "elementary",
        "public",
        "joint",
        "regional",
        "metropolitan",
        "administrative",
        "exempted",
        "village",
        "reorganized",
    }
)
"""Words of a district designator that begins a listing before its number: ``"USD
320 Wamego"`` (``unified school district``), ``"CUSD 300 Hampshire"``, ``"School
District 5 Lincoln Elementary"``. The run must end in one of
:data:`DISTRICT_CODE_HEADS` right before the number, so ``"High School 5"`` and
``"P.S. 5"`` are no district codes."""
DISTRICT_CODE_HEADS: Final[frozenset[str]] = frozenset({"district", "unit"})
"""Nouns that end a district designator: a number right after one is a district's."""

# School levels: compared as a set, so "Lincoln Elementary" never takes
# "Lincoln Middle". "juniorhigh" is "junior high" joined into one level.
LEVELS: Final[frozenset[str]] = frozenset(
    {
        "elementary",
        "primary",
        "intermediate",
        "middle",
        "juniorhigh",
        "high",
        "kindergarten",
        "prekindergarten",
    }
)

# Place words that set one district apart from a namesake ("Lancaster" versus
# "Lancaster County"). A listing that names one of these must find it, but for a
# township's "Township" said on one side only (see MUNICIPAL_QUALIFIERS).
COUNTY_QUALIFIERS: Final[frozenset[str]] = frozenset({"county", "parish", "township"})
# Town-level and district-type words: a listing may leave them out ("Woodbine
# Schools" for "Woodbine Local", "Derry Schools" for New Hampshire's "Derry
# Cooperative School District"), but one that says "Local" does not mean
# "Kettleby City", "Millbrook Area" is not "Millbrook" when both exist, and
# "Lawrence Co. Coop." is not "Lawrence County School District".
TOWN_QUALIFIERS: Final[frozenset[str]] = frozenset(
    {"city", "town", "village", "borough", "local", "area", "regional", "cooperative"}
)
QUALIFIERS: Final[frozenset[str]] = COUNTY_QUALIFIERS | TOWN_QUALIFIERS
"""Every place qualifier. A qualifier is one only where it ends a name, after the name
it qualifies (``"Toledo City"``, ``"Faketown City Schools"``, ``"Milford Exempted
Village"``, ``"Union City High School"``); anywhere else it is a word of the name
like any other (``"Village Christian Academy"``, ``"Town & Country Day School"``,
``"City Academy"``, ``"Kid City Academy"``), which a listing must say: see
:func:`~snowlight.match.normalize.qualifies`."""
PLACE_KINDS: Final[frozenset[str]] = COUNTY_QUALIFIERS | frozenset(
    {"city", "town", "village", "borough"}
)
"""Qualifiers that say what kind of place the words before them name. Only a place's
name comes before one, not a compass direction or a joining word alone: ``"East
Village Elementary"`` and ``"The Village School"`` are names, not East's village. The
other qualifiers (``Local``, ``Area``, ``Regional``, ``Cooperative``) say what kind of
district a name is, whatever the name (``"Northwest Local"``)."""
TOWN_KINDS: Final[frozenset[str]] = frozenset({"city", "town", "village", "borough"})
"""Kinds of town whose word, with more of a name after it, is part of that name:
``"Kid City Academy"``, ``"Global Village Academy"``, ``"Capital City Adventist
School"``. A county's, a township's or a district's kind is not (``"Laclede County
R-1 Conway"``, ``"Ludington Area Catholic School"``, ``"St. Joseph Regional Catholic
School"``): a list leaves those out or says them as the name's own qualifier."""
MUNICIPAL_QUALIFIERS: Final[frozenset[str]] = frozenset(
    {"city", "town", "township", "borough", "village"}
)
"""Qualifiers that say what kind of municipality a district's town is, which the
NCES name and a closings list each say or leave out as they please.

Tennessee's city districts are NCES's ``"Murfreesboro"`` and the lists'
``"Murfreesboro City Schools"``; Pennsylvania's township districts are NCES's
``"Bensalem Township SD"`` and the lists' ``"Bensalem School District"``; New
Jersey's are the other way round (``"Cherry Hill Township School District"`` for
NCES's ``"Cherry Hill School District"``). A municipal word that only one side
says costs nothing when no other record in the listing's scope shares the rest
of the name (see :meth:`~snowlight.match.index.NameIndex.search`); two that
both sides say must agree (``"Union City"`` is not ``"Union Township"``), and
``"Bristol School District"`` names neither ``"Bristol Township SD"`` nor
``"Bristol Borough SD"`` when both are there. ``County`` and ``Parish`` are no
municipality: ``"Lancaster"`` is never ``"Lancaster County"``. Only a word that ends a
name after a place's name is a qualifier at all (see :data:`QUALIFIERS`): the
``Village`` of ``"Village Christian Academy"`` is a word of its name, and
``"Christian Academy"`` is another school."""
COUNTY_LEVEL_QUALIFIERS: Final[frozenset[str]] = COUNTY_QUALIFIERS - MUNICIPAL_QUALIFIERS
"""``County`` and ``Parish``: a record's that a listing leaves out costs it (see
:data:`~snowlight.match.index.COUNTY_LEFT_OUT`)."""
SOFT_QUALIFIERS: Final[frozenset[str]] = frozenset({"area"})
"""Qualifiers a district calls itself by that its NCES name may leave out
(``"Elk River Area Schools"`` is NCES's ``"Elk River Public School District"``)."""

# Designators name the kind of body, not which one. They are stripped from the
# end of a name. Strong ones always go; "school" (singular) marks one school,
# the rest a district.
SCHOOL_DESIGNATORS: Final[frozenset[str]] = frozenset({"school"})
DISTRICT_DESIGNATORS: Final[frozenset[str]] = frozenset(
    {
        "schools",
        "district",
        "districts",
        "system",
        "systems",
        "corporation",
        "department",
        "public",
        "inc",
        "llc",
    }
)
STRONG_DESIGNATORS: Final[frozenset[str]] = SCHOOL_DESIGNATORS | DISTRICT_DESIGNATORS

# Weak designators are words a district's name carries for its legal form
# ("Waunakee Community School District", "Los Angeles Unified", "Riverhead
# Central School District", "Primero Reorganized School District No. 2",
# "Cleveland Municipal", which closings lists call "Cleveland Metropolitan",
# New York's "Tuckahoe Common School District", and "NEW YORK CITY GEOGRAPHIC
# DISTRICT #10", one of the city's districts). They
# are stripped only from district names, only from the end, and never when
# nothing else would remain ("Central SD" stays "central"). Longest phrase first.
WEAK_DESIGNATORS: Final[tuple[tuple[str, ...], ...]] = (
    ("union", "free"),
    ("community", "unit"),
    ("school", "administrative"),
    ("unified",),
    ("independent",),
    ("consolidated",),
    ("unit",),
    ("central",),
    ("community",),
    ("common",),
    ("joint",),
    ("metropolitan",),
    ("municipal",),
    ("administrative",),
    ("reorganized",),
    ("geographic",),
)

# Designators that make a listing read as district-level.
DISTRICT_HINTS: Final[frozenset[str]] = DISTRICT_DESIGNATORS - {"public", "inc", "llc"} | {
    "unified",
    "independent",
    "union free",
    "community unit",
    "board of education",
    "department of education",
    "school board",
}

DISTRICT_WORDS: Final[frozenset[str]] = frozenset(
    {
        "district",
        "districts",
        "system",
        "systems",
        "corporation",
        "department",
        "unified",
        "independent",
        "unit",
        "board",
        "boces",
    }
)
"""Words, anywhere in a name, that say it is a district, not one school or a group of
schools of one level: ``"Township High School District 214"``, ``"Siskiyou Union
High School District"``, ``"Clark County Unified"``, ``"Lake View Charter District"``
(see :func:`~snowlight.match.normalize.named_as_school`)."""

# Nouns that make a listing read as one school even without the word "school".
SCHOOL_NOUNS: Final[frozenset[str]] = frozenset(
    {"academy", "preparatory", "montessori", "institute", "center", "campus"}
)
TYPE_NOUNS: Final[frozenset[str]] = frozenset({"academy", "charter", "preparatory", "institute"})
"""Nouns that say what kind of school a name is. A listing that says one names a
record that says it too: ``"St. Johnsbury Academy"`` is not ``"St. Johnsbury
School"``, ``"Robert Frost Charter School"`` is not the public ``"Robert Frost"``
elementary school. A listing may leave out a record's (``"Lincoln"`` for
``"Lincoln Academy"``)."""

KIND_ONLY_WORDS: Final[frozenset[str]] = (
    SCHOOL_NOUNS
    | TYPE_NOUNS
    | frozenset(
        {
            "school",
            "schools",
            "prep",
            "learning",
            "community",
            "day",
            "care",
            "daycare",
            "child",
            "children",
            "childrens",
            "development",
            "early",
            "childhood",
            "education",
            "educational",
            "program",
            "programs",
            "alternative",
            "career",
            "technical",
            "technology",
            "vocational",
            "virtual",
            "online",
            "cyber",
            "magnet",
            "kid",
            "kids",
            "country",
            "public",
            "private",
            "independent",
            "arts",
            "art",
            "science",
            "sciences",
            "stem",
            "leadership",
            "international",
            "global",
            "classical",
            "collegiate",
            "academic",
            "christian",
            "catholic",
            "lutheran",
            "baptist",
            "episcopal",
            "adventist",
            "jewish",
            "hebrew",
            "islamic",
            "friends",
            "waldorf",
        }
    )
    | PLACE_KINDS
    | TOWN_QUALIFIERS
)
"""Words that say what kind of school or program a name is, not which one: a listing
of nothing else (``"Christian Academy"``, ``"Learning Center"``, ``"Day Care"``,
``"Community School"``, ``"Charter Academy"``) names only a school whose name it
is, word for word and in order (``"The Christian Academy"``, ``"The Learning
Center"``), never one that holds the same words among others or in another order
(``"The Academy Christian School"``, ``"Center for Learning"``, ``"High School in
the Community"``). So does a listing of place words alone (``"Village"``, ``"City
School"``), which names no place. See
:meth:`~snowlight.match.matcher.Matcher._names_only_a_kind`."""

BUSINESS_WORDS: Final[frozenset[str]] = frozenset(
    {"llc", "inc", "incorporated", "ltd", "pllc", "llp"}
)
"""Words that make a listing a business (``"Royston, LLC"``, ``"Penn Waste Inc."``)
unless it also says it is a school (``"River Academy of Excellence, LLC"``)."""

# Leading phrases that designate rather than name: "School District of
# Lancaster", "Public Schools of Robeson County", "Board of Education of ...".
LEADING_DESIGNATORS: Final[tuple[tuple[str, ...], ...]] = (
    ("school", "district", "of", "city", "of"),
    ("school", "district", "of"),
    ("public", "schools", "of"),
    ("schools", "of"),
    ("board", "of", "education", "of"),
)

# Words that barely identify a school: joining words, initials, affiliations.
WEAK_WORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "of",
        "at",
        "for",
        "in",
        "on",
        "a",
        "an",
        "to",
        "catholic",
        "christian",
        "lutheran",
        "baptist",
        "episcopal",
        "adventist",
        "parochial",
        "methodist",
        "presbyterian",
        "junior",
        "jr",
        "senior",
        "exempted",
    }
)
WEAK_WEIGHT: Final = 0.3
GENERIC_LEGAL_WORDS: Final[frozenset[str]] = frozenset(
    {
        "school",
        "district",
        "system",
        "corporation",
        "department",
        "board",
        "education",
        "inc",
        "llc",
    }
)
"""Legal-form words any kind of school district's name may carry, as
:func:`~snowlight.match.normalize.stem` gives them: they tell no two districts of
one town apart, unlike ``Public``, ``Community``, ``Independent`` or ``Unified``
(see :meth:`~snowlight.match.matcher.Matcher._legal_form_tie`)."""
DISTINCT_LEGAL_WORDS: Final[frozenset[str]] = frozenset(
    {"independent", "union", "joint", "common", "consolidated"}
)
"""Legal-form words that tell apart two districts of one name in two places.

Michigan's ``"Genesee ISD"`` is the county's intermediate district, not ``"Genesee
School District"`` of the township, and Texas's ``"Saltgrass ISD"`` is not the
charter district ``"Saltgrass Public Schools"``: a listing that says ``ISD`` names
the one whose name says it. So does one that says ``Union``, ``Joint`` or
``Common`` (``"Westside Union Elementary"`` is not ``"Westside Elementary"`` 260 km
away, though a list that says neither may mean either, and New York's
``"Tuckahoe Common School District"`` is not ``"Tuckahoe Union Free School
District"``), or ``Consolidated`` (Indiana's ``"Northwestern Consolidated School
Corporation"`` is NCES's ``"Northwestern Con School Corp"``, not its
``"Northwestern School Corp"`` two counties away). Other legal-form words are how
the directory happens
to write a name (New Jersey's ``"Washington Township School District"`` and
``"Washington Township Public School District"`` are two townships' systems either
of which a list may call ``"Washington Township Public Schools"``), and tell two
places apart no better than distance does."""

NAME_LIKE_LEGAL_WORDS: Final[frozenset[str]] = frozenset({"central", "union"})
"""Legal-form words that are as often a word of a district's name: Pennsylvania's
``"Manheim Central SD"`` beside ``"Manheim Township SD"``, Ohio's ``"North Union
Local"``. A listing that leaves one out (``"Manheim School District"``) says the
rest of that name no more surely than the rest of a township's whose ``Township``
it leaves out (see :meth:`~snowlight.match.matcher.Matcher._exact_tie`)."""

GENERIC_WORDS: Final[frozenset[str]] = frozenset({"school", "schools"})
"""Designators that stay among a name's words where they do not end it: ``"Village
Preparatory School Woodland Hills"``, ``"The Day School at the Children's
Institute"``, ``"Crawford County Schools-IN"``. They say what kind of body a name
is, not which, so they weigh :data:`WEAK_WEIGHT` in the matcher like joining words,
however rare they are among a directory's words (a small directory would
otherwise make ``School`` weigh as much as a town's name)."""

# Affiliations: words that say a school belongs to a church, a faith or a private
# school tradition. A listing that says one names only records that say it too:
# "Omaha Catholic Schools" is never the city's public district and never a
# public school, and "St. Mary's Catholic" is not "St. Mary's Lutheran". A
# listing may leave a record's affiliation out ("St. Mary's" for "St. Mary's
# Catholic School"). A public record carries one of these words only where it is
# part of its own name, which a listing for it repeats: a place ("Christian
# County", "Pass Christian"), a person ("Hans Christian Andersen"), a program (a
# public Montessori school, a Hebrew language charter school).
AFFILIATIONS: Final[frozenset[str]] = frozenset(
    {
        # churches and faiths
        "catholic",
        "christian",
        "lutheran",
        "baptist",
        "episcopal",
        "adventist",
        "methodist",
        "presbyterian",
        "pentecostal",
        "apostolic",
        "nazarene",
        "evangelical",
        "mennonite",
        "amish",
        "jesuit",
        "orthodox",
        "bible",
        "parochial",
        "diocese",
        "diocesan",
        "archdiocese",
        "archdiocesan",
        "jewish",
        "hebrew",
        "yeshiva",
        "torah",
        "chabad",
        "islamic",
        "muslim",
        # the Religious Society of Friends (Quakers): "Sidwell Friends School",
        # "Moorestown Friends", never Nebraska's public "Friend Public Schools"
        "friends",
        # private school traditions
        "montessori",
        "waldorf",
    }
)
# A church school named for a saint or a devotion ("St. Mary's Catholic School",
# "Sacred Heart Catholic School", "Our Lady of Lourdes Catholic School", "Holy
# Trinity Lutheran School") is often listed without its church ("St. Mary's",
# "Sacred Heart School"): its name already says what it is. Any other school's
# affiliation is part of its name, and a listing that leaves it out names
# another school: "Concord Academy" is not "Concord Christian Academy", and
# "Bridges Academy" is not "The Bridge Christian Academy".
DEVOTIONS: Final[frozenset[str]] = frozenset(
    {
        "saint",
        "sainte",
        "saints",
        "holy",
        "sacred",
        "lady",
        "immaculate",
        "blessed",
        "nativity",
        "assumption",
        "annunciation",
        "resurrection",
        "visitation",
        "incarnation",
        "ascension",
        "epiphany",
        "transfiguration",
        "presentation",
        "redeemer",
        "christ",
    }
)
"""Words of a saint's or a devotion's name, in canonical spelling (``St.`` is
``saint``): a record whose name holds one may be listed without its affiliation."""

LOOSE_PLURALS: Final[frozenset[str]] = frozenset(
    {"art", "science", "letter", "program", "service", "school", "center", "system"}
    | {"scholar", "leader", "kid", "friend", "sport", "skill", "language", "career"}
    | {"pathway", "option", "academic", "trade", "learner", "explorer", "achiever"}
    | {"builder", "innovator", "thinker", "engineer", "project", "resource", "solution"}
    | {"partner", "connection", "student", "girl", "boy", "woman", "craft", "athletic"}
)
"""Words a school's name and a list write with a plural's ``s`` or without it alike, as
the name's kind of school rather than which one (``"School for the Arts and
Science"``, ``"Central School Programs"``, ``"Normandy Schools Collaborative"``,
``"Guadalupe Centers Schools"``), in the singular form a name's tokens take. Any other
word written so on one side only is another word (``"Parks"`` is not ``"Park"``, see
:data:`snowlight.match.index.PLURAL_DIFFERS`)."""

PARISH_AFFILIATIONS: Final[frozenset[str]] = frozenset({"catholic", "parochial"})
"""What a saint's or a devotion's private school is when its name says no church:
a Catholic parish's (``"St. Peter's Catholic School"`` is NCES's ``"ST PETER'S
SCHOOL"``)."""
PARISH_NAMES: Final[frozenset[str]] = DEVOTIONS | frozenset(
    {
        "shepherd",
        "trinity",
        "rosary",
        "savior",
        "saviour",
        "guardian",
        "angels",
        "martyrs",
        "apostles",
        "calvary",
        "guadalupe",
        "lourdes",
        "fatima",
        "mercy",
    }
)
"""Words of the name a parish and its school share (``"St. Peter's"``, ``"Christ the
King"``, ``"Visitation"``, ``"Good Shepherd"``, ``"Holy Trinity"``): a listing that
says one and nothing of a school may be the church."""
CHURCH_FAITHS: Final[frozenset[str]] = frozenset(
    {"lutheran", "baptist", "episcopal", "methodist", "presbyterian", "pentecostal"}
    | {"apostolic", "nazarene", "evangelical", "mennonite", "adventist", "orthodox", "bible"}
)
"""Faiths a church names itself by (``"Immanuel Lutheran"``, ``"Lake Orion
Baptist"``). Not ``Christian`` or ``Catholic``, which a list writes after a town
for its school (``"Southfield Christian"``, ``"Lowell Catholic"``) where a church
says ``Church``; nor a school tradition or a diocese's office."""

# An affiliation word right before one of these names a place, not a faith:
# "Christian County", "St. John the Baptist Parish".
AFFILIATION_PLACES: Final[frozenset[str]] = frozenset({"county", "parish"})
# An affiliation word right after one of these is part of a saint's name: "St.
# John the Baptist" (``the`` is dropped before this is read) is a Catholic
# parish's patron, not a Baptist church.
AFFILIATION_SAINTS: Final[dict[str, frozenset[str]]] = {"baptist": frozenset({"john"})}
SAINT_EPITHETS: Final[dict[str, str]] = {"baptist": "thebaptist"}
"""The token a saint's epithet that is also an affiliation word takes in a name.

An affiliation word weighs little (:data:`WEAK_WORDS`), as a faith a list may leave
out; ``Baptist`` after ``John`` (:data:`AFFILIATION_SAINTS`) is no faith but the
saint's name, which says which of the saints named John a parish's school is named
for, as ``Evangelist`` does: ``"St. John the Baptist School"`` is not ``"ST JOHN
SCHOOL"`` (the Evangelist's, as like as not), and the other way round. So it weighs
as a name's word, under a token of its own."""
# An affiliation word right before one of these names something else: "Friends of
# the Library", "Amigos Por Vida-Friends for Life", which no Quaker meeting runs.
AFFILIATION_NOT_BEFORE: Final[dict[str, frozenset[str]]] = {"friends": frozenset({"of", "for"})}

# Child care chains. Their centres share one brand and many are in the private
# school universe (a Goddard School that teaches kindergarten), so a closings list
# names one by its brand: "Goddard School" is a Goddard School, never the public
# "Goddard Middle School" or "Goddard High". A chain's name, in canonical words,
# is read like an affiliation: a listing that says it names only a record whose
# name says it too. A possessive's "'s" goes before this is read ("Children's" is
# ``children``).
CHAINS: Final[dict[tuple[str, ...], str]] = {
    ("goddard", "school"): "goddard school",
    ("primrose", "school"): "primrose school",
    ("kindercare",): "kindercare",
    ("kinder", "care"): "kindercare",
    ("kiddie", "academy"): "kiddie academy",
    ("learning", "experience"): "learning experience",
    ("bright", "horizons"): "bright horizons",
    ("tutor", "time"): "tutor time",
    ("la", "petite", "academy"): "la petite academy",
    ("childtime",): "childtime",
    ("children", "lighthouse"): "childrens lighthouse",
    ("kids", "r", "kids"): "kids r kids",
    ("lightbridge", "academy"): "lightbridge academy",
    ("celebree", "school"): "celebree school",
    ("creative", "world", "school"): "creative world school",
    ("guidepost", "montessori"): "guidepost montessori",
}
"""Child care chains' names, as canonical words, and the brand each says."""
CHAIN_BRANDS: Final[frozenset[str]] = frozenset(CHAINS.values())
"""The brands :data:`CHAINS` say. Unlike a faith, a brand a record's name says and a
listing leaves out costs nothing: ``"Primrose of Midlothian Village"`` is the
``"Primrose School of Midlothian Village"``, whose other words it says."""

# Designators that, on their own, cannot tell a public district from a private
# school system: "Grand Rapids Christian Schools" is one private school's name.
# A listing that names an affiliation reads as a district only when it also says
# something only a public body says ("District", "Public", "ISD", "Board of
# Education").
SYSTEM_DESIGNATORS: Final[frozenset[str]] = frozenset({"schools", "system", "systems"})

# Words that name a college, university or seminary rather than a K-12 school
# when they end the name or begin "... of X": "Boston College", "Dallas College",
# "University of Denver", "Harrisburg Area Community College". They mean
# something else before a place word ("College Park", "University Heights"),
# after a program word ("Early College", "Middle College", "Gateway to
# College"), and in a name that also says it is a K-12 school ("Boston College
# High School", "Boston University Academy").
NON_K12: Final[frozenset[str]] = frozenset({"college", "university", "seminary"})
NON_K12_PROGRAMS: Final[frozenset[str]] = frozenset({"early", "middle", "mid", "to"})
# Words after a NON_K12 word that still leave it ending the name.
NON_K12_TRAILERS: Final[frozenset[str]] = frozenset(
    {"district", "system", "systems", "campus", "campuses", "inc", "llc"}
)
# Words that say a name is a K-12 school.
K12_WORDS: Final[frozenset[str]] = LEVELS | frozenset(
    {"school", "schools", "academy", "preparatory", "charter", "secondary"}
)

# Words that make a listing name one school where it would otherwise read as a
# bare name: "Valley School of Ligonier" is a private school, never the town's
# "Ligonier Valley SD"; "Iowa School for the Deaf" is one school.
ONE_SCHOOL_LINKS: Final[frozenset[str]] = frozenset({"of", "for"})
"""A word after ``school`` (singular) that makes the name one school's."""

# "Early Learning Center", "Early Childhood Center" and "Center for Early
# Education" name prekindergarten programs: "early" before one of these words
# is the prekindergarten level, so such a listing never takes the town's
# "Learning Center" (an alternative high school) or its elementary school.
EARLY_PROGRAMS: Final[frozenset[str]] = frozenset({"learning", "childhood", "education"})

# Sections. Many lists file each listing under a section ("Schools",
# "Churches", "Business", "Gov't.", "Pre-Schools/Daycare"), which a caller may
# pass on (see :func:`~snowlight.match.normalize.listing_section`).
SCHOOL_SECTIONS: Final[frozenset[str]] = frozenset(
    {"school", "schools", "sch", "schls", "district", "districts", "education", "k12"}
    | {"parochial", "academies", "private", "charter"}
)
"""Words of a section that files K-12 schools (``"KY Private"``, ``"Private &
Charter Schools"``)."""
OTHER_SECTIONS: Final[frozenset[str]] = frozenset(
    {"church", "churches", "worship", "ministries", "synagogue", "synagogues"}
    | {"temple", "temples", "mosque"}
    | {"business", "businesses", "government", "govt", "gov", "munic", "municipal"}
    | {"municipalities", "civic", "daycare", "daycares", "childcare", "preschool"}
    | {"preschools", "preskl", "prek", "nursery", "health", "medical", "hospital"}
    | {"hospitals", "college", "colleges", "university", "universities", "parking"}
    | {"activities", "activ", "events"}
)
"""Words of a section that files churches, businesses, governments, day cares,
colleges and events: none of its listings is a K-12 school's unless its words say
so. Not ``Religious``, under which some lists file their private schools."""
SECTION_PHRASES: Final[tuple[tuple[str, str], ...]] = (
    ("pre school", "preschool"),
    ("pre schools", "preschools"),
    ("pre k", "prek"),
    ("day care", "daycare"),
    ("child care", "childcare"),
)
"""Spellings of a section's words in two, as one."""

# Virtual schools. NCES places one at its operator's office, often across the
# state from the county district that runs it ("Tennessee Connections Academy
# Johnson County 4-8" in White House): it says nothing of where the district is.
VIRTUAL: Final[tuple[tuple[str, ...], ...]] = (
    ("virtual",),
    ("online",),
    ("cyber",),
    ("eschool",),
    ("connections", "academy"),
    ("distance", "learning"),
)
"""Words that say a school teaches online, in folded spelling."""

# Civic bodies. A closings list carries city halls, libraries, senior centers,
# churches and hospitals beside schools, and they share their town's name with
# its district: "City of Monessen" is the city, not "Monessen City SD", and
# "Sabine Pass Senior Center" is not "Sabine Pass School". A listing that names
# one of these and nothing K-12 names no school.
MUNICIPAL_BODIES: Final[frozenset[str]] = frozenset(
    {"city", "town", "village", "borough", "township", "county", "parish", "state"}
)
"""Government words: a name that begins ``"<one of these> of"`` names a government
(``"City of Monessen"``, ``"Village of Oak Park"``, ``"Town of Webb"``)."""
MUNICIPAL_OFFICES: Final[frozenset[str]] = frozenset(
    {
        "hall",
        "offices",
        "office",
        "council",
        "commission",
        "commissioners",
        "court",
        "courts",
        "clerk",
        "treasurer",
        "government",
        "building",
        "buildings",
        "facilities",
        "board",
        "supervisors",
        "trustee",
        "trustees",
        "assessor",
        "auditor",
        "recorder",
        "attorney",
        "prosecutor",
        "probate",
        "judicial",
        "election",
        "elections",
        "tax",
        "sheriff",
        "jail",
        "parks",
        "fair",
        "fairgrounds",
        "museum",
        "airport",
        "health",
        "extension",
        "highway",
        "roads",
        "road",
        "engineer",
        "landfill",
        "recycling",
        "water",
        "sewer",
        "utilities",
        "bank",
    }
)
"""Words that, right after a government word, name its offices or services
(``"Monessen City Hall"``, ``"Orange Beach City Offices"``, ``"Cass County Council
on Aging"``, ``"Prince William County Parks"``, ``"Polk County Board of
Supervisors"``). A school district's own board says ``Education`` or ``School``,
which :data:`CIVIC_EXEMPT` reads first."""
CIVIC_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    # government
    ("government",),
    ("govt",),
    ("courthouse",),
    ("department",),
    ("authority",),
    ("municipal", "court"),
    ("district", "court"),
    ("circuit", "court"),
    ("superior", "court"),
    ("magistrate",),
    ("municipal", "building"),
    ("municipal", "offices"),
    ("municipal", "office"),
    ("municipal", "center"),
    ("municipal", "complex"),
    ("police",),
    ("sheriff",),
    ("fire", "district"),
    ("fire", "station"),
    ("fire", "company"),
    ("fire", "hall"),
    ("fire", "rescue"),
    ("fire", "protection"),
    ("volunteer", "fire"),
    ("water", "district"),
    ("water", "works"),
    ("public", "works"),
    ("park", "district"),
    ("transit",),
    ("sanitation",),
    ("post", "office"),
    # community places
    ("library",),
    ("libraries",),
    ("senior", "center"),
    ("senior", "citizens"),
    ("senior", "services"),
    ("senior", "dining"),
    ("community", "center"),
    ("recreation",),
    ("ymca",),
    ("ywca",),
    ("boys", "and", "girls", "club"),
    ("chamber", "of", "commerce"),
    ("meals", "on", "wheels"),
    ("salvation", "army"),
    ("pantry",),
    ("shelter",),
    ("on", "aging"),
    ("credit", "union"),
    ("food", "bank"),
    ("extension", "office"),
    # clubs and youth programs outside school
    ("4", "h"),
    ("4h",),
    ("scouts",),
    ("troop",),
    ("little", "league"),
    # health
    ("hospital",),
    ("hospitals",),
    ("clinic",),
    ("clinics",),
    ("medical", "center"),
    ("health", "center"),
    ("urgent", "care"),
    # worship
    ("church",),
    ("churches",),
    ("chapel",),
    ("cathedral",),
    ("basilica",),
    ("umc",),
    ("ucc",),
    ("synagogue",),
    ("mosque",),
    ("ministries",),
    ("assembly", "of", "god"),
    ("worship",),
    ("no", "mass"),
    ("masses",),
    ("mass", "canceled"),
    ("mass", "cancelled"),
    ("sunday", "mass"),
    ("daily", "mass"),
    ("weekday", "mass"),
    ("mass", "times"),
    ("mass", "schedule"),
    ("religious", "education"),
    ("faith", "formation"),
    ("bible", "study"),
    ("sunday", "school"),
    ("vacation", "bible", "school"),
    ("ccd",),
)
"""Words that name a government office, a community place, a hospital or a place of
worship, in canonical spelling (``"Dept."`` is ``department``, ``"Sr. Ctr."`` is
``senior center``, ``"4-H"`` is ``4 h``). Chosen so that a K-12 school's name
rarely holds one without also saying ``School`` or a level: ``temple`` and
``parish`` are left out (``"Temple ISD"``, ``"Acadia Parish"``; a parish is read
apart, see :func:`~snowlight.match.normalize.not_school`), ``chapel`` and
``cathedral`` count only where they name the place (``"Chapel Hill"`` and
``"Cathedral City"`` are towns, :data:`CIVIC_IN_NAMES`), ``fire`` counts only
beside a word that makes it a fire company (``"Fire Island"``, ``"Fire Ridge"``
are places), and a Mass only in words that say a church's (``"No Mass"``,
``"Masses"``), not ``"Mass."``, Massachusetts. ``"Sunday School"`` and
``"Vacation Bible School"`` are a church's classes, whose ``School`` says nothing
K-12."""
CIVIC_IN_NAMES: Final[frozenset[str]] = frozenset(
    {"church", "churches", "shelter", "chapel", "cathedral", "basilica"}
)
"""One-word entries of :data:`CIVIC_PHRASES` that also stand inside the name of a
person or a place: ``"Mary Church Terrell"``, ``"Church Point"``, ``"Shelter
Cove"``, ``"Chapel Hill"``, ``"Cathedral City"``. One names a civic body only
where it ends a part of the listing (``"Farrowdale United Methodist Church"``),
comes before ``of`` or ``on`` (``"First Baptist Church of Marion"``, ``"Church on
the Rock"``) or after a faith (``"First Baptist Church Daycare"``)."""
CHURCH_CLASSES: Final[frozenset[tuple[str, ...]]] = frozenset(
    {("sunday", "school"), ("vacation", "bible", "school"), ("religious", "education")}
)
"""A church's classes, whose last word (``school``, ``education``) does not make a
listing K-12. A ``"Bible School"`` alone may be one (``"Athens Bible School"``)."""
PARISH: Final = "parish"
"""A parish is a church (``"St. Peter's Parish"``, ``"Christ the King Parish"``) or,
in Louisiana, a county (``"Acadia Parish"``), whose district a list names bare."""
CIVIC_IN_NAMES_LINKS: Final[frozenset[str]] = frozenset({"of", "on"})
CIVIC_EXEMPT: Final[frozenset[str]] = K12_WORDS | frozenset({"education", "ps"})
"""Words that say a listing is about schools after all: ``"City of Chicago SD 299"``,
``"Township of Ocean School District"``, ``"Los Angeles County Office of
Education"``, ``"Harwick County Board of Education"``, New York City's ``"P.S. 124
Osmond A. Church"``."""

# States. A closings list that covers several states writes a district's state
# beside its name to tell namesakes apart: "Salem MA Public", "Knox County, TN
# Schools", "Collinsville (TX) ISD", "WASHINGTON COUNTY SCHOOLS-KY", "Holden
# R-III School Holden MO", "Salem, Ark.". See :mod:`snowlight.match.states`.
STATE_NAMES: Final[dict[str, str]] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
"""USPS codes and the states' names."""
STATE_ABBREVIATIONS: Final[dict[str, str]] = {
    "Ala.": "AL",
    "Ariz.": "AZ",
    "Ark.": "AR",
    "Calif.": "CA",
    "Cal.": "CA",
    "Colo.": "CO",
    "Conn.": "CT",
    "D.C.": "DC",
    "Fla.": "FL",
    "Ga.": "GA",
    "Ill.": "IL",
    "Kan.": "KS",
    "Kans.": "KS",
    "Ky.": "KY",
    "Mass.": "MA",
    "Md.": "MD",
    "Mich.": "MI",
    "Minn.": "MN",
    "Mo.": "MO",
    "Neb.": "NE",
    "Nebr.": "NE",
    "Nev.": "NV",
    "N.H.": "NH",
    "N.J.": "NJ",
    "N.M.": "NM",
    "N.Y.": "NY",
    "N.C.": "NC",
    "N.D.": "ND",
    "Okla.": "OK",
    "Ore.": "OR",
    "Oreg.": "OR",
    "Pa.": "PA",
    "R.I.": "RI",
    "S.C.": "SC",
    "Tenn.": "TN",
    "Tex.": "TX",
    "Vt.": "VT",
    "Va.": "VA",
    "W.Va.": "WV",
    "W. Va.": "WV",
    "Wis.": "WI",
    "Wisc.": "WI",
    "Wyo.": "WY",
    # These also abbreviate words names use ("Ind." is Independent, "Wash." is
    # Washington, "Del." begins "Del Norte", "S.D." is School District): a state
    # only where one stands alone.
    "Ind.": "IN",
    "Wash.": "WA",
    "La.": "LA",
    "Miss.": "MS",
    "Me.": "ME",
    "Del.": "DE",
    "Mont.": "MT",
    "S.D.": "SD",
}
"""The newspaper abbreviations of the states' names, with their periods."""
LOOSE_STATE_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {"Ind.", "Wash.", "La.", "Miss.", "Me.", "Del.", "Mont.", "S.D."}
)
"""Abbreviations in :data:`STATE_ABBREVIATIONS` that also shorten a word of a name."""
LOOSE_STATE_CODES: Final[frozenset[str]] = frozenset(
    {"IN", "OR", "ME", "OK", "HI", "OH", "DE", "AL", "LA", "MS", "SD", "CO", "MT", "NE", "ID"}
)
"""USPS codes that are also words, abbreviations or parts of names a listing uses:
``"in"``, ``"or"``, ``MS`` (Middle School: ``"Germantown MS"``), ``SD`` (School
District: ``"Brandon Valley SD"``), ``CO`` (County: ``"DOUGLAS CO SCHOOLS"``),
``MT`` (Mount), ``NE`` (Northeast), ``De``, ``La`` and ``Al`` in names. One of
these is a state only where a state stands alone: in brackets, or after a comma
or a hyphen (``"Holly Springs, MS"``, ``"MADISON SCHOOLS-IN"``)."""
REGION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "north",
        "south",
        "east",
        "west",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
        "northern",
        "southern",
        "eastern",
        "western",
        "northeastern",
        "northwestern",
        "southeastern",
        "southwestern",
        "central",
        "mid",
        "middle",
        "upper",
        "lower",
        "greater",
        "inland",
        "coastal",
        "downeast",
        "upstate",
        "downstate",
        "n",
        "s",
        "e",
        "w",
        "ne",
        "nw",
        "se",
        "sw",
        "no",
        "so",
    }
)
"""Words that make the state after them part of a name: ``"Southern NH Montessori
Academy"``, ``"Western PA School for the Deaf"``, ``"Central VA. Training
Center"``, ``"MID-MI Leadership Academy"``."""
STATE_NAME_LINKS: Final[frozenset[str]] = frozenset(
    {"of", "for", "the", "in", "at", "and", "to", "from", "on"}
)
"""Words that make the state after them part of a name: ``"Railroad Museum of PA"``,
``"Girls Inc of NH"``, ``"Great Path Academy at CT State"``."""
