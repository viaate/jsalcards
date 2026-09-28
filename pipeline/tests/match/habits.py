"""SYNTHETIC districts named with NCES's naming habits, and listings that name them as lists do.

NOT REAL DATA. The NCES directory names many districts one way and the closings
lists name them another, the same way every time, state by state:

* Tennessee names a city's district by the city alone (``"Murfreesboro"``); the
  lists say ``"<city> City Schools"``.
* Michigan's intermediate school districts are NCES's ``"<county> ISD"``; the
  lists say ``"<county> Intermediate School District"``, ``"Int. School
  District"`` or ``"Intermediate SD"``.
* Indiana's are ``"<town> Com Sch Corp"``, ``"<town> Con School Corp"``,
  ``"<town> Cnt Com Sch Corp"`` and ``"<county> Co Com Sch Corp"``; the lists
  spell them out.
* Pennsylvania's township districts are ``"<town> Township SD"``; the lists
  often leave ``Township`` out. New Jersey's are the other way round: NCES leaves
  it out (``"Cherry Hill School District"``) and the lists say it.
* Texas's ``"EAGLE MT-SAGINAW ISD"`` is the lists' ``"Eagle Mountain Saginaw ISD"``.
* Ohio names some city districts ``"<town> Local"``; the lists say ``"<town> City
  Schools"``.

:func:`build` generates such a directory, state by state, from made-up town and
county names (ids ``SYN-HAB-...``, county codes starting with ``7``, points on an
arbitrary grid), and listings for every district in the lists' forms. Each
listing is labelled by how it was made, not by the matcher: the district it was
written for, or none where the generator put a second district that bears the
rest of the name beside it (a township's and a borough's of one name, a city
whose county's district bears its name, two Indiana districts of one name), which
is what makes the municipal word or the legal form the only thing that tells
them apart.
"""

import random
from dataclasses import dataclass

from snowlight.match import DirectoryRecord

FIRST: tuple[str, ...] = (
    "Mur", "Tull", "Alc", "Bart", "Dyer", "Eliz", "Green", "Mary", "Sweet", "Manch",
    "Fay", "Brook", "Carr", "Dell", "Fenn", "Gart", "Harl", "Ivor", "Jess", "Kerr",
    "Lind", "Morr", "Nels", "Orr", "Penn", "Quin", "Ross", "Sand", "Tarr", "Vand",
    "Wick", "Yard", "Zell", "Aber", "Bell", "Cald", "Dunn", "Ells", "Frank", "Gill",
)  # fmt: skip
SECOND: tuple[str, ...] = (
    "by", "ton", "ville", "field", "ford", "ham", "dale", "mont", "stead", "worth",
)  # fmt: skip
COUNTY_ROOTS: tuple[str, ...] = (
    "Abernath", "Blackwood", "Carrowell", "Delacour", "Ellerby", "Fairbank", "Gorsham",
    "Hallorin", "Ingram", "Jarrow", "Kinsale", "Lorring", "Merrin", "Norcott", "Oglethorn",
    "Pendrell", "Quimbell", "Rutledge", "Standwick", "Tollard", "Upsham", "Vickers",
    "Whitlow", "Yardell", "Zimmerly", "Ashcott", "Bellamore", "Crowther", "Dunleigh",
    "Everard", "Fenwright", "Garrick", "Hollister", "Iverson", "Kimbrell", "Lathrop",
)  # fmt: skip
DIRECTIONS: tuple[str, ...] = ("North", "South", "East", "West")

HABITS: tuple[str, ...] = (
    "TN city districts",
    "MI intermediate districts",
    "IN abbreviations",
    "PA townships",
    "NJ townships",
    "TX Mt",
    "OH city districts named Local",
)


@dataclass(frozen=True, slots=True)
class HabitCase:
    """A listing written for a district in a list's form, and the answer it should get."""

    listing: str
    state: str
    expected: str | None
    habit: str
    counties: tuple[str, ...] | None = None
    note: str = ""


class _Builder:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311 - test data, not cryptography
        self.records: list[DirectoryRecord] = []
        self.cases: list[HabitCase] = []
        self.count = 0
        self.towns = [first + second for first in FIRST for second in SECOND]
        self.rng.shuffle(self.towns)
        self.roots = list(COUNTY_ROOTS)
        self.rng.shuffle(self.roots)

    def town(self) -> str:
        return self.towns.pop()

    def root(self) -> str:
        """A county's name, or a town's once the counties' names run out."""
        return self.roots.pop() if self.roots else self.town()

    def _id(self) -> str:
        self.count += 1
        return f"SYN-HAB-{self.count:05d}"

    def district(
        self, name: str, state: str, county: str, city: str, point: tuple[float, float]
    ) -> str:
        record_id = self._id()
        self.records.append(
            DirectoryRecord(record_id, name, "district", None, state, county, city, *point)
        )
        return record_id

    def school(  # noqa: PLR0913, PLR0917 - one argument per NCES column
        self,
        name: str,
        district: str,
        state: str,
        county: str,
        city: str,
        point: tuple[float, float],
    ) -> str:
        record_id = self._id()
        self.records.append(
            DirectoryRecord(record_id, name, "school", district, state, county, city, *point)
        )
        return record_id

    def case(  # noqa: PLR0913, PLR0917 - one argument per field of a case
        self,
        listing: str,
        state: str,
        expected: str | None,
        habit: str,
        county: str,
        note: str = "",
    ) -> None:
        """A listing read statewide, and again in its district's county."""
        self.cases.append(HabitCase(listing, state, expected, habit, None, note))
        self.cases.append(HabitCase(listing, state, expected, habit, (county,), note))


def _county(slot: int, index: int) -> tuple[str, tuple[float, float]]:
    """A county's code and centre: counties lie two degrees apart, far beyond reach."""
    code = f"7{slot:02d}{index:02d}"
    point = (30.0 + 2.0 * (index % 8), -120.0 + 2.0 * (index // 8) + 10.0 * slot)
    return code, point


def _tennessee(build: _Builder) -> None:
    """City districts named by the city alone, beside their counties' districts."""
    habit, state = HABITS[0], "TN"
    for i in range(24):
        county, point = _county(1, i)
        town = build.town()
        # One county in six bears the town's name, as a city's county may.
        shared = i % 6 == 0
        root = town if shared else build.root()
        city = build.district(town, state, county, town, point)
        build.school(f"{town} Elementary", city, state, county, town, point)
        build.school(f"{town} High School", city, state, county, town, point)
        county_district = build.district(f"{root} County", state, county, town, point)
        build.school(f"{root} County High School", county_district, state, county, town, point)
        expected = None if shared else city
        note = "its county's district bears the name" if shared else ""
        for form in ("{t} City Schools", "{t} City School District", "{T} CITY SCHOOLS"):
            listing = form.format(t=town, T=town.upper())
            build.case(listing, state, expected, habit, county, note)
        build.case(f"{root} County Schools", state, county_district, habit, county)


def _michigan(build: _Builder) -> None:
    """County intermediate school districts, some beside a public district of one name."""
    habit, state = HABITS[1], "MI"
    forms = (
        "{r} Intermediate School District",
        "{r} Int. School District",
        "{r} Intermediate SD",
        "{r} Intermediate District",
    )
    for i in range(20):
        county, point = _county(2, i)
        root = build.root()
        seat = build.town()
        isd = build.district(f"{root} ISD", state, county, seat, point)
        for form in forms:
            build.case(form.format(r=root), state, isd, habit, county)
        if i % 3 == 0:
            public = build.district(f"{root} Public Schools", state, county, root, point)
            build.case(f"{root} Public Schools", state, public, habit, county)
            build.case(
                f"{root} Intermediate School",
                state,
                None,
                habit,
                county,
                "a school's level, not the county's district",
            )


_INDIANA_FORMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "com": (
        "{n} Com Sch Corp",
        ("{n} Community Schools", "{n} Community School Corporation", "{n} Comm. Schools"),
    ),
    "com school": ("{n} Com School Corp", ("{n} Community Schools",)),
    "com schools": ("{n} Com Schools", ("{n} Community Schools", "{n} Community School Corp.")),
    "con": (
        "{n} Con School Corp",
        ("{n} Consolidated School Corporation", "{n} Consolidated Schools"),
    ),
    "cnt": (
        "{n} Cnt Com Sch Corp",
        ("{n} Central Community Schools", "{n} Central Community School Corporation"),
    ),
}


def _indiana(build: _Builder) -> None:
    """NCES's "Com", "Con", "Cnt" and "Co", and two districts of one name, one "Con"."""
    habit, state = HABITS[2], "IN"
    kinds = sorted(_INDIANA_FORMS)
    for i in range(30):
        county, point = _county(3, i)
        town = build.town()
        name = f"{build.rng.choice(DIRECTIONS)} {town}" if i % 5 == 0 else town
        nces, listings = _INDIANA_FORMS[kinds[i % len(kinds)]]
        district = build.district(nces.format(n=name), state, county, town, point)
        build.school(f"{name} High School", district, state, county, town, point)
        for listing in listings:
            build.case(listing.format(n=name), state, district, habit, county)
    for i in range(30, 36):
        county, point = _county(3, i)
        root = build.root()
        district = build.district(f"{root} Co Com Sch Corp", state, county, root, point)
        for listing in ("{r} County Community Schools", "{r} Co. Community Schools"):
            build.case(listing.format(r=root), state, district, habit, county)
    for i in range(36, 44, 2):
        county, point = _county(3, i)
        other, other_point = _county(3, i + 1)
        town = build.town()
        con = build.district(f"{town} Con School Corp", state, county, town, point)
        plain = build.district(f"{town} School Corp", state, other, town, other_point)
        build.case(f"{town} Consolidated School Corporation", state, con, habit, county)
        # Statewide, a name both bear is neither's; in its own county, the one there.
        build.cases.append(
            HabitCase(
                f"{town} School Corporation",
                state,
                None,
                habit,
                None,
                "two of one name two counties apart, one Consolidated",
            )
        )
        build.cases.append(HabitCase(f"{town} School Corporation", state, plain, habit, (other,)))


def _pennsylvania(build: _Builder) -> None:
    """Township districts alone, beside a borough's, and beside one whose Central names it."""
    habit, state = HABITS[3], "PA"
    for i in range(30):
        county, point = _county(4, i)
        town = build.town()
        township = build.district(f"{town} Township SD", state, county, town, point)
        build.school(f"{town} Twp HS", township, state, county, town, point)
        build.case(f"{town} Township School District", state, township, habit, county)
        build.case(f"{town} Twp. SD", state, township, habit, county)
        pair = i % 3
        if pair == 1:
            borough = build.district(f"{town} Borough SD", state, county, town, point)
            build.case(f"{town} Borough School District", state, borough, habit, county)
        elif pair == 2:
            central = build.district(f"{town} Central SD", state, county, town, point)
            build.case(f"{town} Central School District", state, central, habit, county)
        expected = township if pair == 0 else None
        note = "" if pair == 0 else "another district bears the rest of the name"
        for form in ("{t} School District", "{t} Schools", "{t} SD"):
            build.case(form.format(t=town), state, expected, habit, county, note)
        if pair == 0:
            build.case(
                f"{town} Borough",
                state,
                None,
                habit,
                county,
                "a borough, and no school's word",
            )


def _new_jersey(build: _Builder) -> None:
    """Township districts NCES names without "Township", and a city's and a township's."""
    habit, state = HABITS[4], "NJ"
    for i in range(30):
        county, point = _county(5, i)
        town = build.town()
        kind = i % 3
        if kind == 0:
            district = build.district(f"{town} School District", state, county, town, point)
            for form in (
                "{t} Township School District",
                "{t} Twp. Public Schools",
                "{t} Borough School District",
            ):
                build.case(form.format(t=town), state, district, habit, county)
        elif kind == 1:
            district = build.district(
                f"{town} Township School District", state, county, town, point
            )
            for form in ("{t} School District", "{t} Public Schools"):
                build.case(form.format(t=town), state, district, habit, county)
        else:
            city = build.district(f"{town} City School District", state, county, town, point)
            township = build.district(
                f"{town} Township School District", state, county, town, point
            )
            build.case(f"{town} City Schools", state, city, habit, county)
            build.case(f"{town} Township Schools", state, township, habit, county)
            note = "a city's and a township's of one name"
            build.case(f"{town} Schools", state, None, habit, county, note)
            build.case(f"{town} Borough Schools", state, None, habit, county, note)


def _texas(build: _Builder) -> None:
    """Districts whose NCES name joins two names with "MT-"."""
    habit, state = HABITS[5], "TX"
    for i in range(12):
        county, point = _county(6, i)
        first, second = build.town(), build.town()
        district = build.district(
            f"{first.upper()} MT-{second.upper()} ISD", state, county, second.upper(), point
        )
        build.district(f"{second.upper()} ISD", state, county, second.upper(), point)
        for form in (
            "{f} Mountain {s} ISD",
            "{f} Mountain-{s} ISD",
            "{f} Mt. {s} ISD",
            "{f} Mountain {s} Independent School District",
        ):
            build.case(form.format(f=first, s=second), state, district, habit, county)


def _ohio(build: _Builder) -> None:
    """City districts NCES names "Local", some beside a city district of one name."""
    habit, state = HABITS[6], "OH"
    for i in range(15):
        county, point = _county(7, i)
        town = build.town()
        local = build.district(f"{town} Local", state, county, town, point)
        if i % 3:
            build.case(f"{town} City Schools", state, local, habit, county)
            build.case(f"{town} Local Schools", state, local, habit, county)
            continue
        city = build.district(f"{town} City", state, county, town, point)
        build.case(f"{town} City Schools", state, city, habit, county)
        build.case(f"{town} Local Schools", state, local, habit, county)
        build.case(f"{town} Schools", state, None, habit, county, "a city's and a local's")


def build(seed: int) -> tuple[list[DirectoryRecord], list[HabitCase]]:
    """The synthetic directory and its labelled listings, one state per habit."""
    builder = _Builder(seed)
    for step in (_tennessee, _michigan, _indiana, _pennsylvania, _new_jersey, _texas, _ohio):
        step(builder)
    return builder.records, builder.cases
