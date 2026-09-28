"""SYNTHETIC hand-written directory and labelled listings for the matcher tests.

NOT REAL DATA. The records below are written by hand to put the matcher's hard
cases side by side: namesakes in other states, ``Lancaster`` next to
``Lancaster County``, ``St. Mary's`` in two counties, districts that differ only
by a number, a level or a qualifier. Their names imitate NCES naming habits;
their ids (``SYN-...``), county codes (``8....``, a range no state uses) and
coordinates are made up and describe no real place.

Four made-up charter networks in Texas put campuses in cities hundreds of
kilometres apart, beside a district that straddles a county line and a county's
district with one virtual school registered to it across the state.

Schools whose names begin with a place word or hold one with more of the name
after it (``"VILLAGE CHRISTIAN ACADEMY"``, ``"TOWN & COUNTRY DAY SCHOOL"``,
``"CITY ACADEMY"``, ``"KID CITY ACADEMY"``) stand beside listings that leave the
word out (``"Christian Academy"``, ``"Country Day School"``, ``"Academy"``,
``"Kids Academy"``), which name none of them.

Schools of one name in one market's counties (a Boston-like list's two ``"ST JOHN
SCHOOL"`` 17 km apart, one beside its point; a Chicago-like list's three districts'
``"WALSH ELEM SCHOOL"``) go to the queue whatever the point; beside them lie
namesakes a point may tell apart, one just past the counties and one beyond a
market's reach. Saints' schools whose epithet or pope's numeral tells them apart
(``"ST JOHN THE BAPTIST SCHOOL"``, ``"ST JOHN XXIII CATHOLIC SCHOOL"``, ``"PAUL VI
CATHOLIC HIGH SCHOOL"``) stand beside listings of another saint's.

Schools whose NCES names leave out the level their grades make them (a K-5
``"Lincoln"``, a PK-8 parish's ``"ST JOSEPH SCHOOL"``) stand in a market's counties
beside namesakes whose names say it (``"Lincoln Elementary"``, ``"ST JOSEPH
ELEMENTARY SCHOOL"``): a listing that says the level names them all, and so none;
beside them, a school of other grades (a 6-8 ``"Devonby School"``), a K-12 one, a
PK-1 Lutheran school among PK-8 ones for a preschool, and one alone of its name.

They are tested together with the pattern-generated background of
:mod:`synthetic`, whose county codes start with ``9``, so every case whose
answer could collide with a generated namesake names its county.
"""

from match.synthetic import GRADE_SPANS, Case
from snowlight.match import DirectoryRecord


def _district(  # noqa: PLR0913, PLR0917 - one argument per NCES column
    record_id: str,
    name: str,
    state: str,
    county: str,
    city: str,
    point: tuple[float, float],
    *,
    county_name: str | None = None,
) -> DirectoryRecord:
    return DirectoryRecord(
        record_id, name, "district", None, state, county, city, *point, county=county_name
    )


def _school(  # noqa: PLR0913, PLR0917 - one argument per NCES column
    record_id: str,
    name: str,
    district: str | None,
    state: str,
    county: str,
    city: str,
    point: tuple[float, float],
    *,
    county_name: str | None = None,
    grades: str | None = None,
) -> DirectoryRecord:
    """A school; ``grades`` a key of :data:`~match.synthetic.GRADE_SPANS` (``"K-5"``)."""
    low, high, level = GRADE_SPANS[grades] if grades is not None else (None, None, None)
    return DirectoryRecord(
        record_id,
        name,
        "school",
        district,
        state,
        county,
        city,
        *point,
        county=county_name,
        grade_low=low,
        grade_high=high,
        level=level,
    )


# County codes: 8 + a two-digit state slot + a two-digit county.
PA_A, PA_B, PA_C = "80101", "80102", "80103"
LANCASTER = (40.04, -76.30)
EASTBROOK = (40.25, -76.10)
MILLBROOK = (40.80, -77.90)
TIDEWATER = (47.60, -122.30)
BRACKENMOOR = (42.30, -71.10)
MARROWGATE = (42.35, -83.10)
BRINEWATER = (40.76, -111.89)
FARROWDALE = (40.40, -83.10)
QUENBY = (41.20, -81.90)
HARLOWE = (44.30, -72.60)
PELLSTON = (43.60, -72.90)
MARLOWE = (30.60, -91.10)
MILLERS_CHURCH = (38.90, -77.20)
SABREL_PASS = (31.20, -87.90)
WEXCOMBE_FALLS = (41.60, -81.10)
NORTH_TALLIS = (44.80, -72.20)
ORLEBY = (43.70, -74.90)
TOLLBRIDGE = (44.10, -69.10)
BRACKLEY = (44.30, -69.80)
DUNMORE = (45.20, -68.60)
AUGUSTINE = (44.40, -69.70)
WENDHAM = (39.20, -96.30)
CARROW = (38.40, -97.60)
BRISBANE_SPRINGS = (38.80, -104.70)
ORLAND = (38.40, -105.10)
ORVALE = (41.00, -98.20)
HALVERN = (43.40, -114.20)
HOLCOMBE = (42.40, -71.80)
FRANLOW = (40.40, -79.70)
LANSMERE = (42.70, -84.50)
DES_PELLAM = (41.60, -93.70)
PORTWICK = (43.60, -70.30)
LITTLE_BROOK = (34.70, -92.30)
BURLINGHAM = (44.40, -73.20)
HARTMOOR = (41.70, -72.70)
ORLANE = (40.70, -74.20)
PROVOST = (41.80, -71.40)
KESSEL = (39.10, -94.50)
TAMSEL_HARBOR = (46.80, -92.10)
BRACKWATER = (44.50, -88.00)
HARLAN_DIXBY = (41.60, -87.60)
TAMBLIN = (42.40, -96.40)
TAMSFORD = (42.90, -73.20)
LYMONT = (38.40, -96.20)
VARENNA = (38.30, -122.30)
RICKMOND = (37.93, -122.35)
SUSANFIELD = (40.42, -120.65)
OLDEN_BROOK = (40.41, -74.30)
BUCKMOOR = (33.37, -112.58)
BRACKVILLE = (38.25, -85.76)
HALSTEAD = (35.78, -78.64)
KESSLING = (41.50, -81.69)
DAYWOOD = (39.76, -84.19)
PELLMONT = (41.08, -81.52)
LINDELL = (40.38, -80.05)
PHILMONT = (39.95, -75.16)
MARLOW = (41.43, -78.56)
BYFORD = (42.81, -85.72)
TINSLEY = (41.57, -87.78)
OSWELL = (41.68, -88.35)
MONTFORT = (44.26, -72.58)
RENWICK = (39.53, -119.81)
ALBURY = (40.87, -73.15)
BURLMOOR = (40.07, -74.85)
FALMONT = (38.88, -77.17)
KINGSFORD = (39.64, -94.04)
KESSELBY = (42.40, -83.05)

# Market counties for the charter networks (Texas) and the straddling districts.
CRESTLINE_HQ, TALBERT_CO, MOSSBURG_CO, CANTRELL_CO, AMBERLY_CO = (
    "87401",
    "87402",
    "87403",
    "87404",
    "87405",
)
DELMONT_CO, PORTAGE_CO, WYNNE_CO = "87406", "87407", "87408"
RIVERBEND_CO, ODELL_CO, GARRISON_CO = "87410", "87411", "87412"
BROOKHOLLOW_CO, MEADOW_GLEN_CO = "87413", "87414"
NORTHPARK_CO, BELLTOWN_CO = "87415", "87416"
TIBERTON_CO, PELLSVILLE_CO = "87501", "87502"
HALLORAN_CO, FAR_CO = "87601", "87602"
TALBERT = (32.35, -95.30)
MOSSBURG = (32.50, -94.74)
CANTRELL = (34.98, -101.92)
AMBERLY = (35.22, -101.83)
SOUTHGATE = (29.65, -95.35)
HARBOR = (29.70, -95.60)
ODELL = (31.85, -102.37)


def _campus(  # noqa: PLR0913, PLR0917 - one argument per NCES column
    record_id: str, name: str, district: str, county: str, city: str, point: tuple[float, float]
) -> DirectoryRecord:
    return _school(record_id, name, district, "TX", county, city, point)


NETWORK_RECORDS: tuple[DirectoryRecord, ...] = (
    _district(
        "SYN-TX-CRST", "CRESTLINE HIGH SCHOOLS", "TX", CRESTLINE_HQ, "Harlan Springs", (33.0, -97.0)
    ),
    _campus(
        "SYN-TX-CRTAL", "CRESTLINE H S OF TALBERT", "SYN-TX-CRST", TALBERT_CO, "Talbert", TALBERT
    ),
    _campus(
        "SYN-TX-CRMOS", "CRESTLINE H S - MOSSBURG", "SYN-TX-CRST", MOSSBURG_CO, "Mossburg", MOSSBURG
    ),
    _campus(
        "SYN-TX-CRCAN",
        "CRESTLINE HIGH SCHOOL-CANTRELL",
        "SYN-TX-CRST",
        CANTRELL_CO,
        "Cantrell",
        CANTRELL,
    ),
    _campus(
        "SYN-TX-CRAMB", "CRESTLINE H S OF AMBERLY", "SYN-TX-CRST", AMBERLY_CO, "Amberly", AMBERLY
    ),
    _campus(
        "SYN-TX-CRDEL",
        "CRESTLINE H S OF DELMONT",
        "SYN-TX-CRST",
        DELMONT_CO,
        "Delmont",
        (29.4, -98.5),
    ),
    _campus(
        "SYN-TX-CRPOR",
        "CRESTLINE H S - PORTAGE BEND",
        "SYN-TX-CRST",
        PORTAGE_CO,
        "Portage Bend",
        (27.8, -97.4),
    ),
    _campus(
        "SYN-TX-CRWYN", "CRESTLINE H S OF WYNNE", "SYN-TX-CRST", WYNNE_CO, "Wynne", (31.5, -97.1)
    ),
    _district(
        "SYN-TX-VANT", "VANTAGE PUBLIC SCHOOLS", "TX", RIVERBEND_CO, "Riverbend", (26.2, -98.0)
    ),
    _campus(
        "SYN-TX-VARIA",
        "VANTAGE RIVERBEND ACADEMY",
        "SYN-TX-VANT",
        RIVERBEND_CO,
        "Riverbend",
        (26.2, -98.0),
    ),
    _campus(
        "SYN-TX-VARIC",
        "VANTAGE RIVERBEND COLLEGE PREPARATORY",
        "SYN-TX-VANT",
        RIVERBEND_CO,
        "Riverbend",
        (26.2, -98.0),
    ),
    _campus(
        "SYN-TX-VASAL",
        "VANTAGE SALTMARSH ACADEMY",
        "SYN-TX-VANT",
        RIVERBEND_CO,
        "Saltmarsh",
        (26.1, -97.9),
    ),
    _campus("SYN-TX-VAODA", "VANTAGE ODELL ACADEMY", "SYN-TX-VANT", ODELL_CO, "Odell", ODELL),
    _campus(
        "SYN-TX-VAODC",
        "VANTAGE ODELL COLLEGE PREPARATORY",
        "SYN-TX-VANT",
        ODELL_CO,
        "Odell",
        ODELL,
    ),
    _campus(
        "SYN-TX-VAGAR",
        "VANTAGE GARRISON ACADEMY",
        "SYN-TX-VANT",
        GARRISON_CO,
        "Garrison",
        (30.3, -97.7),
    ),
    _district("SYN-TX-QUIL", "QUILLON ACADEMY", "TX", BROOKHOLLOW_CO, "Brookhollow", (30.7, -96.4)),
    _campus(
        "SYN-TX-QUBRO",
        "QUILLON ACADEMY - LANTERN CENTER",
        "SYN-TX-QUIL",
        BROOKHOLLOW_CO,
        "Brookhollow",
        (30.7, -96.4),
    ),
    _campus(
        "SYN-TX-QUHAR",
        "QUILLON ACADEMY - HARBOR CAMPUS",
        "SYN-TX-QUIL",
        MEADOW_GLEN_CO,
        "Meadow Glen",
        HARBOR,
    ),
    _campus(
        "SYN-TX-QUSOU",
        "QUILLON ACADEMY - SOUTHGATE",
        "SYN-TX-QUIL",
        MEADOW_GLEN_CO,
        "Meadow Glen",
        SOUTHGATE,
    ),
    _district("SYN-TX-HALC", "HALCYON ACADEMY", "TX", NORTHPARK_CO, "Northpark", (32.8, -96.8)),
    _campus(
        "SYN-TX-HANOR",
        "HALCYON ACADEMY - NORTHPARK",
        "SYN-TX-HALC",
        NORTHPARK_CO,
        "Northpark",
        (32.8, -96.8),
    ),
    _campus(
        "SYN-TX-HABEL",
        "HALCYON COLLEGE PREP - BELLTOWN",
        "SYN-TX-HALC",
        BELLTOWN_CO,
        "Belltown",
        (29.8, -95.4),
    ),
)
"""SYNTHETIC charter networks spread across Texas (see the cases' notes)."""

_HALLORAN_NAMESAKES = (
    "Abernethy", "Birchall", "Colville", "Dunstan", "Everard", "Fairleigh", "Gresham",
    "Hartwell", "Ingleby", "Jessop", "Kerrigan", "Lathrop", "Mowbray", "Netherby", "Oakeshott",
    "Pembury", "Quennell", "Rushworth", "Stanway", "Tredwell",
)  # fmt: skip

STRADDLING_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-PA-TIBR", "Tiberton Area SD", "PA", TIBERTON_CO, "Tiberton", (41.63, -79.67)),
    _school(
        "SYN-PA-TIBHS",
        "Tiberton Area HS",
        "SYN-PA-TIBR",
        "PA",
        TIBERTON_CO,
        "Tiberton",
        (41.63, -79.67),
    ),
    _school(
        "SYN-PA-TIBMS",
        "Tiberton Area MS",
        "SYN-PA-TIBR",
        "PA",
        TIBERTON_CO,
        "Tiberton",
        (41.63, -79.67),
    ),
    _school(
        "SYN-PA-COLEL",
        "Colebrook El Sch",
        "SYN-PA-TIBR",
        "PA",
        TIBERTON_CO,
        "Tiberton",
        (41.64, -79.7),
    ),
    _school(
        "SYN-PA-HYDEL",
        "Hydetown El Sch",
        "SYN-PA-TIBR",
        "PA",
        TIBERTON_CO,
        "Hydetown",
        (41.65, -79.72),
    ),
    _school(
        "SYN-PA-PELEL",
        "Pellsville El Sch",
        "SYN-PA-TIBR",
        "PA",
        PELLSVILLE_CO,
        "Pellsville",
        (41.57, -79.58),
    ),
    _district("SYN-FL-HALL", "HALLORAN", "FL", HALLORAN_CO, "Halloran", (28.3, -81.4)),
    *(
        _school(
            f"SYN-FL-HAL{number:02d}",
            f"{namesake.upper()} ELEMENTARY SCHOOL",
            "SYN-FL-HALL",
            "FL",
            HALLORAN_CO,
            "Halloran",
            (28.3 + number / 100, -81.4),
        )
        for number, namesake in enumerate(_HALLORAN_NAMESAKES)
    ),
    _school(
        "SYN-FL-HALVS",
        "HALLORAN VIRTUAL FRANCHISE",
        "SYN-FL-HALL",
        "FL",
        FAR_CO,
        "Portmere",
        (30.3, -81.6),
    ),
)
"""SYNTHETIC districts a market holds only part of, that are still whole districts."""

# Charter districts named as one school, each of whose schools adds a level or a
# campus word to the district's name, all in one county.
WYNDHAVEN_CO, ORVELLE_CO, TAMSIN_CO, QUENMORE_CO = "87701", "87702", "87703", "87704"
VESPERA_CO, TRELLIS_CO, ALDERN_CO, PELLWYN_CO = "87705", "87706", "87707", "87708"
ORENWAY_CO, FARPORT_CO = "87709", "87710"
WYNDHAVEN = (32.40, -95.20)
ORVELLE = (39.05, -94.55)
TAMSIN = (38.90, -77.00)
QUENMORE = (42.10, -86.40)
VESPERA = (40.50, -111.90)
TRELLIS = (44.95, -93.10)
ALDERN = (37.20, -93.30)
PELLWYN = (29.50, -98.40)
ORENWAY = (45.00, -93.30)
FARPORT = (47.50, -92.50)


ACADEMY_RECORDS: tuple[DirectoryRecord, ...] = (
    # Texas: the district's name, and its middle school's is that name and a
    # level; its elementary schools' add "Upper" and "Lower" as well.
    _district("SYN-TX-WYND", "WYNDHAVEN ACADEMY", "TX", WYNDHAVEN_CO, "Corsley", WYNDHAVEN),
    _school(
        "SYN-TX-WYNMS",
        "WYNDHAVEN ACADEMY MIDDLE",
        "SYN-TX-WYND",
        "TX",
        WYNDHAVEN_CO,
        "Corsley",
        WYNDHAVEN,
    ),
    _school(
        "SYN-TX-WYNUE",
        "WYNDHAVEN ACADEMY UPPER EL",
        "SYN-TX-WYND",
        "TX",
        WYNDHAVEN_CO,
        "Corsley",
        WYNDHAVEN,
    ),
    _school(
        "SYN-TX-WYNLE",
        "WYNDHAVEN ACADEMY LOWER EL",
        "SYN-TX-WYND",
        "TX",
        WYNDHAVEN_CO,
        "Corsley",
        WYNDHAVEN,
    ),
    _school(
        "SYN-TX-WYNHS", "WYNDHAVEN H S", "SYN-TX-WYND", "TX", WYNDHAVEN_CO, "Corsley", WYNDHAVEN
    ),
    # Missouri: the schools are the district's name and a level or a part after a hyphen.
    _district("SYN-MO-ORVA", "ORVELLE ACADEMY", "MO", ORVELLE_CO, "KESSINGTON", ORVELLE),
    _school(
        "SYN-MO-ORVMS",
        "ORVELLE ACADEMY-MIDDLE",
        "SYN-MO-ORVA",
        "MO",
        ORVELLE_CO,
        "KESSINGTON",
        ORVELLE,
    ),
    _school(
        "SYN-MO-ORVUP",
        "ORVELLE ACADEMY-UPPER",
        "SYN-MO-ORVA",
        "MO",
        ORVELLE_CO,
        "KESSINGTON",
        ORVELLE,
    ),
    _school(
        "SYN-MO-ORVLO",
        "ORVELLE ACADEMY-LOWER",
        "SYN-MO-ORVA",
        "MO",
        ORVELLE_CO,
        "KESSINGTON",
        ORVELLE,
    ),
    # District of Columbia: a public charter school's district and its two campuses.
    _district("SYN-DC-TAMS", "Tamsin PCS", "DC", TAMSIN_CO, "Pellham", TAMSIN),
    _school("SYN-DC-TAMMS", "Tamsin PCS - MS", "SYN-DC-TAMS", "DC", TAMSIN_CO, "Pellham", TAMSIN),
    _school(
        "SYN-DC-TAMHS",
        "Tamsin PCS - International HS",
        "SYN-DC-TAMS",
        "DC",
        TAMSIN_CO,
        "Pellham",
        TAMSIN,
    ),
    # Michigan: NCES's double spaces and a run-together "MiddleHigh".
    _district("SYN-MI-QUEN", "Quenmore Academy", "MI", QUENMORE_CO, "BENWICK", QUENMORE),
    _school(
        "SYN-MI-QUENE",
        "Quenmore Academy  Elementary",
        "SYN-MI-QUEN",
        "MI",
        QUENMORE_CO,
        "BENWICK",
        QUENMORE,
    ),
    _school(
        "SYN-MI-QUENM",
        "Quenmore Academy  MiddleHigh School",
        "SYN-MI-QUEN",
        "MI",
        QUENMORE_CO,
        "BENWICK",
        QUENMORE,
    ),
    # Utah: an elementary and a middle school, each the district's name and a level.
    _district("SYN-UT-VESP", "Vespera Academy", "UT", VESPERA_CO, "DRAYMOOR", VESPERA),
    _school(
        "SYN-UT-VESPE",
        "Vespera Academy Elementary",
        "SYN-UT-VESP",
        "UT",
        VESPERA_CO,
        "DRAYMOOR",
        VESPERA,
    ),
    _school(
        "SYN-UT-VESPM",
        "Vespera Academy Middle",
        "SYN-UT-VESP",
        "UT",
        VESPERA_CO,
        "DRAYMOOR",
        VESPERA,
    ),
    # Minnesota: an elementary school, a charter school and a campus in another town.
    _district("SYN-MN-TREL", "TRELLIS Academy", "MN", TRELLIS_CO, "SAINT ORWELL", TRELLIS),
    _school(
        "SYN-MN-TRELE",
        "TRELLIS Academy Elementary",
        "SYN-MN-TREL",
        "MN",
        TRELLIS_CO,
        "SAINT ORWELL",
        TRELLIS,
    ),
    _school(
        "SYN-MN-TRELC",
        "TRELLIS Academy Charter School",
        "SYN-MN-TREL",
        "MN",
        TRELLIS_CO,
        "SAINT ORWELL",
        TRELLIS,
    ),
    _school(
        "SYN-MN-TRELF",
        "TRELLIS Academy 6-12 - Farnham",
        "SYN-MN-TREL",
        "MN",
        TRELLIS_CO,
        "FARNHAM",
        (44.80, -93.25),
    ),
    # Missouri: a district whose name says neither school nor district, and whose
    # high school adds a level: "Aldern Village School" may be either.
    _district("SYN-MO-ALDV", "ALDERN VILLAGE", "MO", ALDERN_CO, "ALDERN", ALDERN),
    _school(
        "SYN-MO-ALDVH",
        "ALDERN VILLAGE HIGH SCHOOL",
        "SYN-MO-ALDV",
        "MO",
        ALDERN_CO,
        "ALDERN",
        ALDERN,
    ),
    _school(
        "SYN-MO-ALDVE", "ALDERN VILLAGE ELEM.", "SYN-MO-ALDV", "MO", ALDERN_CO, "ALDERN", ALDERN
    ),
    # Texas: a district one of whose schools has its very name.
    _district("SYN-TX-PELW", "PELLWYN ACADEMY", "TX", PELLWYN_CO, "Marbeck", PELLWYN),
    _school(
        "SYN-TX-PELWS",
        "PELLWYN ACADEMY",
        "SYN-TX-PELW",
        "TX",
        PELLWYN_CO,
        "Marbeck",
        PELLWYN,
        grades="K-5",
    ),
    _school(
        "SYN-TX-PELWM",
        "PELLWYN ACADEMY MIDDLE",
        "SYN-TX-PELW",
        "TX",
        PELLWYN_CO,
        "Marbeck",
        PELLWYN,
        grades="6-8",
    ),
    # Minnesota: a charter school's district with a campus in a town far away.
    # At home its one campus the name fits says a level more, beside another of
    # its schools; far away its one campus there that the name fits says only
    # its town more.
    _district("SYN-MN-OREN", "Orenway Charter School", "MN", ORENWAY_CO, "Lindqvist", ORENWAY),
    _school(
        "SYN-MN-ORENE",
        "Orenway Charter Elem",
        "SYN-MN-OREN",
        "MN",
        ORENWAY_CO,
        "Lindqvist",
        ORENWAY,
    ),
    _school(
        "SYN-MN-ORENH", "OCS High School", "SYN-MN-OREN", "MN", ORENWAY_CO, "Lindqvist", ORENWAY
    ),
    _school(
        "SYN-MN-ORENF",
        "Orenway Charter School - Farport",
        "SYN-MN-OREN",
        "MN",
        FARPORT_CO,
        "Farport",
        FARPORT,
    ),
    _school(
        "SYN-MN-ORENO", "OCS Online Program", "SYN-MN-OREN", "MN", FARPORT_CO, "Farport", FARPORT
    ),
)
"""SYNTHETIC charter districts named as one school, whose schools' names add to it."""

# Made-up points for the districts named for a town elsewhere.
EDGEMERE = (32.60, -95.60)
SAN_ARVELLO = (29.42, -98.49)
CINDALE = (39.15, -84.60)
OAKHURST_HILL = (38.90, -82.57)
FORT_KELLAN = (41.60, -122.84)
TARROWS_VALLEY = (37.05, -122.02)
GRAND_MAREN = (42.96, -85.66)
KENTMOOR = (42.87, -85.64)
FORT_MARIS = (26.64, -81.87)
MADDOCK = (30.46, -83.41)
BLUE_ASTER = (39.26, -84.38)
VARROW_HILL = (39.60, -82.10)
FENWICK_FALLS = (43.01, -83.69)
GENMOOR = (43.12, -83.60)
MARLEN_RAPIDS = (42.90, -85.50)
KESSFORD_CITY = (43.22, -85.74)
YARROWSTOWN = (41.10, -80.65)
QUARTZ_GLEN = (34.65, -118.20)
FIVE_PINES = (36.40, -120.10)
EDGEMERE_CO, SAN_ARVELLO_CO = "87801", "87802"
CINDALE_CO, OAKHURST_HILL_CO = "87803", "87804"
FORT_KELLAN_CO, TARROWS_VALLEY_CO = "87805", "87806"
GRAND_MAREN_CO, LEEMONT_CO, MADDOCK_CO = "87807", "87808", "87809"
BLUE_ASTER_CO, VARROW_HILL_CO, GENMOOR_CO, KESSFORD_CO = "87810", "87811", "87812", "87813"
YARROWSTOWN_CO, QUARTZ_GLEN_CO, FIVE_PINES_CO = "87814", "87815", "87816"
HARWOOD_SPRINGS, BRENNAN = (40.80, -81.40), (39.20, -84.10)
HARWOOD_SPRINGS_CO, BRENNAN_CO = "87817", "87818"
MATTLEY, MATTLEY_CO = (42.20, -85.78), "87819"

NAMESAKE_RECORDS: tuple[DirectoryRecord, ...] = (
    # Texas: the town of Edgemere's district, and a district of the same name
    # 440 km away, named for a neighbourhood of San Arvello.
    _district("SYN-TX-EDGT", "EDGEMERE ISD", "TX", EDGEMERE_CO, "EDGEMERE", EDGEMERE),
    _school("SYN-TX-EDGTH", "EDGEMERE H S", "SYN-TX-EDGT", "TX", EDGEMERE_CO, "EDGEMERE", EDGEMERE),
    _district("SYN-TX-EDGS", "EDGEMERE ISD", "TX", SAN_ARVELLO_CO, "SAN ARVELLO", SAN_ARVELLO),
    _school(
        "SYN-TX-EDGSC",
        "CALDERA EL",
        "SYN-TX-EDGS",
        "TX",
        SAN_ARVELLO_CO,
        "SAN ARVELLO",
        SAN_ARVELLO,
    ),
    _school(
        "SYN-TX-EDGSW",
        "WINSLOW MIDDLE",
        "SYN-TX-EDGS",
        "TX",
        SAN_ARVELLO_CO,
        "SAN ARVELLO",
        SAN_ARVELLO,
    ),
    _district("SYN-TX-SARV", "SAN ARVELLO ISD", "TX", SAN_ARVELLO_CO, "SAN ARVELLO", SAN_ARVELLO),
    # Ohio: a district named for hills, in a city, and the district of a town
    # named for one hill, 180 km away; "Union" is a legal form.
    _district("SYN-OH-OAKHS", "Oakhurst Hills Local", "OH", CINDALE_CO, "Cindale", CINDALE),
    _school(
        "SYN-OH-OAKHSH",
        "Oakhurst Hills High School",
        "SYN-OH-OAKHS",
        "OH",
        CINDALE_CO,
        "Cindale",
        CINDALE,
    ),
    _district(
        "SYN-OH-OAKHU",
        "Oakhurst Hill Union Local",
        "OH",
        OAKHURST_HILL_CO,
        "Oakhurst Hill",
        OAKHURST_HILL,
    ),
    _school(
        "SYN-OH-OAKHUH",
        "Oakhurst Hill High School",
        "SYN-OH-OAKHU",
        "OH",
        OAKHURST_HILL_CO,
        "Oakhurst Hill",
        OAKHURST_HILL,
    ),
    # California: a valley's district in a fort town, and the district of a
    # town whose name is the valley's with an s.
    _district(
        "SYN-CA-TARV", "Tarrow Valley Unified", "CA", FORT_KELLAN_CO, "Fort Kellan", FORT_KELLAN
    ),
    _school(
        "SYN-CA-TARVH",
        "Tarrow Valley High",
        "SYN-CA-TARV",
        "CA",
        FORT_KELLAN_CO,
        "Fort Kellan",
        FORT_KELLAN,
    ),
    _district(
        "SYN-CA-TARSV",
        "Tarrows Valley Unified",
        "CA",
        TARROWS_VALLEY_CO,
        "Tarrows Valley",
        TARROWS_VALLEY,
    ),
    _school(
        "SYN-CA-TARSVH",
        "Tarrows Valley High",
        "SYN-CA-TARSV",
        "CA",
        TARROWS_VALLEY_CO,
        "Tarrows Valley",
        TARROWS_VALLEY,
    ),
    # Michigan: a city's district whose office and schools have the next
    # city's address, while the one school addressed in the city is that next
    # city's district's.
    _district(
        "SYN-MI-KENT", "Kentmoor Public Schools", "MI", GRAND_MAREN_CO, "GRAND MAREN", GRAND_MAREN
    ),
    _school(
        "SYN-MI-KENTH",
        "Kentmoor High School",
        "SYN-MI-KENT",
        "MI",
        GRAND_MAREN_CO,
        "GRAND MAREN",
        GRAND_MAREN,
    ),
    _district(
        "SYN-MI-GMAR",
        "Grand Maren Public Schools",
        "MI",
        GRAND_MAREN_CO,
        "GRAND MAREN",
        GRAND_MAREN,
    ),
    _school(
        "SYN-MI-BROOK",
        "Brookvale Elementary",
        "SYN-MI-GMAR",
        "MI",
        GRAND_MAREN_CO,
        "KENTMOOR",
        KENTMOOR,
    ),
    # Florida: a county's district named by the county alone, and a town of
    # that name in another county, whose school is that county's district's.
    _district("SYN-FL-LEEM", "LEEMONT", "FL", LEEMONT_CO, "FORT MARIS", FORT_MARIS),
    _school(
        "SYN-FL-LEEMH",
        "FORT MARIS HIGH SCHOOL",
        "SYN-FL-LEEM",
        "FL",
        LEEMONT_CO,
        "FORT MARIS",
        FORT_MARIS,
    ),
    _district("SYN-FL-MADD", "MADDOCK", "FL", MADDOCK_CO, "MADDOCK", MADDOCK),
    _school(
        "SYN-FL-LEEMES",
        "LEEMONT ELEMENTARY SCHOOL",
        "SYN-FL-MADD",
        "FL",
        MADDOCK_CO,
        "LEEMONT",
        (30.50, -83.30),
    ),
    # Ohio: a "Community City" district and a "Union Local" one, which lists
    # call "... Community Schools" and "... Schools".
    _district(
        "SYN-OH-SABC", "Sablemoor Community City", "OH", BLUE_ASTER_CO, "Blue Aster", BLUE_ASTER
    ),
    _school(
        "SYN-OH-SABCH",
        "Sablemoor High School",
        "SYN-OH-SABC",
        "OH",
        BLUE_ASTER_CO,
        "Blue Aster",
        BLUE_ASTER,
    ),
    _district(
        "SYN-OH-VARU", "Varrow Hill Union Local", "OH", VARROW_HILL_CO, "Varrow Hill", VARROW_HILL
    ),
    _school(
        "SYN-OH-VARUM",
        "Varrow Hill Middle School",
        "SYN-OH-VARU",
        "OH",
        VARROW_HILL_CO,
        "Varrow Hill",
        VARROW_HILL,
    ),
    # Michigan: a county's intermediate district and a township's district of
    # one name; an intermediate district and a village's district.
    _district("SYN-MI-GENI", "Genmoor ISD", "MI", GENMOOR_CO, "FENWICK FALLS", FENWICK_FALLS),
    _district("SYN-MI-GENS", "Genmoor School District", "MI", GENMOOR_CO, "GENMOOR", GENMOOR),
    _school(
        "SYN-MI-GENES",
        "Genmoor Elementary School",
        "SYN-MI-GENS",
        "MI",
        GENMOOR_CO,
        "GENMOOR",
        GENMOOR,
    ),
    _district("SYN-MI-KESI", "Kessford ISD", "MI", KESSFORD_CO, "MARLEN RAPIDS", MARLEN_RAPIDS),
    _district(
        "SYN-MI-KESC",
        "Kessford City Community Schools",
        "MI",
        KESSFORD_CO,
        "KESSFORD CITY",
        KESSFORD_CITY,
    ),
    _school(
        "SYN-MI-KESCH",
        "Kessford City High School",
        "SYN-MI-KESC",
        "MI",
        KESSFORD_CO,
        "KESSFORD CITY",
        KESSFORD_CITY,
    ),
    # Ohio: a city's district, and a charter school named for the city, its own
    # district of one school.
    _district("SYN-OH-YARC", "Yarrowstown City", "OH", YARROWSTOWN_CO, "Yarrowstown", YARROWSTOWN),
    _school(
        "SYN-OH-YARCH",
        "Wickmere High School",
        "SYN-OH-YARC",
        "OH",
        YARROWSTOWN_CO,
        "Yarrowstown",
        YARROWSTOWN,
    ),
    _district(
        "SYN-OH-YARCS",
        "Yarrowstown Community School",
        "OH",
        YARROWSTOWN_CO,
        "Yarrowstown",
        YARROWSTOWN,
    ),
    _school(
        "SYN-OH-YARCSS",
        "Yarrowstown Community School",
        "SYN-OH-YARCS",
        "OH",
        YARROWSTOWN_CO,
        "Yarrowstown",
        YARROWSTOWN,
    ),
    # Ohio: a local district named for a creek, in a city, and the district of
    # a town of that name 230 km away.
    _district(
        "SYN-OH-BRENL",
        "Brennan Local",
        "OH",
        HARWOOD_SPRINGS_CO,
        "Harwood Springs",
        HARWOOD_SPRINGS,
    ),
    _school(
        "SYN-OH-BRENLH",
        "Brennan High School",
        "SYN-OH-BRENL",
        "OH",
        HARWOOD_SPRINGS_CO,
        "Harwood Springs",
        HARWOOD_SPRINGS,
    ),
    _district("SYN-OH-BRENC", "Brennan City", "OH", BRENNAN_CO, "Brennan", BRENNAN),
    _school(
        "SYN-OH-BRENCM",
        "Tolland Middle School",
        "SYN-OH-BRENC",
        "OH",
        BRENNAN_CO,
        "Brennan",
        BRENNAN,
    ),
    # Michigan: a town's district of three schools whose name ends "School".
    _district("SYN-MI-MATT", "Mattley Consolidated School", "MI", MATTLEY_CO, "MATTLEY", MATTLEY),
    _school(
        "SYN-MI-MATTH", "Mattley High School", "SYN-MI-MATT", "MI", MATTLEY_CO, "MATTLEY", MATTLEY
    ),
    _school(
        "SYN-MI-MATTM", "Mattley Middle School", "SYN-MI-MATT", "MI", MATTLEY_CO, "MATTLEY", MATTLEY
    ),
    _school(
        "SYN-MI-MATTE",
        "Lake Orrin Elementary School",
        "SYN-MI-MATT",
        "MI",
        MATTLEY_CO,
        "MATTLEY",
        MATTLEY,
    ),
    # California: a union elementary district, and an elementary district of
    # the same name 260 km away.
    _district(
        "SYN-CA-WEXU", "Wexley Union Elementary", "CA", QUARTZ_GLEN_CO, "Quartz Glen", QUARTZ_GLEN
    ),
    _school(
        "SYN-CA-WEXUS",
        "Juniper Mesa Elementary",
        "SYN-CA-WEXU",
        "CA",
        QUARTZ_GLEN_CO,
        "Quartz Glen",
        QUARTZ_GLEN,
    ),
    _district("SYN-CA-WEXE", "Wexley Elementary", "CA", FIVE_PINES_CO, "Five Pines", FIVE_PINES),
    _school(
        "SYN-CA-WEXES",
        "Wexley Elementary",
        "SYN-CA-WEXE",
        "CA",
        FIVE_PINES_CO,
        "Five Pines",
        FIVE_PINES,
    ),
)
"""SYNTHETIC districts named for a town elsewhere, or spelled one letter apart."""

# Made-up counties (with made-up names) and points for the names NCES ends with a
# bracket: a county that tells namesakes apart, a second name, a legal form, an
# Arizona entity number, a school's grades, and a bracket the CCD cut open.
TALLIS_CO, QUENBY_CO = "87901", "87902"
VANMOOR, GIFFMOOR = (45.64, -122.60), (48.30, -118.10)
ORRIN_CO, OAKMERE_CO, INGRAM_CO, MONROW_CO = "88001", "88002", "88003", "88004"
ADRAMOOR, MADLEY_HEIGHTS = (41.90, -84.04), (42.49, -83.10)
MASONBY, ERIMOOR, MONROW, NEWBRIDGE = (
    (42.58, -84.44),
    (41.78, -83.50),
    (41.92, -83.40),
    (42.01, -83.35),
)
ROCKMERE_CO, ERIEMOOR_CO, LIVINGMOOR_CO = "88101", "88102", "88103"
GARNERMOOR, THIELLMOOR, ANGLEMOOR, NUNDLE = (
    (41.20, -74.00),
    (41.21, -74.02),
    (42.64, -79.03),
    (42.58, -77.94),
)
WESTMOOR_CO, SUFFMOOR_CO, WARMOOR_CO = "88104", "88105", "88106"
GLENMOOR_FALLS = (43.31, -73.64)
TUCKERMOOR_EAST, TUCKERMOOR_SOUTH = (40.95, -73.83), (40.88, -72.39)
BRACKENDALE = (40.68, -73.94)
COCANNA_CO, MARIPA_CO, VARNELL_CO = "88201", "88202", "88203"
FLAGMOOR, PHOENMOOR, VARNELL = (35.20, -111.65), (33.45, -112.07), (32.69, -114.62)
CHANDMOOR = (33.31, -111.84)
COMANDRA_CO, LAWMOOR = "88301", (34.60, -98.40)
BELLMOOR_CO, BEXMOOR_CO, COLDMOOR_CO = "88401", "88402", "88403"
KILLOWAY, SAN_ANTOMOOR, COLDMOOR = (31.12, -97.73), (29.42, -98.49), (30.59, -95.13)
ERIVALE_CO, EDVALE = "88501", (41.33, -82.60)
CAPEMOOR_CO, CAPEMOOR = "88601", (39.08, -74.82)
WASHMOOR_CO, WASHMOOR = "88701", (40.55, -89.28)
SHELLMOOR_CO, SHELLMOOR = "88801", (45.74, -91.85)

BRACKET_RECORDS: tuple[DirectoryRecord, ...] = (
    # Washington: one name in two counties, each told apart by its county.
    _district(
        "SYN-WA-EVBT",
        "Everbrook School District (Tallis)",
        "WA",
        TALLIS_CO,
        "VANMOOR",
        VANMOOR,
        county_name="Tallis County",
    ),
    _school(
        "SYN-WA-EVBTHS",
        "Everbrook High School",
        "SYN-WA-EVBT",
        "WA",
        TALLIS_CO,
        "Vanmoor",
        VANMOOR,
        county_name="Tallis County",
    ),
    _school(
        "SYN-WA-EVBTMS",
        "Cascade Ridge Middle School",
        "SYN-WA-EVBT",
        "WA",
        TALLIS_CO,
        "Vanmoor",
        VANMOOR,
        county_name="Tallis County",
    ),
    _district(
        "SYN-WA-EVBQ",
        "Everbrook School District (Quenby)",
        "WA",
        QUENBY_CO,
        "GIFFMOOR",
        GIFFMOOR,
        county_name="Quenby County",
    ),
    _school(
        "SYN-WA-EVBQS",
        "Everbrook School",
        "SYN-WA-EVBQ",
        "WA",
        QUENBY_CO,
        "Giffmoor",
        GIFFMOOR,
        county_name="Quenby County",
    ),
    # Michigan: a district told apart by its county from a namesake 100 km away
    # that needs no bracket; two namesakes each with a bracket; and a district
    # whose bracket names the county another district is named for.
    _district(
        "SYN-MI-MADO",
        "Madley School District (Orrin)",
        "MI",
        ORRIN_CO,
        "ADRAMOOR",
        ADRAMOOR,
        county_name="Orrin County",
    ),
    _school(
        "SYN-MI-MADOE",
        "Madley Elementary School",
        "SYN-MI-MADO",
        "MI",
        ORRIN_CO,
        "ADRAMOOR",
        ADRAMOOR,
        county_name="Orrin County",
    ),
    _district(
        "SYN-MI-MADH",
        "Madley District Public Schools",
        "MI",
        OAKMERE_CO,
        "MADLEY HEIGHTS",
        MADLEY_HEIGHTS,
        county_name="Oakmere County",
    ),
    _school(
        "SYN-MI-MADHS",
        "Madley High School",
        "SYN-MI-MADH",
        "MI",
        OAKMERE_CO,
        "MADLEY HEIGHTS",
        MADLEY_HEIGHTS,
        county_name="Oakmere County",
    ),
    _district(
        "SYN-MI-MASI",
        "Masonby Public Schools (Ingram)",
        "MI",
        INGRAM_CO,
        "MASONBY",
        MASONBY,
        county_name="Ingram County",
    ),
    _school(
        "SYN-MI-MASIH",
        "Masonby High School",
        "SYN-MI-MASI",
        "MI",
        INGRAM_CO,
        "MASONBY",
        MASONBY,
        county_name="Ingram County",
    ),
    _district(
        "SYN-MI-MASM",
        "Masonby Consolidated Schools (Monrow)",
        "MI",
        MONROW_CO,
        "ERIMOOR",
        ERIMOOR,
        county_name="Monrow County",
    ),
    _district(
        "SYN-MI-MONR",
        "Monrow Public Schools",
        "MI",
        MONROW_CO,
        "MONROW",
        MONROW,
        county_name="Monrow County",
    ),
    _district(
        "SYN-MI-JEFM",
        "Jeffrow Schools (Monrow)",
        "MI",
        MONROW_CO,
        "NEWBRIDGE",
        NEWBRIDGE,
        county_name="Monrow County",
    ),
    # New York: districts known by a second name, which their high schools bear.
    _district(
        "SYN-NY-CARV",
        "CARVERTON-STONY MILL CSD (NORTH ROCKMERE)",
        "NY",
        ROCKMERE_CO,
        "GARNERMOOR",
        GARNERMOOR,
        county_name="Rockmere County",
    ),
    _school(
        "SYN-NY-CARVHS",
        "NORTH ROCKMERE HIGH SCHOOL",
        "SYN-NY-CARV",
        "NY",
        ROCKMERE_CO,
        "THIELLMOOR",
        THIELLMOOR,
        county_name="Rockmere County",
    ),
    _school(
        "SYN-NY-CARVES",
        "CARVERTON ELEMENTARY SCHOOL",
        "SYN-NY-CARV",
        "NY",
        ROCKMERE_CO,
        "GARNERMOOR",
        GARNERMOOR,
        county_name="Rockmere County",
    ),
    _district(
        "SYN-NY-EVAN",
        "EVANDER-BRANTLY CENTRAL SCHOOL DISTRICT (LAKE VESTRY)",
        "NY",
        ERIEMOOR_CO,
        "ANGLEMOOR",
        ANGLEMOOR,
        county_name="Eriemoor County",
    ),
    _school(
        "SYN-NY-EVANHS",
        "LAKE VESTRY SENIOR HIGH SCHOOL",
        "SYN-NY-EVAN",
        "NY",
        ERIEMOOR_CO,
        "ANGLEMOOR",
        ANGLEMOOR,
        county_name="Eriemoor County",
    ),
    _district(
        "SYN-NY-DALN",
        "DALLOW-NUNDLE CENTRAL SCHOOL DISTRICT (KESTREQUA)",
        "NY",
        LIVINGMOOR_CO,
        "NUNDLE",
        NUNDLE,
        county_name="Livingmoor County",
    ),
    _school(
        "SYN-NY-DALNHS",
        "KESTREQUA HIGH SCHOOL",
        "SYN-NY-DALN",
        "NY",
        LIVINGMOOR_CO,
        "NUNDLE",
        NUNDLE,
        county_name="Livingmoor County",
    ),
    # New York: a Common School District and a Union Free School District of
    # one name in two counties.
    _district(
        "SYN-NY-TUCKC",
        "TUCKERMOOR COMMON SCHOOL DISTRICT",
        "NY",
        SUFFMOOR_CO,
        "SOUTHMOOR",
        TUCKERMOOR_SOUTH,
        county_name="Suffmoor County",
    ),
    _district(
        "SYN-NY-TUCKU",
        "TUCKERMOOR UNION FREE SCHOOL DISTRICT",
        "NY",
        WESTMOOR_CO,
        "EASTMOOR",
        TUCKERMOOR_EAST,
        county_name="Westmoor County",
    ),
    # New York: a charter school's district whose name ends "(THE)".
    _district(
        "SYN-NY-BRKN",
        "BRACKENDALE CHARTER SCHOOL (THE)",
        "NY",
        ROCKMERE_CO,
        "BRACKENDALE",
        BRACKENDALE,
        county_name="Rockmere County",
    ),
    _school(
        "SYN-NY-BRKNS",
        "BRACKENDALE CHARTER SCHOOL",
        "SYN-NY-BRKN",
        "NY",
        ROCKMERE_CO,
        "BRACKENDALE",
        BRACKENDALE,
        county_name="Rockmere County",
    ),
    # Arizona: districts end with the state's entity number, one with a bracket
    # the CCD cut open at 60 characters; a charter holder named as a company.
    _district(
        "SYN-AZ-FLAG",
        "Flagmoor Unified District (4192)",
        "AZ",
        COCANNA_CO,
        "FLAGMOOR",
        FLAGMOOR,
        county_name="Cocanna County",
    ),
    _school(
        "SYN-AZ-FLAGHS",
        "Flagmoor High School",
        "SYN-AZ-FLAG",
        "AZ",
        COCANNA_CO,
        "FLAGMOOR",
        FLAGMOOR,
        county_name="Cocanna County",
    ),
    _school(
        "SYN-AZ-FLAGMS",
        "Sinagua Ridge Middle School",
        "SYN-AZ-FLAG",
        "AZ",
        COCANNA_CO,
        "FLAGMOOR",
        FLAGMOOR,
        county_name="Cocanna County",
    ),
    _district(
        "SYN-AZ-FLJA",
        "Flagmoor Junior Academy (4207)",
        "AZ",
        COCANNA_CO,
        "FLAGMOOR",
        FLAGMOOR,
        county_name="Cocanna County",
    ),
    _school(
        "SYN-AZ-FLJAS",
        "Flagmoor Junior Academy",
        "SYN-AZ-FLJA",
        "AZ",
        COCANNA_CO,
        "FLAGMOOR",
        FLAGMOOR,
        county_name="Cocanna County",
    ),
    _district(
        "SYN-AZ-SWTE",
        "Southmoor Technical Education District of Varnell (ST (92705)",
        "AZ",
        VARNELL_CO,
        "VARNELL",
        VARNELL,
        county_name="Varnell County",
    ),
    _district(
        "SYN-AZ-FRND",
        "Friendmoor House Inc. (4303)",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _school(
        "SYN-AZ-FRNDS",
        "Friendmoor House Academia del Pueblo",
        "SYN-AZ-FRND",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    # Arizona: a charter holder named "Inc.", and another holder's school named
    # as the first without its "Inc.".
    _district(
        "SYN-AZ-BRTI",
        "Brightmoor-School Inc. (4452)",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _school(
        "SYN-AZ-BRTIS",
        "Brightmoor-School - Paradise Vale",
        "SYN-AZ-BRTI",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _district(
        "SYN-AZ-BRTJ",
        "Jensmoor Holdings Inc. dba Brightmoor-School (79951)",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _school(
        "SYN-AZ-BRTJS",
        "Brightmoor-School",
        "SYN-AZ-BRTJ",
        "AZ",
        MARIPA_CO,
        "CHANDMOOR",
        CHANDMOOR,
        county_name="Maripa County",
    ),
    # Arizona: two charter holders of one name, told apart by their entity numbers.
    _district(
        "SYN-AZ-HRV1",
        "Harrowvale Charter Schools Inc. (6361)",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _school(
        "SYN-AZ-HRV1S",
        "Harrowvale Mesa Ridge",
        "SYN-AZ-HRV1",
        "AZ",
        MARIPA_CO,
        "PHOENMOOR",
        PHOENMOOR,
        county_name="Maripa County",
    ),
    _district(
        "SYN-AZ-HRV2",
        "Harrowvale Charter Schools Inc. (81078)",
        "AZ",
        MARIPA_CO,
        "CHANDMOOR",
        CHANDMOOR,
        county_name="Maripa County",
    ),
    _school(
        "SYN-AZ-HRV2S",
        "Harrowvale Chandmoor",
        "SYN-AZ-HRV2",
        "AZ",
        MARIPA_CO,
        "CHANDMOOR",
        CHANDMOOR,
        county_name="Maripa County",
    ),
    # New York: a town's system and a common school district of one school
    # beside it, in one town.
    _district(
        "SYN-NY-GLNC",
        "GLENMOOR FALLS CITY SCHOOL DISTRICT",
        "NY",
        WARMOOR_CO,
        "GLENMOOR FALLS",
        GLENMOOR_FALLS,
        county_name="Warmoor County",
    ),
    _school(
        "SYN-NY-GLNCH",
        "GLENMOOR FALLS SENIOR HIGH SCHOOL",
        "SYN-NY-GLNC",
        "NY",
        WARMOOR_CO,
        "GLENMOOR FALLS",
        GLENMOOR_FALLS,
        county_name="Warmoor County",
    ),
    _school(
        "SYN-NY-GLNCM",
        "GLENMOOR FALLS MIDDLE SCHOOL",
        "SYN-NY-GLNC",
        "NY",
        WARMOOR_CO,
        "GLENMOOR FALLS",
        GLENMOOR_FALLS,
        county_name="Warmoor County",
    ),
    _district(
        "SYN-NY-GLNM",
        "GLENMOOR FALLS COMMON SCHOOL DISTRICT",
        "NY",
        WARMOOR_CO,
        "GLENMOOR FALLS",
        GLENMOOR_FALLS,
        county_name="Warmoor County",
    ),
    _school(
        "SYN-NY-GLNMS",
        "ABRAHAM WINGATE SCHOOL",
        "SYN-NY-GLNM",
        "NY",
        WARMOOR_CO,
        "GLENMOOR FALLS",
        GLENMOOR_FALLS,
        county_name="Warmoor County",
    ),
    # Oklahoma: a charter district whose legal form is in brackets.
    _district(
        "SYN-OK-COMA",
        "COMANDRA ACADEMY (CHARTER)",
        "OK",
        COMANDRA_CO,
        "LAWMOOR",
        LAWMOOR,
        county_name="Comandra County",
    ),
    _school(
        "SYN-OK-COMAS",
        "COMANDRA ACADEMY",
        "SYN-OK-COMA",
        "OK",
        COMANDRA_CO,
        "LAWMOOR",
        LAWMOOR,
        county_name="Comandra County",
    ),
    # Texas: a town's district, and a charter district elsewhere whose bracket
    # names the town, where its one school is.
    _district(
        "SYN-TX-KILL",
        "KILLOWAY ISD",
        "TX",
        BELLMOOR_CO,
        "KILLOWAY",
        KILLOWAY,
        county_name="Bellmoor County",
    ),
    _school(
        "SYN-TX-KILLHS",
        "KILLOWAY H S",
        "SYN-TX-KILL",
        "TX",
        BELLMOOR_CO,
        "KILLOWAY",
        KILLOWAY,
        county_name="Bellmoor County",
    ),
    _district(
        "SYN-TX-MALB",
        "RICHARD MALBURN ALTER HIGH SCHOOL (KILLOWAY)",
        "TX",
        BEXMOOR_CO,
        "SAN ANTOMOOR",
        SAN_ANTOMOOR,
        county_name="Bexmoor County",
    ),
    _school(
        "SYN-TX-MALBS",
        "RICHARD MALBURN ALTER H S",
        "SYN-TX-MALB",
        "TX",
        BELLMOOR_CO,
        "KILLOWAY",
        KILLOWAY,
        county_name="Bellmoor County",
    ),
    # Texas: schools whose names say only a place word and a level.
    _district("SYN-TX-COLD", "COLDMOOR ISD", "TX", COLDMOOR_CO, "COLDMOOR", COLDMOOR),
    _school("SYN-TX-STREL", "STREET EL", "SYN-TX-COLD", "TX", COLDMOOR_CO, "COLDMOOR", COLDMOOR),
    _school("SYN-TX-MTEL", "MOUNT EL", "SYN-TX-COLD", "TX", COLDMOOR_CO, "COLDMOOR", COLDMOOR),
    # Ohio: a district known by its former name.
    _district(
        "SYN-OH-EDVL",
        "Edvale Local (formerly Berrow-Millan)",
        "OH",
        ERIVALE_CO,
        "Edvale",
        EDVALE,
        county_name="Erivale County",
    ),
    # New Jersey: a township named with a level word.
    _district(
        "SYN-NJ-HIGHT",
        "High Township School District",
        "NJ",
        CAPEMOOR_CO,
        "Capemoor Court House",
        CAPEMOOR,
    ),
    _school(
        "SYN-NJ-HIGHTE",
        "High Township Elementary #1",
        "SYN-NJ-HIGHT",
        "NJ",
        CAPEMOOR_CO,
        "CAPEMOOR COURT HOUSE",
        CAPEMOOR,
    ),
    _school(
        "SYN-NJ-HIGHTM",
        "High Township Middle School",
        "SYN-NJ-HIGHT",
        "NJ",
        CAPEMOOR_CO,
        "CAPEMOOR COURT HOUSE",
        CAPEMOOR,
    ),
    _school(
        "SYN-NJ-HIGHTH",
        "High Township High School",
        "SYN-NJ-HIGHT",
        "NJ",
        CAPEMOOR_CO,
        "CAPEMOOR COURT HOUSE",
        CAPEMOOR,
    ),
    # Illinois: a district whose name is a legal form and a number.
    _district("SYN-IL-CSD51", "Consolidated SD 51", "IL", WASHMOOR_CO, "Washmoor", WASHMOOR),
    # Wisconsin: schools whose names end with their grades.
    _district(
        "SYN-WI-SHEL", "Shellmoor Lake School District", "WI", SHELLMOOR_CO, "Shellmoor", SHELLMOOR
    ),
    _school(
        "SYN-WI-SHELE",
        "Shellmoor Lake Elementary (3-6)",
        "SYN-WI-SHEL",
        "WI",
        SHELLMOOR_CO,
        "Shellmoor",
        SHELLMOOR,
    ),
    _school(
        "SYN-WI-SHELP",
        "Shellmoor Lake Primary (K-2)",
        "SYN-WI-SHEL",
        "WI",
        SHELLMOOR_CO,
        "Shellmoor",
        SHELLMOOR,
    ),
)
"""SYNTHETIC districts and schools whose NCES-shaped names end with a bracket."""

# Made-up counties (with made-up names) and points for the districts a list tells
# apart from a namesake in another state by writing the state beside the name
# ("Salmere MA Public", "Knoxmere County, TN Schools", "Collinsby (TX) ISD",
# "Holdenby R-III School Holdenby MO"), and for names a state is part of.
SALMERE_MA_CO, SALMERE_NH_CO = "88901", "88902"
KNOXMERE_TN_CO, KNOXMERE_KY_CO = "88903", "88904"
COLLINSBY_TX_CO, COLLINSBY_OK_CO = "88905", "88906"
MADMERE_NC_CO, MADMERE_GA_CO = "88907", "88908"
POCAMERE_WV_CO, POCAMERE_VA_CO = "88909", "88910"
CASMERE_CO, LEAVMERE_CO, BATESMERE_CO = "88911", "88912", "88913"
KESSBY_MO_CO, KESSBY_KS_CO = "88914", "88915"
TONGANBY_KS_CO, TONGANBY_MO_CO = "88916", "88917"
GERMANBY_TN_CO, GERMANBY_MS_CO = "88918", "88919"
BRENMERE_CO = "88920"
BRIGHTMERE_CO, WEXMERE_CO, BAXMERE_CO, JONMERE_CO = "88921", "88922", "88923", "88924"
EVERMERE_CO, PUTMERE_CO, WESTMERE_CO, IDAMERE_CO = "88925", "88926", "88927", "88928"
OARKBY_AR_CO, OARKBY_MO_CO = "88929", "88930"
WASHC_KY_CO, WASHC_TN_CO = "88931", "88932"
MILLMERE_KY_CO, MILLMERE_TN_CO = "88933", "88934"
CIGARMOOR_VA_CO, JONESMERE_NC_CO = "88935", "88936"
HENMERE_MO_CO, SHAWBY_KS_CO = "88937", "88938"
WESTMOOR_MO_CO, WESTMOOR_KS_CO = "88939", "88940"
NORTONBY_VA_CO, NORTONBY_TN_CO = "88944", "88945"
RANDBY_AL_CO, RANDBY_GA_CO = "88946", "88947"
HARRBY_MS_CO, HARRBY_AL_CO = "88948", "88949"
RAVENBY_CO, APPLEBY_CO = "88950", "88951"
TROYBY_CO, OTHERBY_CO, SPRINGBY_IL_CO = "88952", "88953", "88954"
HERTBY_CO, JOHNSMERE_CO, WHITEBY_CO = "88955", "88956", "88957"
SALMERE_MA, SALMERE_NH = (42.52, -70.90), (42.79, -71.20)
KNOXMERE_TN, KNOXMERE_KY = (35.96, -83.92), (36.86, -83.32)
COLLINSBY_TX, COLLINSBY_OK = (33.56, -96.91), (34.35, -95.84)
MADMERE_NC, MADMERE_GA = (35.80, -82.68), (34.13, -83.21)
POCAMERE_WV, POCAMERE_VA = (38.22, -80.09), (37.27, -81.34)
HOLDENBY_MO, HOLDENBY_KS, BUTTERBY = (38.71, -94.00), (39.22, -95.20), (38.26, -94.33)
KESSBY_MO, KESSBY_KS = (39.10, -94.58), (39.11, -94.63)
TONGANBY_KS, TONGANBY_MO = (39.11, -95.09), (37.60, -91.54)
GERMANBY_TN, GERMANBY_MS = (35.09, -89.81), (32.54, -90.08)
BRENMERE, CASTLEMERE = (39.40, -104.80), (39.37, -104.86)
LONDONBY, NASHMERE, PITTSMERE = (42.87, -71.37), (42.77, -71.47), (40.44, -79.99)
BAXMERE, OLATHBY, SAN_JOMERE = (43.80, -83.00), (38.88, -94.82), (37.34, -121.89)
PUTMERE, WESTMERE_IN, MEMBY = (41.65, -82.82), (40.04, -86.13), (35.15, -90.05)
OARKBY_AR, OARKBY_MO = (35.69, -93.60), (37.64, -91.54)
SPRINGMERE_KY, JONESBY_TN = (37.72, -85.22), (36.29, -82.47)
MILLMERE_KY, MILLMERE_TN = (37.00, -86.40), (36.10, -86.70)
CIGARMOOR_VA, JONESMERE_NC = (38.80, -77.10), (35.60, -78.80)
CHILBY, SHAWBY_KS = (38.60, -93.90), (38.20, -95.70)
WESTBY, WESTMOOR_KS = (39.36, -94.78), (37.80, -96.80)
NORTONBY_VA, NORTONBY_TN = (36.93, -82.63), (35.90, -84.00)
RANDBY_AL, RANDBY_GA = (33.20, -85.40), (31.80, -84.80)
HARRBY_MS, HARRBY_AL = (30.40, -89.10), (32.40, -86.30)
RAVENBY, APPLEBY = (41.15, -81.24), (40.75, -81.84)
TROYBY, OTHERBY, SPRINGBY_IL = (38.98, -90.98), (37.20, -93.30), (39.80, -89.60)
HERTBY, JOHNSMERE, WHITEBY = (36.30, -76.98), (36.47, -81.80), (36.47, -86.67)

STATE_RECORDS: tuple[DirectoryRecord, ...] = (
    # Massachusetts and New Hampshire: a town's district of one name in each.
    _district("SYN-MA-SALM", "Salmere", "MA", SALMERE_MA_CO, "Salmere", SALMERE_MA),
    _school(
        "SYN-MA-SALMH", "Salmere High School", "SYN-MA-SALM", "MA", SALMERE_MA_CO, "Salmere",
        SALMERE_MA,
    ),
    _district(
        "SYN-NH-SALM", "Salmere School District", "NH", SALMERE_NH_CO, "Salmere", SALMERE_NH
    ),
    _school(
        "SYN-NH-SALMH", "Salmere High School", "SYN-NH-SALM", "NH", SALMERE_NH_CO, "Salmere",
        SALMERE_NH,
    ),
    # Tennessee and Kentucky: a county's district of one name in each.
    _district(
        "SYN-TN-KNXC", "Knoxmere County", "TN", KNOXMERE_TN_CO, "Knoxby", KNOXMERE_TN,
        county_name="Knoxmere County",
    ),
    _district(
        "SYN-KY-KNXC", "Knoxmere County", "KY", KNOXMERE_KY_CO, "Harlmere", KNOXMERE_KY,
        county_name="Knoxmere County",
    ),
    # Texas and Oklahoma: a town's ISD and a town's public schools of one name.
    _district("SYN-TX-COLL", "COLLINSBY ISD", "TX", COLLINSBY_TX_CO, "COLLINSBY", COLLINSBY_TX),
    _district("SYN-OK-COLL", "COLLINSBY", "OK", COLLINSBY_OK_CO, "Collinsby", COLLINSBY_OK),
    # North Carolina and Georgia: a county's district of one name in each.
    _district(
        "SYN-NC-MADC", "Madmere County Schools", "NC", MADMERE_NC_CO, "Marsby", MADMERE_NC,
        county_name="Madmere County",
    ),
    _district(
        "SYN-GA-MADC", "Madmere County", "GA", MADMERE_GA_CO, "Danmere", MADMERE_GA,
        county_name="Madmere County",
    ),
    # West Virginia and Virginia.
    _district(
        "SYN-WV-POCA", "Pocamere County Schools", "WV", POCAMERE_WV_CO, "Buckmere", POCAMERE_WV,
        county_name="Pocamere County",
    ),
    _district(
        "SYN-VA-POCA", "Pocamere County Public Schools", "VA", POCAMERE_VA_CO, "Tazby",
        POCAMERE_VA, county_name="Pocamere County",
    ),
    # Missouri and Kansas: numbered districts the Kansas City lists call "<name>
    # R-n School <town> MO", one named for its town and one for another place,
    # a Kansas namesake of the first, and a city's district in each state.
    _district(
        "SYN-MO-HOLD", "HOLDENBY R-III", "MO", CASMERE_CO, "Holdenby", HOLDENBY_MO,
        county_name="Casmere County",
    ),
    _school(
        "SYN-MO-HOLDE", "HOLDENBY ELEM.", "SYN-MO-HOLD", "MO", CASMERE_CO, "Holdenby",
        HOLDENBY_MO, county_name="Casmere County",
    ),
    _school(
        "SYN-MO-HOLDM", "HOLDENBY MIDDLE", "SYN-MO-HOLD", "MO", CASMERE_CO, "Holdenby",
        HOLDENBY_MO, county_name="Casmere County",
    ),
    _school(
        "SYN-MO-HOLDH", "HOLDENBY HIGH", "SYN-MO-HOLD", "MO", CASMERE_CO, "Holdenby",
        HOLDENBY_MO, county_name="Casmere County",
    ),
    _district(
        "SYN-KS-HOLD", "Holdenby", "KS", LEAVMERE_CO, "Holdenby", HOLDENBY_KS,
        county_name="Leavmere County",
    ),
    _district(
        "SYN-MO-BALL", "BALLMERE R-II", "MO", BATESMERE_CO, "Butterby", BUTTERBY,
        county_name="Batesmere County",
    ),
    _school(
        "SYN-MO-BALLE", "BALLMERE ELEM.", "SYN-MO-BALL", "MO", BATESMERE_CO, "Butterby",
        BUTTERBY, county_name="Batesmere County",
    ),
    _school(
        "SYN-MO-BALLH", "BALLMERE HIGH", "SYN-MO-BALL", "MO", BATESMERE_CO, "Butterby",
        BUTTERBY, county_name="Batesmere County",
    ),
    _district("SYN-MO-KESS", "KESSBY CITY 33", "MO", KESSBY_MO_CO, "KESSBY CITY", KESSBY_MO),
    _district("SYN-KS-KESS", "Kessby City", "KS", KESSBY_KS_CO, "Kessby City", KESSBY_KS),
    _district("SYN-KS-TONG", "Tonganby", "KS", TONGANBY_KS_CO, "Tonganby", TONGANBY_KS),
    _district("SYN-MO-TONG", "TONGANBY R-I", "MO", TONGANBY_MO_CO, "Tonganby", TONGANBY_MO),
    # Tennessee and Mississippi: a town's middle school, where "MS" is Middle
    # School, and a district of the town's name in Mississippi.
    _district(
        "SYN-TN-GERD", "Germanby Municipal School District", "TN", GERMANBY_TN_CO, "Germanby",
        GERMANBY_TN,
    ),
    _school(
        "SYN-TN-GERMS", "Germanby Middle School", "SYN-TN-GERD", "TN", GERMANBY_TN_CO,
        "Germanby", GERMANBY_TN,
    ),
    _school(
        "SYN-TN-GERHS", "Germanby High School", "SYN-TN-GERD", "TN", GERMANBY_TN_CO, "Germanby",
        GERMANBY_TN,
    ),
    _district(
        "SYN-MS-GERM", "Germanby School District", "MS", GERMANBY_MS_CO, "Germanby", GERMANBY_MS
    ),
    _school(
        "SYN-MS-GERAC", "Germanby Attendance Center", "SYN-MS-GERM", "MS", GERMANBY_MS_CO,
        "Germanby", GERMANBY_MS,
    ),
    # Tennessee: a school of two levels written with a slash, and a middle
    # school a list writes "- MS".
    _school("SYN-TN-IDAES", "Idamere Academy ES/MS", None, "TN", IDAMERE_CO, "Memby", MEMBY),
    _school(
        "SYN-TN-FREMS", "FREEMERE PREPARATORY ACADEMY MIDDLE", None, "TN", IDAMERE_CO, "Memby",
        MEMBY,
    ),
    # Colorado: a county's district and its town's, where "Co." is County.
    _district(
        "SYN-CO-BRENC", "Brenmere County School District RE-1", "CO", BRENMERE_CO,
        "Castlemere", CASTLEMERE, county_name="Brenmere County",
    ),
    _district(
        "SYN-CO-BREN", "Brenmere School District 2", "CO", BRENMERE_CO, "Brenmere", BRENMERE,
        county_name="Brenmere County",
    ),
    # New Hampshire and Pennsylvania: schools named for part of their state.
    _school(
        "SYN-NH-SNHB", "SOUTHERN NH BRIGHTMERE ACADEMY", None, "NH", BRIGHTMERE_CO, "Londonby",
        LONDONBY,
    ),
    _school(
        "SYN-NH-SBRI", "SOUTHERN BRIGHTMERE ACADEMY", None, "NH", BRIGHTMERE_CO, "Nashmere",
        NASHMERE,
    ),
    _school(
        "SYN-PA-WPWD", "WESTERN PENNSYLVANIA WEXMERE SCHOOL FOR THE DEAF", None, "PA",
        WEXMERE_CO, "Pittsmere", PITTSMERE,
    ),
    # Michigan and Kansas: towns' and counties' districts beside a job center and a
    # meals program named for the state.
    _district("SYN-MI-BAXM", "Baxmere Public Schools", "MI", BAXMERE_CO, "Baxmere", BAXMERE),
    _district(
        "SYN-KS-JONC", "Jonmere County", "KS", JONMERE_CO, "Olathby", OLATHBY,
        county_name="Jonmere County",
    ),
    # California: a school whose own name ends with a state's code.
    _school(
        "SYN-CA-EVAR", "EVERMERE MONTESSORI SCHOOL - AR", None, "CA", EVERMERE_CO, "San Jomere",
        SAN_JOMERE,
    ),
    # Ohio and Indiana: names whose hyphens join a state's code or name.
    _district(
        "SYN-OH-PUTB", "Putmere-In-Bay Local", "OH", PUTMERE_CO, "Putmere-In-Bay", PUTMERE
    ),
    _district(
        "SYN-IN-WESW", "Westmere-Washington Schools", "IN", WESTMERE_CO, "Westmere", WESTMERE_IN
    ),
    # Arkansas and Missouri: a town's district of one name in each.
    _district(
        "SYN-AR-OARK", "OARKBY SCHOOL DISTRICT", "AR", OARKBY_AR_CO, "OARKBY", OARKBY_AR
    ),
    _district("SYN-MO-OARK", "OARKBY R-80", "MO", OARKBY_MO_CO, "Oarkby", OARKBY_MO),
    # Kentucky and Tennessee: a county's district of one name in each, the county
    # named as a state is ("WASHINGTON COUNTY SCHOOLS-KY"), and a middle school
    # of one name in each, whose level is a region word too ("Middle KY").
    _district(
        "SYN-KY-WASC", "Washington County", "KY", WASHC_KY_CO, "Springmere", SPRINGMERE_KY,
        county_name="Washington County",
    ),
    _district(
        "SYN-TN-WASC", "Washington County Schools", "TN", WASHC_TN_CO, "Jonesby", JONESBY_TN,
        county_name="Washington County",
    ),
    _school(
        "SYN-KY-MILMS", "Millmere Middle", None, "KY", MILLMERE_KY_CO, "Millmere", MILLMERE_KY
    ),
    _school(
        "SYN-TN-MILMS", "Millmere Middle School", None, "TN", MILLMERE_TN_CO, "Millmere",
        MILLMERE_TN,
    ),
    # Virginia and North Carolina: schools whose own names hold a state's code
    # that is no state: a doctor's "MD", and "SC" for School.
    _school(
        "SYN-VA-CIGMD", "TOMAS CIGARMOOR MD EL", None, "VA", CIGARMOOR_VA_CO, "Cigarmoor",
        CIGARMOOR_VA,
    ),
    _school(
        "SYN-NC-JONSC", "JONESMERE INT SC", None, "NC", JONESMERE_NC_CO, "Jonesmere",
        JONESMERE_NC,
    ),
    # Missouri and Kansas: a numbered district the Kansas City lists write
    # "<name> R-n MO <town>", with a Kansas namesake; a county's numbered
    # district that lists write without "Co.", with a Kansas namesake.
    _district("SYN-MO-SHAW", "SHAWBY R-III", "MO", HENMERE_MO_CO, "CHILBY", CHILBY),
    _district("SYN-KS-SHAW", "Shawby", "KS", SHAWBY_KS_CO, "Shawby", SHAWBY_KS),
    _district("SYN-MO-WESTM", "WESTMOOR CO. R-II", "MO", WESTMOOR_MO_CO, "WESTBY", WESTBY),
    _district("SYN-KS-WESTM", "Westmoor", "KS", WESTMOOR_KS_CO, "Westmoor", WESTMOOR_KS),
    # Virginia and Tennessee: a city's schools of one name in each.
    _district(
        "SYN-VA-NORC", "Nortonby City Public Schools", "VA", NORTONBY_VA_CO, "Nortonby",
        NORTONBY_VA,
    ),
    _district("SYN-TN-NORC", "Nortonby City", "TN", NORTONBY_TN_CO, "Nortonby", NORTONBY_TN),
    # Alabama and Georgia, Mississippi and Alabama: counties' districts of one
    # name in each, which lists write with a code that is also a word ("AL",
    # and "MS" for Middle School).
    _district(
        "SYN-AL-RANC", "Randby County", "AL", RANDBY_AL_CO, "Randby", RANDBY_AL,
        county_name="Randby County",
    ),
    _district(
        "SYN-GA-RANC", "Randby County", "GA", RANDBY_GA_CO, "Cuthby", RANDBY_GA,
        county_name="Randby County",
    ),
    _district(
        "SYN-MS-HARC", "Harrby County School District", "MS", HARRBY_MS_CO, "Gulfby", HARRBY_MS,
        county_name="Harrby County",
    ),
    _district(
        "SYN-AL-HARC", "Harrby County", "AL", HARRBY_AL_CO, "Harrby", HARRBY_AL,
        county_name="Harrby County",
    ),
    # Ohio: two local districts of one name, which lists tell apart by the town
    # they join to the name with a hyphen ("Southbrook Local SD-Ravenby").
    _district("SYN-OH-SBRR", "Southbrook Local", "OH", RAVENBY_CO, "Ravenby", RAVENBY),
    _district("SYN-OH-SBRA", "Southbrook Local", "OH", APPLEBY_CO, "Appleby", APPLEBY),
    # Missouri and Illinois: three parish schools of one name, one in Troyby.
    _school("SYN-MO-SHTR", "SACRED HEART SCHOOL", None, "MO", TROYBY_CO, "TROYBY", TROYBY),
    _school("SYN-MO-SHOT", "SACRED HEART SCHOOL", None, "MO", OTHERBY_CO, "OTHERBY", OTHERBY),
    _school(
        "SYN-IL-SHSP", "Sacred Heart School", None, "IL", SPRINGBY_IL_CO, "Springby",
        SPRINGBY_IL,
    ),
    # North Carolina: a county's district beside the county's court.
    _district(
        "SYN-NC-HERC", "Hertby County Schools", "NC", HERTBY_CO, "Wintonby", HERTBY,
        county_name="Hertby County",
    ),
    # Tennessee: a county's district with two virtual schools that NCES places at
    # their operator's office across the state.
    _district(
        "SYN-TN-JOHC", "Johnsmere County", "TN", JOHNSMERE_CO, "Mountainby", JOHNSMERE,
        county_name="Johnsmere County",
    ),
    *(
        _school(
            f"SYN-TN-JOH{number}", name, "SYN-TN-JOHC", "TN", JOHNSMERE_CO, "Mountainby",
            (JOHNSMERE[0] + number / 100, JOHNSMERE[1]),
        )
        for number, name in enumerate(
            (
                "Johnsmere Co High School", "Johnsmere Co Middle School",
                "Doeby Elementary", "Laurelby Elementary",
            )
        )
    ),
    *(
        _school(
            f"SYN-TN-JOHV{grades}", f"Tennmere Connections Academy Johnsmere County {grades}",
            "SYN-TN-JOHC", "TN", WHITEBY_CO, "Whiteby", WHITEBY,
        )
        for grades in ("4-8", "9-12")
    ),
)  # fmt: skip
"""SYNTHETIC districts and schools a list tells apart by their state, or whose names
hold a state."""

# Made-up counties and points for a Kansas City-like market of two states, whose
# lists carry churches beside schools: parish schools named for their parish, as
# NCES's private school survey names them there ("ST PETER'S SCHOOL", "CHRIST THE
# KING PARISH SCHOOL", "VISITATION CATHOLIC SCHOOL", "ST ELIZABETH ELEMENTARY
# SCHOOL", "OUR LADY OF ... SCHOOL"); a namesake in another market, about 190 km
# away, and one just past the market's counties, 40 km from them (as Ottawa's
# "SACRED HEART CATHOLIC SCHOOL" lies past Kansas City's); two schools of one
# devotion, one that says its faith; and a saint's school of another church.
KANBY_MO_CO, WYANBY_KS_CO, LEABY_KS_CO, OTTABY_KS_CO = "88941", "88942", "88943", "88960"
KC = (KANBY_MO_CO, WYANBY_KS_CO)
KANBY, WYANBY, OVERBY = (39.05, -94.55), (39.11, -94.69), (38.98, -94.67)
LEABY, OTTABY = (40.35, -96.10), (38.75, -95.05)

PARISH_RECORDS: tuple[DirectoryRecord, ...] = (
    _school("SYN-MO-KSTPE", "ST PETER'S SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY),
    _school("SYN-KS-LSTPE", "ST PETER SCHOOL", None, "KS", LEABY_KS_CO, "LEABY", LEABY),
    _school(
        "SYN-KS-KCTK",
        "CHRIST THE KING PARISH SCHOOL",
        None,
        "KS",
        WYANBY_KS_CO,
        "WYANBY",
        WYANBY,
    ),
    _school("SYN-MO-KVIS", "VISITATION CATHOLIC SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY),
    _school(
        "SYN-MO-KSTEL", "ST ELIZABETH ELEMENTARY SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY
    ),
    _school(
        "SYN-KS-KOLS", "OUR LADY OF SORROWS SCHOOL", None, "KS", WYANBY_KS_CO, "WYANBY", WYANBY
    ),
    _school("SYN-KS-KHSP", "HOLY SPIRIT SCHOOL", None, "KS", WYANBY_KS_CO, "OVERBY", OVERBY),
    _school("SYN-MO-KHCR", "HOLY CROSS SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY),
    _school(
        "SYN-KS-KHCRC", "HOLY CROSS CATHOLIC SCHOOL", None, "KS", WYANBY_KS_CO, "OVERBY", OVERBY
    ),
    _school(
        "SYN-MO-KSTPL", "ST PAUL'S EPISCOPAL DAY SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY
    ),
    _school("SYN-MO-KHFAM", "HOLY FAMILY SCHOOL", None, "MO", KANBY_MO_CO, "KANBY", KANBY),
    _school(
        "SYN-KS-OHFAM", "HOLY FAMILY CATHOLIC SCHOOL", None, "KS", OTTABY_KS_CO, "OTTABY", OTTABY
    ),
)
"""SYNTHETIC parish schools of a two-state market whose lists carry their churches."""

# Made-up counties and points for a Boston-like market of two states, whose list
# names schools of the second state's counties just past its own (as WMUR's names
# New Hampshire's Grafton County): Massachusetts names a district by its town
# alone ("Hanbury") and New Hampshire by its town and legal form ("Hanbury School
# District"), so the name of the twin just past the counties is the listing's word
# for word and the one in them is shorter; a school of one name in both; and a
# pair whose New Hampshire twin lies far north, 160 km from the market.
HANBY_MA_CO, PEMBY_NH_CO, HANBY_NH_CO, LYTBY_NH_CO = "88961", "88962", "88963", "88964"
BOSBY = (HANBY_MA_CO, PEMBY_NH_CO)
HANBURY_MA, LYTTLEBY_MA, PEMBROOK_NH = (42.12, -70.90), (42.30, -70.95), (43.33, -71.60)
HANBURY_NH, LYTTLEBY_NH = (43.62, -72.05), (44.85, -71.45)

TWIN_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-MA-HAN", "Hanbury", "MA", HANBY_MA_CO, "Hanbury", HANBURY_MA),
    _school("SYN-MA-HANHS", "Hanbury High", "SYN-MA-HAN", "MA", HANBY_MA_CO, "Hanbury", HANBURY_MA),
    _school(
        "SYN-MA-RUSES",
        "Russet Elementary School",
        "SYN-MA-HAN",
        "MA",
        HANBY_MA_CO,
        "Hanbury",
        HANBURY_MA,
    ),
    _district("SYN-MA-LYT", "Lyttleby", "MA", HANBY_MA_CO, "Lyttleby", LYTTLEBY_MA),
    _school(
        "SYN-MA-LYTHS",
        "Lyttleby High School",
        "SYN-MA-LYT",
        "MA",
        HANBY_MA_CO,
        "Lyttleby",
        LYTTLEBY_MA,
    ),
    _district("SYN-NH-PEM", "Pembrook School District", "NH", PEMBY_NH_CO, "Pembrook", PEMBROOK_NH),
    _school(
        "SYN-NH-PEMES",
        "Pembrook Elementary School",
        "SYN-NH-PEM",
        "NH",
        PEMBY_NH_CO,
        "Pembrook",
        PEMBROOK_NH,
    ),
    _district("SYN-NH-HANSD", "Hanbury School District", "NH", HANBY_NH_CO, "Hanbury", HANBURY_NH),
    _school(
        "SYN-NH-HANHS",
        "Hanbury High School",
        "SYN-NH-HANSD",
        "NH",
        HANBY_NH_CO,
        "Hanbury",
        HANBURY_NH,
    ),
    _school(
        "SYN-NH-RUSES",
        "Russet Elementary School",
        "SYN-NH-HANSD",
        "NH",
        HANBY_NH_CO,
        "Rumbury",
        HANBURY_NH,
    ),
    _district(
        "SYN-NH-LYTSD", "Lyttleby School District", "NH", LYTBY_NH_CO, "Lyttleby", LYTTLEBY_NH
    ),
    _school(
        "SYN-NH-LYTHS",
        "Lyttleby High School",
        "SYN-NH-LYTSD",
        "NH",
        LYTBY_NH_CO,
        "Lyttleby",
        LYTTLEBY_NH,
    ),
)
"""SYNTHETIC namesakes in two states of one market, one pair just past its counties."""

# A Missouri district named for a saint and numbered, as "ST. JAMES R-I" is, far
# from a market whose counties hold a private school of the saint's name.
JARVIS_CO, JARVIS_PARISH_CO = "88965", "88966"
JARVIS_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-MO-JARD", "ST. JARVIS R-I", "MO", JARVIS_CO, "ST JARVIS", (37.99, -91.61)),
    _school(
        "SYN-MO-JARHS",
        "ST. JARVIS HIGH",
        "SYN-MO-JARD",
        "MO",
        JARVIS_CO,
        "ST JARVIS",
        (37.99, -91.61),
    ),
    _school(
        "SYN-MO-JARC",
        "ST JARVIS CATHOLIC SCHOOL",
        None,
        "MO",
        JARVIS_PARISH_CO,
        "MILLSBY",
        (38.53, -89.99),
    ),
)
"""SYNTHETIC: a numbered district named for a saint, and a private school of the name."""


# NCES naming habits a closings list reads the other way. County codes 88970-88989.
HABIT_TN_CO, HABIT_MI_CO, HABIT_IN_A, HABIT_IN_B, HABIT_IN_C = (
    "88970",
    "88971",
    "88972",
    "88973",
    "88974",
)
HABIT_PA_A, HABIT_PA_B, HABIT_NJ_A, HABIT_NJ_B, HABIT_TX_CO = (
    "88975",
    "88976",
    "88977",
    "88978",
    "88979",
)
HABIT_TN_B, HABIT_OH_CO, HABIT_RI_CO, HABIT_MA_CO = "88980", "88981", "88982", "88983"
HABIT_MO_CO, HABIT_MI_B, HABIT_MI_C = "88984", "88985", "88986"
HABIT_RECORDS: tuple[DirectoryRecord, ...] = (
    # Tennessee: a city's district named by the city alone, which lists call
    # "<city> City Schools", beside its county's.
    _district("SYN-TN-MURB", "Murrowby", "TN", HABIT_TN_CO, "Murrowby", (35.85, -86.39)),
    _school(
        "SYN-TN-MURBE",
        "Murrowby Elementary",
        "SYN-TN-MURB",
        "TN",
        HABIT_TN_CO,
        "Murrowby",
        (35.85, -86.39),
    ),
    _district("SYN-TN-RUTC", "Rutherby County", "TN", HABIT_TN_CO, "Murrowby", (35.84, -86.40)),
    # And a city whose county's district bears its name too.
    _district("SYN-TN-TULB", "Tullby", "TN", HABIT_TN_B, "Tullby", (35.36, -86.21)),
    _district("SYN-TN-TULC", "Tullby County", "TN", HABIT_TN_B, "Tullby", (35.37, -86.22)),
    # Michigan: a county's intermediate school district, which NCES calls ISD,
    # beside the township's public schools of one name.
    _district("SYN-MI-WASI", "Washby ISD", "MI", HABIT_MI_CO, "ANN WASHBY", (42.28, -83.74)),
    _district("SYN-MI-WASP", "Washby Public Schools", "MI", HABIT_MI_CO, "Washby", (42.20, -83.60)),
    # Indiana: NCES's "Com", "Con", "Cnt" and "Co".
    _district(
        "SYN-IN-SRIP", "South Ripton Com Sch Corp", "IN", HABIT_IN_A, "Versby", (39.07, -85.25)
    ),
    _school(
        "SYN-IN-SRIPH",
        "South Ripton High School",
        "SYN-IN-SRIP",
        "IN",
        HABIT_IN_A,
        "Versby",
        (39.07, -85.25),
    ),
    _district(
        "SYN-IN-BART", "Bartley Con School Corp", "IN", HABIT_IN_A, "Columby", (39.20, -85.92)
    ),
    _district(
        "SYN-IN-BROW", "Brownsby Cnt Com Sch Corp", "IN", HABIT_IN_A, "Brownsby", (38.88, -86.04)
    ),
    _district(
        "SYN-IN-HUNT", "Huntley Co Com Sch Corp", "IN", HABIT_IN_A, "Huntley", (40.88, -85.50)
    ),
    _district(
        "SYN-IN-JEFF", "Southwestern-Jeffery Co Con", "IN", HABIT_IN_A, "Hanby", (38.74, -85.46)
    ),
    # Two districts of one name two counties apart, one of them "Con".
    _district(
        "SYN-IN-NWC", "Norwester Con School Corp", "IN", HABIT_IN_B, "Shelby", (39.52, -85.78)
    ),
    _district("SYN-IN-NWS", "Norwester School Corp", "IN", HABIT_IN_C, "Kokby", (40.49, -86.13)),
    # Pennsylvania: a township's district, which lists call "<town> School
    # District"; a township's and a borough's of one name; a township's beside
    # a district whose "Central" is part of its name.
    _district("SYN-PA-BENT", "Bensby Township SD", "PA", HABIT_PA_A, "Bensby", (40.10, -74.94)),
    _school(
        "SYN-PA-BENTH", "Bensby HS", "SYN-PA-BENT", "PA", HABIT_PA_A, "Bensby", (40.10, -74.94)
    ),
    _district("SYN-PA-BRIT", "Bristow Township SD", "PA", HABIT_PA_A, "Levitby", (40.14, -74.86)),
    _district("SYN-PA-BRIB", "Bristow Borough SD", "PA", HABIT_PA_A, "Bristow", (40.10, -74.85)),
    _district("SYN-PA-MANT", "Mannby Township SD", "PA", HABIT_PA_B, "Lancby", (40.08, -76.31)),
    _district("SYN-PA-MANC", "Mannby Central SD", "PA", HABIT_PA_B, "Mannby", (40.16, -76.40)),
    # New Jersey: a township's district NCES names without "Township"; a city's
    # and a township's of one name.
    _district(
        "SYN-NJ-CHER",
        "Cherrow Hill School District",
        "NJ",
        HABIT_NJ_A,
        "Cherrow Hill",
        (39.93, -75.02),
    ),
    _district(
        "SYN-NJ-UNIC", "Unionby City School District", "NJ", HABIT_NJ_B, "Unionby", (40.77, -74.03)
    ),
    _district(
        "SYN-NJ-UNIT",
        "Unionby Township School District",
        "NJ",
        HABIT_NJ_B,
        "Unionby",
        (40.70, -74.26),
    ),
    # Texas: "MT" ending one name of a pair is Mountain; an ISD and its
    # intermediate school.
    _district(
        "SYN-TX-EAGM", "EAGLEBY MT-SAGINOW ISD", "TX", HABIT_TX_CO, "FORT BY", (32.87, -97.39)
    ),
    _district("SYN-TX-BRAX", "BRAXBY ISD", "TX", HABIT_TX_CO, "BRAXBY", (32.70, -97.10)),
    _school(
        "SYN-TX-BRAXI", "BRAXBY INT", "SYN-TX-BRAX", "TX", HABIT_TX_CO, "BRAXBY", (32.70, -97.10)
    ),
    # Ohio: a city's district NCES names "Local".
    _district("SYN-OH-LOCK", "Lockby Local", "OH", HABIT_OH_CO, "Cincby", (39.23, -84.46)),
    # A private school that is an "Independent School", and a cooperative school.
    _school(
        "SYN-PA-STONE",
        "STONBY INDEPENDENT SCHOOL",
        None,
        "PA",
        HABIT_PA_B,
        "LANCBY",
        (40.04, -76.30),
    ),
    _district(
        "SYN-MA-HILC",
        "Hillby Cooperative Charter Public",
        "MA",
        HABIT_MA_CO,
        "Eastby",
        (42.27, -72.67),
    ),
    _school(
        "SYN-MA-HILCS",
        "Hillby Cooperative Charter Public School",
        "SYN-MA-HILC",
        "MA",
        HABIT_MA_CO,
        "Eastby",
        (42.27, -72.67),
    ),
    # Missouri's state schools, which NCES names without "State"; a town's
    # district beside a university's initials; Pennsylvania's "CS" inside a
    # name; a Tennessee charter school NCES does not call one.
    _district(
        "SYN-MO-SSSD",
        "MISSBY SCHOOLS FOR SEVERELY DISABLED",
        "MO",
        HABIT_MO_CO,
        "JEFFBY CITY",
        (38.57, -92.17),
    ),
    _school(
        "SYN-MO-MAPV",
        "MAPLEBY VALLEY SCHOOL",
        "SYN-MO-SSSD",
        "MO",
        HABIT_MO_CO,
        "KANSBY CITY",
        (39.03, -94.55),
    ),
    _district("SYN-TX-TEXC", "TEXBY CITY ISD", "TX", HABIT_TX_CO, "TEXBY CITY", (29.39, -94.92)),
    _district(
        "SYN-PA-PENC",
        "Pennby Hills CS of Enterprise",
        "PA",
        HABIT_PA_B,
        "Pennby Hills",
        (40.47, -79.83),
    ),
    _school(
        "SYN-PA-PENCS",
        "Pennby Hills CS of Enterprise",
        "SYN-PA-PENC",
        "PA",
        HABIT_PA_B,
        "Pennby Hills",
        (40.47, -79.83),
    ),
    _district(
        "SYN-TN-SHEL", "Shelbourne County Schools", "TN", HABIT_TN_B, "Memby", (35.15, -90.05)
    ),
    _school(
        "SYN-TN-MERIT",
        "Memby Merit Academy",
        "SYN-TN-SHEL",
        "TN",
        HABIT_TN_B,
        "Memby",
        (35.15, -90.05),
    ),
    # Missouri: a charter district named as one academy, whose schools add a part.
    _district("SYN-MO-UNIV", "UNIVBY ACADEMY", "MO", HABIT_MO_CO, "KANSBY CITY", (39.05, -94.57)),
    _school(
        "SYN-MO-UNIVM",
        "UNIVBY ACADEMY-MIDDLE",
        "SYN-MO-UNIV",
        "MO",
        HABIT_MO_CO,
        "KANSBY CITY",
        (39.05, -94.57),
    ),
    _school(
        "SYN-MO-UNIVU",
        "UNIVBY ACADEMY-UPPER",
        "SYN-MO-UNIV",
        "MO",
        HABIT_MO_CO,
        "KANSBY CITY",
        (39.05, -94.57),
    ),
    # Michigan: a district named with its county in brackets beside a namesake
    # two counties off, as NCES writes them.
    _district(
        "SYN-MI-RIVO",
        "Rivenby School District (Harlan)",
        "MI",
        HABIT_MI_B,
        "CALBY",
        (42.95, -85.10),
        county_name="Harlan County",
    ),
    _school(
        "SYN-MI-RIVOE",
        "Rivenby Elementary School",
        "SYN-MI-RIVO",
        "MI",
        HABIT_MI_B,
        "CALBY",
        (42.95, -85.10),
        county_name="Harlan County",
    ),
    _district(
        "SYN-MI-RIVH",
        "Rivenby District Public Schools",
        "MI",
        HABIT_MI_C,
        "RIVENBY HEIGHTS",
        (43.60, -84.20),
        county_name="Tamby County",
    ),
    # A state's section of a two-state list: one town's district in each state.
    _district("SYN-RI-SCIT", "Scitby", "RI", HABIT_RI_CO, "Clayby", (41.80, -71.62)),
    _district("SYN-MA-SCIT", "Scitby", "MA", HABIT_MA_CO, "Scitby", (42.20, -70.72)),
)
"""SYNTHETIC: districts and schools named as NCES names them where closings lists
name them otherwise (Tennessee's city districts, Michigan's intermediate school
districts, Indiana's abbreviations, Pennsylvania's and New Jersey's townships,
Texas's "MT"), with the namesakes that must still leave a listing no answer."""


# School systems NCES splits into several districts. County codes 88990-88999.
SYSTEM_MT_A, SYSTEM_MT_B, SYSTEM_AZ, SYSTEM_CA, SYSTEM_IL = (
    "88990",
    "88991",
    "88992",
    "88993",
    "88994",
)
SYSTEM_NY_A, SYSTEM_NY_B, SYSTEM_OK = "88995", "88996", "88997"
TAMSBY = (46.10, -110.20)
KELLBY = (48.20, -114.30)
KELLBY_EVERMONT = (48.22, -114.25)
MILEBY = (46.40, -105.80)
BOULBY = (46.23, -112.12)
BOULBY_JEFFBY = (46.24, -112.11)
PHENBY = (33.45, -112.07)
PHENBY_UNION = (33.47, -112.05)
PETALBY = (38.23, -122.64)
MERCBY = (37.30, -120.48)
ATWABY = (37.35, -120.61)
STREBBY = (41.12, -88.84)
STREBBY_HIGH = (41.13, -88.83)
BRONBY = (40.75, -73.99)
QUEENBY = (40.72, -73.80)


SYSTEM_RECORDS: tuple[DirectoryRecord, ...] = (
    # Montana: a town's elementary and high school districts of one name, at one office.
    _district("SYN-MT-TAMSE", "Tamsby Elem", "MT", SYSTEM_MT_A, "Tamsby", TAMSBY),
    _district("SYN-MT-TAMSH", "Tamsby H S", "MT", SYSTEM_MT_A, "Tamsby", TAMSBY),
    _school(
        "SYN-MT-TAMMS", "Tamsby Middle School", "SYN-MT-TAMSE", "MT", SYSTEM_MT_A, "Tamsby", TAMSBY
    ),
    _school(
        "SYN-MT-TAMCV", "Cora Vail School", "SYN-MT-TAMSE", "MT", SYSTEM_MT_A, "Tamsby", TAMSBY
    ),
    _school(
        "SYN-MT-TAMHS", "Tamsby Sr High School", "SYN-MT-TAMSH", "MT", SYSTEM_MT_A, "Tamsby", TAMSBY
    ),
    # Oklahoma: a town of the name, whose district is named by the town alone.
    _district("SYN-OK-TAMS", "TAMSBY", "OK", SYSTEM_OK, "TAMSBY", (36.53, -97.55)),
    # Montana: an elementary district named for its town and a high school
    # district named otherwise, at one office (Kalispell's "Kalispell Elem" and
    # "Flathead H S"); another elementary district of the town, with an office
    # of its own ("Evergreen Elem").
    _district("SYN-MT-KELE", "Kellby Elem", "MT", SYSTEM_MT_A, "Kellby", KELLBY),
    _district("SYN-MT-GLAH", "Glacierby H S", "MT", SYSTEM_MT_A, "Kellby", KELLBY),
    _district("SYN-MT-EVRE", "Evermont Elem", "MT", SYSTEM_MT_A, "Kellby", KELLBY_EVERMONT),
    _school(
        "SYN-MT-KELMS", "Kellby Middle School", "SYN-MT-KELE", "MT", SYSTEM_MT_A, "Kellby", KELLBY
    ),
    _school(
        "SYN-MT-GLAHS", "Glacierby High School", "SYN-MT-GLAH", "MT", SYSTEM_MT_A, "Kellby", KELLBY
    ),
    _school(
        "SYN-MT-RPHS", "Rising Pine High School", "SYN-MT-GLAH", "MT", SYSTEM_MT_A, "Kellby", KELLBY
    ),
    _school(
        "SYN-MT-EVRS",
        "Evermont School",
        "SYN-MT-EVRE",
        "MT",
        SYSTEM_MT_A,
        "Kellby",
        KELLBY_EVERMONT,
    ),
    # Montana: a town that ends "City", whose high school district is its county's
    # ("Miles City Elem" and "Custer County H S"), at one office.
    _district("SYN-MT-MILE", "Mileby City Elem", "MT", SYSTEM_MT_B, "Mileby City", MILEBY),
    _district("SYN-MT-CUSH", "Custerby County H S", "MT", SYSTEM_MT_B, "Mileby City", MILEBY),
    _school(
        "SYN-MT-MILWS",
        "Washington School",
        "SYN-MT-MILE",
        "MT",
        SYSTEM_MT_B,
        "Mileby City",
        MILEBY,
    ),
    _school(
        "SYN-MT-CUSHS",
        "Custerby County District High School",
        "SYN-MT-CUSH",
        "MT",
        SYSTEM_MT_B,
        "Mileby City",
        MILEBY,
    ),
    # Montana: the same pair with an office each ("Boulder Elem" and
    # "Jefferson H S"): run apart, no system.
    _district("SYN-MT-BOUE", "Boulby Elem", "MT", SYSTEM_MT_B, "Boulby", BOULBY),
    _district("SYN-MT-JEFH", "Jeffby H S", "MT", SYSTEM_MT_B, "Boulby", BOULBY_JEFFBY),
    _school("SYN-MT-BOUS", "Boulby School", "SYN-MT-BOUE", "MT", SYSTEM_MT_B, "Boulby", BOULBY),
    _school(
        "SYN-MT-JEFHS",
        "Jeffby High School",
        "SYN-MT-JEFH",
        "MT",
        SYSTEM_MT_B,
        "Boulby",
        BOULBY_JEFFBY,
    ),
    # Montana: two elementary districts of one name in two counties: no system.
    _district("SYN-MT-HARA", "Harlby Elem", "MT", SYSTEM_MT_A, "Harlby", (46.90, -110.90)),
    _district("SYN-MT-HARB", "Harlby Elem", "MT", SYSTEM_MT_B, "North Harlby", (46.30, -105.20)),
    # Arizona: a town's elementary district and its union high school district
    # of one name, an office each, as NCES ends their names with entity numbers.
    _district(
        "SYN-AZ-PHNE", "Phenby Elementary District (4256)", "AZ", SYSTEM_AZ, "Phenby", PHENBY
    ),
    _district(
        "SYN-AZ-PHNH",
        "Phenby Union High School District (4286)",
        "AZ",
        SYSTEM_AZ,
        "Phenby",
        PHENBY_UNION,
    ),
    _school(
        "SYN-AZ-PHNES", "Lowell Brandt School", "SYN-AZ-PHNE", "AZ", SYSTEM_AZ, "Phenby", PHENBY
    ),
    _school(
        "SYN-AZ-PHNBIO",
        "Phenby Union Bioscience High School",
        "SYN-AZ-PHNH",
        "AZ",
        SYSTEM_AZ,
        "Phenby",
        PHENBY_UNION,
    ),
    # California: a city's elementary and high school districts of one name at
    # one office ("Petaluma City Elementary" and "Petaluma Joint Union High");
    # and a city's elementary district beside a union high school district of
    # the name whose office is in another town ("Merced City Elementary" and
    # "Merced Union High", in Atwater).
    _district("SYN-CA-PETE", "Petalby City Elementary", "CA", SYSTEM_CA, "Petalby", PETALBY),
    _district("SYN-CA-PETH", "Petalby Joint Union High", "CA", SYSTEM_CA, "Petalby", PETALBY),
    _school("SYN-CA-PETHS", "Petalby High", "SYN-CA-PETH", "CA", SYSTEM_CA, "Petalby", PETALBY),
    _school(
        "SYN-CA-PETES", "Mary Colley Elementary", "SYN-CA-PETE", "CA", SYSTEM_CA, "Petalby", PETALBY
    ),
    _district("SYN-CA-MERE", "Mercby City Elementary", "CA", SYSTEM_CA, "Mercby", MERCBY),
    _district("SYN-CA-MERH", "Mercby Union High", "CA", SYSTEM_CA, "Atwaby", ATWABY),
    _school("SYN-CA-MERHS", "Atwaby High", "SYN-CA-MERH", "CA", SYSTEM_CA, "Atwaby", ATWABY),
    _school(
        "SYN-CA-MERES", "Rose Hall Elementary", "SYN-CA-MERE", "CA", SYSTEM_CA, "Mercby", MERCBY
    ),
    # California: a city's elementary and high school districts of one name
    # that neither says "City", which lists call "<city> City Schools" ("Santa
    # Rosa Elementary" and "Santa Rosa High"), beside a charter academy of the
    # name in another town; and a city's elementary district that says "City"
    # beside a union high school district that does not ("Salinas City
    # Elementary" and "Salinas Union High"), an office each.
    _district("SYN-CA-ROSE", "Rosaby Elementary", "CA", SYSTEM_CA, "Rosaby", (38.44, -122.71)),
    _district("SYN-CA-ROSH", "Rosaby High", "CA", SYSTEM_CA, "Rosaby", (38.45, -122.70)),
    _school(
        "SYN-CA-ROSHS",
        "Maple Crest High",
        "SYN-CA-ROSH",
        "CA",
        SYSTEM_CA,
        "Rosaby",
        (38.45, -122.70),
    ),
    _school(
        "SYN-CA-ROSES",
        "Lin Ward Elementary",
        "SYN-CA-ROSE",
        "CA",
        SYSTEM_CA,
        "Rosaby",
        (38.44, -122.71),
    ),
    _district("SYN-CA-ROSA", "Rosaby Academy District", "CA", "88998", "Menby", (33.70, -117.18)),
    _school(
        "SYN-CA-ROSAS", "Rosaby Academy", "SYN-CA-ROSA", "CA", "88998", "Menby", (33.70, -117.18)
    ),
    _district(
        "SYN-CA-SALE", "Salinby City Elementary", "CA", SYSTEM_CA, "Salinby", (36.67, -121.65)
    ),
    _district("SYN-CA-SALH", "Salinby Union High", "CA", SYSTEM_CA, "Salinby", (36.68, -121.64)),
    _school(
        "SYN-CA-SALES",
        "Kent Oyler Elementary",
        "SYN-CA-SALE",
        "CA",
        SYSTEM_CA,
        "Salinby",
        (36.67, -121.65),
    ),
    _school(
        "SYN-CA-SALHS",
        "Harden Ridge High",
        "SYN-CA-SALH",
        "CA",
        SYSTEM_CA,
        "Salinby",
        (36.68, -121.64),
    ),
    # Illinois: a town's elementary and township high school districts.
    _district("SYN-IL-STRE", "Strebby ESD 44", "IL", SYSTEM_IL, "Strebby", STREBBY),
    _district("SYN-IL-STRH", "Strebby Twp HSD 40", "IL", SYSTEM_IL, "Strebby", STREBBY_HIGH),
    _school(
        "SYN-IL-STRES", "Centennial Elem School", "SYN-IL-STRE", "IL", SYSTEM_IL, "Strebby", STREBBY
    ),
    _school(
        "SYN-IL-STRHS",
        "Strebby Twp High School",
        "SYN-IL-STRH",
        "IL",
        SYSTEM_IL,
        "Strebby",
        STREBBY_HIGH,
    ),
    # New York: a city whose system NCES splits into geographic districts in two
    # counties, with a district 75 of special schools, beside a charter school
    # of the city's name ("NEW YORK CITY GEOGRAPHIC DISTRICT # 1", "NYC SPECIAL
    # SCHOOLS - DISTRICT 75", "NEW YORK CITY CHARTER SCHOOL OF THE ARTS").
    _district(
        "SYN-NY-BC01", "BRONBY CITY GEOGRAPHIC DISTRICT # 1", "NY", SYSTEM_NY_A, "BRONBY", BRONBY
    ),
    _district(
        "SYN-NY-BC02", "BRONBY CITY GEOGRAPHIC DISTRICT # 2", "NY", SYSTEM_NY_A, "BRONBY", BRONBY
    ),
    _district(
        "SYN-NY-BC10", "BRONBY CITY GEOGRAPHIC DISTRICT #10", "NY", SYSTEM_NY_B, "QUEENBY", QUEENBY
    ),
    _district(
        "SYN-NY-BC11", "BRONBY CITY GEOGRAPHIC DISTRICT #11", "NY", SYSTEM_NY_B, "QUEENBY", QUEENBY
    ),
    _district(
        "SYN-NY-BC75",
        "BRONBY CITY SPECIAL SCHOOLS - DISTRICT 75",
        "NY",
        SYSTEM_NY_A,
        "BRONBY",
        BRONBY,
    ),
    _district(
        "SYN-NY-BCCA", "BRONBY CITY CHARTER SCHOOL OF THE ARTS", "NY", SYSTEM_NY_A, "BRONBY", BRONBY
    ),
    _school("SYN-NY-PS101", "PS 101 ADA LANE", "SYN-NY-BC01", "NY", SYSTEM_NY_A, "BRONBY", BRONBY),
    _school(
        "SYN-NY-PS102", "PS 102 MARCUS HOLT", "SYN-NY-BC02", "NY", SYSTEM_NY_A, "BRONBY", BRONBY
    ),
    _school(
        "SYN-NY-IS210", "IS 210 NELL PRATT", "SYN-NY-BC10", "NY", SYSTEM_NY_B, "QUEENBY", QUEENBY
    ),
    _school(
        "SYN-NY-PS211", "PS 211 OTTO REYES", "SYN-NY-BC11", "NY", SYSTEM_NY_B, "QUEENBY", QUEENBY
    ),
    _school("SYN-NY-P751", "P751 HARBOR VIEW", "SYN-NY-BC75", "NY", SYSTEM_NY_A, "BRONBY", BRONBY),
    _school("SYN-NY-P752", "P752 TIDE HILL", "SYN-NY-BC75", "NY", SYSTEM_NY_A, "BRONBY", BRONBY),
    _school(
        "SYN-NY-BCCAS",
        "BRONBY CITY CHARTER SCHOOL OF THE ARTS",
        "SYN-NY-BCCA",
        "NY",
        SYSTEM_NY_A,
        "BRONBY",
        BRONBY,
    ),
)
"""SYNTHETIC: school systems NCES splits into several districts (a town's elementary
and high school districts, a city's geographic districts), and the pairs that are
no system: two offices, two towns, two counties."""

# Made-up counties and points for markets of two states whose namesakes each
# state writes its own way: Tennessee names a city's district by the city alone
# ("Bristmoor"), Virginia with "City Public Schools", 3 km apart as Bristol's two
# halves are; Florida names a county's district by the county alone
# ("ESCAMBRY"), Alabama with "County", 70 km apart; Kentucky's "Independent" and
# Ohio's "Exempted Village", 115 km apart; and a county's district in Kentucky
# beside a town's in Indiana, which a list tells apart by "County". A private
# school NCES names with its campus, and one with two campuses.
BRISTMOOR_TN_CO, BRISTMOOR_VA_CO, ESCAMBRY_FL_CO, ESCAMBRY_AL_CO = (
    "88005",
    "88006",
    "88007",
    "88008",
)
COVERMOOR_KY_CO, COVERMOOR_OH_CO, MADMOOR_KY_CO, MADMOOR_IN_CO = (
    "88009",
    "88010",
    "88011",
    "88012",
)
BRISTMOOR_TN, BRISTMOOR_VA = (36.57, -82.20), (36.59, -82.18)
ESCAMBRY_FL, ESCAMBRY_AL = (30.45, -87.22), (31.10, -87.07)
COVERMOOR_KY, COVERMOOR_OH = (39.08, -84.51), (40.12, -84.35)
MADMOOR_KY, MADMOOR_IN = (37.75, -84.29), (38.74, -85.38)
PELLBROOK, HOLLOWBY_NORTH, HOLLOWBY_SOUTH = (39.03, -94.59), (38.98, -94.67), (38.90, -94.66)
BETWEEN_KESSBY = (39.105, -94.60)
"""A point between Kessby City's two halves, as a Kansas City station's is."""

ACROSS_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-TN-BRIS", "Bristmoor", "TN", BRISTMOOR_TN_CO, "Bristmoor", BRISTMOOR_TN),
    _school(
        "SYN-TN-BRISH", "Bristmoor High School", "SYN-TN-BRIS", "TN", BRISTMOOR_TN_CO,
        "Bristmoor", BRISTMOOR_TN,
    ),
    _school(
        "SYN-TN-BRISE", "Anderby Elementary", "SYN-TN-BRIS", "TN", BRISTMOOR_TN_CO,
        "Bristmoor", BRISTMOOR_TN,
    ),
    _district(
        "SYN-VA-BRIS", "Bristmoor City Public Schools", "VA", BRISTMOOR_VA_CO, "Bristmoor",
        BRISTMOOR_VA,
    ),
    _school(
        "SYN-VA-BRISH", "Bristmoor High", "SYN-VA-BRIS", "VA", BRISTMOOR_VA_CO, "Bristmoor",
        BRISTMOOR_VA,
    ),
    _school(
        "SYN-VA-BRISE", "Highby Elementary", "SYN-VA-BRIS", "VA", BRISTMOOR_VA_CO, "Bristmoor",
        BRISTMOOR_VA,
    ),
    _district(
        "SYN-FL-ESCA", "ESCAMBRY", "FL", ESCAMBRY_FL_CO, "PENSABY", ESCAMBRY_FL,
        county_name="Escambry County",
    ),
    _school(
        "SYN-FL-ESCAH", "PENSABY HIGH SCHOOL", "SYN-FL-ESCA", "FL", ESCAMBRY_FL_CO, "PENSABY",
        ESCAMBRY_FL, county_name="Escambry County",
    ),
    _school(
        "SYN-FL-ESCAE", "WARRINGBY ELEMENTARY SCHOOL", "SYN-FL-ESCA", "FL", ESCAMBRY_FL_CO,
        "PENSABY", ESCAMBRY_FL, county_name="Escambry County",
    ),
    _district(
        "SYN-AL-ESCA", "Escambry County", "AL", ESCAMBRY_AL_CO, "Brewby", ESCAMBRY_AL,
        county_name="Escambry County",
    ),
    _school(
        "SYN-AL-ESCAH", "Brewby High School", "SYN-AL-ESCA", "AL", ESCAMBRY_AL_CO, "Brewby",
        ESCAMBRY_AL, county_name="Escambry County",
    ),
    _school(
        "SYN-AL-ESCAE", "Flomby Elementary School", "SYN-AL-ESCA", "AL", ESCAMBRY_AL_CO,
        "Brewby", ESCAMBRY_AL, county_name="Escambry County",
    ),
    _district(
        "SYN-KY-COVI", "Covermoor Independent", "KY", COVERMOOR_KY_CO, "Covermoor", COVERMOOR_KY
    ),
    _school(
        "SYN-KY-COVIH", "Holmesby High School", "SYN-KY-COVI", "KY", COVERMOOR_KY_CO,
        "Covermoor", COVERMOOR_KY,
    ),
    _school(
        "SYN-KY-COVIE", "Glenby Elementary", "SYN-KY-COVI", "KY", COVERMOOR_KY_CO, "Covermoor",
        COVERMOOR_KY,
    ),
    _district(
        "SYN-OH-COVE", "Covermoor Exempted Village", "OH", COVERMOOR_OH_CO, "Covermoor",
        COVERMOOR_OH,
    ),
    _school(
        "SYN-OH-COVEH", "Covermoor High School", "SYN-OH-COVE", "OH", COVERMOOR_OH_CO,
        "Covermoor", COVERMOOR_OH,
    ),
    _school(
        "SYN-OH-COVEE", "Covermoor Elementary School", "SYN-OH-COVE", "OH", COVERMOOR_OH_CO,
        "Covermoor", COVERMOOR_OH,
    ),
    _district(
        "SYN-KY-MADC", "Madmoor County", "KY", MADMOOR_KY_CO, "Richby", MADMOOR_KY,
        county_name="Madmoor County",
    ),
    _school(
        "SYN-KY-MADCH", "Madmoor Central High School", "SYN-KY-MADC", "KY", MADMOOR_KY_CO,
        "Richby", MADMOOR_KY, county_name="Madmoor County",
    ),
    _school(
        "SYN-KY-MADCE", "Kirksby Elementary", "SYN-KY-MADC", "KY", MADMOOR_KY_CO, "Richby",
        MADMOOR_KY, county_name="Madmoor County",
    ),
    _district(
        "SYN-IN-MADT", "Madmoor Consolidated Schools", "IN", MADMOOR_IN_CO, "Madmoor", MADMOOR_IN
    ),
    _school(
        "SYN-IN-MADTH", "Madmoor Junior-Senior High School", "SYN-IN-MADT", "IN", MADMOOR_IN_CO,
        "Madmoor", MADMOOR_IN,
    ),
    _school(
        "SYN-IN-MADTE", "Deputyby Elementary School", "SYN-IN-MADT", "IN", MADMOOR_IN_CO,
        "Madmoor", MADMOOR_IN,
    ),
    _school(
        "SYN-MO-PELL", "THE PELLBROOK HILL SCHOOL - WARNELL CAMPUS", None, "MO", KANBY_MO_CO,
        "KANBY", PELLBROOK,
    ),
    _school(
        "SYN-KS-HOLN", "HOLLOWBY DAY SCHOOL - NORTH CAMPUS", None, "KS", WYANBY_KS_CO, "OVERBY",
        HOLLOWBY_NORTH,
    ),
    _school(
        "SYN-KS-HOLS", "HOLLOWBY DAY SCHOOL - SOUTH CAMPUS", None, "KS", WYANBY_KS_CO, "OVERBY",
        HOLLOWBY_SOUTH,
    ),
)  # fmt: skip
"""SYNTHETIC namesakes across a state line, each written as its state writes names, and
private schools NCES names with their campus."""

# Made-up counties and points for districts one of whose schools a list's name
# says word for word while the district's name does not: the listing says a
# word, a level or a legal form the district's name lacks. Tennessee's "Cheatham
# Co Central" (the county's Central High School) beside "Cheatham County",
# Ohio's "Lakota Central" beside "Lakota Local", California's independent study
# school "Selma Independent" beside "Selma Unified" and "Waterford Junior"
# beside "Waterford Unified", Texas's juvenile justice programs ("CYPRESS-FAIRBANKS
# J J A E P", "WHITEHOUSE A E P") beside their ISDs, a Minnesota intermediate
# district's program named "District 287 - ALC - IS", and a county's community
# school named for a city whose school system is two districts. Beside them the
# names that stay the district's: a school a district names "<town> Schools"
# (Texas's "MINERAL WELLS SCHOOLS" in "MINERAL WELLS ISD"), and a district of
# one school.
CHEDDBY_CO, LAKEBY_CO, SELMBY_CO, CYPRBY_CO, DAKBY_CO, CRAFTBY_CO = (
    "88013",
    "88014",
    "88015",
    "88016",
    "88017",
    "88018",
)
CHEDDBY, LAKEBY, SELMBY, WATERBY = (
    (36.30, -87.10),
    (39.35, -84.40),
    (36.57, -119.61),
    (37.64, -120.76),
)
CYPRBY, WHITBY, MINERBY = (29.95, -95.65), (32.22, -95.22), (32.81, -98.11)
DAKBY, CRAFTBY = (44.73, -93.20), (44.65, -72.37)

OWN_SCHOOL_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-TN-CHDC", "Cheddby County", "TN", CHEDDBY_CO, "Ashby", CHEDDBY),
    _school(
        "SYN-TN-CHDCC", "Cheddby Co Central", "SYN-TN-CHDC", "TN", CHEDDBY_CO, "Ashby", CHEDDBY
    ),
    _school(
        "SYN-TN-CHDCM", "Cheddby Middle School", "SYN-TN-CHDC", "TN", CHEDDBY_CO, "Ashby", CHEDDBY
    ),
    _school(
        "SYN-TN-CHDCE", "West Cheddby Elementary", "SYN-TN-CHDC", "TN", CHEDDBY_CO, "Ashby",
        CHEDDBY,
    ),
    _school(
        "SYN-TN-CHDCV", "Cheddby County Virtual School", "SYN-TN-CHDC", "TN", CHEDDBY_CO, "Ashby",
        CHEDDBY,
    ),
    _district("SYN-OH-LAKL", "Lakeby Local", "OH", LAKEBY_CO, "Liberby Township", LAKEBY),
    _school(
        "SYN-OH-LAKLC", "Lakeby Central", "SYN-OH-LAKL", "OH", LAKEBY_CO, "Liberby Township",
        LAKEBY,
    ),
    _school(
        "SYN-OH-LAKLE", "Lakeby East High School", "SYN-OH-LAKL", "OH", LAKEBY_CO,
        "Liberby Township", LAKEBY,
    ),
    _school(
        "SYN-OH-LAKLR", "Lakeby Ridge Junior School", "SYN-OH-LAKL", "OH", LAKEBY_CO,
        "Liberby Township", LAKEBY,
    ),
    _district("SYN-CA-SELU", "Selmby Unified", "CA", SELMBY_CO, "Selmby", SELMBY),
    _school("SYN-CA-SELI", "Selmby Independent", "SYN-CA-SELU", "CA", SELMBY_CO, "Selmby", SELMBY),
    _school("SYN-CA-SELH", "Selmby High", "SYN-CA-SELU", "CA", SELMBY_CO, "Selmby", SELMBY),
    _school("SYN-CA-SELM", "Garfby Middle", "SYN-CA-SELU", "CA", SELMBY_CO, "Selmby", SELMBY),
    _district("SYN-CA-WATU", "Waterby Unified", "CA", SELMBY_CO, "Waterby", WATERBY),
    _school("SYN-CA-WATJ", "Waterby Junior", "SYN-CA-WATU", "CA", SELMBY_CO, "Waterby", WATERBY),
    _school("SYN-CA-WATH", "Waterby High", "SYN-CA-WATU", "CA", SELMBY_CO, "Waterby", WATERBY),
    _school("SYN-CA-WATE", "Hickby Elementary", "SYN-CA-WATU", "CA", SELMBY_CO, "Waterby", WATERBY),
    _district("SYN-TX-CYFA", "CYPRBY-FAIRMONT ISD", "TX", CYPRBY_CO, "HOUSBY", CYPRBY),
    _school(
        "SYN-TX-CYFJ", "CYPRBY-FAIRMONT J J A E P", "SYN-TX-CYFA", "TX", CYPRBY_CO, "HOUSBY", CYPRBY
    ),
    _school("SYN-TX-CYFP", "CYPRBY PARK H S", "SYN-TX-CYFA", "TX", CYPRBY_CO, "HOUSBY", CYPRBY),
    _school("SYN-TX-CYFC", "CYPRBY CREEK H S", "SYN-TX-CYFA", "TX", CYPRBY_CO, "HOUSBY", CYPRBY),
    _school("SYN-TX-CYFE", "LANGBY EL", "SYN-TX-CYFA", "TX", CYPRBY_CO, "HOUSBY", CYPRBY),
    _district("SYN-TX-WHIT", "WHITBY ISD", "TX", CYPRBY_CO, "WHITBY", WHITBY),
    _school("SYN-TX-WHITA", "WHITBY A E P", "SYN-TX-WHIT", "TX", CYPRBY_CO, "WHITBY", WHITBY),
    _school("SYN-TX-WHITH", "WHITBY H S", "SYN-TX-WHIT", "TX", CYPRBY_CO, "WHITBY", WHITBY),
    _school("SYN-TX-WHITJ", "WHITBY J H", "SYN-TX-WHIT", "TX", CYPRBY_CO, "WHITBY", WHITBY),
    _district("SYN-TX-MINW", "MINERBY WELLS ISD", "TX", CYPRBY_CO, "MINERBY WELLS", MINERBY),
    _school(
        "SYN-TX-MINWS", "MINERBY WELLS SCHOOLS", "SYN-TX-MINW", "TX", CYPRBY_CO, "MINERBY WELLS",
        MINERBY,
    ),
    _school(
        "SYN-TX-MINWH", "MINERBY WELLS H S", "SYN-TX-MINW", "TX", CYPRBY_CO, "MINERBY WELLS",
        MINERBY,
    ),
    _district("SYN-MN-I917", "Intermediate School District 917", "MN", DAKBY_CO, "Rosemby", DAKBY),
    _school(
        "SYN-MN-I917A", "District 917 - ALC - IS", "SYN-MN-I917", "MN", DAKBY_CO, "Rosemby", DAKBY
    ),
    _school("SYN-MN-I917B", "ALC Eastby HS-IS", "SYN-MN-I917", "MN", DAKBY_CO, "Rosemby", DAKBY),
    _school(
        "SYN-MN-I917C", "Dakby Alternative Learning Center", "SYN-MN-I917", "MN", DAKBY_CO,
        "Rosemby", DAKBY,
    ),
    _district(
        "SYN-CA-SONO", "Sonby County Office of Education", "CA", SYSTEM_CA, "Sonby", PETALBY
    ),
    _school(
        "SYN-CA-SONOP", "Petalby Community", "SYN-CA-SONO", "CA", SYSTEM_CA, "Petalby", PETALBY
    ),
    _district("SYN-VT-CRAF", "Craftby School District", "VT", CRAFTBY_CO, "Craftby", CRAFTBY),
    _school("SYN-VT-CRAFS", "Craftby Schools", "SYN-VT-CRAF", "VT", CRAFTBY_CO, "Craftby", CRAFTBY),
)  # fmt: skip
"""SYNTHETIC districts one of whose schools a list's name says word for word while the
district's name does not, and names that stay the district's."""

# New Jersey townships of one name in two counties, each running a district NCES
# writes its own way: "Township of Unionmere School District" beside "Unionmere
# Township School District" (the word order is no part of the name, as New
# Jersey's "Township of Union School District" and "Union Township School
# District"), "Lawrencemere Township School District" beside "Lawrencemere Township
# Public School District" (nor is the legal form), and "Springmere Public School
# District" beside "Springmere Township School District" (NCES leaves a township's
# "Township" out as often as it says it). Only a point much nearer one of them,
# or counties that hold one and lie beyond a list's reach of the other, tells
# them apart. Made-up names, counties and places.
UNIONMERE_A_CO, UNIONMERE_B_CO, OCEANMERE_A_CO, OCEANMERE_B_CO = "88021", "88022", "88023", "88024"
LAWRENCEMERE_A_CO, LAWRENCEMERE_B_CO = "88025", "88026"
MONROEMERE_A_CO, MONROEMERE_B_CO = "88027", "88028"
FRANKLINMERE_A_CO, FRANKLINMERE_B_CO, FRANKLINMERE_C_CO, FRANKLINMERE_D_CO = (
    "88029",
    "88030",
    "88031",
    "88032",
)
SPRINGMERE_A_CO, SPRINGMERE_B_CO = "88033", "88034"
UNIONMERE_A, UNIONMERE_B = (41.30, -74.10), (41.22, -75.18)
"""91 km apart: beyond a list's reach of each other."""
OCEANMERE_A, OCEANMERE_B = (41.05, -73.60), (40.60, -73.80)
"""53 km apart: within it."""
LAWRENCEMERE_A, LAWRENCEMERE_B = (40.05, -75.85), (41.00, -75.40)
MONROEMERE_A, MONROEMERE_B = (41.45, -73.70), (40.75, -74.30)
FRANKLINMERE_A, FRANKLINMERE_B = (40.20, -75.60), (41.60, -74.90)
FRANKLINMERE_C, FRANKLINMERE_D = (41.35, -74.45), (41.95, -74.50)
SPRINGMERE_A, SPRINGMERE_B = (41.70, -73.95), (40.95, -74.60)


def _township(
    record_id: str,
    name: str,
    county: str,
    town: str,
    point: tuple[float, float],
    *schools: str,
) -> tuple[DirectoryRecord, ...]:
    """A New Jersey township's district, and its schools."""
    district = _district(record_id, name, "NJ", county, town, point)
    return (
        district,
        *(
            _school(f"{record_id}{i}", school, record_id, "NJ", county, town, point)
            for i, school in enumerate(schools, start=1)
        ),
    )


TOWNSHIP_RECORDS: tuple[DirectoryRecord, ...] = (
    *_township(
        "SYN-NJ-UNIA",
        "Township of Unionmere School District",
        UNIONMERE_A_CO,
        "Unionmere",
        UNIONMERE_A,
        "Unionmere High School",
        "Connecby Elementary School",
    ),
    *_township(
        "SYN-NJ-UNIB",
        "Unionmere Township School District",
        UNIONMERE_B_CO,
        "Pittsby",
        UNIONMERE_B,
        "Unionmere Township Elementary School",
        "Unionmere Township Middle School",
    ),
    *_township(
        "SYN-NJ-OCEA",
        "Township of Oceanmere School District",
        OCEANMERE_A_CO,
        "Oakby",
        OCEANMERE_A,
        "Oceanmere Township High School",
        "Oceanmere Township Elementary School",
    ),
    *_township(
        "SYN-NJ-OCEB",
        "Oceanmere Township School District",
        OCEANMERE_B_CO,
        "Waretby",
        OCEANMERE_B,
        "Waretby Elementary School",
        "Priffby Elementary School",
    ),
    *_township(
        "SYN-NJ-LAWA",
        "Lawrencemere Township School District",
        LAWRENCEMERE_A_CO,
        "Cedarby",
        LAWRENCEMERE_A,
        "Lawrencemere Township Elementary School",
    ),
    *_township(
        "SYN-NJ-LAWB",
        "Lawrencemere Township Public School District",
        LAWRENCEMERE_B_CO,
        "Lawrencemere",
        LAWRENCEMERE_B,
        "Lawrencemere High School",
        "Lawrencemere Middle School",
    ),
    *_township(
        "SYN-NJ-MONA",
        "Monroemere Township School District",
        MONROEMERE_A_CO,
        "Monroemere",
        MONROEMERE_A,
        "Monroemere Township High School",
        "Monroemere Township Middle School",
    ),
    *_township(
        "SYN-NJ-MONB",
        "Monroemere Township Public School District",
        MONROEMERE_B_CO,
        "Williamsby",
        MONROEMERE_B,
        "Williamsby High School",
        "Hollyby Glen Elementary School",
    ),
    *_township(
        "SYN-NJ-FRAA",
        "Township of Franklinmere School District",
        FRANKLINMERE_A_CO,
        "Franklinmere",
        FRANKLINMERE_A,
        "Franklinmere Township Elementary School",
    ),
    *_township(
        "SYN-NJ-FRAB",
        "Franklinmere Township School District",
        FRANKLINMERE_B_CO,
        "Quakerby",
        FRANKLINMERE_B,
        "Franklinmere Township School",
    ),
    *_township(
        "SYN-NJ-FRAC",
        "Franklinmere Township Public School District",
        FRANKLINMERE_C_CO,
        "Somersby",
        FRANKLINMERE_C,
        "Franklinmere High School",
        "Franklinmere Middle School",
    ),
    *_township(
        "SYN-NJ-FRAD",
        "Franklinmere Borough School District",
        FRANKLINMERE_D_CO,
        "Franklinmere",
        FRANKLINMERE_D,
        "Franklinmere Borough School",
    ),
    *_township(
        "SYN-NJ-SPRA",
        "Springmere Public School District",
        SPRINGMERE_A_CO,
        "Springmere",
        SPRINGMERE_A,
        "Dayby Elementary School",
        "Gaudby Middle School",
    ),
    *_township(
        "SYN-NJ-SPRB",
        "Springmere Township School District",
        SPRINGMERE_B_CO,
        "Jobsby",
        SPRINGMERE_B,
        "Springmere Township Elementary School",
    ),
)


# Private and public schools whose names begin with a place word (Village, City,
# Town) or hold one with more of the name after it: the word is the name's own,
# and a listing that leaves it out names another school. Beside them, districts
# whose City ends the name after their town's, which a listing may leave out.
LEAD_NC_CO, LEAD_CA_CO, LEAD_NJ_CO, LEAD_CO_CO, LEAD_IN_CO = (
    "88040",
    "88041",
    "88042",
    "88043",
    "88044",
)
LEAD_MO_CO, LEAD_OH_CO, LEAD_GA_CO, LEAD_MI_CO, LEAD_NY_CO = (
    "88045",
    "88046",
    "88047",
    "88048",
    "88049",
)
LEAD_IL_CO, LEAD_NJ_B_CO = "88050", "88052"
QUELLMOOR = (39.95, -82.40)
BRINDLEBY = (40.60, -74.60)
OSTERMOOR = (44.70, -85.60)
PALLISBY = (42.60, -76.20)
LEADING_RECORDS: tuple[DirectoryRecord, ...] = (
    _school(
        "SYN-NC-VCA", "VILLAGE CHRISTIAN ACADEMY", None, "NC", LEAD_NC_CO, "Corvell", (35.9, -79.1)
    ),
    _school(
        "SYN-CA-TCD",
        "TOWN & COUNTRY DAY SCHOOL",
        None,
        "CA",
        LEAD_CA_CO,
        "Nettleby",
        (37.4, -121.9),
    ),
    _school(
        "SYN-CA-VMS",
        "VILLAGE MONTESSORI SCHOOL",
        None,
        "CA",
        LEAD_CA_CO,
        "Nettleby",
        (37.4, -121.9),
    ),
    _district(
        "SYN-NJ-VCHD", "The Village Charter School", "NJ", LEAD_NJ_CO, "Trentby", (40.2, -74.7)
    ),
    _school(
        "SYN-NJ-VCHS",
        "The Village Charter School",
        "SYN-NJ-VCHD",
        "NJ",
        LEAD_NJ_CO,
        "Trentby",
        (40.2, -74.7),
    ),
    _school(
        "SYN-CO-VCDC",
        "VILLAGE CHILD DEVELOPMENT CENTER",
        None,
        "CO",
        LEAD_CO_CO,
        "Lorriby",
        (39.6, -105.0),
    ),
    _school("SYN-IN-KCA", "KID CITY ACADEMY", None, "IN", LEAD_IN_CO, "Marrowby", (39.8, -86.2)),
    _school("SYN-MO-CA", "CITY ACADEMY", None, "MO", LEAD_MO_CO, "Sainby", (38.6, -90.3)),
    _school(
        "SYN-OH-VCS", "VILLAGE CHRISTIAN SCHOOL", None, "OH", LEAD_OH_CO, "Quellmoor", QUELLMOOR
    ),
    _district("SYN-OH-QUEC", "Quellmoor City", "OH", LEAD_OH_CO, "Quellmoor", QUELLMOOR),
    _school(
        "SYN-OH-QUEH",
        "Quellmoor High School",
        "SYN-OH-QUEC",
        "OH",
        LEAD_OH_CO,
        "Quellmoor",
        QUELLMOOR,
    ),
    _school(
        "SYN-OH-QUEE",
        "Harlan Brooke Elementary",
        "SYN-OH-QUEC",
        "OH",
        LEAD_OH_CO,
        "Quellmoor",
        QUELLMOOR,
    ),
    _school("SYN-GA-MIT", "MONTESSORI IN TOWN", None, "GA", LEAD_GA_CO, "Atlaby", (33.8, -84.4)),
    _school(
        "SYN-MI-OCC",
        "OSTERMOOR CITY CHRISTIAN SCHOOL",
        None,
        "MI",
        LEAD_MI_CO,
        "Ostermoor",
        OSTERMOOR,
    ),
    _district("SYN-NY-PALC", "Pallisby Central SD", "NY", LEAD_NY_CO, "Pallisby", PALLISBY),
    _school(
        "SYN-NY-EVE",
        "EAST VILLAGE ELEMENTARY",
        "SYN-NY-PALC",
        "NY",
        LEAD_NY_CO,
        "Pallisby",
        PALLISBY,
    ),
    _school(
        "SYN-NY-PALM",
        "PALLISBY MIDDLE SCHOOL",
        "SYN-NY-PALC",
        "NY",
        LEAD_NY_CO,
        "Pallisby",
        PALLISBY,
    ),
    _school(
        "SYN-IL-GVA", "GLOBAL VILLAGE ACADEMY", None, "IL", LEAD_IL_CO, "Joliby", (41.5, -88.1)
    ),
    _school(
        "SYN-IL-MVA", "MONTESSORI VILLAGE ACADEMY", None, "IL", LEAD_IL_CO, "Joliby", (41.5, -88.1)
    ),
    _district(
        "SYN-NJ-BRNC", "Brindleby City School District", "NJ", LEAD_NJ_B_CO, "Brindleby", BRINDLEBY
    ),
    _school(
        "SYN-NJ-BRNH",
        "Brindleby City High School",
        "SYN-NJ-BRNC",
        "NJ",
        LEAD_NJ_B_CO,
        "Brindleby",
        BRINDLEBY,
    ),
    _school(
        "SYN-NJ-BRNE",
        "Robert Waite Elementary School",
        "SYN-NJ-BRNC",
        "NJ",
        LEAD_NJ_B_CO,
        "Brindleby",
        BRINDLEBY,
    ),
)


# Listings of nothing but kind words ("Christian Academy", "Day Care", "Learning
# Center") beside schools whose names hold those words in another order or among
# others; Quaker schools beside a district named "Friend"; a child care chain's
# centre beside public schools of its brand's name; districts a list numbers in
# words ("Spartby District Seven").
KIND_SC_CO, KIND_IL_CO, KIND_CT_CO, KIND_KS_CO, KIND_NE_CO = (
    "88053",
    "88054",
    "88055",
    "88056",
    "88057",
)
KIND_CO_CO, KIND_NJ_CO, SPARTBY_CO, ANDERSBY_CO = "88058", "88059", "88060", "88061"
KIND_RECORDS: tuple[DirectoryRecord, ...] = (
    _school(
        "SYN-SC-ACS", "THE ACADEMY CHRISTIAN SCHOOL", None, "SC", KIND_SC_CO, "Colby", (34.0, -81.0)
    ),
    _school(
        "SYN-SC-CFL", "CENTER FOR LEARNING INC", None, "SC", KIND_SC_CO, "Colby", (34.0, -81.0)
    ),
    _school("SYN-IL-CDS", "CARE DAY SCHOOL", None, "IL", KIND_IL_CO, "Peorby", (40.7, -89.6)),
    _district("SYN-CT-HRT", "Hartby School District", "CT", KIND_CT_CO, "Hartby", (41.8, -72.7)),
    _school(
        "SYN-CT-HSC",
        "High School In The Community",
        "SYN-CT-HRT",
        "CT",
        KIND_CT_CO,
        "Hartby",
        (41.8, -72.7),
    ),
    _school(
        "SYN-KS-TLC",
        "The Learning Center",
        "SYN-KS-PLN",
        "KS",
        KIND_KS_CO,
        "Plainby",
        (38.9, -97.6),
    ),
    _district("SYN-KS-PLN", "Plainby", "KS", KIND_KS_CO, "Plainby", (38.9, -97.6)),
    _district("SYN-NE-FRD", "FRIEND PUBLIC SCHOOLS", "NE", KIND_NE_CO, "Friend", (40.6, -97.3)),
    _school(
        "SYN-NE-FRDS",
        "FRIEND SECONDARY SCHOOL",
        "SYN-NE-FRD",
        "NE",
        KIND_NE_CO,
        "Friend",
        (40.6, -97.3),
    ),
    _school(
        "SYN-NE-FRDE",
        "FRIEND ELEMENTARY SCHOOL",
        "SYN-NE-FRD",
        "NE",
        KIND_NE_CO,
        "Friend",
        (40.6, -97.3),
    ),
    _school("SYN-NE-OFS", "OMBY FRIENDS SCHOOL", None, "NE", KIND_NE_CO, "Friend", (40.62, -97.3)),
    _district(
        "SYN-CO-LTB", "Littleby School District", "CO", KIND_CO_CO, "Littleby", (39.6, -105.0)
    ),
    _school(
        "SYN-CO-GDM",
        "Goddard Middle School",
        "SYN-CO-LTB",
        "CO",
        KIND_CO_CO,
        "Littleby",
        (39.6, -105.0),
    ),
    _school(
        "SYN-CO-LTH",
        "Littleby High School",
        "SYN-CO-LTB",
        "CO",
        KIND_CO_CO,
        "Littleby",
        (39.6, -105.0),
    ),
    _school("SYN-NJ-GDS", "THE GODDARD SCHOOL", None, "NJ", KIND_NJ_CO, "Brickby", (40.1, -74.1)),
    _district("SYN-SC-SP7", "Spartby 07", "SC", SPARTBY_CO, "Spartby", (34.9, -81.9)),
    _district("SYN-SC-SP3", "Spartby 03", "SC", SPARTBY_CO, "Cowby", (35.0, -81.8)),
    _district("SYN-SC-AN5", "Andersby 05", "SC", ANDERSBY_CO, "Andersby", (34.5, -82.6)),
    _district(
        "SYN-SC-A5C", "Andersby Five Charter School", "SC", ANDERSBY_CO, "Andersby", (34.5, -82.6)
    ),
)

# Schools of one name in one market: a Boston-like list for Massachusetts and New
# Hampshire, whose counties hold two "ST JOHN SCHOOL" 17 km apart (one 1 km from
# the market's point), and a Chicago-like list whose counties hold three districts'
# "WALSH ELEM SCHOOL". The point says nothing of which one a list means. Beside
# them, namesakes the point may tell apart: one just past the counties, one beyond
# a market's reach of the point.
HARBOURNE = (42.52, -71.62)
"""The Boston-like market's point."""
HARBOURNE_CO, WELLMOOR_CO, PEABURY_CO, CONCORBY_CO = "89101", "89102", "89103", "89105"
HARBOURNE_COUNTIES = (HARBOURNE_CO, WELLMOOR_CO, PEABURY_CO, CONCORBY_CO)
"""The market's counties: three in Massachusetts and one in New Hampshire."""
GRAFTBY_CO, PITTSMOOR_CO = "89104", "89106"
"""Massachusetts counties outside the market's: just past them, and far beyond."""
PITTSMOOR = (42.45, -73.25)
LAKEPORT = (41.70, -88.90)
"""The Chicago-like market's point."""
LAKEPORT_CO, ORLAND_GROVE_CO, DOWNSMERE_CO = "89201", "89202", "89203"
LAKEPORT_COUNTIES = (LAKEPORT_CO, ORLAND_GROVE_CO, DOWNSMERE_CO)
POPE_CO, PAUL_VI_CO, LUTHERAN_JOHN_CO, TWO_JOHNS_CO = "89401", "89402", "89403", "89404"
"""Ohio counties of saints' schools: a pope's (``"ST JOHN XXIII"``, ``"PAUL VI"``), a
Lutheran ``"ST JOHN"``, and the Baptist's and the Evangelist's side by side."""

SAME_NAME_RECORDS: tuple[DirectoryRecord, ...] = (
    _school(
        "SYN-MA-SJHA", "ST JOHN SCHOOL", None, "MA", HARBOURNE_CO, "Harbourne", (42.525, -71.615)
    ),
    _school("SYN-MA-SJWM", "ST JOHN SCHOOL", None, "MA", WELLMOOR_CO, "Wellmoor", (42.41, -71.76)),
    _school(
        "SYN-MA-SJBP",
        "ST JOHN THE BAPTIST SCHOOL",
        None,
        "MA",
        PEABURY_CO,
        "Peabury",
        (42.67, -71.42),
    ),
    _school(
        "SYN-MA-SHRS",
        "SACRED HEART ELEMENTARY",
        None,
        "MA",
        HARBOURNE_CO,
        "Roslinby",
        (42.44, -71.58),
    ),
    _school(
        "SYN-MA-SHBR", "SACRED HEARTS SCHOOL", None, "MA", PEABURY_CO, "Bradmoor", (42.87, -71.40)
    ),
    _school(
        "SYN-MA-SBWM", "ST BRENDAN SCHOOL", None, "MA", WELLMOOR_CO, "Wellmoor", (42.47, -71.68)
    ),
    _school("SYN-MA-SBGR", "ST BRENDAN SCHOOL", None, "MA", GRAFTBY_CO, "Graftby", (42.30, -72.40)),
    _school(
        "SYN-MA-SCHA", "ST CECILIA SCHOOL", None, "MA", HARBOURNE_CO, "Harbourne", (42.54, -71.60)
    ),
    _school("SYN-MA-SCPT", "ST CECILIA SCHOOL", None, "MA", PITTSMOOR_CO, "Pittsmoor", PITTSMOOR),
    _district(
        "SYN-NH-CONC", "Concorby School District", "NH", CONCORBY_CO, "Concorby", (42.95, -71.45)
    ),
    _school(
        "SYN-NH-CONCH",
        "Concorby High School",
        "SYN-NH-CONC",
        "NH",
        CONCORBY_CO,
        "Concorby",
        (42.95, -71.45),
    ),
    _district("SYN-IL-LKP", "LAKEPORT SD 299", "IL", LAKEPORT_CO, "Lakeport", LAKEPORT),
    _school(
        "SYN-IL-LKWA",
        "WALSH ELEM SCHOOL",
        "SYN-IL-LKP",
        "IL",
        LAKEPORT_CO,
        "Lakeport",
        (41.72, -88.88),
    ),
    _school(
        "SYN-IL-LKLB",
        "LIBERTY ELEMENTARY SCHOOL",
        "SYN-IL-LKP",
        "IL",
        LAKEPORT_CO,
        "Lakeport",
        (41.67, -88.88),
    ),
    _school(
        "SYN-IL-LKHA", "HARMON ELEM SCHOOL", "SYN-IL-LKP", "IL", LAKEPORT_CO, "Lakeport", LAKEPORT
    ),
    _district(
        "SYN-IL-ORG", "Orland Grove SD 135", "IL", ORLAND_GROVE_CO, "Orland Grove", (41.55, -89.10)
    ),
    _school(
        "SYN-IL-ORWA",
        "Walsh Elem School",
        "SYN-IL-ORG",
        "IL",
        ORLAND_GROVE_CO,
        "Orland Grove",
        (41.55, -89.10),
    ),
    _school(
        "SYN-IL-ORLB",
        "Liberty Elementary School",
        "SYN-IL-ORG",
        "IL",
        ORLAND_GROVE_CO,
        "Orland Grove",
        (41.56, -89.08),
    ),
    _school(
        "SYN-IL-ORJH",
        "Orland Grove Jr High School",
        "SYN-IL-ORG",
        "IL",
        ORLAND_GROVE_CO,
        "Orland Grove",
        (41.55, -89.10),
    ),
    _district(
        "SYN-IL-DWN", "Downsmere Grade SD 58", "IL", DOWNSMERE_CO, "Downsmere", (41.95, -88.60)
    ),
    _school(
        "SYN-IL-DWWA",
        "WALSH ELEMENTARY SCHOOL",
        "SYN-IL-DWN",
        "IL",
        DOWNSMERE_CO,
        "Downsmere",
        (41.95, -88.60),
    ),
    _school(
        "SYN-OH-SJ23",
        "ST JOHN XXIII CATHOLIC SCHOOL",
        None,
        "OH",
        POPE_CO,
        "Middlemoor",
        (39.50, -84.40),
    ),
    _school(
        "SYN-OH-PVI",
        "PAUL VI CATHOLIC HIGH SCHOOL",
        None,
        "OH",
        PAUL_VI_CO,
        "Fairby",
        (39.80, -84.00),
    ),
    _school(
        "SYN-OH-SJLU",
        "ST JOHN LUTHERAN SCHOOL",
        None,
        "OH",
        LUTHERAN_JOHN_CO,
        "Marby",
        (40.60, -83.10),
    ),
    _school(
        "SYN-OH-SJBA",
        "ST JOHN THE BAPTIST SCHOOL",
        None,
        "OH",
        TWO_JOHNS_CO,
        "Canby",
        (40.80, -81.40),
    ),
    _school(
        "SYN-OH-SJEV",
        "ST JOHN THE EVANGELIST SCHOOL",
        None,
        "OH",
        TWO_JOHNS_CO,
        "Canby",
        (40.81, -81.38),
    ),
    _school(
        "SYN-IL-DWMS",
        "Downsmere Middle School",
        "SYN-IL-DWN",
        "IL",
        DOWNSMERE_CO,
        "Downsmere",
        (41.95, -88.60),
    ),
)


# Schools whose names leave out the level their grades make them, in the Boston-like
# and Chicago-like markets' counties, beside namesakes whose names say it. NCES
# names Massachusetts's K-5 schools "Lincoln" and parish schools "ST JOSEPH
# SCHOOL"; a list names them "Lincoln Elementary" and "St. Joseph Elementary".
LEVEL_RECORDS: tuple[DirectoryRecord, ...] = (
    _school(
        "SYN-MA-SJMD",
        "ST JOSEPH ELEMENTARY SCHOOL",
        None,
        "MA",
        HARBOURNE_CO,
        "Medby",
        (42.42, -71.11),
        grades="PK-8",
    ),
    _school(
        "SYN-MA-SJND",
        "ST JOSEPH SCHOOL",
        None,
        "MA",
        WELLMOOR_CO,
        "Needby",
        (42.28, -71.24),
        grades="PK-8",
    ),
    _school(
        "SYN-MA-SJWK",
        "ST JOSEPH SCHOOL",
        None,
        "MA",
        PEABURY_CO,
        "Wakeby",
        (42.50, -71.07),
        grades="PK-8",
    ),
    _district("SYN-MA-WINB", "Winby", "MA", WELLMOOR_CO, "Winby", (42.45, -71.14)),
    _school(
        "SYN-MA-WBLN",
        "Lincoln Elementary",
        "SYN-MA-WINB",
        "MA",
        WELLMOOR_CO,
        "Winby",
        (42.45, -71.14),
        grades="K-5",
    ),
    _district("SYN-MA-MELB", "Melby", "MA", WELLMOOR_CO, "Melby", (42.46, -71.07)),
    _school(
        "SYN-MA-MBLN",
        "Lincoln",
        "SYN-MA-MELB",
        "MA",
        WELLMOOR_CO,
        "Melby",
        (42.46, -71.07),
        grades="K-5",
    ),
    _district("SYN-MA-LINB", "Linby", "MA", WELLMOOR_CO, "Linby", (42.42, -71.30)),
    _school(
        "SYN-MA-LBLN",
        "Lincoln School",
        "SYN-MA-LINB",
        "MA",
        WELLMOOR_CO,
        "Linby",
        (42.42, -71.30),
        grades="PK-8",
    ),
    _district("SYN-MA-SKOB", "Skoby", "MA", PEABURY_CO, "Skoby", (42.60, -71.30)),
    _school(
        "SYN-MA-SKDV",
        "Devonby Elem School",
        "SYN-MA-SKOB",
        "MA",
        PEABURY_CO,
        "Skoby",
        (42.60, -71.30),
        grades="K-5",
    ),
    _school(
        "SYN-MA-SKHL",
        "Hallby Elementary School",
        "SYN-MA-SKOB",
        "MA",
        PEABURY_CO,
        "Skoby",
        (42.61, -71.31),
        grades="K-5",
    ),
    _district("SYN-MA-PLNB", "Plainby", "MA", PEABURY_CO, "Plainby", (42.70, -71.20)),
    _school(
        "SYN-MA-PLDV",
        "Devonby School",
        "SYN-MA-PLNB",
        "MA",
        PEABURY_CO,
        "Plainby",
        (42.70, -71.20),
        grades="6-8",
    ),
    _school(
        "SYN-MA-PLWS",
        "Winstowe",
        "SYN-MA-PLNB",
        "MA",
        PEABURY_CO,
        "Plainby",
        (42.71, -71.21),
        grades="K-5",
    ),
    _school(
        "SYN-MA-HLBK",
        "HALLBY SCHOOL",
        None,
        "MA",
        PEABURY_CO,
        "Plainby",
        (42.69, -71.22),
        grades="K-12",
    ),
    _school(
        "SYN-IL-LKDV",
        "Devonmoor Elem School",
        "SYN-IL-LKP",
        "IL",
        LAKEPORT_CO,
        "Lakeport",
        (41.71, -88.91),
        grades="K-5",
    ),
    _school(
        "SYN-IL-ORDV",
        "Devonmoor School",
        "SYN-IL-ORG",
        "IL",
        ORLAND_GROVE_CO,
        "Orland Grove",
        (41.54, -89.11),
        grades="K-5",
    ),
    _school(
        "SYN-IL-SJLE",
        "ST JOHN'S LUTHERAN SCHOOL",
        None,
        "IL",
        DOWNSMERE_CO,
        "Elby",
        (42.03, -88.28),
        grades="PK-1",
    ),
    _school(
        "SYN-IL-SJLK",
        "ST JOHN LUTHERAN SCHOOL",
        None,
        "IL",
        LAKEPORT_CO,
        "Lakeport",
        (41.69, -88.87),
        grades="PK-8",
    ),
    _school(
        "SYN-IL-SJLB",
        "ST JOHN LUTHERAN SCHOOL",
        None,
        "IL",
        ORLAND_GROVE_CO,
        "Libby",
        (41.60, -89.00),
        grades="PK-8",
    ),
    _school(
        "SYN-IL-CHLU",
        "CHRIST LUTHERAN SCHOOL",
        None,
        "IL",
        LAKEPORT_CO,
        "Lakeport",
        (41.72, -88.86),
        grades="PK-KG",
    ),
    _school(
        "SYN-IL-NBJH",
        "Northby Junior High School",
        "SYN-IL-DWN",
        "IL",
        DOWNSMERE_CO,
        "Northby",
        (42.10, -88.50),
        grades="7-9",
    ),
    _school(
        "SYN-IL-MDNB",
        "Northby School",
        "SYN-IL-ORG",
        "IL",
        ORLAND_GROVE_CO,
        "Mendby",
        (41.50, -89.20),
        grades="5-8",
    ),
)


# Schools named for a person, of one surname and level in one county: one whose
# name gives initials, one a forename (and its initial). A listing of the surname
# alone names both, and so neither: the forenames it leaves out weigh the same
# whether the name spells them or gives only their initials. A school whose name
# is the listing's, word for word, comes before them. Real-shaped, after
# Middlesex County's "J F Kennedy Middle School" (Natick) beside "John F Kennedy
# Middle" (Waltham) and "John F Kennedy Middle School" (Woburn), Hidalgo County's
# "L B JOHNSON EL" beside "LYNDON B JOHNSON EL" and "B L GARZA MIDDLE" beside
# "BEATRIZ G GARZA MIDDLE", Harris County's "WHITE E EL", "ED H WHITE EL" and "MARK
# WHITE EL", Los Angeles County's "R. D. White Elementary" beside "Charles White
# Elementary", and Calcasieu Parish's "J. I. Watson" beside "Pearl Watson"; but
# every name here is made up.
TAMBY = (41.35, -70.25)
TAMBY_CO, NATWICK_CO = "89501", "89502"
TAMBY_COUNTIES = (TAMBY_CO, NATWICK_CO)
HIDBY = (29.00, -103.80)
HIDBY_CO = "89601"
HARBY_CO = "89602"
LOSBY = (35.30, -115.50)
LOSBY_CO = "89701"
CALBY = (32.50, -93.50)
CALBY_CO = "89801"
KENTBY = (38.90, -75.50)
KENTBY_CO = "89901"
BLACKBY = (45.00, -114.00)
BLACKBY_CO = "89951"
PERSON = "a school named for a person, by its surname or its person's name"
PERSON_NEGATIVE = "hard negative: a surname two schools' people share"

PERSON_RECORDS: tuple[DirectoryRecord, ...] = (
    _district("SYN-MA-NATB", "Natby", "MA", TAMBY_CO, "Natby", TAMBY),
    _district("SYN-MA-WALB", "Walby", "MA", NATWICK_CO, "Walby", (41.40, -70.30)),
    _district("SYN-MA-WOBB", "Wobby", "MA", NATWICK_CO, "Wobby", (41.45, -70.35)),
    _school(
        "SYN-MA-JFKN", "J F Kennaby Middle School", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY
    ),
    _school(
        "SYN-MA-JFKW",
        "John F Kennaby Middle",
        "SYN-MA-WALB",
        "MA",
        NATWICK_CO,
        "Walby",
        (41.40, -70.30),
    ),
    _school(
        "SYN-MA-JFKB",
        "John F Kennaby Middle School",
        "SYN-MA-WOBB",
        "MA",
        NATWICK_CO,
        "Wobby",
        (41.45, -70.35),
    ),
    # A surname alone beside a person's name: both, and so neither.
    _school("SYN-MA-REED", "Reedby Elem School", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY),
    _school(
        "SYN-MA-CREED",
        "Charles Reedby Elementary Sch",
        "SYN-MA-WALB",
        "MA",
        NATWICK_CO,
        "Walby",
        (41.40, -70.30),
    ),
    _school(
        "SYN-MA-FRYE", "Fryby Elementary School", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY
    ),
    _school(
        "SYN-MA-HFRY",
        "Harry E Fryby School",
        "SYN-MA-WOBB",
        "MA",
        NATWICK_CO,
        "Wobby",
        (41.45, -70.35),
        grades="K-5",
    ),
    # Initials a record writes as one word, and letters that differ.
    _school("SYN-MA-WWWK", "W W Walkby Elem School", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY),
    _school(
        "SYN-MA-WALK",
        "Walkby School",
        "SYN-MA-WALB",
        "MA",
        NATWICK_CO,
        "Walby",
        (41.40, -70.30),
        grades="K-5",
    ),
    _school("SYN-MA-JBNL", "J B Nelby Elem School", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY),
    _school(
        "SYN-MA-VHNL",
        "V H Nelby Elem School",
        "SYN-MA-WALB",
        "MA",
        NATWICK_CO,
        "Walby",
        (41.40, -70.30),
    ),
    _school(
        "SYN-MA-FCBD",
        "FC BOYDBY SR CHRISTIAN SCHOOL",
        None,
        "MA",
        TAMBY_CO,
        "Natby",
        TAMBY,
        grades="K-12",
    ),
    _district("SYN-TX-EDBY", "EDBY ISD", "TX", HIDBY_CO, "Edby", HIDBY),
    _district("SYN-TX-ELSB", "ELSBY ISD", "TX", HIDBY_CO, "Elsby", (29.05, -103.85)),
    _school("SYN-TX-LBJE", "L B JOHNBY EL", "SYN-TX-EDBY", "TX", HIDBY_CO, "EDBY", HIDBY),
    _school(
        "SYN-TX-LYBJ",
        "LYNDON B JOHNBY EL",
        "SYN-TX-ELSB",
        "TX",
        HIDBY_CO,
        "ELSBY",
        (29.05, -103.85),
    ),
    _school("SYN-TX-BLGZ", "B L GARZBY MIDDLE", "SYN-TX-EDBY", "TX", HIDBY_CO, "EDBY", HIDBY),
    _school(
        "SYN-TX-BGGZ",
        "BEATRIZ G GARZBY MIDDLE",
        "SYN-TX-ELSB",
        "TX",
        HIDBY_CO,
        "ELSBY",
        (29.05, -103.85),
    ),
    _district("SYN-TX-HOUB", "HOUSBY ISD", "TX", HARBY_CO, "Housby", (29.60, -104.30)),
    _school(
        "SYN-TX-WHTE", "WHITBY E EL", "SYN-TX-HOUB", "TX", HARBY_CO, "HOUSBY", (29.60, -104.30)
    ),
    _school(
        "SYN-TX-EDHW", "ED H WHITBY EL", "SYN-TX-HOUB", "TX", HARBY_CO, "HOUSBY", (29.62, -104.32)
    ),
    _school(
        "SYN-TX-MRKW", "MARK WHITBY EL", "SYN-TX-HOUB", "TX", HARBY_CO, "HOUSBY", (29.64, -104.34)
    ),
    _district("SYN-CA-GLNB", "Glenby Unified", "CA", LOSBY_CO, "Glenby", LOSBY),
    _school(
        "SYN-CA-RDWH", "R. D. Whiteby Elementary", "SYN-CA-GLNB", "CA", LOSBY_CO, "Glenby", LOSBY
    ),
    _school(
        "SYN-CA-CHWH",
        "Charles Whiteby Elementary",
        "SYN-CA-GLNB",
        "CA",
        LOSBY_CO,
        "Losby",
        (35.35, -115.55),
    ),
    _school(
        "SYN-CA-WHOK",
        "Whiteby Oak Elementary",
        "SYN-CA-GLNB",
        "CA",
        LOSBY_CO,
        "Westby",
        (35.40, -115.60),
    ),
    # California writes a person's forenames in brackets after the surname.
    _school(
        "SYN-CA-KNJF",
        "Kenby (John F.) Elementary",
        "SYN-CA-GLNB",
        "CA",
        LOSBY_CO,
        "Artby",
        (35.25, -115.45),
    ),
    _school(
        "SYN-CA-RFKB",
        "Robert F. Kenby Elementary",
        "SYN-CA-GLNB",
        "CA",
        LOSBY_CO,
        "Compby",
        (35.20, -115.40),
    ),
    _school(
        "SYN-CA-BRBL",
        "Burbby (Luther) Elementary",
        "SYN-CA-GLNB",
        "CA",
        LOSBY_CO,
        "Artby",
        (35.25, -115.45),
    ),
    _district("SYN-LA-CALB", "Calby Parish", "LA", CALBY_CO, "Lake Calby", CALBY),
    _school(
        "SYN-LA-JIWT",
        "J. I. Watby Elementary School",
        "SYN-LA-CALB",
        "LA",
        CALBY_CO,
        "Iowby",
        CALBY,
    ),
    _school(
        "SYN-LA-PRWT",
        "Pearl Watby Elementary School",
        "SYN-LA-CALB",
        "LA",
        CALBY_CO,
        "Lake Calby",
        (32.55, -93.55),
    ),
    _school("SYN-LA-CVKG", "C. V. Koogby Middle", "SYN-LA-CALB", "LA", CALBY_CO, "Iowby", CALBY),
    _district("SYN-DE-KENB", "Kentby School District", "DE", KENTBY_CO, "Harrby", KENTBY),
    _school(
        "SYN-DE-WTCH",
        "Chipby (W.T.) Middle School",
        "SYN-DE-KENB",
        "DE",
        KENTBY_CO,
        "Harrby",
        KENTBY,
    ),
    _school(
        "SYN-DE-LLRD",
        "Redby (Louis L.) Middle School",
        "SYN-DE-KENB",
        "DE",
        KENTBY_CO,
        "Middby",
        (38.95, -75.55),
    ),
    # A surname and "School" alone may name a school no directory holds (a list's
    # private "Pingree School"), never "Lawrence W Pingree", a K-5 school.
    _school(
        "SYN-MA-PNGB",
        "Lawrence W Pingby",
        "SYN-MA-WALB",
        "MA",
        NATWICK_CO,
        "Weyby",
        (41.40, -70.30),
        grades="K-5",
    ),
    # A title alone is no forename: "Chief Charby School" is no "Charby Elementary".
    _district("SYN-MT-CHRB", "Charby Elem", "MT", BLACKBY_CO, "Charby", BLACKBY),
    _school("SYN-MT-CHRE", "Charby Elementary", "SYN-MT-CHRB", "MT", BLACKBY_CO, "Charby", BLACKBY),
    _school(
        "SYN-MT-CHCH",
        "Chief Charby School",
        "SYN-MT-CHRB",
        "MT",
        BLACKBY_CO,
        "Missby",
        (45.05, -114.05),
        grades="K-5",
    ),
)

# Schools named for a word written with a plural's "s" or without it: two names
# (Harris County's "PARKS EL" beside "DEER PARK EL"; "Brooks School" in Middlesex;
# "THE OAKS SCHOOL" in Los Angeles County; Kent County's "Lakes Elementary School").
# A saint's possessive, an apostrophe's written as a space, a devotion's name and a
# word that says the school's kind are no plural.
PLURAL = "a word with a plural's s or without"
PLURAL_NEGATIVE = "hard negative: a word written with a plural's s the other name lacks"
PLURAL_RECORDS: tuple[DirectoryRecord, ...] = (
    _school("SYN-TX-PRKS", "PARKS EL", "SYN-TX-HOUB", "TX", HARBY_CO, "PASBY", (29.66, -104.36)),
    _school(
        "SYN-TX-DRPK", "DEER PARK EL", "SYN-TX-HOUB", "TX", HARBY_CO, "HOUSBY", (29.68, -104.38)
    ),
    _school("SYN-TX-GRVS", "GROVES EL", "SYN-TX-HOUB", "TX", HARBY_CO, "HUMBY", (29.70, -104.40)),
    _school("SYN-MA-BRKS", "Brooks School", None, "MA", TAMBY_CO, "Medby", TAMBY, grades="K-5"),
    _school(
        "SYN-MA-WNBK", "Winn Brook", "SYN-MA-NATB", "MA", TAMBY_CO, "Natby", TAMBY, grades="K-5"
    ),
    _school(
        "SYN-CA-OAKS",
        "THE OAKS SCHOOL",
        None,
        "CA",
        LOSBY_CO,
        "Losby",
        (35.35, -115.55),
        grades="K-5",
    ),
    _school(
        "SYN-DE-LAKS",
        "Lakes Elementary School",
        "SYN-DE-KENB",
        "DE",
        KENTBY_CO,
        "Rockby",
        (38.85, -75.45),
    ),
    _school(
        "SYN-DE-WLSH", "WELSBY HILLS SCHOOL", None, "DE", KENTBY_CO, "Granby", KENTBY, grades="K-5"
    ),
    _school(
        "SYN-DE-TRRY",
        "TERRY S MONTESSORI SCHOOL",
        None,
        "DE",
        KENTBY_CO,
        "Harrby",
        KENTBY,
        grades="PK-KG",
    ),
    _school(
        "SYN-DE-CLVA",
        "Clevby Arts and Social Sciences Academy",
        "SYN-DE-KENB",
        "DE",
        KENTBY_CO,
        "Harrby",
        KENTBY,
        grades="K-5",
    ),
)


RECORDS: tuple[DirectoryRecord, ...] = (
    # Pennsylvania: "Lancaster" and "Lancaster County" side by side.
    _district("SYN-PA-LANSD", "Lancaster SD", "PA", PA_A, "Lancaster", LANCASTER),
    _school("SYN-PA-LANHS", "Lancaster HS", "SYN-PA-LANSD", "PA", PA_A, "Lancaster", LANCASTER),
    _school("SYN-PA-HAMEL", "Hamilton El Sch", "SYN-PA-LANSD", "PA", PA_A, "Lancaster", LANCASTER),
    _school("SYN-PA-LINMS", "Lincoln MS", "SYN-PA-LANSD", "PA", PA_A, "Lancaster", LANCASTER),
    _school(
        "SYN-PA-MAINST", "Main Street El Sch", "SYN-PA-LANSD", "PA", PA_A, "Lancaster", LANCASTER
    ),
    _district("SYN-PA-LANCO", "Lancaster County SD", "PA", PA_B, "Eastbrook", EASTBROOK),
    _school(
        "SYN-PA-LANCC",
        "Lancaster County Career Center",
        "SYN-PA-LANCO",
        "PA",
        PA_B,
        "Eastbrook",
        EASTBROOK,
    ),
    _school("SYN-PA-PEQHS", "Pequea Valley HS", "SYN-PA-LANCO", "PA", PA_B, "Eastbrook", EASTBROOK),
    _district("SYN-PA-MILSD", "Millbrook Area SD", "PA", PA_C, "Millbrook", MILLBROOK),
    # Minnesota: a district that calls itself "Elkmere Area Schools", which NCES
    # names without "Area"; Pennsylvania: two districts that differ by "Area".
    _district(
        "SYN-MN-ELKM", "Elkmere Public School District", "MN", "88958", "Elkmere", (45.3, -93.6)
    ),
    _district("SYN-PA-BRKA", "Brookmere Area SD", "PA", "88959", "Brookmere", (40.9, -77.2)),
    _district("SYN-PA-BRKS", "Brookmere SD", "PA", "88959", "Brookmere", (40.9, -77.2)),
    _school(
        "SYN-PA-MILHS", "Millbrook Area HS", "SYN-PA-MILSD", "PA", PA_C, "Millbrook", MILLBROOK
    ),
    _school("SYN-PA-OAKRI", "Oakridge El Sch", "SYN-PA-MILSD", "PA", PA_C, "Millbrook", MILLBROOK),
    _district("SYN-PA-MTPSD", "Mount Pleasant Area SD", "PA", PA_C, "Ramsay", MILLBROOK),
    _school("SYN-PA-RAMEL", "Ramsay El Sch", "SYN-PA-MTPSD", "PA", PA_C, "Ramsay", MILLBROOK),
    _district("SYN-PA-ARTSD", "Arts and Sciences Academy CS", "PA", PA_A, "Lancaster", LANCASTER),
    _school(
        "SYN-PA-ARTS",
        "Arts and Sciences Academy CS",
        "SYN-PA-ARTSD",
        "PA",
        PA_A,
        "Lancaster",
        LANCASTER,
    ),
    _school("SYN-PA-STMA", "St. Mary's School", None, "PA", PA_A, "Lancaster", LANCASTER),
    _school("SYN-PA-STMB", "ST MARY SCHOOL", None, "PA", PA_B, "Eastbrook", EASTBROOK),
    _school(
        "SYN-PA-STJOE", "St. Joseph Elementary School", None, "PA", PA_A, "Lancaster", LANCASTER
    ),
    _school("SYN-PA-STJOH", "ST JOSEPH HIGH SCHOOL", None, "PA", PA_B, "Eastbrook", EASTBROOK),
    _school("SYN-PA-STPAU", "St. Paul Catholic School", None, "PA", PA_C, "Millbrook", MILLBROOK),
    # South Carolina: only "Lancaster County".
    _district(
        "SYN-SC-LANCO",
        "Lancaster County School District",
        "SC",
        "80201",
        "Lancaster",
        (34.7, -80.8),
    ),
    _school(
        "SYN-SC-LANHI", "Lancaster High", "SYN-SC-LANCO", "SC", "80201", "Lancaster", (34.7, -80.8)
    ),
    _school(
        "SYN-SC-STMA", "St. Mary's Catholic School", None, "SC", "80201", "Lancaster", (34.7, -80.8)
    ),
    # New York.
    _district(
        "SYN-NY-WENUF",
        "WENDOVER UNION FREE SCHOOL DISTRICT",
        "NY",
        "80301",
        "Wendover",
        (41.0, -73.8),
    ),
    _school(
        "SYN-NY-WENHS",
        "WENDOVER SENIOR HIGH SCHOOL",
        "SYN-NY-WENUF",
        "NY",
        "80301",
        "Wendover",
        (41.0, -73.8),
    ),
    _district(
        "SYN-NY-RIVCS",
        "RIVERHOLLOW CENTRAL SCHOOL DISTRICT",
        "NY",
        "80302",
        "Riverhollow",
        (42.9, -75.0),
    ),
    _district(
        "SYN-NY-GENCI", "Genesee City School District", "NY", "80303", "Genesee", (43.1, -77.6)
    ),
    _school("SYN-NY-STMA", "ST. MARY'S SCHOOL", None, "NY", "80302", "Riverhollow", (42.9, -75.0)),
    # Missouri: numbered districts.
    _district("SYN-MO-WEX", "WEXFORD R-IV", "MO", "80401", "Wexford", (38.8, -90.8)),
    _school(
        "SYN-MO-WEXMS", "WEXFORD MIDDLE", "SYN-MO-WEX", "MO", "80401", "Wexford", (38.8, -90.8)
    ),
    _school(
        "SYN-MO-WEXSM",
        "WEXFORD SOUTH MIDDLE",
        "SYN-MO-WEX",
        "MO",
        "80401",
        "Wexford",
        (38.8, -90.8),
    ),
    _school(
        "SYN-MO-HERPR", "HERITAGE PRIMARY", "SYN-MO-WEX", "MO", "80401", "Wexford", (38.8, -90.8)
    ),
    _district("SYN-MO-OAK2", "OAKHURST R-II", "MO", "80402", "Oakhurst", (37.5, -92.0)),
    _district("SYN-MO-OAK3", "OAKHURST R-III", "MO", "80403", "Oakhurst", (37.6, -92.1)),
    _district("SYN-MO-STCH", "ST. CHARLTON R-VI", "MO", "80401", "Saint Charlton", (38.8, -90.5)),
    _school(
        "SYN-MO-STCHS",
        "SAINT CHARLTON HIGH SCHOOL",
        "SYN-MO-STCH",
        "MO",
        "80401",
        "Saint Charlton",
        (38.8, -90.5),
    ),
    _district("SYN-MO-MTV", "MOUNT VERNAL R-V", "MO", "80403", "Mount Vernal", (37.1, -93.8)),
    # Texas: ISD, CISD and the NCES "EL", "H S" and "J H" spellings.
    _district("SYN-TX-BRAZ", "BRAZOS BEND ISD", "TX", "80501", "Brazos Bend", (29.5, -95.7)),
    _school(
        "SYN-TX-BRAHS",
        "BRAZOS BEND H S",
        "SYN-TX-BRAZ",
        "TX",
        "80501",
        "Brazos Bend",
        (29.5, -95.7),
    ),
    _school("SYN-TX-MYATT", "MYATT EL", "SYN-TX-BRAZ", "TX", "80501", "Brazos Bend", (29.5, -95.7)),
    _school(
        "SYN-TX-RIVJH", "RIVERSIDE J H", "SYN-TX-BRAZ", "TX", "80501", "Brazos Bend", (29.5, -95.7)
    ),
    _district("SYN-TX-ELCAM", "EL CAMPO ISD", "TX", "80502", "El Campo", (29.2, -96.3)),
    _school(
        "SYN-TX-ELCHS", "EL CAMPO H S", "SYN-TX-ELCAM", "TX", "80502", "El Campo", (29.2, -96.3)
    ),
    _school(
        "SYN-TX-NSIDE", "NORTHSIDE EL", "SYN-TX-ELCAM", "TX", "80502", "El Campo", (29.2, -96.3)
    ),
    _district("SYN-TX-CYPH", "CYPRESS HOLLOW CISD", "TX", "80503", "Cypress Hollow", (30.0, -95.6)),
    # Illinois: numbered districts.
    _district(
        "SYN-IL-CU300",
        "Community Unit School District 300",
        "IL",
        "80601",
        "Carpenter",
        (42.1, -88.3),
    ),
    _district("SYN-IL-PAL15", "Palmer CCSD 15", "IL", "80602", "Palmer", (42.1, -88.0)),
    _district("SYN-IL-PAL16", "Palmer SD 16", "IL", "80602", "Palmer", (42.1, -88.0)),
    _district(
        "SYN-IL-LAKE",
        "Lakeshore Public Schools Dist 299",
        "IL",
        "80603",
        "Lakeshore",
        (41.9, -87.7),
    ),
    # California.
    _district("SYN-CA-LOSR", "Los Robles Unified", "CA", "80701", "Los Robles", (34.0, -118.2)),
    _school(
        "SYN-CA-LRHS",
        "Los Robles High",
        "SYN-CA-LOSR",
        "CA",
        "80701",
        "Los Robles",
        (34.0, -118.2),
    ),
    _school(
        "SYN-CA-ACAD",
        "Academia Señora del Valle",
        "SYN-CA-LOSR",
        "CA",
        "80701",
        "Los Robles",
        (34.0, -118.2),
    ),
    _district("SYN-CA-MESA", "Mesa Verde Union High", "CA", "80702", "Mesa Verde", (32.7, -117.0)),
    _district("SYN-CA-ROBLA", "Robla Elementary", "CA", "80703", "Robla", (38.6, -121.4)),
    _school(
        "SYN-CA-ROBES",
        "Robla Elementary School",
        "SYN-CA-ROBLA",
        "CA",
        "80703",
        "Robla",
        (38.6, -121.4),
    ),
    # Montana: elementary and high school districts named like their schools.
    _district("SYN-MT-HELEL", "Helmsley Elem", "MT", "81901", "Helmsley", (46.9, -113.1)),
    _school(
        "SYN-MT-HELSC", "Helmsley School", "SYN-MT-HELEL", "MT", "81901", "Helmsley", (46.9, -113.1)
    ),
    _district("SYN-MT-TARHS", "Tarkio County H S", "MT", "81901", "Helmsley", (46.8, -113.0)),
    # Alabama: a city district and a county district share a name and a county.
    _district("SYN-AL-BRAMC", "Brambleton City", "AL", "80801", "Brambleton", (34.3, -86.2)),
    _school(
        "SYN-AL-BRAHS",
        "Brambleton High School",
        "SYN-AL-BRAMC",
        "AL",
        "80801",
        "Brambleton",
        (34.3, -86.2),
    ),
    _school(
        "SYN-AL-LINC1",
        "Lincoln Elementary School",
        "SYN-AL-BRAMC",
        "AL",
        "80801",
        "Brambleton",
        (34.3, -86.2),
    ),
    _district("SYN-AL-BRACO", "Brambleton County", "AL", "80801", "Oxbow", (34.4, -86.1)),
    _school(
        "SYN-AL-BCOHS",
        "Brambleton County High School",
        "SYN-AL-BRACO",
        "AL",
        "80801",
        "Oxbow",
        (34.4, -86.1),
    ),
    _school(
        "SYN-AL-LINC2",
        "Lincoln Elementary School",
        "SYN-AL-BRACO",
        "AL",
        "80801",
        "Oxbow",
        (34.4, -86.1),
    ),
    _school(
        "SYN-AL-PLGRV",
        "Pleasant Grove Elementary",
        "SYN-AL-BRACO",
        "AL",
        "80801",
        "Oxbow",
        (34.4, -86.1),
    ),
    # Ohio: a city district and a local district share a name.
    _district(
        "SYN-OH-KETC", "Kettleby City School District", "OH", "80901", "Kettleby", (39.7, -84.2)
    ),
    _district("SYN-OH-KETL", "Kettleby Local", "OH", "80902", "Kettleby", (39.8, -84.3)),
    _district("SYN-OH-WOOD", "Woodbine Local", "OH", "80903", "Woodbine", (40.1, -82.9)),
    # Virginia and Maryland: the same district name in two states.
    _district(
        "SYN-VA-HARW", "Harwick County Public Schools", "VA", "81001", "Harwick", (38.0, -78.5)
    ),
    _district(
        "SYN-MD-HARW", "Harwick County Public Schools", "MD", "81101", "Harwick", (39.3, -76.6)
    ),
    _district("SYN-VA-FAIR", "Fairbourne Co Pblc Schs", "VA", "81002", "Fairbourne", (38.8, -77.3)),
    # Louisiana, New Jersey, Wisconsin, Indiana, Maine, Colorado.
    _district("SYN-LA-TECHE", "Bayou Teche Parish", "LA", "81201", "Teche", (30.0, -91.8)),
    _district(
        "SYN-NJ-HAMT", "Hamilton Township School District", "NJ", "81301", "Hamilton", (40.2, -74.7)
    ),
    _district("SYN-NJ-HAMB", "Hamilton School District", "NJ", "81302", "Hamilton", (40.9, -74.2)),
    _district(
        "SYN-WI-WAUN", "Waunona Community School District", "WI", "81401", "Waunona", (43.2, -89.4)
    ),
    _district(
        "SYN-IN-KESS", "Kessler-Hart School Corporation", "IN", "81501", "Kessler", (41.7, -86.2)
    ),
    _district("SYN-ME-MSAD72", "MSAD 72", "ME", "81601", "Fryer", (44.0, -70.9)),
    _district("SYN-CO-PLAT", "Platte-Canyon 28J", "CO", "81701", "Platte", (39.7, -104.8)),
    # Nebraska: one district's schools that differ only by level.
    _district("SYN-NE-CORN", "Cornhusk Public Schools", "NE", "81801", "Cornhusk", (40.8, -96.7)),
    _school(
        "SYN-NE-LINES",
        "Lincoln Elementary School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-LINMS",
        "Lincoln Middle School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-WASHS",
        "Washington High School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-WASJH",
        "Washington Junior High School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-MLKHS",
        "Martin Luther King Jr High School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-STPLU",
        "St. Paul Lutheran School",
        None,
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-COLPK",
        "College Park Elementary School",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    _school(
        "SYN-NE-HCAND",
        "Hans Christian Andersen Elementary",
        "SYN-NE-CORN",
        "NE",
        "81801",
        "Cornhusk",
        (40.8, -96.7),
    ),
    # Washington: a city's public district beside private schools with the city's name.
    _district(
        "SYN-WA-TIDE", "Tidewater School District No. 1", "WA", "82001", "Tidewater", TIDEWATER
    ),
    _school(
        "SYN-WA-TIDHS",
        "Tidewater High School",
        "SYN-WA-TIDE",
        "WA",
        "82001",
        "Tidewater",
        TIDEWATER,
    ),
    _school(
        "SYN-WA-TIDCS", "TIDEWATER CHRISTIAN SCHOOLS", None, "WA", "82001", "Tidewater", TIDEWATER
    ),
    _school(
        "SYN-WA-TIDLU",
        "Tidewater Lutheran High School",
        None,
        "WA",
        "82001",
        "Tidewater",
        TIDEWATER,
    ),
    _school(
        "SYN-WA-TIDAD",
        "TIDEWATER ADVENTIST CHRISTIAN SCHOOL",
        None,
        "WA",
        "82001",
        "Tidewater",
        TIDEWATER,
    ),
    _school(
        "SYN-WA-TIDMO",
        "Montessori Academy of Tidewater",
        None,
        "WA",
        "82001",
        "Tidewater",
        TIDEWATER,
    ),
    # Massachusetts: a college and a university that share a town's name with a
    # district, a "College High School" and a "University Academy".
    _district("SYN-MA-BRAK", "Brackenmoor", "MA", "82101", "Brackenmoor", BRACKENMOOR),
    _school(
        "SYN-MA-BRLAT",
        "Brackenmoor Latin School",
        "SYN-MA-BRAK",
        "MA",
        "82101",
        "Brackenmoor",
        BRACKENMOOR,
    ),
    _school(
        "SYN-MA-BREC",
        "Brackenmoor Early College",
        "SYN-MA-BRAK",
        "MA",
        "82101",
        "Brackenmoor",
        BRACKENMOOR,
    ),
    _school(
        "SYN-MA-BRCHS",
        "BRACKENMOOR COLLEGE HIGH SCHOOL",
        None,
        "MA",
        "82101",
        "Brackenmoor",
        BRACKENMOOR,
    ),
    _school(
        "SYN-MA-BRUA",
        "BRACKENMOOR UNIVERSITY ACADEMY",
        None,
        "MA",
        "82101",
        "Brackenmoor",
        BRACKENMOOR,
    ),
    # Place names that hold a college or a faith word.
    _district(
        "SYN-OH-UNIVH",
        "University Heights City",
        "OH",
        "80904",
        "University Heights",
        (41.5, -81.5),
    ),
    _district("SYN-TX-COLM", "COLLEGE MESA ISD", "TX", "80504", "College Mesa", (30.6, -96.3)),
    _district("SYN-KY-CHRCO", "Christian County", "KY", "82301", "Hopkinsburg", (36.9, -87.5)),
    _school(
        "SYN-KY-CHRHS",
        "Christian County High School",
        "SYN-KY-CHRCO",
        "KY",
        "82301",
        "Hopkinsburg",
        (36.9, -87.5),
    ),
    _district(
        "SYN-MS-PORTC",
        "Port Christian School District",
        "MS",
        "82201",
        "Port Christian",
        (30.3, -89.2),
    ),
    _school(
        "SYN-MS-PORHS",
        "Port Christian High School",
        "SYN-MS-PORTC",
        "MS",
        "82201",
        "Port Christian",
        (30.3, -89.2),
    ),
    _district(
        "SYN-LA-SJBP", "St. John the Baptist Parish", "LA", "81202", "Reserve", (30.1, -90.6)
    ),
    _school(
        "SYN-LA-SJBS", "ST JOHN THE BAPTIST SCHOOL", None, "LA", "81202", "Reserve", (30.1, -90.6)
    ),
    # Names that differ only in designators. A city's district and a charter
    # district in one town and county: the legal form a listing says tells them
    # apart when only one name says it ("Public"), or when one name's legal form
    # is the listing's and the other's says more; "Marrowgate Schools" says
    # nothing that does. Two townships in two counties, one "Public", and a
    # charter "Public Schools" beside the "ISD" in another county are two
    # places: which one a listing means cannot be read from the designators it
    # happens to use, so these are held back.
    _district(
        "SYN-MI-MARPS",
        "Marrowgate Public Schools Community District",
        "MI",
        "82401",
        "Marrowgate",
        MARROWGATE,
    ),
    _school(
        "SYN-MI-MARHS",
        "Marrowgate Central High School",
        "SYN-MI-MARPS",
        "MI",
        "82401",
        "Marrowgate",
        MARROWGATE,
    ),
    _district(
        "SYN-MI-MARCS", "Marrowgate Community Schools", "MI", "82401", "Marrowgate", MARROWGATE
    ),
    _school(
        "SYN-MI-MARCA",
        "Marrowgate Community Academy",
        "SYN-MI-MARCS",
        "MI",
        "82401",
        "Marrowgate",
        MARROWGATE,
    ),
    _district(
        "SYN-NJ-QUIA",
        "Quillmoor Township School District",
        "NJ",
        "82501",
        "Quillmoor",
        (39.5, -74.7),
    ),
    _district(
        "SYN-NJ-QUIB",
        "Quillmoor Township Public School District",
        "NJ",
        "82502",
        "Quillmoor",
        (40.2, -74.5),
    ),
    _district(
        "SYN-TX-SALTC", "SALTGRASS PUBLIC SCHOOLS", "TX", "80505", "Saltgrass", (29.4, -98.5)
    ),
    _district("SYN-TX-SALT", "SALTGRASS ISD", "TX", "80506", "Saltgrass", (29.8, -95.9)),
    # Colorado: a city's district, named by its number and county, and a
    # program's district of one school with the city's name and the same number.
    _district(
        "SYN-CO-HAR1",
        "School District No. 1 in the county of Harrowby and State of C",
        "CO",
        "82402",
        "Harrowby",
        (39.70, -104.90),
    ),
    _school(
        "SYN-CO-HARHS",
        "Quillan High School",
        "SYN-CO-HAR1",
        "CO",
        "82402",
        "Harrowby",
        (39.70, -104.90),
    ),
    _school(
        "SYN-CO-HARMS",
        "Stroud Middle School",
        "SYN-CO-HAR1",
        "CO",
        "82402",
        "Harrowby",
        (39.70, -104.90),
    ),
    _district("SYN-CO-HARP", "HARROWBY 1", "CO", "82402", "Harrowby", (39.70, -104.90)),
    # A town's elementary and high school districts, two city charter districts
    # of one name but for "City" and "Village", and a charter school beside the
    # town's district: none of them differ only in their legal form.
    _district("SYN-CA-KELE", "Kelburn Union Elementary", "CA", "82403", "Kelburn", (38.1, -122.2)),
    _school(
        "SYN-CA-KELES",
        "Tamarind Elementary School",
        "SYN-CA-KELE",
        "CA",
        "82403",
        "Kelburn",
        (38.1, -122.2),
    ),
    _school(
        "SYN-CA-KELMS",
        "Kelburn Union Middle School",
        "SYN-CA-KELE",
        "CA",
        "82403",
        "Kelburn",
        (38.1, -122.2),
    ),
    _district("SYN-CA-KELH", "Kelburn Union High", "CA", "82403", "Kelburn", (38.1, -122.2)),
    _school(
        "SYN-CA-KELHS",
        "Kelburn Union High School",
        "SYN-CA-KELH",
        "CA",
        "82403",
        "Kelburn",
        (38.1, -122.2),
    ),
    _district("SYN-DC-CAPC", "Capwell City PCS", "DC", "82404", "Pellham", TAMSIN),
    *(
        _school(
            f"SYN-DC-CAPC{part[0]}",
            f"Capwell City PCS - {part} School",
            "SYN-DC-CAPC",
            "DC",
            "82404",
            "Pellham",
            TAMSIN,
        )
        for part in ("Lower", "Middle", "High")
    ),
    _district("SYN-DC-CAPV", "Capwell Village PCS", "DC", "82404", "Pellham", TAMSIN),
    _school("SYN-DC-CAPVS", "Capwell Village PCS", "SYN-DC-CAPV", "DC", "82404", "Pellham", TAMSIN),
    _district("SYN-PA-AVMSD", "Avonmere SD", "PA", "82405", "Avonmere", (39.8, -75.8)),
    *(
        _school(
            f"SYN-PA-AVM{level[0]}",
            f"Avonmere {level}",
            "SYN-PA-AVMSD",
            "PA",
            "82405",
            "Avonmere",
            (39.8, -75.8),
        )
        for level in ("Area HS", "MS", "El Sch")
    ),
    _district("SYN-PA-AVMCS", "Avonmere CS", "PA", "82405", "Avonmere", (39.8, -75.8)),
    _school(
        "SYN-PA-AVMCSS", "Avonmere CS", "SYN-PA-AVMCS", "PA", "82405", "Avonmere", (39.8, -75.8)
    ),
    _school(
        "SYN-CO-HARPS",
        "Harrowby Online Program",
        "SYN-CO-HARP",
        "CO",
        "82402",
        "Harrowby",
        (39.70, -104.90),
    ),
    # Utah: a district named for its city without the city's "City".
    _district("SYN-UT-BRINE", "Brinewater District", "UT", "82601", "Brinewater City", BRINEWATER),
    _school(
        "SYN-UT-BRIHS",
        "Brinewater High",
        "SYN-UT-BRINE",
        "UT",
        "82601",
        "Brinewater City",
        BRINEWATER,
    ),
    _district(
        "SYN-UT-BRVAL", "Brinewater Valley District", "UT", "82602", "Brinewater City", BRINEWATER
    ),
    # Pennsylvania: a town whose name holds "College", and a charter district
    # that runs one school of its own name.
    _district(
        "SYN-PA-RIDCO",
        "Ridgemont College Area SD",
        "PA",
        PA_C,
        "Ridgemont College",
        MILLBROOK,
    ),
    _school(
        "SYN-PA-RIDHS",
        "Ridgemont College Area HS",
        "SYN-PA-RIDCO",
        "PA",
        PA_C,
        "Ridgemont College",
        MILLBROOK,
    ),
    _district("SYN-PA-HARMD", "Harborview Montessori CS", "PA", PA_A, "Lancaster", LANCASTER),
    _school(
        "SYN-PA-HARM",
        "Harborview Montessori CS",
        "SYN-PA-HARMD",
        "PA",
        PA_A,
        "Lancaster",
        LANCASTER,
    ),
    # Pennsylvania: a career and technology center is a district of campuses.
    _district(
        "SYN-PA-RAVCT",
        "Ravensburg County Career and Technology Center",
        "PA",
        PA_B,
        "Eastbrook",
        EASTBROOK,
    ),
    _school(
        "SYN-PA-RAVMG",
        "Ravensburg County Career and Technology Center - Millgate",
        "SYN-PA-RAVCT",
        "PA",
        PA_B,
        "Eastbrook",
        EASTBROOK,
    ),
    _school(
        "SYN-PA-RAVSB",
        "Ravensburg County Career and Technology Center - Stonebury",
        "SYN-PA-RAVCT",
        "PA",
        PA_B,
        "Eastbrook",
        EASTBROOK,
    ),
    # Districts named for their town as a village or a town, beside the town's
    # own government: Ohio's exempted village districts and Vermont's town
    # districts. The city districts are Kettleby, Brambleton and Genesee above.
    _district(
        "SYN-OH-FARR", "Farrowdale Exempted Village", "OH", "80905", "Farrowdale", FARROWDALE
    ),
    _school(
        "SYN-OH-FARHS",
        "Farrowdale High School",
        "SYN-OH-FARR",
        "OH",
        "80905",
        "Farrowdale",
        FARROWDALE,
    ),
    _district("SYN-OH-QUEN", "Quenby Exempted Village", "OH", "80906", "Quenby", QUENBY),
    _district("SYN-VT-HARL", "Harlowe Town School District", "VT", "82701", "Harlowe", HARLOWE),
    _school(
        "SYN-VT-HARLE",
        "Harlowe Elementary School",
        "SYN-VT-HARL",
        "VT",
        "82701",
        "Harlowe",
        HARLOWE,
    ),
    _district("SYN-VT-PELL", "Pellston Town School District", "VT", "82702", "Pellston", PELLSTON),
    # Louisiana: a district whose legal name begins "City of", as some do.
    _district("SYN-LA-MARL", "City of Marlowe School District", "LA", "81203", "Marlowe", MARLOWE),
    # Virginia: a city whose name holds a civic word.
    _district(
        "SYN-VA-MILCH",
        "Millers Church City Public Schools",
        "VA",
        "81003",
        "Millers Church",
        MILLERS_CHURCH,
    ),
    # Towns of two words, where a civic body's name shares the district's rare
    # words and adds only a common one ("Center"): a city district that runs one
    # school named for the town, an exempted village and a town district.
    _district("SYN-AL-SABR", "Sabrel Pass City", "AL", "80802", "Sabrel Pass", SABREL_PASS),
    _school(
        "SYN-AL-SABRS",
        "Sabrel Pass School",
        "SYN-AL-SABR",
        "AL",
        "80802",
        "Sabrel Pass",
        SABREL_PASS,
    ),
    _school(
        "SYN-AL-ADACP",
        "Ada Church Pellow",
        "SYN-AL-SABR",
        "AL",
        "80802",
        "Sabrel Pass",
        SABREL_PASS,
    ),
    _district(
        "SYN-OH-WEXF",
        "Wexcombe Falls Exempted Village",
        "OH",
        "80907",
        "Wexcombe Falls",
        WEXCOMBE_FALLS,
    ),
    _school(
        "SYN-OH-WEXHS",
        "Wexcombe Falls High School",
        "SYN-OH-WEXF",
        "OH",
        "80907",
        "Wexcombe Falls",
        WEXCOMBE_FALLS,
    ),
    _district(
        "SYN-VT-NTAL",
        "North Tallis Town School District",
        "VT",
        "82703",
        "North Tallis",
        NORTH_TALLIS,
    ),
    _school(
        "SYN-VT-NTALE",
        "North Tallis Elementary School",
        "SYN-VT-NTAL",
        "VT",
        "82703",
        "North Tallis",
        NORTH_TALLIS,
    ),
    # New York: a district whose legal name begins "Town of".
    _district(
        "SYN-NY-ORLE",
        "TOWN OF ORLEBY UNION FREE SCHOOL DISTRICT",
        "NY",
        "80304",
        "Orleby",
        ORLEBY,
    ),
    # Pennsylvania: a "Valley" district beside a private "Valley School of" its town,
    # and a learning center (an alternative school) beside the town's
    # prekindergarten "Early Learning Center", which the directory does not hold.
    _district("SYN-PA-TAMB", "Tamberlin Valley SD", "PA", PA_C, "Tamberlin", MILLBROOK),
    _school(
        "SYN-PA-TAMHS", "Tamberlin Valley HS", "SYN-PA-TAMB", "PA", PA_C, "Tamberlin", MILLBROOK
    ),
    _school(
        "SYN-PA-TAMMS", "Tamberlin Valley MS", "SYN-PA-TAMB", "PA", PA_C, "Tamberlin", MILLBROOK
    ),
    _school(
        "SYN-PA-TAMLC",
        "Tamberlin Learning Center",
        "SYN-PA-TAMB",
        "PA",
        PA_C,
        "Tamberlin",
        MILLBROOK,
    ),
    _school(
        "SYN-PA-HOLEC",
        "Holloway Early Childhood Center",
        "SYN-PA-TAMB",
        "PA",
        PA_C,
        "Tamberlin",
        MILLBROOK,
    ),
    # Maine: districts named only by a code. Regional school units and school
    # administrative districts are numbered separately, so "RSU 91" and "MSAD 91"
    # are two districts, and a district that is both carries both numbers. Their
    # schools are named for their towns and areas ("Seacliff"). A town's own
    # district belongs to no unit.
    _district("SYN-ME-RSU84", "RSU 84", "ME", "82801", "Tollbridge", TOLLBRIDGE),
    _school(
        "SYN-ME-SEAHS",
        "Seacliff High School",
        "SYN-ME-RSU84",
        "ME",
        "82801",
        "Tollbridge",
        TOLLBRIDGE,
    ),
    _school(
        "SYN-ME-SEAMS",
        "Seacliff Middle School",
        "SYN-ME-RSU84",
        "ME",
        "82801",
        "Kettering",
        TOLLBRIDGE,
    ),
    _school(
        "SYN-ME-KETGS",
        "Kettering Grammar School",
        "SYN-ME-RSU84",
        "ME",
        "82801",
        "Kettering",
        TOLLBRIDGE,
    ),
    _school(
        "SYN-ME-MARPC",
        "Marram Point Central School",
        "SYN-ME-RSU84",
        "ME",
        "82801",
        "Marram Point",
        TOLLBRIDGE,
    ),
    _district("SYN-ME-RSU93", "RSU 93/MSAD 84", "ME", "82802", "Brackley", BRACKLEY),
    _school(
        "SYN-ME-BRAHS",
        "Brackley Area High School",
        "SYN-ME-RSU93",
        "ME",
        "82802",
        "Brackley",
        BRACKLEY,
    ),
    _school(
        "SYN-ME-BRAMS",
        "Brackley Regional Middle School",
        "SYN-ME-RSU93",
        "ME",
        "82802",
        "Brackley",
        BRACKLEY,
    ),
    _school(
        "SYN-ME-FENCS",
        "Fenmoor-Aldwick Consolidated School",
        "SYN-ME-RSU93",
        "ME",
        "82802",
        "Fenmoor",
        BRACKLEY,
    ),
    _district("SYN-ME-SAD91", "MSAD 91", "ME", "82803", "Dunmore", DUNMORE),
    _school(
        "SYN-ME-DUNCS",
        "Dunmore Community School",
        "SYN-ME-SAD91",
        "ME",
        "82803",
        "Dunmore",
        DUNMORE,
    ),
    _district("SYN-ME-RSU91", "RSU 91", "ME", "82803", "Loxham", DUNMORE),
    _school(
        "SYN-ME-LOXES",
        "Loxham Elementary School",
        "SYN-ME-RSU91",
        "ME",
        "82803",
        "Loxham",
        DUNMORE,
    ),
    _school("SYN-ME-LOXHS", "Loxham High School", "SYN-ME-RSU91", "ME", "82803", "Loxham", DUNMORE),
    _district("SYN-ME-AUGP", "Augustine Public Schools", "ME", "82804", "Augustine", AUGUSTINE),
    _school("SYN-ME-AUGLS", "Lincoln School", "SYN-ME-AUGP", "ME", "82804", "Augustine", AUGUSTINE),
    _school(
        "SYN-ME-WEXEE", "Wexbury Eddy School", "SYN-ME-AUGP", "ME", "82804", "Wexbury", AUGUSTINE
    ),
    # Kansas: districts named for their town, whose "USD" numbers only closings
    # lists give, and two virtual schools that carry their district's number.
    _district("SYN-KS-WEND", "Wendham", "KS", "82901", "Wendham", WENDHAM),
    _school("SYN-KS-WENHS", "Wendham High", "SYN-KS-WEND", "KS", "82901", "Wendham", WENDHAM),
    _school(
        "SYN-KS-WENMS", "Wendham Middle School", "SYN-KS-WEND", "KS", "82901", "Wendham", WENDHAM
    ),
    _school(
        "SYN-KS-WENVA",
        "USD 431 Virtual Academy",
        "SYN-KS-WEND",
        "KS",
        "82901",
        "Wendham",
        WENDHAM,
    ),
    _district("SYN-KS-CARV", "Carrow Valley", "KS", "82902", "Tessmer", CARROW),
    _school("SYN-KS-CARHS", "Carrow Valley High", "SYN-KS-CARV", "KS", "82902", "Tessmer", CARROW),
    _school(
        "SYN-KS-CARVA",
        "USD 432 Virtual Academy",
        "SYN-KS-CARV",
        "KS",
        "82902",
        "Tessmer",
        CARROW,
    ),
    # Colorado: districts whose legal name gives only a number and a county,
    # and one named for a county whose town is Orland.
    _district(
        "SYN-CO-D5",
        "School District No. 5 in the county of Garrow and State of",
        "CO",
        "83001",
        "Brisbane Springs",
        BRISBANE_SPRINGS,
    ),
    _school(
        "SYN-CO-KETHS",
        "Ketterly High School",
        "SYN-CO-D5",
        "CO",
        "83001",
        "Brisbane Springs",
        BRISBANE_SPRINGS,
    ),
    _school(
        "SYN-CO-KETMS",
        "Ketterly Middle School",
        "SYN-CO-D5",
        "CO",
        "83001",
        "Brisbane Springs",
        BRISBANE_SPRINGS,
    ),
    _school(
        "SYN-CO-ASHES",
        "Ashgrove Elementary School",
        "SYN-CO-D5",
        "CO",
        "83001",
        "Brisbane Springs",
        BRISBANE_SPRINGS,
    ),
    _district(
        "SYN-CO-D8",
        "Palisade School District No. 8 in the county of Garrow an",
        "CO",
        "83001",
        "Palisade",
        BRISBANE_SPRINGS,
    ),
    _school(
        "SYN-CO-PALHS",
        "Palisade-Fort Garrow High School",
        "SYN-CO-D8",
        "CO",
        "83001",
        "Palisade",
        BRISBANE_SPRINGS,
    ),
    _district("SYN-CO-TESS", "Tessaly Re-4", "CO", "83002", "Orland", ORLAND),
    _school("SYN-CO-ORLHS", "Orland High School", "SYN-CO-TESS", "CO", "83002", "Orland", ORLAND),
    _school(
        "SYN-CO-ORLES", "Orland Elementary School", "SYN-CO-TESS", "CO", "83002", "Orland", ORLAND
    ),
    # Nebraska: a town's school system, whose schools name their level; Idaho:
    # one school whose own name ends "Public School", in a county's district.
    _district("SYN-NE-ORV", "ORVALE PUBLIC SCHOOLS", "NE", "83101", "Orvale", ORVALE),
    _school(
        "SYN-NE-ORVES", "ORVALE ELEMENTARY SCHOOL", "SYN-NE-ORV", "NE", "83101", "Orvale", ORVALE
    ),
    _school(
        "SYN-NE-ORVSS", "ORVALE SECONDARY SCHOOL", "SYN-NE-ORV", "NE", "83101", "Orvale", ORVALE
    ),
    _district("SYN-ID-BRIS", "BRISCOE COUNTY DISTRICT", "ID", "83201", "Briscoe", HALVERN),
    _school(
        "SYN-ID-HALPS", "HALVERN PUBLIC SCHOOL", "SYN-ID-BRIS", "ID", "83201", "Halvern", HALVERN
    ),
    # Massachusetts and New Hampshire: a private school, a public elementary
    # school named for a person, and a charter academy across the state line.
    _school("SYN-MA-BIRCH", "BIRCHMONT SCHOOL", None, "MA", "82102", "Holcombe", HOLCOMBE),
    _school("SYN-MA-HOLF", "Hollis Frost", "SYN-MA-BRAK", "MA", "82101", "Brackenmoor", HOLCOMBE),
    _school(
        "SYN-NH-BIRCH",
        "The Birchmont Academy of Arts and Letters Public Charter Sch",
        None,
        "NH",
        "83301",
        "Salem",
        HOLCOMBE,
    ),
    _school("SYN-VT-ASHB", "Ashbury School", None, "VT", "82704", "Ashbury", PELLSTON),
    # Massachusetts names a regional district without "Regional" and its high
    # school with it; Pennsylvania has a "Regional" and an "Area" district.
    _district("SYN-MA-WACH", "Wachbury", "MA", "82103", "Holcombe", HOLCOMBE),
    _school(
        "SYN-MA-WACHS", "Wachbury Regional High", "SYN-MA-WACH", "MA", "82103", "Holcombe", HOLCOMBE
    ),
    _district("SYN-PA-FRAR", "Franlow Regional SD", "PA", "80104", "Murrow", FRANLOW),
    _district("SYN-PA-FRAA", "Franlow Area SD", "PA", "80105", "Franlow", FRANLOW),
    # A private school whose name says nothing of its kind; a charter school that
    # is a district of its own, named without "Charter"; one named "Chartered".
    _school("SYN-MO-TOLL", "TOLLIS DEO", None, "MO", "83401", "Tollis", CARROW),
    _district("SYN-MN-WRENH", "WREN HOLLOW COMMUNITY SCHOOL", "MN", "83501", "Wren", ORVALE),
    _school(
        "SYN-MN-WRENS",
        "WREN HOLLOW COMMUNITY SCHOOL",
        "SYN-MN-WRENH",
        "MN",
        "83501",
        "Wren",
        ORVALE,
    ),
    _school(
        "SYN-NH-KESTR",
        "Kestrel Falls Chartered Public School",
        None,
        "NH",
        "83302",
        "Kestrel",
        HOLCOMBE,
    ),
    # North Dakota: a town's district named with its number, and its schools.
    _district("SYN-ND-HART", "HARTWELL 49", "ND", "83601", "Hartwell", ORVALE),
    _school(
        "SYN-ND-HARES",
        "HARTWELL ELEMENTARY SCHOOL",
        "SYN-ND-HART",
        "ND",
        "83601",
        "Hartwell",
        ORVALE,
    ),
    _school(
        "SYN-ND-HARHS", "HARTWELL HIGH SCHOOL", "SYN-ND-HART", "ND", "83601", "Hartwell", ORVALE
    ),
    # Towns named for where they lie from another town, beside that town, in one
    # county: "East Lansmere" is not "Lansmere". Some towns have no such
    # neighbour, so "E. Portwick" names nothing. Middle initials and a leading
    # initial stay initials.
    _district(
        "SYN-MI-LANM", "Lansmere Public School District", "MI", "83701", "Lansmere", LANSMERE
    ),
    _school(
        "SYN-MI-LANHS", "Lansmere High School", "SYN-MI-LANM", "MI", "83701", "Lansmere", LANSMERE
    ),
    _school(
        "SYN-MI-TOLES",
        "Harry S. Tollman Elementary School",
        "SYN-MI-LANM",
        "MI",
        "83701",
        "Lansmere",
        LANSMERE,
    ),
    _district(
        "SYN-MI-ELANM", "East Lansmere Public Schools", "MI", "83701", "East Lansmere", LANSMERE
    ),
    _school(
        "SYN-MI-ELANHS",
        "East Lansmere High School",
        "SYN-MI-ELANM",
        "MI",
        "83701",
        "East Lansmere",
        LANSMERE,
    ),
    _school(
        "SYN-MI-BARES",
        "Joel E. Barrow Elementary School",
        "SYN-MI-ELANM",
        "MI",
        "83701",
        "East Lansmere",
        LANSMERE,
    ),
    _school(
        "SYN-MI-CURES",
        "E. Halden Currie Elementary",
        "SYN-MI-ELANM",
        "MI",
        "83701",
        "East Lansmere",
        LANSMERE,
    ),
    _district(
        "SYN-IA-DESP",
        "Des Pellam Independent Comm School District",
        "IA",
        "83801",
        "Des Pellam",
        DES_PELLAM,
    ),
    _district(
        "SYN-IA-WDESP",
        "West Des Pellam Comm School District",
        "IA",
        "83801",
        "West Des Pellam",
        DES_PELLAM,
    ),
    _district("SYN-ME-PORTW", "Portwick Public Schools", "ME", "83901", "Portwick", PORTWICK),
    _district(
        "SYN-AR-LBRK", "LITTLE BROOK SCHOOL DISTRICT", "AR", "84001", "Little Brook", LITTLE_BROOK
    ),
    _district(
        "SYN-AR-NLBRK",
        "NORTH LITTLE BROOK SCHOOL DISTRICT",
        "AR",
        "84001",
        "North Little Brook",
        LITTLE_BROOK,
    ),
    _district("SYN-VT-BURL", "Burlingham School District", "VT", "84101", "Burlingham", BURLINGHAM),
    _school(
        "SYN-VT-BURHS",
        "Burlingham High School",
        "SYN-VT-BURL",
        "VT",
        "84101",
        "Burlingham",
        BURLINGHAM,
    ),
    _district(
        "SYN-VT-SBURL",
        "South Burlingham School District",
        "VT",
        "84101",
        "South Burlingham",
        BURLINGHAM,
    ),
    _school(
        "SYN-VT-SBURHS",
        "South Burlingham High School",
        "SYN-VT-SBURL",
        "VT",
        "84101",
        "South Burlingham",
        BURLINGHAM,
    ),
    _school(
        "SYN-VT-TAMS",
        "Village School of North Tamsford",
        None,
        "VT",
        "84102",
        "North Tamsford",
        TAMSFORD,
    ),
    _district("SYN-CT-HARTM", "Hartmoor School District", "CT", "84201", "Hartmoor", HARTMOOR),
    _district("SYN-NJ-ORL", "Orlane School District", "NJ", "84301", "Orlane", ORLANE),
    _district("SYN-NJ-EORL", "East Orlane School District", "NJ", "84301", "East Orlane", ORLANE),
    _district("SYN-RI-PROV", "Provost", "RI", "84401", "Provost", PROVOST),
    _district("SYN-RI-EPROV", "East Provost", "RI", "84401", "East Provost", PROVOST),
    _district("SYN-MO-KESC", "KESSEL CITY 33", "MO", "84501", "Kessel City", KESSEL),
    _district("SYN-MO-NKESC", "NORTH KESSEL CITY 74", "MO", "84501", "North Kessel City", KESSEL),
    _district(
        "SYN-MN-TAMH",
        "Grand Tamsel Harbor Public School District",
        "MN",
        "84601",
        "Grand Tamsel Harbor",
        TAMSEL_HARBOR,
    ),
    _district(
        "SYN-WI-EBRK",
        "East Brackwater Falls Area School District",
        "WI",
        "84701",
        "East Brackwater Falls",
        BRACKWATER,
    ),
    # NCES abbreviates directions too: "W Harlan-Dixby", "Pellam-W Holliver",
    # "SO TAMBLIN CITY", and a campus after a dash.
    _district("SYN-IL-WHAR", "W Harlan-Dixby PSD 147", "IL", "84801", "Harlan", HARLAN_DIXBY),
    _district("SYN-IL-PELL", "Pellam-W Holliver SD 105", "IL", "84801", "Pellam", HARLAN_DIXBY),
    _district("SYN-IL-LTAM", "Lake Tamsin CUSD 95", "IL", "84802", "Lake Tamsin", HARLAN_DIXBY),
    _school(
        "SYN-IL-LTAMN",
        "Lake Tamsin Middle - N Campus",
        "SYN-IL-LTAM",
        "IL",
        "84802",
        "Lake Tamsin",
        HARLAN_DIXBY,
    ),
    _school(
        "SYN-IL-LTAMS",
        "Lake Tamsin Middle - S Campus",
        "SYN-IL-LTAM",
        "IL",
        "84802",
        "Lake Tamsin",
        HARLAN_DIXBY,
    ),
    _district(
        "SYN-NE-STAM",
        "SO TAMBLIN CITY COMMUNITY SCHS",
        "NE",
        "84901",
        "South Tamblin City",
        TAMBLIN,
    ),
    _district("SYN-NE-TAM", "TAMBLIN PUBLIC SCHOOLS", "NE", "84901", "Tamblin", TAMBLIN),
    _district("SYN-KS-NLYM", "North Lymont County", "KS", "85001", "Lymont", LYMONT),
    # A private school's affiliation is part of its name, unless its name is a
    # saint's or a devotion's: "Pellbridge Academy" is not "Pellbridge Christian
    # Academy", but "Sacred Heart School" is "Sacred Heart Catholic School".
    _school(
        "SYN-NH-PELCA", "PELLBRIDGE CHRISTIAN ACADEMY", None, "NH", "85101", "Pellbridge", HOLCOMBE
    ),
    _school(
        "SYN-VA-BRINC",
        "THE BRINDLE CHRISTIAN ACADEMY",
        None,
        "VA",
        "85201",
        "Brindle Station",
        MILLERS_CHURCH,
    ),
    _school("SYN-KS-SACH", "SACRED HEART CATHOLIC SCHOOL", None, "KS", "85002", "Tessmer", CARROW),
    # A listing that names the school's town beside it may leave its church out.
    _school("SYN-MA-CHEVC", "CHEVERWOOD CATHOLIC SCHOOL", None, "MA", "85102", "Marlden", HOLCOMBE),
    _district("SYN-MA-MARL", "Marlden", "MA", "85102", "Marlden", HOLCOMBE),
    # Pennsylvania: a township's school in a district named for another town,
    # and New Hampshire: a town whose one school is named for it.
    _district("SYN-PA-DALL", "Dallenby Area SD", "PA", "85601", "Dallenby", FRANLOW),
    _school("SYN-PA-YARTW", "Yarwick Twp El Sch", "SYN-PA-DALL", "PA", "85601", "Yarwick", FRANLOW),
    _district(
        "SYN-NH-SAU49", "Wentmoor Regional School District", "NH", "85502", "Wentmoor", HOLCOMBE
    ),
    _school(
        "SYN-NH-EFFES",
        "Effley Elementary School",
        "SYN-NH-SAU49",
        "NH",
        "85502",
        "Effley",
        HOLCOMBE,
    ),
    # Kansas: one "ST MARY" whose name says nothing of its kind among others that
    # say "School", in counties 250 km from its own; "Saint Mary's Academy" is none
    # of them.
    _school("SYN-KS-STMY", "ST MARY", None, "KS", "85003", "Garrow", CARROW),
    _school("SYN-KS-STMYS", "ST MARY'S SCHOOL", None, "KS", "85004", "Ellery", (39.80, -99.80)),
    _school(
        "SYN-KS-STMYC", "ST MARY CATHOLIC SCHOOL", None, "KS", "85005", "Newbury", (37.20, -95.10)
    ),
    # A leading code before a town whose name ends "Center".
    _district("SYN-KS-HARC", "Harrow Center Pub Sch", "KS", "85006", "Harrow Center", CARROW),
    _school(
        "SYN-KS-HARCH",
        "Harrow Center High School",
        "SYN-KS-HARC",
        "KS",
        "85006",
        "Harrow Center",
        CARROW,
    ),
    _school(
        "SYN-KS-HARCM",
        "Harrow Center Middle School",
        "SYN-KS-HARC",
        "KS",
        "85006",
        "Harrow Center",
        CARROW,
    ),
    # Minnesota: a city's system beside a charter school named for the city.
    _district("SYN-MN-STPEL", "Saint Pellam Public Schools", "MN", "84602", "Saint Pellam", ORVALE),
    _district("SYN-MN-STPCS", "St. Pellam City School", "MN", "84602", "Saint Pellam", ORVALE),
    _school(
        "SYN-MN-STPCSS",
        "St. Pellam City School",
        "SYN-MN-STPCS",
        "MN",
        "84602",
        "Saint Pellam",
        ORVALE,
    ),
    # Texas: an apostrophe a feed sends as an HTML entity. Ohio: a school network
    # whose name begins with a letter.
    _district("SYN-TX-LEVC", "LEVERIDGE'S CHAPEL ISD", "TX", "85301", "Overbrook", (32.2, -94.9)),
    _school("SYN-OH-EPREP", "E Prep Woodmere", None, "OH", "85401", "Woodmere", QUENBY),
    _school(
        "SYN-OH-VPREP",
        "Village Preparatory School Tamsin Hills",
        None,
        "OH",
        "85401",
        "Woodmere",
        QUENBY,
    ),
    # Minnesota: a city named for its direction from another, whose name begins
    # "St." ("So. St. Pellam").
    _district(
        "SYN-MN-SSTPEL",
        "South St. Pellam Public School Dist",
        "MN",
        "84602",
        "South Saint Pellam",
        ORVALE,
    ),
    # New Hampshire splits a charter school by level into records of one name,
    # the schools of a district of that name; a town district beside it has two
    # schools of one name and a third.
    _district("SYN-NH-GBAY", "Grenmoor Bay Charter School", "NH", "85501", "Exmoor", HOLCOMBE),
    _school(
        "SYN-NH-GBAYH",
        "Grenmoor Bay Charter School (H)",
        "SYN-NH-GBAY",
        "NH",
        "85501",
        "Exmoor",
        HOLCOMBE,
    ),
    _school(
        "SYN-NH-GBAYM",
        "Grenmoor Bay Charter School (M)",
        "SYN-NH-GBAY",
        "NH",
        "85501",
        "Exmoor",
        HOLCOMBE,
    ),
    _district("SYN-NH-EXM", "Exmoor School District", "NH", "85501", "Exmoor", HOLCOMBE),
    _school(
        "SYN-NH-EXMCE",
        "Tolliver Central School (Elem)",
        "SYN-NH-EXM",
        "NH",
        "85501",
        "Exmoor",
        HOLCOMBE,
    ),
    _school(
        "SYN-NH-EXMCM",
        "Tolliver Central School (Middle)",
        "SYN-NH-EXM",
        "NH",
        "85501",
        "Exmoor",
        HOLCOMBE,
    ),
    _school("SYN-NH-EXMHS", "Exmoor High School", "SYN-NH-EXM", "NH", "85501", "Exmoor", HOLCOMBE),
    # A town's name is its school system, never the one school named for it or
    # in it. California: "Varenna" is "Varenna Valley Unified", whose high
    # school is "Varenna High"; Rickmond's schools are Bayshore Unified's, and
    # the district named "Rickmond Elementary" lies in another county.
    _district("SYN-CA-VARV", "Varenna Valley Unified", "CA", "85701", "Varenna", VARENNA),
    _school("SYN-CA-VARHS", "Varenna High", "SYN-CA-VARV", "CA", "85701", "Varenna", VARENNA),
    _school(
        "SYN-CA-VARJE",
        "Varenna Junction Elementary",
        "SYN-CA-VARV",
        "CA",
        "85701",
        "Calloway Canyon",
        VARENNA,
    ),
    _district("SYN-CA-BAYU", "Bayshore Unified", "CA", "85702", "Rickmond", RICKMOND),
    _school(
        "SYN-CA-HWYES", "Harbor Way Elementary", "SYN-CA-BAYU", "CA", "85702", "Rickmond", RICKMOND
    ),
    _school("SYN-CA-RICHS", "Rickmond High", "SYN-CA-BAYU", "CA", "85702", "Rickmond", RICKMOND),
    _district("SYN-CA-RICE", "Rickmond Elementary", "CA", "85703", "Susanfield", SUSANFIELD),
    _school(
        "SYN-CA-RICES",
        "Rickmond Elementary",
        "SYN-CA-RICE",
        "CA",
        "85703",
        "Susanfield",
        SUSANFIELD,
    ),
    # New Jersey: a township's district whose schools' addresses are another
    # town's; a township and a city of one name side by side.
    _district(
        "SYN-NJ-OLDB", "Olden Brook Township School District", "NJ", "85801", "Matlock", OLDEN_BROOK
    ),
    _school(
        "SYN-NJ-OLDBH",
        "Olden Brook High School",
        "SYN-NJ-OLDB",
        "NJ",
        "85801",
        "MATLOCK",
        OLDEN_BROOK,
    ),
    _school(
        "SYN-NJ-OLDBG", "GODWIN SCHOOL OF OLDEN BROOK", None, "NJ", "85801", "MATLOCK", OLDEN_BROOK
    ),
    _district(
        "SYN-NJ-NEPT", "Nepford Township School District", "NJ", "85801", "Nepford", OLDEN_BROOK
    ),
    _school(
        "SYN-NJ-NEPTH", "Nepford High School", "SYN-NJ-NEPT", "NJ", "85801", "Nepford", OLDEN_BROOK
    ),
    _district(
        "SYN-NJ-NEPC", "Nepford City School District", "NJ", "85801", "Nepford City", OLDEN_BROOK
    ),
    _school(
        "SYN-NJ-NEPCE",
        "Nepford City Elementary School",
        "SYN-NJ-NEPC",
        "NJ",
        "85801",
        "Nepford City",
        OLDEN_BROOK,
    ),
    # Arizona: a town with an elementary district and a high school district.
    _district("SYN-AZ-BUCE", "Buckmoor Elementary District", "AZ", "85901", "Buckmoor", BUCKMOOR),
    _school(
        "SYN-AZ-BUCES",
        "Buckmoor Elementary School",
        "SYN-AZ-BUCE",
        "AZ",
        "85901",
        "Buckmoor",
        BUCKMOOR,
    ),
    _district(
        "SYN-AZ-BUCH", "Buckmoor Union High School District", "AZ", "85901", "Buckmoor", BUCKMOOR
    ),
    _school(
        "SYN-AZ-BUCHS",
        "Buckmoor Union High School",
        "SYN-AZ-BUCH",
        "AZ",
        "85901",
        "Buckmoor",
        BUCKMOOR,
    ),
    # Kentucky and North Carolina: a city whose schools are its county's, and a
    # private school named for the city.
    _district("SYN-KY-CORW", "Corwin County", "KY", "86001", "Brackville", BRACKVILLE),
    _school(
        "SYN-KY-TOLES", "Tolland Elementary", "SYN-KY-CORW", "KY", "86001", "Brackville", BRACKVILLE
    ),
    _school(
        "SYN-KY-VSOB", "VILLAGE SCHOOL OF BRACKVILLE", None, "KY", "86001", "BRACKVILLE", BRACKVILLE
    ),
    _district("SYN-NC-WEXC", "Wexmoor County Schools", "NC", "86101", "Halstead", HALSTEAD),
    _school("SYN-NC-OAKMS", "Oakmere Middle", "SYN-NC-WEXC", "NC", "86101", "Halstead", HALSTEAD),
    _school("SYN-NC-THEHS", "THE HALSTEAD SCHOOL", None, "NC", "86101", "HALSTEAD", HALSTEAD),
    # Ohio: a city's district, and schools of another city named for it and
    # for a village whose own schools are a local district's.
    _district("SYN-OH-KESC", "Kessling City", "OH", "86201", "Kessling", KESSLING),
    _school(
        "SYN-OH-KESHS", "Kessling High School", "SYN-OH-KESC", "OH", "86201", "Kessling", KESSLING
    ),
    _district("SYN-OH-DAYC", "Daywood City", "OH", "86202", "Daywood", DAYWOOD),
    _school(
        "SYN-OH-KESES",
        "Kessling Elementary School",
        "SYN-OH-DAYC",
        "OH",
        "86202",
        "Daywood",
        DAYWOOD,
    ),
    _school(
        "SYN-OH-PELES",
        "Pellmont Elementary School",
        "SYN-OH-DAYC",
        "OH",
        "86202",
        "Daywood",
        DAYWOOD,
    ),
    _district("SYN-OH-HARL", "Hartwell Local", "OH", "86203", "Hartwell", PELLMONT),
    _school(
        "SYN-OH-HARMS", "Hartwell Middle School", "SYN-OH-HARL", "OH", "86203", "Pellmont", PELLMONT
    ),
    # Pennsylvania: a district named for a township its schools' addresses do
    # not name, which only a preschool's does; a city's district beside a
    # private school named for the city; a town named for a saint.
    _district("SYN-PA-MTLIN", "Mt Lindell SD", "PA", "86301", "Pittsfield", LINDELL),
    _school("SYN-PA-MTLHS", "Mt Lindell SHS", "SYN-PA-MTLIN", "PA", "86301", "Pittsfield", LINDELL),
    _school(
        "SYN-PA-ACORN",
        "LITTLE ACORNS LEARNING CENTER",
        None,
        "PA",
        "86301",
        "MOUNT LINDELL",
        LINDELL,
    ),
    _district("SYN-PA-PHIL", "Philmont City SD", "PA", "86302", "Philmont", PHILMONT),
    _school("SYN-PA-PHILS", "THE PHILMONT SCHOOL", None, "PA", "86302", "PHILMONT", PHILMONT),
    _district("SYN-PA-STMAR", "St Marlow Area SD", "PA", "86303", "Saint Marlow", MARLOW),
    _school(
        "SYN-PA-STMARH",
        "St Marlow Area HS",
        "SYN-PA-STMAR",
        "PA",
        "86303",
        "Saint Marlow",
        MARLOW,
    ),
    _school("SYN-PA-STMARS", "ST MARLOW'S SCHOOL", None, "PA", "86304", "Harwick", MARLOW),
    # Michigan: a town whose name holds a school noun, and a city's district
    # named "... School District of the City of".
    _district(
        "SYN-MI-BYFC", "Byford Center Public Schools", "MI", "86401", "Byford Center", BYFORD
    ),
    _school(
        "SYN-MI-BYFCH",
        "Byford Center High School",
        "SYN-MI-BYFC",
        "MI",
        "86401",
        "Byford Center",
        BYFORD,
    ),
    _district(
        "SYN-MI-HAMT", "Hamlow School District of the City of", "MI", "86402", "Hamlow", MARROWGATE
    ),
    _district("SYN-MI-HAMA", "Hamlow Academy", "MI", "86402", "Hamlow", MARROWGATE),
    _school("SYN-MI-HAMAS", "Hamlow Academy", "SYN-MI-HAMA", "MI", "86402", "Hamlow", MARROWGATE),
    _school(
        "SYN-MI-HAMHS", "Hamlow High School", "SYN-MI-HAMT", "MI", "86402", "Hamlow", MARROWGATE
    ),
    # Illinois: a village whose high school is a high school district's, named
    # for another town, and a town whose district is named by its number alone.
    _district("SYN-IL-BREM", "Bremfield CHSD 228", "IL", "86501", "Midvale", TINSLEY),
    _school(
        "SYN-IL-TINHS",
        "Tinsley Park High School",
        "SYN-IL-BREM",
        "IL",
        "86501",
        "Tinsley Park",
        TINSLEY,
    ),
    _district("SYN-IL-CU309", "CUSD 309", "IL", "86502", "Oswell", OSWELL),
    _school("SYN-IL-OSWHS", "Oswell High School", "SYN-IL-CU309", "IL", "86502", "Oswell", OSWELL),
    _school(
        "SYN-IL-OSWEH", "Oswell East High School", "SYN-IL-CU309", "IL", "86502", "Oswell", OSWELL
    ),
    # Vermont: a town's high school, of a union district named for it and more.
    _district(
        "SYN-VT-MONRU",
        "Montfort Roxbury Unified Union School District #71",
        "VT",
        "86601",
        "Montfort",
        MONTFORT,
    ),
    _school(
        "SYN-VT-MONHS", "Montfort High School", "SYN-VT-MONRU", "VT", "86601", "Montfort", MONTFORT
    ),
    # Nevada: a city whose high school is its county's.
    _district("SYN-NV-WASH", "Washburn County School District", "NV", "86701", "Renwick", RENWICK),
    _school(
        "SYN-NV-RENHS", "RENWICK HIGH SCHOOL", "SYN-NV-WASH", "NV", "86701", "RENWICK", RENWICK
    ),
    # New York: a hamlet named for a saint, whose school is another town's district's.
    _district(
        "SYN-NY-SMITH", "SMITHFIELD CENTRAL SCHOOL DISTRICT", "NY", "86801", "Smithfield", ALBURY
    ),
    _school(
        "SYN-NY-STALB",
        "SAINT ALBURY ELEMENTARY SCHOOL",
        "SYN-NY-SMITH",
        "NY",
        "86801",
        "SAINT ALBURY",
        ALBURY,
    ),
    # New Jersey: a city and a township of one name, both in the town.
    _district(
        "SYN-NJ-BURC", "Burlmoor City Public School District", "NJ", "86901", "Burlmoor", BURLMOOR
    ),
    _school(
        "SYN-NJ-BURCH",
        "Burlmoor City High School",
        "SYN-NJ-BURC",
        "NJ",
        "86901",
        "Burlmoor",
        BURLMOOR,
    ),
    _district(
        "SYN-NJ-BURT", "Burlmoor Township School District", "NJ", "86901", "Burlmoor", BURLMOOR
    ),
    _school(
        "SYN-NJ-BURTH",
        "Burlmoor Township High School",
        "SYN-NJ-BURT",
        "NJ",
        "86901",
        "Burlmoor",
        BURLMOOR,
    ),
    # Virginia: a city's own district, and the county's high school in the city.
    _district("SYN-VA-FALC", "Falmont City Public Schools", "VA", "87001", "Falmont", FALMONT),
    _district("SYN-VA-FARC", "Farrow County Public Schools", "VA", "87002", "Annandale", FALMONT),
    _school("SYN-VA-FALHS", "Falmont High", "SYN-VA-FARC", "VA", "87002", "Falmont", FALMONT),
    # Missouri and Arkansas: a town of one name in each, one with a district
    # named for it, one whose high school is another town's district's.
    _district("SYN-MO-KING", "KINGSFORD 42", "MO", "87101", "KINGSFORD", KINGSFORD),
    _district("SYN-AR-JASP", "JASPEN SCHOOL DISTRICT", "AR", "87201", "JASPEN", KINGSFORD),
    _school(
        "SYN-AR-KINHS",
        "KINGSFORD HIGH SCHOOL",
        "SYN-AR-JASP",
        "AR",
        "87201",
        "KINGSFORD",
        KINGSFORD,
    ),
    # Michigan: a town whose schools are another town's district's, and a
    # charter school's own district named for the town.
    _district("SYN-MI-MARF", "Marrowfield Public Schools", "MI", "87301", "Marrowfield", KESSELBY),
    _school(
        "SYN-MI-KESHS", "Kesselby High School", "SYN-MI-MARF", "MI", "87301", "Kesselby", KESSELBY
    ),
    _district("SYN-MI-KESA", "Kesselby Academy", "MI", "87301", "Kesselby", KESSELBY),
    _school("SYN-MI-KESAS", "Kesselby Academy", "SYN-MI-KESA", "MI", "87301", "Kesselby", KESSELBY),
    # Texas: charter networks whose campuses lie in cities hundreds of kilometres
    # apart. A listing from one market names the network's campus there, never
    # its schools in the other cities. One network is named as one school (NCES
    # writes "H S OF" and "H S -" for its campuses), one as a school system, one
    # as an academy, and one has a campus of another kind in a market.
    *NETWORK_RECORDS,
    # A district that straddles a market's edge, most of its schools just
    # outside the market's counties, and a county's district with one virtual
    # school registered to it from across the state: both are whole districts.
    *STRADDLING_RECORDS,
    # Charter districts named as one academy, whose schools add a level or a
    # part to that name: the name alone is the district.
    *ACADEMY_RECORDS,
    # Districts named for a town that lies elsewhere, or spelled a letter
    # apart from another town's; legal forms lists leave out.
    *NAMESAKE_RECORDS,
    # Names that end with a bracket: a county, a second name, a legal form, an
    # entity number, a school's grades.
    *BRACKET_RECORDS,
    # Namesakes in two states that a list tells apart by the state, and names
    # that hold a state.
    *STATE_RECORDS,
    # Parish schools, whose churches share their names.
    *PARISH_RECORDS,
    # Namesakes in two states of one market, just past its counties and far.
    *TWIN_RECORDS,
    # A numbered district named for a saint, and a private school of the name.
    *JARVIS_RECORDS,
    # NCES naming habits a closings list reads the other way.
    *HABIT_RECORDS,
    # School systems NCES splits into several districts.
    *SYSTEM_RECORDS,
    # Namesakes across a state line, each written its state's way; private
    # schools named with their campus.
    *ACROSS_RECORDS,
    # A school a list's name says word for word, beside a district whose name
    # does not.
    *OWN_SCHOOL_RECORDS,
    # Townships of one name in two counties of New Jersey.
    *TOWNSHIP_RECORDS,
    # Schools whose names begin with or hold a place word.
    *LEADING_RECORDS,
    # Kind words alone, Quaker schools, a child care chain, numbers in words.
    *KIND_RECORDS,
    # Schools of one name in one market's counties, and namesakes beyond them.
    *SAME_NAME_RECORDS,
    # Schools whose names leave out their level, beside namesakes whose names say it.
    *LEVEL_RECORDS,
    # Schools named for a person, of one surname in one county.
    *PERSON_RECORDS,
    # Schools named for a word with a plural's "s" or without it.
    *PLURAL_RECORDS,
)


DESIGNATORS_ONLY = "hard negative: names differ only in designators"
LEGAL_FORM = "names of one town differ only in designators"
CIVIC = "hard negative: a civic body, not a school"
CODE = "district code"
CODE_NEGATIVE = "hard negative: district code"
DIRECTION = "direction"
DIRECTION_NEGATIVE = "hard negative: direction"
PLACE = "a place's name"
PLACE_NEGATIVE = "hard negative: a place's name"
NETWORK = "a network's campus"
NETWORK_NEGATIVE = "hard negative: a network's campuses"
OWN_NAME = "a district's own name"
OWN_NAME_NEGATIVE = "hard negative: a district's own name"
NAMESAKE = "a town's name, and a district of that name elsewhere"
NAMESAKE_NEGATIVE = "hard negative: a town's name, and a district of that name elsewhere"
SPELLING = "spelled as listed"
SPELLING_NEGATIVE = "hard negative: spelled a letter apart"
BRACKET = "a bracket NCES ends a name with"
BRACKET_NEGATIVE = "hard negative: a bracket NCES ends a name with"
STATE = "a state beside the name"
STATE_NEGATIVE = "hard negative: a state beside the name"
STATE_IN_NAME = "a state in the name"
STATE_IN_NAME_NEGATIVE = "hard negative: a state in the name"
PARISH = "a parish's school"
PARISH_NEGATIVE = "hard negative: a parish's church"
JUST_PAST = "hard negative: a namesake just past the counties"
SAME_NAME = "one of two schools of one name, the other outside the market"
SAME_NAME_NEGATIVE = "hard negative: schools of one name in one market"
SAINT = "a saint's epithet or a pope's numeral, a name's word"
SAINT_NEGATIVE = "hard negative: another saint's school"
HABIT = "an NCES naming habit read the other way"
HABIT_NEGATIVE = "hard negative: an NCES naming habit"
SYSTEM = "a school system NCES splits into districts"
SYSTEM_NEGATIVE = "hard negative: one district of a school system, or none"
ACROSS = "a namesake across a state line"
ACROSS_NEGATIVE = "hard negative: a namesake across a state line"
CAMPUS = "a private school named with its campus"
CAMPUS_NEGATIVE = "hard negative: a private school of two campuses"
OWN_SCHOOL = "a school named as the listing, beside its district"
OWN_SCHOOL_NEGATIVE = "hard negative: a school named as the listing, never its district"
TOWNSHIP = "a township whose namesake in another county runs a district"
TOWNSHIP_NEGATIVE = "hard negative: two townships of one name in two counties"
LEADING = "a place word that begins or holds a school's name"
LEADING_NEGATIVE = "hard negative: a school's place word left out"
LEVEL = "a school by a level its name leaves out"
LEVEL_NEGATIVE = "hard negative: a level a namesake's name leaves out"
KIND_ONLY = "kind words alone, a school's name word for word"
KIND_ONLY_NEGATIVE = "hard negative: kind words alone"
TAMSBY_SYSTEM = ("SYN-MT-TAMSH",)
KELLBY_SYSTEM = ("SYN-MT-GLAH",)
MILEBY_SYSTEM = ("SYN-MT-CUSH",)
PHENBY_SYSTEM = ("SYN-AZ-PHNH",)
PETALBY_SYSTEM = ("SYN-CA-PETH",)
STREBBY_SYSTEM = ("SYN-IL-STRH",)
BRONBY_SYSTEM = ("SYN-NY-BC02", "SYN-NY-BC10", "SYN-NY-BC11", "SYN-NY-BC75")
MO_KS = ("MO", "KS")


def case(  # noqa: PLR0913 - one argument per field of a case
    listing: str,
    states: tuple[str, ...] | str,
    expected: str | None,
    *,
    counties: tuple[str, ...] | str | None = None,
    near: tuple[float, float] | None = None,
    note: str = "",
    category: str | None = None,
    also: tuple[str, ...] = (),
) -> Case:
    """A labelled listing; a string ``states`` or ``counties`` means just that one.

    ``also``: the other records a listing of a school system names with ``expected``.
    """
    return Case(
        listing,
        (states,) if isinstance(states, str) else states,
        expected,
        counties=(counties,) if isinstance(counties, str) else counties,
        near=near,
        note=note,
        category=category,
        also=also,
    )


def _level(
    listing: str, expected: str | None, note: str, *, chicago: bool = False, near: bool = True
) -> Case:
    """A listing of the Boston-like market (or the ``chicago``-like), at its point if ``near``."""
    states, counties, point = (
        (("IL", "IN"), LAKEPORT_COUNTIES, LAKEPORT)
        if chicago
        else (("MA", "NH"), HARBOURNE_COUNTIES, HARBOURNE)
    )
    return case(
        listing, states, expected, counties=counties, near=point if near else None, note=note
    )


CASES: tuple[Case, ...] = (
    # Kind words alone name only a school whose name they are, word for word.
    case("Christian Academy", "SC", None, counties=KIND_SC_CO, note=KIND_ONLY_NEGATIVE),
    case("Learning Center", "SC", None, counties=KIND_SC_CO, note=KIND_ONLY_NEGATIVE),
    case("Day Care", "IL", None, counties=KIND_IL_CO, note=KIND_ONLY_NEGATIVE),
    case("Community School", "CT", None, counties=KIND_CT_CO, note=KIND_ONLY_NEGATIVE),
    case("Academy Christian School", "SC", "SYN-SC-ACS", counties=KIND_SC_CO, note=KIND_ONLY),
    case("Center for Learning", "SC", "SYN-SC-CFL", counties=KIND_SC_CO, note=KIND_ONLY),
    case("Care Day School", "IL", "SYN-IL-CDS", counties=KIND_IL_CO, note=KIND_ONLY),
    case("Learning Center", "KS", "SYN-KS-TLC", counties=KIND_KS_CO, note=KIND_ONLY),
    # "Friends" is a Quaker school's, never a district named "Friend".
    case("Friends", "NE", None, counties=KIND_NE_CO, note=KIND_ONLY_NEGATIVE + ": Friend"),
    case("Friends School", "NE", None, counties=KIND_NE_CO, note=KIND_ONLY_NEGATIVE),
    case("Friend Public Schools", "NE", "SYN-NE-FRD", counties=KIND_NE_CO),
    case("Friend Schools", "NE", "SYN-NE-FRD", counties=KIND_NE_CO),
    case("Omby Friends School", "NE", "SYN-NE-OFS", counties=KIND_NE_CO),
    case("Omby Friends", "NE", "SYN-NE-OFS", counties=KIND_NE_CO),
    # A child care chain's centre is never a public school of its brand's name.
    case("Goddard School", "CO", None, note=KIND_ONLY_NEGATIVE + ": a child care chain"),
    case("Goddard School", "CO", None, counties=KIND_CO_CO, note=KIND_ONLY_NEGATIVE),
    case("Goddard Middle School", "CO", "SYN-CO-GDM", counties=KIND_CO_CO),
    case("Goddard School", "NJ", "SYN-NJ-GDS", counties=KIND_NJ_CO, note="a child care chain"),
    # District numbers in words.
    case("Spartby District Seven", "SC", "SYN-SC-SP7", note="a district number in words"),
    case("Spartby School District Three", "SC", "SYN-SC-SP3", note="a district number in words"),
    case("Spartby Seven", "SC", "SYN-SC-SP7", note="a district number in words"),
    case("Spartby Three Schools", "SC", "SYN-SC-SP3", note="a district number in words"),
    case("Spartby District One", "SC", None, note="hard negative: a district number in words"),
    case("Andersby School District Five", "SC", "SYN-SC-AN5", note="a district number in words"),
    case(
        "Andersby Five Charter School",
        "SC",
        "SYN-SC-A5C",
        note="a charter school's own name, its Five no district's number",
    ),
    # A place word that begins a school's name, or has more of the name after it,
    # is the name's own: the name without it is another school's, or nobody's.
    case("Christian Academy", "NC", None, note=LEADING_NEGATIVE + ": Village Christian Academy"),
    case("Christian Academy", "NC", None, counties=LEAD_NC_CO, note=LEADING_NEGATIVE),
    case("Christian Academy - Closed", "NC", None, near=(35.9, -79.1), note=LEADING_NEGATIVE),
    case("Country Day School", "CA", None, note=LEADING_NEGATIVE + ": Town & Country Day School"),
    case("Country Day School", "CA", None, counties=LEAD_CA_CO, note=LEADING_NEGATIVE),
    case("Country Day", "CA", None, counties=LEAD_CA_CO, note=LEADING_NEGATIVE),
    case("Montessori School", "CA", None, counties=LEAD_CA_CO, note=LEADING_NEGATIVE),
    case("Montessori School", "CA", None, note=LEADING_NEGATIVE + ": Village Montessori School"),
    case("Charter School", "NJ", None, counties=LEAD_NJ_CO, note=LEADING_NEGATIVE),
    case("Child Development Center", "CO", None, note=LEADING_NEGATIVE),
    case("Child Development Center", "CO", None, counties=LEAD_CO_CO, note=LEADING_NEGATIVE),
    case("Kids Academy", "IN", None, note=LEADING_NEGATIVE + ": Kid City Academy"),
    case("Kid Academy", "IN", None, counties=LEAD_IN_CO, note=LEADING_NEGATIVE),
    case("Academy", "MO", None, note=LEADING_NEGATIVE + ": City Academy"),
    case("Academy", "MO", None, counties=LEAD_MO_CO, note=LEADING_NEGATIVE),
    case("The Academy", "MO", None, counties=LEAD_MO_CO, note=LEADING_NEGATIVE),
    case("Christian", "OH", None, counties=LEAD_OH_CO, note=LEADING_NEGATIVE),
    case("Christian School", "OH", None, counties=LEAD_OH_CO, note=LEADING_NEGATIVE),
    case("Montessori", "GA", None, counties=LEAD_GA_CO, note=LEADING_NEGATIVE + ": in Town"),
    case("Montessori School", "GA", None, counties=LEAD_GA_CO, note=LEADING_NEGATIVE),
    case("Ostermoor Christian School", "MI", None, counties=LEAD_MI_CO, note=LEADING_NEGATIVE),
    case("East Elementary", "NY", None, counties=LEAD_NY_CO, note=LEADING_NEGATIVE),
    case("Global Academy", "IL", None, counties=LEAD_IL_CO, note=LEADING_NEGATIVE),
    case("Montessori Academy", "IL", None, counties=LEAD_IL_CO, note=LEADING_NEGATIVE),
    case(
        "Brindleby High School",
        "NJ",
        None,
        counties=LEAD_NJ_B_CO,
        note=LEADING_NEGATIVE + ": a school's City ends its place's name",
    ),
    case("Village Christian Academy", "NC", "SYN-NC-VCA", counties=LEAD_NC_CO, note=LEADING),
    case("VILLAGE CHRISTIAN ACAD. - Closed", "NC", "SYN-NC-VCA", counties=LEAD_NC_CO, note=LEADING),
    case("Town & Country Day School", "CA", "SYN-CA-TCD", counties=LEAD_CA_CO, note=LEADING),
    case("Town and Country Day School", "CA", "SYN-CA-TCD", counties=LEAD_CA_CO, note=LEADING),
    case("Village Montessori School", "CA", "SYN-CA-VMS", counties=LEAD_CA_CO, note=LEADING),
    case("The Village Charter School", "NJ", "SYN-NJ-VCHS", counties=LEAD_NJ_CO, note=LEADING),
    case(
        "Village Child Development Center", "CO", "SYN-CO-VCDC", counties=LEAD_CO_CO, note=LEADING
    ),
    case("Kid City Academy", "IN", "SYN-IN-KCA", counties=LEAD_IN_CO, note=LEADING),
    case("City Academy", "MO", "SYN-MO-CA", counties=LEAD_MO_CO, note=LEADING),
    case(
        "Village Christian School (Closed)", "OH", "SYN-OH-VCS", counties=LEAD_OH_CO, note=LEADING
    ),
    case("Montessori in Town", "GA", "SYN-GA-MIT", counties=LEAD_GA_CO, note=LEADING),
    case("Ostermoor City Christian School", "MI", "SYN-MI-OCC", counties=LEAD_MI_CO, note=LEADING),
    case("East Village Elementary", "NY", "SYN-NY-EVE", counties=LEAD_NY_CO, note=LEADING),
    case("Global Village Academy", "IL", "SYN-IL-GVA", counties=LEAD_IL_CO, note=LEADING),
    case("Montessori Village Academy", "IL", "SYN-IL-MVA", counties=LEAD_IL_CO, note=LEADING),
    case("Brindleby City High School", "NJ", "SYN-NJ-BRNH", counties=LEAD_NJ_B_CO, note=LEADING),
    # A City that ends a district's name after its town's is the town's: a list may
    # leave it out.
    case("Quellmoor City Schools", "OH", "SYN-OH-QUEC", note=LEADING + ": a district's City"),
    case("Quellmoor Schools", "OH", "SYN-OH-QUEC", note=LEADING + ": a district's City"),
    case("Quellmoor Public Schools", "OH", "SYN-OH-QUEC", note=LEADING + ": a district's City"),
    case("Quellmoor", "OH", "SYN-OH-QUEC", note=LEADING + ": a district's City"),
    case("Brindleby City Schools", "NJ", "SYN-NJ-BRNC", note=LEADING + ": a district's City"),
    case("Brindleby Public Schools", "NJ", "SYN-NJ-BRNC", note=LEADING + ": a district's City"),
    # "Lancaster" against "Lancaster County".
    case("Lancaster School District", "PA", "SYN-PA-LANSD"),
    case("Lancaster SD", "PA", "SYN-PA-LANSD"),
    case("Lancaster Schools", "PA", "SYN-PA-LANSD"),
    case("LANCASTER SCHOOL DISTRICT", "PA", "SYN-PA-LANSD", note="case"),
    case("Lancaster", "PA", "SYN-PA-LANSD", note="bare name: its own schools do not compete"),
    case("School District of Lancaster", "PA", "SYN-PA-LANSD", note="leading designator"),
    case("Lancaster County Schools", "PA", "SYN-PA-LANCO"),
    case("Lancaster County School District", "PA", "SYN-PA-LANCO"),
    case("lancaster county school district", "PA", "SYN-PA-LANCO", note="case"),
    case("Lancaster Co. SD", "PA", "SYN-PA-LANCO", note="Co. is County"),
    case("Lancaster County Career Center", "PA", "SYN-PA-LANCC", counties=PA_B),
    case("Lancaster County Schools", "SC", "SYN-SC-LANCO"),
    case("Lancaster Co School District", "SC", "SYN-SC-LANCO"),
    case("Lancaster School District", "SC", None, note="hard negative: county left out"),
    case("Lancaster Schools", "SC", None, note="hard negative: county left out"),
    case("Lancaster SD", "OH", None, note="hard negative: other state"),
    case("Lancaster High", "SC", "SYN-SC-LANHI", counties="80201"),
    case("Lancaster High School", "PA", "SYN-PA-LANHS", counties=PA_A),
    case("Lancaster HS", "PA", "SYN-PA-LANHS", counties=PA_A),
    # Noise around a name.
    case("Lancaster SD - All Schools", "PA", "SYN-PA-LANSD"),
    case("Lancaster School District (Closed)", "PA", "SYN-PA-LANSD"),
    case("Lancaster School District: 2-Hour Delay", "PA", "SYN-PA-LANSD"),
    case("Lancaster School District - Early Dismissal at 12:30 PM", "PA", "SYN-PA-LANSD"),
    case("Lancaster School District -- Closed", "PA", "SYN-PA-LANSD"),
    case("Lancaster School District (E-Learning Day)", "PA", "SYN-PA-LANSD"),
    case("Lancaster School System", "PA", "SYN-PA-LANSD"),
    case("Lancaster Public Schools, all locations", "PA", "SYN-PA-LANSD"),
    case("All Schools", "PA", None, note="only noise"),
    case("(Closed)", "PA", None, note="only noise"),
    case("Schools", "PA", None, note="only a designator"),
    # St. Mary's: two counties side by side (the schools 30 km apart), other
    # states, affiliations. Each county's is as much the other's listing: the
    # county does not tell them apart, but a point near one does, the other lying
    # outside the listing's county. Read in the whole state, a point beside one
    # says nothing: the other lies within a market's reach of it.
    case("St. Mary's School", "PA", None, note="hard negative: two St. Mary's in the state"),
    case("St. Mary's School", "PA", None, counties=PA_A, note=JUST_PAST),
    case("St. Marys School", "PA", None, counties=PA_A, note=JUST_PAST),
    case("Saint Mary School", "PA", None, counties=PA_A, note=JUST_PAST),
    case("ST. MARY'S", "PA", None, counties=PA_A, note=PARISH_NEGATIVE + ": church or school"),
    case("ST. MARY'S", "PA", None, counties=PA_A, note=JUST_PAST, category="Schools"),
    case("St. Mary Catholic School", "PA", None, counties=PA_A, note=JUST_PAST),
    case("St. Mary's School - Remote Learning", "PA", None, counties=PA_A, note=JUST_PAST),
    case("St. Mary's School", "PA", None, counties=PA_B, note=JUST_PAST),
    case(
        "St. Mary's School",
        "PA",
        "SYN-PA-STMA",
        counties=PA_A,
        near=(40.03, -76.31),
        note="a namesake just past the county, and a point that says which",
    ),
    case(
        "St. Mary Catholic School",
        "PA",
        "SYN-PA-STMB",
        counties=PA_B,
        near=(40.26, -76.09),
        note="a parish's school, whose name says no church, nearest",
    ),
    case("St. Mary's School", "PA", None, counties=PA_C, note="hard negative: wrong county"),
    case(
        "St. Mary's School",
        "PA",
        None,
        near=(40.03, -76.31),
        note=SAME_NAME_NEGATIVE + ": the other 30 km off, within reach of the point",
    ),
    case(
        "St. Mary's School",
        "PA",
        None,
        near=(40.26, -76.09),
        note=SAME_NAME_NEGATIVE + ": the other 30 km off, within reach of the point",
    ),
    case(
        "St. Mary's School", "PA", None, near=(35.0, -100.0), note="both far: distance says nothing"
    ),
    case("St. Mary's School", "NY", "SYN-NY-STMA", counties="80302"),
    case("St. Mary's School", "NY", None, counties="80301", note="hard negative: wrong county"),
    case("St. Mary's School", "SC", "SYN-SC-STMA", counties="80201"),
    case("St. Mary's School", ("PA", "NY"), None, counties=(PA_A, "80302"), note="two states"),
    case("St. Paul School", "PA", "SYN-PA-STPAU", counties=PA_C),
    case("St. Paul Catholic School", "PA", "SYN-PA-STPAU", counties=PA_C),
    case("St. Paul Lutheran School", "PA", None, counties=PA_C, note="affiliation differs"),
    case("St. Paul Lutheran School", "NE", "SYN-NE-STPLU", counties="81801"),
    case("St. Paul Catholic School", "NE", None, counties="81801", note="affiliation differs"),
    case("St. Joseph Elementary", "PA", "SYN-PA-STJOE", counties=(PA_A, PA_B)),
    case("St. Joseph High School", "PA", "SYN-PA-STJOH", counties=(PA_A, PA_B)),
    case("St. Joseph's", "PA", None, counties=(PA_A, PA_B), note="elementary or high"),
    case("St. Joseph Middle School", "PA", None, counties=(PA_A, PA_B), note="no such level"),
    # Abbreviations both ways.
    case("Hamilton Elementary School", "PA", "SYN-PA-HAMEL", counties=PA_A),
    case("Hamilton Elem.", "PA", "SYN-PA-HAMEL", counties=PA_A),
    case("HAMILTON ES", "PA", "SYN-PA-HAMEL", counties=PA_A),
    case("Main St. Elementary", "PA", "SYN-PA-MAINST", counties=PA_A, note="St. is Street"),
    case("Main Street Elementary School", "PA", "SYN-PA-MAINST", counties=PA_A),
    case("Lincoln Middle School", "PA", "SYN-PA-LINMS", counties=PA_A),
    case("Lincoln Middle", "PA", "SYN-PA-LINMS", counties=PA_A),
    case("Lincoln Elementary", "PA", None, counties=PA_A, note="no such level"),
    case("Millbrook Area School District", "PA", "SYN-PA-MILSD"),
    case("Millbrook Area Schools", "PA", "SYN-PA-MILSD"),
    case("Millbrook School District", "PA", "SYN-PA-MILSD", note="Area left out"),
    case("Millbrook Area High School", "PA", "SYN-PA-MILHS", counties=PA_C),
    case("Millbrook High School", "PA", "SYN-PA-MILHS", counties=PA_C, note="Area left out"),
    case("Elkmere Area Schools", "MN", "SYN-MN-ELKM", note="Area, which NCES leaves out"),
    case("Elkmere Area School District 728", "MN", "SYN-MN-ELKM", note="Area and its number"),
    case("Brookmere Area Schools", "PA", "SYN-PA-BRKA", note="the one that says Area"),
    case("Brookmere SD", "PA", "SYN-PA-BRKS"),
    case("Brookmere Schools", "PA", "SYN-PA-BRKS", note="the one that does not say Area"),
    case("Mt. Pleasant Area School District", "PA", "SYN-PA-MTPSD", note="Mt. is Mount"),
    case("Mount Pleasant Schools", "PA", "SYN-PA-MTPSD"),
    case("Oak Ridge Elementary", "PA", "SYN-PA-OAKRI", counties=PA_C, note="Oak Ridge/Oakridge"),
    case("Oakridge El. School", "PA", "SYN-PA-OAKRI", counties=PA_C),
    case("Ramsay Elementary", "PA", "SYN-PA-RAMEL", counties=PA_C),
    case("Arts & Sciences Academy Charter School", "PA", "SYN-PA-ARTS", note="& is and"),
    case("Arts and Sciences Academy CS", "PA", "SYN-PA-ARTS"),
    # New York.
    case("Wendover UFSD", "NY", "SYN-NY-WENUF"),
    case("Wendover U.F.S.D.", "NY", "SYN-NY-WENUF"),
    case("Wendover Union Free Schools", "NY", "SYN-NY-WENUF"),
    case("Wendover Schools", "NY", "SYN-NY-WENUF"),
    case("Wendover High School", "NY", "SYN-NY-WENHS", counties="80301", note="Senior High"),
    case("Wendover Sr. High", "NY", "SYN-NY-WENHS", counties="80301"),
    case("Riverhollow CSD", "NY", "SYN-NY-RIVCS"),
    case("Riverhollow Central Schools", "NY", "SYN-NY-RIVCS"),
    case("Genesee City Schools", "NY", "SYN-NY-GENCI"),
    case("Genesee City School District", "NY", "SYN-NY-GENCI"),
    # Missouri: R-II style numbers.
    case("Wexford R-IV", "MO", "SYN-MO-WEX"),
    case("Wexford R-4 School District", "MO", "SYN-MO-WEX"),
    case("Wexford R4 Schools", "MO", "SYN-MO-WEX"),
    case("Wexford School District", "MO", "SYN-MO-WEX", note="number left out"),
    case("Wexford", "MO", "SYN-MO-WEX", note="bare name"),
    case("Wexford R-IV School District -- Closed", "MO", "SYN-MO-WEX"),
    case("Wexford R-5", "MO", None, note="hard negative: other number"),
    case("Wexford Middle School", "MO", "SYN-MO-WEXMS", counties="80401"),
    case("Wexford Middle - All Schools", "MO", "SYN-MO-WEXMS", counties="80401"),
    case("Wexford South Middle", "MO", "SYN-MO-WEXSM", counties="80401"),
    case("Heritage Primary School", "MO", "SYN-MO-HERPR", counties="80401"),
    case("Oakhurst R-2", "MO", "SYN-MO-OAK2"),
    case("Oakhurst R-II School District", "MO", "SYN-MO-OAK2"),
    case("Oakhurst R-3", "MO", "SYN-MO-OAK3"),
    case("Oakhurst R-III Schools", "MO", "SYN-MO-OAK3"),
    case("Oakhurst R-4", "MO", None, note="hard negative: no such number"),
    case("Oakhurst Schools", "MO", None, note="hard negative: two numbers"),
    case("Oakhurst Schools", "MO", None, counties="80402", note=JUST_PAST + ": R-III, 14 km away"),
    case("Oakhurst Schools", "MO", "SYN-MO-OAK2", counties="80402", near=(37.5, -92.0)),
    case("Saint Charlton R-6 School District", "MO", "SYN-MO-STCH", note="St. is Saint"),
    case("St. Charlton High School", "MO", "SYN-MO-STCHS", counties="80401"),
    case("Mt. Vernal R-5 Schools", "MO", "SYN-MO-MTV"),
    case("Mount Vernal R-V", "MO", "SYN-MO-MTV"),
    # Texas.
    case("Brazos Bend Independent School District", "TX", "SYN-TX-BRAZ"),
    case("Brazos Bend ISD", "TX", "SYN-TX-BRAZ"),
    case("Brazos Bend I.S.D.", "TX", "SYN-TX-BRAZ"),
    case("Brazos Bend Schools", "TX", "SYN-TX-BRAZ"),
    case("Brazos Bend High School", "TX", "SYN-TX-BRAHS", counties="80501", note="H S"),
    case("Brazos Bend HS", "TX", "SYN-TX-BRAHS", counties="80501"),
    case("Myatt Elementary", "TX", "SYN-TX-MYATT", counties="80501", note="EL"),
    case("Riverside Junior High", "TX", "SYN-TX-RIVJH", counties="80501", note="J H"),
    case("Riverside Jr. High School", "TX", "SYN-TX-RIVJH", counties="80501"),
    case("Riverside High School", "TX", None, counties="80501", note="junior high is not high"),
    case("El Campo ISD", "TX", "SYN-TX-ELCAM", note="El is not Elementary here"),
    case("El Campo High School", "TX", "SYN-TX-ELCHS", counties="80502"),
    case("Northside Elementary", "TX", "SYN-TX-NSIDE", counties="80502"),
    case("Cypress Hollow Consolidated ISD", "TX", "SYN-TX-CYPH"),
    case("Cypress Hollow CISD", "TX", "SYN-TX-CYPH"),
    # Illinois.
    case("CUSD 300", "IL", "SYN-IL-CU300"),
    case("Community Unit School District #300", "IL", "SYN-IL-CU300"),
    case("C.U.S.D. No. 300", "IL", "SYN-IL-CU300"),
    case("CUSD 301", "IL", None, note="hard negative: other number"),
    case("Palmer CCSD 15", "IL", "SYN-IL-PAL15"),
    case("Palmer #15", "IL", "SYN-IL-PAL15"),
    case("Palmer School District 16", "IL", "SYN-IL-PAL16"),
    case("Palmer SD 17", "IL", None, note="hard negative: no such number"),
    case("Palmer Schools", "IL", None, note="hard negative: two numbers"),
    case("Lakeshore Public Schools", "IL", "SYN-IL-LAKE", note="number left out"),
    # California.
    case("Los Robles Unified School District", "CA", "SYN-CA-LOSR"),
    case("Los Robles USD", "CA", "SYN-CA-LOSR"),
    case("Los Robles Unified", "CA", "SYN-CA-LOSR"),
    case("LRUSD", "CA", None, note="an acronym is left to aliases"),
    case("Los Robles High School", "CA", "SYN-CA-LRHS", counties="80701"),
    case("Mesa Verde UHSD", "CA", "SYN-CA-MESA"),
    case("Mesa Verde Union High School District", "CA", "SYN-CA-MESA"),
    case("Robla Elementary School District", "CA", "SYN-CA-ROBLA"),
    case("Robla Elementary School", "CA", "SYN-CA-ROBES", counties="80703"),
    case("Robla Elementary", "CA", "SYN-CA-ROBLA", note="the district's own name"),
    case("Helmsley Elementary", "MT", "SYN-MT-HELEL", note="an elementary district"),
    case("Helmsley Elem. School District", "MT", "SYN-MT-HELEL"),
    case("Helmsley School", "MT", "SYN-MT-HELSC", counties="81901"),
    case("Helmsley High School", "MT", None, note="no such level"),
    case("Tarkio County High School", "MT", "SYN-MT-TARHS", note="a high school district"),
    case("Academia Senora del Valle", "CA", "SYN-CA-ACAD", note="diacritics"),
    case("ACADEMIA SEÑORA DEL VALLE", "CA", "SYN-CA-ACAD", note="diacritics"),
    # Alabama: city against county, and a namesake in each.
    case("Brambleton City Schools", "AL", "SYN-AL-BRAMC"),
    case("Brambleton City School System", "AL", "SYN-AL-BRAMC"),
    case("Brambleton Schools", "AL", "SYN-AL-BRAMC", note="a town's name, not the county's"),
    case("Brambleton County Schools", "AL", "SYN-AL-BRACO"),
    case("Brambleton Co. Schools", "AL", "SYN-AL-BRACO"),
    case("Brambleton County Board of Education", "AL", "SYN-AL-BRACO"),
    case("Brambleton County BOE", "AL", "SYN-AL-BRACO"),
    case("Bramleton City Schools", "AL", "SYN-AL-BRAMC", note="typo"),
    case("Brambleton City Schools", "GA", None, note="hard negative: other state"),
    case("Brambleton High School", "AL", "SYN-AL-BRAHS", counties="80801"),
    case("Brambleton County High School", "AL", "SYN-AL-BCOHS", counties="80801"),
    case("Lincoln Elementary", "AL", None, counties="80801", note="one in each district"),
    case("Lincoln Elementary - Brambleton", "AL", "SYN-AL-LINC1", note="city beside the name"),
    case("Lincoln Elementary (Oxbow)", "AL", "SYN-AL-LINC2", note="city beside the name"),
    case("Brambleton County Schools: Lincoln Elementary", "AL", "SYN-AL-LINC2"),
    case("Brambleton City Schools - Lincoln Elementary", "AL", "SYN-AL-LINC1"),
    case("Lincoln Elementary - Nowhere", "AL", None, note="unknown context"),
    case("Pleasant Grove Elementary", "AL", "SYN-AL-PLGRV", counties="80801"),
    case("Diocese of Brambleton Schools", "AL", None, note="not in the directory"),
    case("Brambleton Community College", "AL", None, note="not a K-12 school"),
    case("Brambleton County Government Offices", "AL", None, note="not a school"),
    case("Brambleton Public Library", "AL", None, note="not a school"),
    # Ohio.
    case("Kettleby City Schools", "OH", "SYN-OH-KETC"),
    case("Kettleby Local Schools", "OH", "SYN-OH-KETL"),
    case("Kettleby Local School District", "OH", "SYN-OH-KETL"),
    case("Kettleby Schools", "OH", None, note="hard negative: city or local"),
    case("Woodbine Local Schools", "OH", "SYN-OH-WOOD"),
    case("Woodbine Schools", "OH", "SYN-OH-WOOD"),
    # Virginia and Maryland.
    case("Harwick County Public Schools", "VA", "SYN-VA-HARW"),
    case("Harwick County Public Schools", "MD", "SYN-MD-HARW"),
    case("Harwick County Public Schools", ("MD", "VA"), None, note="same name, two states"),
    case("Harwick County Schools", ("MD", "VA"), "SYN-MD-HARW", near=(39.2, -76.7)),
    case("Harwick County Schools", ("MD", "VA"), "SYN-VA-HARW", near=(38.1, -78.4)),
    case(
        "Harwick County Schools", ("MD", "VA"), None, near=(38.65, -77.55), note="halfway between"
    ),
    case("Fairbourne County Public Schools", "VA", "SYN-VA-FAIR", note="Co Pblc Schs"),
    case("Fairbourne Co. Public Schools", "VA", "SYN-VA-FAIR"),
    case("FCPS", "VA", None, note="an acronym is left to aliases"),
    # Louisiana, New Jersey, Wisconsin, Indiana, Maine, Colorado.
    case("Bayou Teche Parish Schools", "LA", "SYN-LA-TECHE"),
    case("Bayou Teche Parish School Board", "LA", "SYN-LA-TECHE"),
    case("Bayou Teche Schools", "LA", None, note="parish left out"),
    case("Hamilton Township Schools", "NJ", "SYN-NJ-HAMT"),
    case("Hamilton Twp. School District", "NJ", "SYN-NJ-HAMT"),
    case(
        "Hamilton Schools",
        "NJ",
        None,
        note=TOWNSHIP_NEGATIVE + ": two counties' districts, one's Township left out",
    ),
    case("Hamilton Schools", "NJ", "SYN-NJ-HAMB", near=(40.9, -74.2), note=TOWNSHIP),
    case("Hamilton Schools", "NJ", "SYN-NJ-HAMT", near=(40.2, -74.7), note=TOWNSHIP),
    case("Waunona Community Schools", "WI", "SYN-WI-WAUN"),
    case("Waunona CSD", "WI", "SYN-WI-WAUN"),
    case("Waunona School District", "WI", "SYN-WI-WAUN"),
    case("Kessler Hart Schools", "IN", "SYN-IN-KESS"),
    case("Kessler-Hart School Corp.", "IN", "SYN-IN-KESS"),
    case("M.S.A.D. #72", "ME", "SYN-ME-MSAD72"),
    case("SAD 72", "ME", "SYN-ME-MSAD72"),
    case("MSAD 71", "ME", None, note="hard negative: other number"),
    case("Platte Canyon School District 28J", "CO", "SYN-CO-PLAT"),
    case("Platte-Canyon 28-J", "CO", "SYN-CO-PLAT"),
    # Nebraska: levels.
    case("Lincoln Elem", "NE", "SYN-NE-LINES", counties="81801"),
    case("Lincoln MS", "NE", "SYN-NE-LINMS", counties="81801"),
    case("Lincoln Junior High", "NE", None, counties="81801", note="no such level"),
    case("Lincoln School", "NE", None, counties="81801", note="elementary or middle"),
    case("Washington Jr. High", "NE", "SYN-NE-WASJH", counties="81801"),
    case("Washington HS", "NE", "SYN-NE-WASHS", counties="81801"),
    case("Washington Senior High", "NE", "SYN-NE-WASHS", counties="81801"),
    case("Washington Middle School", "NE", None, counties="81801", note="no such level"),
    case("Martin Luther King Jr. High School", "NE", "SYN-NE-MLKHS", counties="81801"),
    case("MLK High School", "NE", "SYN-NE-MLKHS", counties="81801", note="Jr is a name suffix"),
    case("Cornhusk Public Schools", "NE", "SYN-NE-CORN"),
    case("Cornhusk Schools - All Schools", "NE", "SYN-NE-CORN"),
    case("College Park Elementary", "NE", "SYN-NE-COLPK", counties="81801", note="a place"),
    case("Hans Christian Andersen Elementary", "NE", "SYN-NE-HCAND", counties="81801"),
    # A church or faith named in the listing is never the town's public district.
    case("Lancaster Catholic Schools", "PA", None, note="hard negative: affiliation"),
    case("Lancaster Christian Schools", "PA", None, note="hard negative: affiliation"),
    case("Lancaster Lutheran Schools", "PA", None, note="hard negative: affiliation"),
    case("Lancaster Christian School", "PA", None, note="hard negative: affiliation"),
    case("Lancaster Catholic", "PA", None, note="hard negative: affiliation"),
    case("Catholic Schools of Lancaster", "PA", None, note="hard negative: affiliation"),
    case("Lancaster Mennonite School", "PA", None, note="hard negative: affiliation"),
    case("Millbrook Christian Schools - All Schools", "PA", None, note="hard negative"),
    case("Cornhusk Catholic Schools", "NE", None, note="hard negative: affiliation"),
    case("Cornhusk Lutheran Schools", "NE", None, note="hard negative: affiliation"),
    case("Cornhusk Catholic Schools - All Schools", "NE", None, note="hard negative"),
    case("Wexford Catholic Schools", "MO", None, note="hard negative: affiliation"),
    case("Oakhurst Baptist Schools", "MO", None, note="hard negative: affiliation"),
    case("Brazos Bend Christian Schools", "TX", None, note="hard negative: affiliation"),
    case("Wendover Catholic Schools", "NY", None, note="hard negative: affiliation"),
    case("Genesee Christian Schools", "NY", None, note="hard negative: affiliation"),
    case("Riverhollow Jewish Day School", "NY", None, note="hard negative: affiliation"),
    case("Kettleby Christian Schools", "OH", None, note="hard negative: affiliation"),
    case("Brambleton Catholic Schools", "AL", None, note="hard negative: affiliation"),
    case("Brambleton Christian Schools", "AL", None, note="hard negative: affiliation"),
    case("Archdiocese of Brambleton Schools", "AL", None, note="hard negative: affiliation"),
    case("Los Robles Christian Schools", "CA", None, note="hard negative: affiliation"),
    case("Harwick County Catholic Schools", "VA", None, note="hard negative: affiliation"),
    case("Waunona Lutheran Schools", "WI", None, note="hard negative: affiliation"),
    case("Palmer Islamic School", "IL", None, note="hard negative: affiliation"),
    case("Wexford Montessori School", "MO", None, note="hard negative: affiliation"),
    # Tidewater: the public district beside private schools named for the city.
    case("Tidewater Public Schools", "WA", "SYN-WA-TIDE"),
    case("Tidewater Schools", "WA", "SYN-WA-TIDE"),
    case("Tidewater School District", "WA", "SYN-WA-TIDE"),
    case("Tidewater Christian Schools", "WA", "SYN-WA-TIDCS", note="the private school's name"),
    case("Tidewater Christian Schools - Closed", "WA", "SYN-WA-TIDCS"),
    case("Tidewater Lutheran High School", "WA", "SYN-WA-TIDLU", counties="82001"),
    case("Tidewater Lutheran", "WA", None, note=PARISH_NEGATIVE + ": a church's faith alone"),
    case("Tidewater Lutheran", "WA", "SYN-WA-TIDLU", note=PARISH, category="Private Schools"),
    case("Tidewater Adventist Christian School", "WA", "SYN-WA-TIDAD"),
    case("Montessori Academy of Tidewater", "WA", "SYN-WA-TIDMO"),
    case("Tidewater Catholic Schools", "WA", None, note="hard negative: affiliation"),
    case("Tidewater Catholic", "WA", None, note="hard negative: affiliation"),
    case("Tidewater Lutheran Schools", "WA", None, note="a group, not its high school"),
    case("Tidewater Adventist School", "WA", None, note="hard negative: record says more"),
    case("Tidewater Jewish Day School", "WA", None, note="hard negative: affiliation"),
    case("Tidewater Islamic School", "WA", None, note="hard negative: affiliation"),
    case("Tidewater Christian High School", "WA", None, note="hard negative: affiliation"),
    # Colleges and universities are not K-12 schools, whatever shares their words.
    case("Brackenmoor College", "MA", None, note="hard negative: a college"),
    case("Brackenmoor University", "MA", None, note="hard negative: a university"),
    case("University of Brackenmoor", "MA", None, note="hard negative: a university"),
    case("Brackenmoor Community College", "MA", None, note="hard negative: a college"),
    case("Brackenmoor State University", "MA", None, note="hard negative: a university"),
    case("Brackenmoor College - Closed", "MA", None, note="hard negative: a college"),
    case("BRACKENMOOR COLLEGE (All Campuses)", "MA", None, note="hard negative: a college"),
    case("Brackenmoor Univ.", "MA", None, note="hard negative: a university"),
    case("Brackenmoor Seminary", "MA", None, note="hard negative: a seminary"),
    case("Brackenmoor College", "MA", None, counties="82101", note="hard negative: a college"),
    case("Brackenmoor College High School", "MA", "SYN-MA-BRCHS"),
    case("Brackenmoor College High", "MA", "SYN-MA-BRCHS"),
    case("Brackenmoor College HS", "MA", "SYN-MA-BRCHS", counties="82101"),
    case("Brackenmoor University Academy", "MA", "SYN-MA-BRUA"),
    case("Brackenmoor Early College", "MA", "SYN-MA-BREC", note="a K-12 program"),
    case("Brackenmoor Public Schools", "MA", "SYN-MA-BRAK"),
    case("Brackenmoor Latin School", "MA", "SYN-MA-BRLAT"),
    case("University Heights City Schools", "OH", "SYN-OH-UNIVH", note="a place"),
    case("University Heights Schools", "OH", "SYN-OH-UNIVH", note="a place"),
    case("College Mesa ISD", "TX", "SYN-TX-COLM", note="a place"),
    case("College Mesa Schools", "TX", "SYN-TX-COLM", note="a place"),
    # Faith words that are part of a place or a saint's name.
    case("Christian County Schools", "KY", "SYN-KY-CHRCO", note="a county"),
    case("Christian County Public Schools", "KY", "SYN-KY-CHRCO", note="a county"),
    case("Christian Co. Schools", "KY", "SYN-KY-CHRCO", note="a county"),
    case("Christian County High School", "KY", "SYN-KY-CHRHS", counties="82301"),
    case("Port Christian School District", "MS", "SYN-MS-PORTC", note="a town"),
    case("Port Christian Schools", "MS", "SYN-MS-PORTC", note="a town"),
    case("Port Christian High School", "MS", "SYN-MS-PORHS", counties="82201"),
    case("St. John the Baptist Parish Schools", "LA", "SYN-LA-SJBP", note="a parish"),
    case("St. John the Baptist Parish School Board", "LA", "SYN-LA-SJBP"),
    case("St. John the Baptist School", "LA", "SYN-LA-SJBS", counties="81202", note="a saint"),
    case(
        "St. John the Baptist Catholic School",
        "LA",
        "SYN-LA-SJBS",
        counties="81202",
        note="a parish's school, whose name says no church",
    ),
    # A Louisiana parish's district, named bare, is no church; a Mass is.
    case("St. John the Baptist Parish", "LA", "SYN-LA-SJBP", note="a Louisiana parish"),
    case("Bayou Teche Parish", "LA", "SYN-LA-TECHE", note="a Louisiana parish"),
    case(
        "St. John the Baptist Parish - No Mass",
        "LA",
        None,
        counties="81202",
        note=PARISH_NEGATIVE + ": a church's Mass",
    ),
    # Names that differ only in designators: in one town and county the legal
    # form a listing says tells them apart; in two places they stay in the queue
    # for an alias.
    case(
        "Marrowgate Public Schools Community District",
        "MI",
        "SYN-MI-MARPS",
        note=LEGAL_FORM + ": the district's own name",
    ),
    case(
        "Marrowgate Public Schools", "MI", "SYN-MI-MARPS", note=LEGAL_FORM + ": only it says Public"
    ),
    case(
        "Marrowgate Public Schools",
        "MI",
        "SYN-MI-MARPS",
        counties="82401",
        note=LEGAL_FORM + ": only it says Public",
    ),
    case(
        "Marrowgate Community Schools",
        "MI",
        "SYN-MI-MARCS",
        note=LEGAL_FORM + ": its legal form is the listing's, the other's says more",
    ),
    case("Marrowgate Schools", "MI", None, note=DESIGNATORS_ONLY),
    case("MARROWGATE SCHOOL DISTRICT", "MI", None, note=DESIGNATORS_ONLY),
    case("Marrowgate Central High School", "MI", "SYN-MI-MARHS", counties="82401"),
    case("Marrowgate Central HS", "MI", "SYN-MI-MARHS"),
    case("Quillmoor Township School District", "NJ", None, note=DESIGNATORS_ONLY),
    case("Quillmoor Township Public School District", "NJ", None, note=DESIGNATORS_ONLY),
    case("Quillmoor Township Public Schools", "NJ", None, note=DESIGNATORS_ONLY),
    case("Quillmoor Twp. Schools", "NJ", "SYN-NJ-QUIB", counties="82502", note="county settles it"),
    case("Quillmoor Township Schools", "NJ", "SYN-NJ-QUIA", counties="82501"),
    case("Saltgrass ISD", "TX", "SYN-TX-SALT", note="ISD names the one whose name says it"),
    case("Saltgrass Public Schools", "TX", None, note=DESIGNATORS_ONLY),
    case("Saltgrass Schools", "TX", None, note=DESIGNATORS_ONLY),
    case("Saltgrass ISD", "TX", "SYN-TX-SALT", counties="80506", note="county settles it"),
    case("Saltgrass Public Schools", "TX", "SYN-TX-SALTC", counties="80505"),
    case(
        "Harrowby Public Schools",
        "CO",
        "SYN-CO-HAR1",
        note=LEGAL_FORM + ": a school system, not a program's district of one school",
    ),
    case("Harrowby Schools", "CO", "SYN-CO-HAR1", note=LEGAL_FORM + ": a school system"),
    case("Harrowby 1", "CO", None, note=DESIGNATORS_ONLY),
    case("Harrowby Online Program", "CO", "SYN-CO-HARPS"),
    case(
        "Kelburn Union Schools",
        "CA",
        "SYN-CA-KELE",
        also=("SYN-CA-KELH",),
        note=SYSTEM + ": a town's two districts of one name are its school system",
    ),
    case(
        "Kelburn Union School District",
        "CA",
        "SYN-CA-KELE",
        also=("SYN-CA-KELH",),
        note=SYSTEM + ": both say Union",
    ),
    case("Kelburn Union Elementary School District", "CA", "SYN-CA-KELE"),
    case("Kelburn Union High School District", "CA", "SYN-CA-KELH"),
    case("Kelburn Union High School", "CA", "SYN-CA-KELHS", counties="82403"),
    case("Capwell Public Charter Schools", "DC", None, note=DESIGNATORS_ONLY + ": City or Village"),
    case("Capwell City PCS", "DC", "SYN-DC-CAPC", note=OWN_NAME),
    case("Capwell City Public Charter School", "DC", "SYN-DC-CAPC", note=OWN_NAME),
    case("Capwell City PCS - Middle School", "DC", "SYN-DC-CAPCM"),
    case("Capwell Village PCS", "DC", "SYN-DC-CAPVS", note="a district of one school: the school"),
    case(
        "Avonmere Charter Schools", "PA", "SYN-PA-AVMCS", note="the charter school's own district"
    ),
    case("Avonmere Charter School", "PA", "SYN-PA-AVMCSS"),
    case("Avonmere School District", "PA", "SYN-PA-AVMSD"),
    case("Avonmere Area High School", "PA", "SYN-PA-AVMA", counties="82405"),
    # More faiths beside a district's town.
    case("Marrowgate Catholic Schools", "MI", None, note="hard negative: affiliation"),
    case("Quillmoor Christian Schools", "NJ", None, note="hard negative: affiliation"),
    case("Saltgrass Lutheran Schools", "TX", None, note="hard negative: affiliation"),
    case("Hamilton Catholic Schools", "NJ", None, note="hard negative: affiliation"),
    case("Brackenmoor Catholic Schools", "MA", None, note="hard negative: affiliation"),
    case("Brackenmoor Christian Schools", "MA", None, note="hard negative: affiliation"),
    # A district named for its city without the city's "City".
    case("Brinewater City School District", "UT", "SYN-UT-BRINE", note="City is the city's"),
    case("Brinewater City Schools", "UT", "SYN-UT-BRINE"),
    case("Brinewater School District", "UT", "SYN-UT-BRINE"),
    case("Brinewater City High School", "UT", "SYN-UT-BRIHS", counties="82601"),
    case(
        "Brinewater Valley City Schools",
        "UT",
        "SYN-UT-BRVAL",
        note="a City the NCES name leaves out, and no other district of the name",
    ),
    case("Brinewater City School District", "NV", None, note="hard negative: other state"),
    # A town named "... College" is not a college.
    case("Ridgemont College", "PA", "SYN-PA-RIDCO", note="a town"),
    case("Ridgemont College - Closed", "PA", "SYN-PA-RIDCO", note="a town"),
    case("Ridgemont College Area School District", "PA", "SYN-PA-RIDCO"),
    case("Ridgemont College Area High School", "PA", "SYN-PA-RIDHS", counties=PA_C),
    case("Ridgemont University", "PA", None, note="hard negative: a university"),
    case("Ridgemont Community College", "PA", None, note="hard negative: a college"),
    # A charter district and the one school it runs do not compete.
    case("Harborview Montessori Charter School", "PA", "SYN-PA-HARM", note="its own district"),
    case("Harborview Montessori CS", "PA", "SYN-PA-HARM"),
    case("Harborview Montesori Charter School", "PA", "SYN-PA-HARM", note="typo"),
    # A career and technology center is a district, and each campus a school.
    case("Ravensburg County Career & Technology Center", "PA", "SYN-PA-RAVCT"),
    case("RAVENSBURG COUNTY CAREER AND TECHNOLOGY CENTER (Closed)", "PA", "SYN-PA-RAVCT"),
    case("Ravensburg County Career and Technology Center - Millgate", "PA", "SYN-PA-RAVMG"),
    case("Ravensburg Career & Technology Center", "PA", None, note="hard negative: no county"),
    # A town's government, community places and churches, beside a district
    # named for the town as a city, a village or a town, are not schools.
    case("City of Kettleby", "OH", None, note=CIVIC),
    case("City Of Kettleby (Closed)", "OH", None, note=CIVIC),
    case("CITY OF KETTLEBY - Offices Closed", "OH", None, note=CIVIC),
    case("Kettleby City Hall", "OH", None, note=CIVIC),
    case("Kettleby City Council", "OH", None, note=CIVIC),
    case("Kettleby Senior Center", "OH", None, note=CIVIC),
    case("Kettleby Community Center - Closed", "OH", None, note=CIVIC),
    case("Kettleby Public Library", "OH", None, note=CIVIC),
    case("City of Brambleton", "AL", None, note=CIVIC),
    case("Brambleton City Hall", "AL", None, note=CIVIC),
    case("First Baptist Church of Brambleton", "AL", None, note=CIVIC),
    case("Brambleton Hospital", "AL", None, note=CIVIC),
    case("Brambleton Police Dept.", "AL", None, note=CIVIC),
    case("City of Genesee", "NY", None, note=CIVIC),
    case("Genesee Water Department", "NY", None, note=CIVIC),
    case("Genesee YMCA", "NY", None, note=CIVIC),
    case("City of University Heights", "OH", None, note=CIVIC),
    case("Village of Farrowdale", "OH", None, note=CIVIC),
    case("Farrowdale Village Hall", "OH", None, note=CIVIC),
    case("Farrowdale Sr. Citizens Center", "OH", None, note=CIVIC),
    case("Farrowdale United Methodist Church", "OH", None, note=CIVIC),
    case("Village of Quenby", "OH", None, note=CIVIC),
    case("Quenby Parks & Recreation", "OH", None, note=CIVIC),
    case("Town of Harlowe", "VT", None, note=CIVIC),
    case("Harlowe Town Hall", "VT", None, note=CIVIC),
    case("Harlowe Town Offices", "VT", None, note=CIVIC),
    case("Harlowe Meals on Wheels", "VT", None, note=CIVIC),
    case("Town of Pellston", "VT", None, note=CIVIC),
    case("Pellston Health Center", "VT", None, note=CIVIC),
    case("City of Marlowe", "LA", None, note=CIVIC),
    case("Millers Church City Hall", "VA", None, note=CIVIC),
    case("Millers Church Senior Center", "VA", None, note=CIVIC),
    case("City of Sabrel Pass", "AL", None, note=CIVIC),
    case("City Of Sabrel Pass - City Hall Closed", "AL", None, note=CIVIC),
    case("Sabrel Pass Senior Center", "AL", None, note=CIVIC),
    case("Sabrel Pass Sr. Center (Closed)", "AL", None, note=CIVIC),
    case("Sabrel Pass Senior Citizens Center", "AL", None, note=CIVIC),
    case("Sabrel Pass Community Center", "AL", None, note=CIVIC),
    case("Sabrel Pass Volunteer Fire Department", "AL", None, note=CIVIC),
    case("Sabrel Pass Housing Authority", "AL", None, note=CIVIC),
    case("Sabrel Pass Church of Christ", "AL", None, note=CIVIC),
    case("Sabrel Pass Senior Center", "AL", None, counties="80802", note=CIVIC),
    case("Village of Wexcombe Falls", "OH", None, note=CIVIC),
    case("VILLAGE OF WEXCOMBE FALLS (Closed)", "OH", None, note=CIVIC),
    case("Wexcombe Falls Senior Center", "OH", None, note=CIVIC),
    case("Wexcombe Falls Village Offices", "OH", None, note=CIVIC),
    case("Wexcombe Falls Parks and Recreation", "OH", None, note=CIVIC),
    case("Wexcombe Falls Municipal Building", "OH", None, note=CIVIC),
    case("Town of North Tallis", "VT", None, note=CIVIC),
    case("North Tallis Town Clerk", "VT", None, note=CIVIC),
    case("North Tallis Senior Center", "VT", None, note=CIVIC),
    case("North Tallis Hospital", "VT", None, note=CIVIC),
    case("North Tallis Water Department", "VT", None, note=CIVIC),
    case("Town of Orleby", "NY", None, note=CIVIC),
    case("Town of Orleby Offices", "NY", None, note=CIVIC),
    case("Kettleby 4-H", "OH", None, note=CIVIC),
    case("Kettleby City 4-H Club", "OH", None, note=CIVIC),
    case("Brambleton County 4-H", "AL", None, note=CIVIC),
    case("Brambleton County Parks", "AL", None, note=CIVIC),
    case("Brambleton City Parks and Recreation", "AL", None, note=CIVIC),
    case("Brambleton County Board of Commissioners", "AL", None, note=CIVIC),
    case("Brambleton County Health Dept.", "AL", None, note=CIVIC),
    case("Brambleton County Extension Office", "AL", None, note=CIVIC),
    case("Brambleton County Fair", "AL", None, note=CIVIC),
    case("Brambleton County Day School", "AL", None, note="hard negative: not its high school"),
    # The districts beside them, as closings lists name them.
    case("Farrowdale Exempted Village Schools", "OH", "SYN-OH-FARR"),
    case("Farrowdale Exempted Village School District", "OH", "SYN-OH-FARR"),
    case("Farrowdale EVSD", "OH", "SYN-OH-FARR"),
    case("Farrowdale Schools", "OH", "SYN-OH-FARR", note="village left out"),
    case("Farrowdale High School", "OH", "SYN-OH-FARHS", counties="80905"),
    case("Quenby Exempted Village Schools", "OH", "SYN-OH-QUEN"),
    case("Quenby Local Schools", "OH", None, note="hard negative: a local, not a village"),
    case("Harlowe Town School District", "VT", "SYN-VT-HARL"),
    case("Harlowe Schools", "VT", "SYN-VT-HARL", note="town left out"),
    case("Harlowe Elementary", "VT", "SYN-VT-HARLE", counties="82701"),
    case("Pellston Town Schools", "VT", "SYN-VT-PELL"),
    case("City of Marlowe Schools", "LA", "SYN-LA-MARL", note="the district's own name"),
    case("City of Marlowe School District", "LA", "SYN-LA-MARL"),
    case("Marlowe City Schools", "LA", "SYN-LA-MARL"),
    case("Millers Church", "VA", "SYN-VA-MILCH", note="a town's name, not a church"),
    case("Millers Church City", "VA", "SYN-VA-MILCH", note="a town's name, not a church"),
    case("Millers Church City Public Schools", "VA", "SYN-VA-MILCH"),
    case("Kettleby City", "OH", "SYN-OH-KETC", note="the district, not the city"),
    case("Sabrel Pass City Schools", "AL", "SYN-AL-SABR"),
    case("Sabrel Pass", "AL", "SYN-AL-SABR", note="a bare town name is its district"),
    case("Sabrel Pass School", "AL", "SYN-AL-SABRS", counties="80802"),
    case("Sabrel Pass School (Closed)", "AL", "SYN-AL-SABRS"),
    case("Ada Church Pellow", "AL", "SYN-AL-ADACP", note="Church in a person's name"),
    case("Ada Church Pellow School", "AL", "SYN-AL-ADACP", counties="80802"),
    case("Wexcombe Falls Exempted Village Schools", "OH", "SYN-OH-WEXF"),
    case("Wexcombe Falls EVSD", "OH", "SYN-OH-WEXF"),
    case("Wexcombe Falls Schools", "OH", "SYN-OH-WEXF", note="village left out"),
    case("Wexcombe Falls High School", "OH", "SYN-OH-WEXHS", counties="80907"),
    case("North Tallis Town School District", "VT", "SYN-VT-NTAL"),
    case("North Tallis Schools", "VT", "SYN-VT-NTAL", note="town left out"),
    case("North Tallis Elementary", "VT", "SYN-VT-NTALE", counties="82703"),
    case("Town of Orleby UFSD", "NY", "SYN-NY-ORLE", note="the district's own name"),
    case("Town of Orleby Schools", "NY", "SYN-NY-ORLE", note="the district's own name"),
    # "Valley School of" a town is one private school, never the town's district.
    case("Valley School of Tamberlin", "PA", None, note="hard negative: one school"),
    case("Tamberlin Valley School District", "PA", "SYN-PA-TAMB"),
    case("Tamberlin Valley Schools", "PA", "SYN-PA-TAMB"),
    # "Early Learning Center" is prekindergarten, not the town's learning center.
    case("Tamberlin Early Learning Center", "PA", None, note="hard negative: prekindergarten"),
    case("Tamberlin Learning Center", "PA", "SYN-PA-TAMLC"),
    case("Holloway Early Childhood Center", "PA", "SYN-PA-HOLEC"),
    case("HOLLOWAY EARLY CHILDHOOD CTR. (Closed)", "PA", "SYN-PA-HOLEC"),
    case("Holloway Elementary", "PA", None, note="hard negative: prekindergarten, not elementary"),
    # A district code before the name: the code names the district, and what
    # follows names the district's town or area, or one of its schools.
    case("RSU 84", "ME", "SYN-ME-RSU84", note=CODE),
    case("R.S.U. #84", "ME", "SYN-ME-RSU84", note=CODE),
    case("Regional School Unit 84", "ME", "SYN-ME-RSU84", note=CODE),
    case("RSU 84 - Seacliff", "ME", "SYN-ME-RSU84", note=CODE + ": its schools' area"),
    case("RSU 84 Seacliff Schools", "ME", "SYN-ME-RSU84", note=CODE + ": its schools' area"),
    case("RSU 84 - Kettering, Marram Point", "ME", "SYN-ME-RSU84", note=CODE + ": its towns"),
    case("RSU 84 Seacliff High School", "ME", "SYN-ME-SEAHS", note=CODE + ": one of its schools"),
    case(
        "RSU 84 Kettering Grammar School", "ME", "SYN-ME-KETGS", note=CODE + ": one of its schools"
    ),
    case("MSAD 84", "ME", "SYN-ME-RSU93", note=CODE + ": the other series"),
    case("RSU 93", "ME", "SYN-ME-RSU93", note=CODE),
    case("SAD 84 / RSU 93", "ME", "SYN-ME-RSU93", note=CODE),
    case("MSAD 84 - Brackley, Fenmoor", "ME", "SYN-ME-RSU93", note=CODE + ": its towns"),
    case("MSAD 91", "ME", "SYN-ME-SAD91", note=CODE),
    case("MSAD 91 Dunmore", "ME", "SYN-ME-SAD91", note=CODE + ": its town"),
    case("RSU 91", "ME", "SYN-ME-RSU91", note=CODE + ": same number, other series"),
    case("RSU 91 Loxham High School", "ME", "SYN-ME-LOXHS", note=CODE + ": one of its schools"),
    case("MSAD 91 - Dunmore Community School", "ME", "SYN-ME-DUNCS", note=CODE),
    case("AOS 97 Wexbury Eddy School", "ME", "SYN-ME-WEXEE", note=CODE + ": a unit never named"),
    case("RSU 84 - Adult Education", "ME", None, note=CODE_NEGATIVE + ": a program"),
    case("RSU 84 - Waldron County", "ME", None, note=CODE_NEGATIVE + ": a place it cannot place"),
    case("RSU 84 Lincoln School", "ME", None, note=CODE_NEGATIVE + ": a town district's school"),
    case("RSU 93 Seacliff High School", "ME", None, note=CODE_NEGATIVE + ": another unit's"),
    case("MSAD 93", "ME", None, note=CODE_NEGATIVE + ": RSU 93 is MSAD 84"),
    case("RSU 85", "ME", None, note=CODE_NEGATIVE + ": no such unit"),
    case("RSU 84 - Brackley", "ME", None, note=CODE_NEGATIVE + ": another unit's town"),
    case("RSU 91 Dunmore", "ME", None, note=CODE_NEGATIVE + ": MSAD 91's town"),
    case("MSAD 91 Loxham High School", "ME", None, note=CODE_NEGATIVE + ": RSU 91's school"),
    case("RSU 84 KidsCare", "ME", None, note=CODE_NEGATIVE + ": a program"),
    case("MSAD 84 Seacliff High School", "ME", None, note=CODE_NEGATIVE + ": RSU 84's school"),
    case("USD 431 Wendham", "KS", "SYN-KS-WEND", note=CODE),
    case("USD #431 Wendham Schools", "KS", "SYN-KS-WEND", note=CODE),
    case("U.S.D. 431 - Wendham", "KS", "SYN-KS-WEND", note=CODE),
    case("Wendham USD 431", "KS", "SYN-KS-WEND", note="a district code after the name"),
    case("USD 431 Wendham High School", "KS", "SYN-KS-WENHS", note=CODE + ": one of its schools"),
    case("USD 431 Virtual Academy", "KS", "SYN-KS-WENVA", note=CODE + ": in the school's name"),
    case("USD 432 Carrow Valley", "KS", "SYN-KS-CARV", note=CODE),
    case("USD 433 Virtual Academy", "KS", None, note=CODE_NEGATIVE + ": another number"),
    case("USD 431 Wendham Catholic Schools", "KS", None, note=CODE_NEGATIVE + ": a faith"),
    case("USD 431 Wendham Community College", "KS", None, note=CODE_NEGATIVE + ": a college"),
    case("USD 431", "KS", None, note=CODE_NEGATIVE + ": a number the directory never gives"),
    case("USD 431 Marbleton", "KS", None, note=CODE_NEGATIVE + ": no such town"),
    case("D-5 Ketterly", "CO", "SYN-CO-D5", note=CODE + ": its schools' name"),
    case("D-5 Ketterly Schools", "CO", "SYN-CO-D5", note=CODE + ": its schools' name"),
    case("D-8 Palisade-Ft Garrow", "CO", "SYN-CO-D8", note=CODE),
    case("RE-4 Orland Schools", "CO", "SYN-CO-TESS", note=CODE + ": its town"),
    case("RE-4 Tessaly", "CO", "SYN-CO-TESS", note=CODE),
    case("D-5 Ketterly High School", "CO", "SYN-CO-KETHS", note=CODE + ": one of its schools"),
    case("D-6 Ketterly", "CO", None, note=CODE_NEGATIVE + ": another number"),
    case("D-5 Ashgrove", "CO", None, note=CODE_NEGATIVE + ": one school's name"),
    case("RE-3 Orland", "CO", None, note=CODE_NEGATIVE + ": another number"),
    case("D-8 Ketterly High School", "CO", None, note=CODE_NEGATIVE + ": another district's"),
    case("D-5 Orland High School", "CO", None, note=CODE_NEGATIVE + ": another district's"),
    case("RE-4 Ketterly", "CO", None, note=CODE_NEGATIVE + ": another district's schools"),
    # "<Town> Public School" is the town's school system, or a school of that name.
    case("ORVALE PUBLIC SCHOOL", "NE", "SYN-NE-ORV", note="a town's public school is its system"),
    case("Orvale Public Schools", "NE", "SYN-NE-ORV"),
    case("Orvale Elementary", "NE", "SYN-NE-ORVES"),
    case("Halvern Public School", "ID", "SYN-ID-HALPS", note="a school of that name"),
    # Ohio's "Ex. Vill." is "Exempted Village".
    case("Wexcombe Falls Ex Vill SD", "OH", "SYN-OH-WEXF"),
    case("Farrowdale Ex. Vil. Schools", "OH", "SYN-OH-FARR"),
    # A business is not a school.
    case("Kettleby, LLC", "OH", None, note="hard negative: a business"),
    case("Brackenmoor Holdings Inc.", "MA", None, note="hard negative: a business"),
    case("Tamberlin Valley LLC", "PA", None, note="hard negative: a business"),
    # A school's kind: an academy or a charter school is not a school that does
    # not say so.
    case("The Birchmont Academy", ("MA", "NH"), None, note="hard negative: not an academy"),
    case("Birchmont School", "MA", "SYN-MA-BIRCH"),
    case("Hollis Frost Charter School", "MA", None, note="hard negative: not a charter school"),
    case("Hollis Frost", "MA", "SYN-MA-HOLF"),
    case("Ashbury Academy", "VT", None, note="hard negative: not an academy"),
    case("Ashbury School", "VT", "SYN-VT-ASHB"),
    case("Tollis Deo Academy", "MO", "SYN-MO-TOLL", note="its name says nothing of its kind"),
    case(
        "Wren Hollow Community Charter School", "MN", "SYN-MN-WRENS", note="a district of its own"
    ),
    case("Kestrel Falls Charter School", "NH", "SYN-NH-KESTR", note="Chartered is Charter"),
    case(
        "Hartwell Public School", "ND", "SYN-ND-HART", note="a town's public school is its system"
    ),
    case("Hartwell High School", "ND", "SYN-ND-HARHS"),
    # "Regional" names a district whose schools say it, and tells two apart.
    case("Wachbury Regional", "MA", "SYN-MA-WACH", note="the district, not its high school"),
    case("Wachbury Regional High School", "MA", "SYN-MA-WACHS"),
    case("Franlow Regional School District", "PA", "SYN-PA-FRAR"),
    case("Franlow Area Schools", "PA", "SYN-PA-FRAA"),
    case("Franlow Schools", "PA", None, note="hard negative: two districts"),
    # A direction names another town: "E. Lansmere" is East Lansmere, never
    # Lansmere, and a town with no such neighbour has no match.
    case("E. Lansmere Public Schools", "MI", "SYN-MI-ELANM", note=DIRECTION),
    case("E Lansmere Schools", "MI", "SYN-MI-ELANM", note=DIRECTION),
    case("East Lansmere Public Schools", "MI", "SYN-MI-ELANM", note=DIRECTION),
    case("E. LANSMERE PUBLIC SCHOOLS (Closed)", "MI", "SYN-MI-ELANM", note=DIRECTION),
    case("Lansmere Public Schools", "MI", "SYN-MI-LANM", note=DIRECTION),
    case("Lansmere Schools", "MI", "SYN-MI-LANM", counties="83701", note=DIRECTION),
    case("E. Lansmere High School", "MI", "SYN-MI-ELANHS", counties="83701", note=DIRECTION),
    case("Lansmere High School", "MI", "SYN-MI-LANHS", counties="83701", note=DIRECTION),
    case("W. Lansmere Public Schools", "MI", None, note=DIRECTION_NEGATIVE),
    case("N. Lansmere Schools", "MI", None, counties="83701", note=DIRECTION_NEGATIVE),
    case("S Lansmere High School", "MI", None, counties="83701", note=DIRECTION_NEGATIVE),
    case("W. Des Pellam Schools", "IA", "SYN-IA-WDESP", note=DIRECTION),
    case("W Des Pellam Community Schools", "IA", "SYN-IA-WDESP", note=DIRECTION),
    case("Des Pellam Public Schools", "IA", "SYN-IA-DESP", note=DIRECTION),
    case("E. Des Pellam Schools", "IA", None, note=DIRECTION_NEGATIVE),
    case("S. Des Pellam Schools", "IA", None, counties="83801", note=DIRECTION_NEGATIVE),
    case("Portwick Public Schools", "ME", "SYN-ME-PORTW", note=DIRECTION),
    case("S. Portwick Schools", "ME", None, note=DIRECTION_NEGATIVE),
    case("So. Portwick Schools", "ME", None, counties="83901", note=DIRECTION_NEGATIVE),
    case("South Portwick Schools", "ME", None, note=DIRECTION_NEGATIVE),
    case("E. Portwick Public Schools", "ME", None, note=DIRECTION_NEGATIVE),
    case("N. Little Brook School District", "AR", "SYN-AR-NLBRK", note=DIRECTION),
    case("No. Little Brook SD", "AR", "SYN-AR-NLBRK", note=DIRECTION),
    case("Little Brook School District", "AR", "SYN-AR-LBRK", note=DIRECTION),
    case("S. Little Brook SD", "AR", None, note=DIRECTION_NEGATIVE),
    case("S. Burlingham School District", "VT", "SYN-VT-SBURL", note=DIRECTION),
    case("So. Burlingham High School", "VT", "SYN-VT-SBURHS", note=DIRECTION),
    case("Burlingham School District", "VT", "SYN-VT-BURL", note=DIRECTION),
    case("Burlingham High School", "VT", "SYN-VT-BURHS", note=DIRECTION),
    case("N. Burlingham SD", "VT", None, note=DIRECTION_NEGATIVE),
    case("W. Burlingham High School", "VT", None, counties="84101", note=DIRECTION_NEGATIVE),
    case("Village School of N. Tamsford", "VT", "SYN-VT-TAMS", note=DIRECTION),
    case("Hartmoor Public Schools", "CT", "SYN-CT-HARTM", note=DIRECTION),
    case("W. Hartmoor Public Schools", "CT", None, note=DIRECTION_NEGATIVE),
    case("West Hartmoor Public Schools", "CT", None, note=DIRECTION_NEGATIVE),
    case("W. Hartmoor PS", "CT", None, counties="84201", note=DIRECTION_NEGATIVE),
    case("E. Orlane School District", "NJ", "SYN-NJ-EORL", note=DIRECTION),
    case("Orlane School District", "NJ", "SYN-NJ-ORL", note=DIRECTION),
    case("W. Orlane SD", "NJ", None, note=DIRECTION_NEGATIVE),
    case("E. Provost Schools", "RI", "SYN-RI-EPROV", note=DIRECTION),
    case("Provost Schools", "RI", "SYN-RI-PROV", note=DIRECTION),
    case("N. Provost Schools", "RI", None, note=DIRECTION_NEGATIVE),
    case("E./N. Provost Schools", "RI", None, note=DIRECTION_NEGATIVE + ": two towns"),
    case("N. Kessel City Schools", "MO", "SYN-MO-NKESC", note=DIRECTION),
    case("Kessel City Schools", "MO", "SYN-MO-KESC", note=DIRECTION),
    case("S. Kessel City Schools", "MO", None, note=DIRECTION_NEGATIVE),
    case("Grand Tamsel Harbor Schools", "MN", "SYN-MN-TAMH", note=DIRECTION),
    case("E. Grand Tamsel Harbor Public Schools", "MN", None, note=DIRECTION_NEGATIVE),
    case("West Grand Tamsel Harbor Schools", "MN", None, note=DIRECTION_NEGATIVE),
    case("E. Brackwater Falls Area Schools", "WI", "SYN-WI-EBRK", note=DIRECTION),
    case("Brackwater Falls Area Schools", "WI", None, note=DIRECTION_NEGATIVE + ": left out"),
    case("W. Brackwater Falls Schools", "WI", None, note=DIRECTION_NEGATIVE),
    case("West Harlan-Dixby School District 147", "IL", "SYN-IL-WHAR", note=DIRECTION),
    case("Harlan-Dixby School District 147", "IL", None, note=DIRECTION_NEGATIVE + ": left out"),
    case("Pellam-West Holliver SD 105", "IL", "SYN-IL-PELL", note=DIRECTION),
    case("Pellam-E Holliver SD 105", "IL", None, note=DIRECTION_NEGATIVE),
    case("Lake Tamsin Middle School North Campus", "IL", "SYN-IL-LTAMN", note=DIRECTION),
    case("Lake Tamsin Middle - S Campus", "IL", "SYN-IL-LTAMS", note=DIRECTION),
    case("Lake Tamsin Middle School", "IL", None, note=DIRECTION_NEGATIVE + ": two campuses"),
    case("South Tamblin City Community Schools", "NE", "SYN-NE-STAM", note=DIRECTION),
    case("So. Tamblin City Schools", "NE", "SYN-NE-STAM", note=DIRECTION),
    case("Tamblin Public Schools", "NE", "SYN-NE-TAM", note=DIRECTION),
    case("N. Tamblin Public Schools", "NE", None, note=DIRECTION_NEGATIVE),
    case("USD 251 N. Lymont County", "KS", "SYN-KS-NLYM", note=DIRECTION + ": after a code"),
    case("USD 252 S. Lymont County", "KS", None, note=DIRECTION_NEGATIVE + ": after a code"),
    # A letter between a given name and a surname is a middle initial, and one
    # before another initial or a given name stays what the record says.
    case("Harry S. Tollman Elementary", "MI", "SYN-MI-TOLES", note="middle initial"),
    case("Harry S Tollman Elem", "MI", "SYN-MI-TOLES", note="middle initial"),
    case("Harry Tollman Elementary School", "MI", "SYN-MI-TOLES", note="middle initial left out"),
    case("Joel E. Barrow Elementary", "MI", "SYN-MI-BARES", note="middle initial"),
    case("Joel Barrow Elementary", "MI", "SYN-MI-BARES", note="middle initial left out"),
    case("E. Halden Currie Elementary", "MI", "SYN-MI-CURES", note="as the record spells it"),
    # An affiliation left out: only a saint's or a devotion's school may be
    # listed without it.
    case("Pellbridge Christian Academy", ("NH", "MA"), "SYN-NH-PELCA"),
    case("Pellbridge Academy", ("NH", "MA"), None, note="hard negative: affiliation left out"),
    case("Pellbridge Academy", "NH", None, counties="85101", note="hard negative: left out"),
    case("Brindles Academy", ("NC", "VA"), None, note="hard negative: affiliation left out"),
    case("Brindle Christian Academy", "VA", "SYN-VA-BRINC"),
    case("Cheverwood School - Marlden", "MA", "SYN-MA-CHEVC", note="its town named beside it"),
    case("Cheverwood School", "MA", None, note="hard negative: affiliation left out"),
    case("Pellbridge Academy - Pellbridge", "NH", None, note="hard negative: only the town"),
    # A place and its kind is a township or a county, not a school named for it.
    case("Yarwick Township", "PA", None, note="hard negative: a township, not its school"),
    case("Yarwick Twp.", "PA", None, note="hard negative: a township, not its school"),
    case("Yarwick Township Elementary", "PA", "SYN-PA-YARTW"),
    case("Yarwick Twp El Sch", "PA", "SYN-PA-YARTW"),
    case("Effley", "NH", None, note=PLACE_NEGATIVE + ": its one school is not its system"),
    case("Effley Elementary School", "NH", "SYN-NH-EFFES"),
    case("Effley Elementary", "NH", "SYN-NH-EFFES"),
    case("Sacred Heart School", "KS", "SYN-KS-SACH", note="a devotion's school"),
    case("Sacred Heart Catholic School", "KS", "SYN-KS-SACH"),
    case("Saint Mary's Academy", "KS", None, note="hard negative: no St. Mary's says Academy"),
    case("St. Mary's School", "KS", None, note="hard negative: three St. Mary's in the state"),
    case("St. Mary", "KS", None, counties="85003", note=PARISH_NEGATIVE + ": church or school"),
    case("St. Mary", "KS", "SYN-KS-STMY", counties="85003", category="Parochial School"),
    case("St. Mary's Catholic School", "KS", "SYN-KS-STMYC", counties="85005"),
    # A leading code before a town named "... Center" names the district.
    case("USD 262 Harrow Center", "KS", "SYN-KS-HARC", note=CODE + ": a town named Center"),
    case("Harrow Center USD 262", "KS", "SYN-KS-HARC", note="a district code after the name"),
    case("USD 262 Harrow Center High School", "KS", "SYN-KS-HARCH", note=CODE),
    # A city's system, not the charter school named for the city.
    case("St. Pellam Public Schools", "MN", "SYN-MN-STPEL", note="the system, not the charter"),
    case("Saint Pellam Schools", "MN", "SYN-MN-STPEL", note="the system, not the charter"),
    case("St. Pellam City School", "MN", "SYN-MN-STPCSS", note="the charter school"),
    # An HTML entity a feed left in; a school network named with a letter.
    case("Leveridge&#039;s Chapel ISD", "TX", "SYN-TX-LEVC", note="an HTML entity"),
    case("Leveridge&#39;s Chapel ISD (Closed)", "TX", "SYN-TX-LEVC", note="an HTML entity"),
    case("E Prep Woodmere", "OH", "SYN-OH-EPREP", note="a letter before Prep is no direction"),
    case(
        "E Prep and Village Prep Tamsin Hills",
        "OH",
        "SYN-OH-VPREP",
        note="a letter before Prep is no direction; School inside a name weighs little",
    ),
    case("Village Prep Tamsin Hills", "OH", "SYN-OH-VPREP", note="School left out"),
    # A direction before "St.".
    case("So. St. Pellam Public Schools", "MN", "SYN-MN-SSTPEL", note=DIRECTION),
    case("S. St. Pellam Schools", "MN", "SYN-MN-SSTPEL", note=DIRECTION),
    case("South Saint Pellam Schools", "MN", "SYN-MN-SSTPEL", note=DIRECTION),
    case("N. St. Pellam Public Schools", "MN", None, note=DIRECTION_NEGATIVE),
    # One school split by level names its district; two of a district's three
    # schools that share a name stay rivals.
    case("Grenmoor Bay Charter School", "NH", "SYN-NH-GBAY", note="split by level"),
    case("Grenmoor Bay Charter School (H)", "NH", "SYN-NH-GBAYH", note="split by level"),
    case("Grenmoor Bay Charter High School", "NH", "SYN-NH-GBAYH", note="split by level"),
    case("Tolliver Central School", "NH", None, note="hard negative: two of three schools"),
    case("Tolliver Central Elementary", "NH", "SYN-NH-EXMCE"),
    # A town's name is its school system, never one school named for it or in it.
    case("Varenna", "CA", "SYN-CA-VARV", note=PLACE + ": its district, not its high school"),
    case("Varenna", "CA", "SYN-CA-VARV", counties="85701", note=PLACE + ": not its high school"),
    case("VARENNA - Closed", "CA", "SYN-CA-VARV", note=PLACE + ": not its high school"),
    case("Varenna (2 Hour Delay)", "CA", "SYN-CA-VARV", note=PLACE + ": not its high school"),
    case("Varenna Valley Unified", "CA", "SYN-CA-VARV"),
    case("Varenna Valley Schools", "CA", "SYN-CA-VARV"),
    case("Varenna Valley", "CA", "SYN-CA-VARV", note=PLACE + ": a district's own name"),
    case("Varenna High", "CA", "SYN-CA-VARHS"),
    case("Varenna High School", "CA", "SYN-CA-VARHS"),
    case("Rickmond", "CA", None, note=PLACE_NEGATIVE + ": a district of its name lies elsewhere"),
    case("Rickmond", "CA", None, counties="85702", note=PLACE_NEGATIVE + ": not its high school"),
    case("Rickmond Elementary", "CA", "SYN-CA-RICE", note="a district of one school"),
    case("Rickmond Elementary District", "CA", "SYN-CA-RICE"),
    case("Bayshore Unified", "CA", "SYN-CA-BAYU"),
    case("Rickmond High School", "CA", "SYN-CA-RICHS"),
    case(
        "Olden Brook", "NJ", "SYN-NJ-OLDB", note=PLACE + ": its township's district, not its school"
    ),
    case("Olden Brook - Closed", "NJ", "SYN-NJ-OLDB", note=PLACE + ": not its high school"),
    case("Olden Brook Township Schools", "NJ", "SYN-NJ-OLDB"),
    case("Olden Brook Twp. Public Schools", "NJ", "SYN-NJ-OLDB"),
    case("Olden Brook High School", "NJ", "SYN-NJ-OLDBH"),
    case("Godwin School of Olden Brook", "NJ", "SYN-NJ-OLDBG"),
    case("Nepford", "NJ", "SYN-NJ-NEPT", note=PLACE + ": the township, not the city beside it"),
    case("Nepford City", "NJ", "SYN-NJ-NEPC", note=PLACE),
    case("Nepford City Schools", "NJ", "SYN-NJ-NEPC"),
    case("Nepford Township Schools", "NJ", "SYN-NJ-NEPT"),
    case("Nepford High School", "NJ", "SYN-NJ-NEPTH"),
    case(
        "Buckmoor",
        "AZ",
        "SYN-AZ-BUCE",
        also=("SYN-AZ-BUCH",),
        note=SYSTEM + ": a place's name is its elementary and union high districts, never a school",
    ),
    case(
        "Buckmoor - All Schools",
        "AZ",
        "SYN-AZ-BUCE",
        also=("SYN-AZ-BUCH",),
        note=SYSTEM + ": a place's name is its two districts",
    ),
    case("Buckmoor Union", "AZ", "SYN-AZ-BUCH", note=SYSTEM_NEGATIVE + ": Union"),
    case("Buckmoor Union High", "AZ", "SYN-AZ-BUCH", note="Union is a legal form"),
    case("Buckmoor High School District", "AZ", "SYN-AZ-BUCH", note="Union is a legal form"),
    case("Buckmoor Elementary District", "AZ", "SYN-AZ-BUCE"),
    case("Buckmoor Union High School District", "AZ", "SYN-AZ-BUCH"),
    case("Brackville", "KY", None, note=PLACE_NEGATIVE + ": not the Village School"),
    case("BRACKVILLE (Closed)", "KY", None, note=PLACE_NEGATIVE + ": not the Village School"),
    case("Brackville", "KY", None, counties="86001", note=PLACE_NEGATIVE + ": not a school in it"),
    case("Village School of Brackville", "KY", "SYN-KY-VSOB"),
    case("Corwin County Public Schools", "KY", "SYN-KY-CORW"),
    case("Tolland Elementary", "KY", "SYN-KY-TOLES"),
    case("Halstead", "NC", None, note=PLACE_NEGATIVE + ": not The Halstead School"),
    case("Halstead - 2 Hour Delay", "NC", None, note=PLACE_NEGATIVE + ": not The Halstead School"),
    case("The Halstead School", "NC", "SYN-NC-THEHS"),
    case("Wexmoor County Schools", "NC", "SYN-NC-WEXC"),
    case("Kessling", "OH", "SYN-OH-KESC", note=PLACE + ": not a school named for it elsewhere"),
    case("Kessling Schools", "OH", "SYN-OH-KESC"),
    case("Kessling Elementary School", "OH", "SYN-OH-KESES"),
    case("Pellmont", "OH", None, note=PLACE_NEGATIVE + ": not a school named for it elsewhere"),
    case("Pellmont", "OH", None, counties="86202", note=PLACE_NEGATIVE + ": not its namesake"),
    case("Pellmont Elementary", "OH", "SYN-OH-PELES"),
    case("Mt. Lindell", "PA", "SYN-PA-MTLIN", note=PLACE + ": a district's own name"),
    case("Mount Lindell", "PA", "SYN-PA-MTLIN", note=PLACE + ": a district's own name"),
    case("Mt Lindell SHS", "PA", "SYN-PA-MTLHS"),
    case("Philmont", "PA", "SYN-PA-PHIL", note=PLACE + ": not The Philmont School"),
    case("The Philmont School", "PA", "SYN-PA-PHILS"),
    case("St. Marlow's", "PA", None, note=PLACE_NEGATIVE + ": a town and a parish school"),
    case("St Marlow Area SD", "PA", "SYN-PA-STMAR"),
    case(
        "St. Marlow's School",
        "PA",
        None,
        counties="86304",
        note=JUST_PAST + ": the town's high school, a county away",
    ),
    case(
        "St. Marlow's School",
        "PA",
        None,
        counties=("86304", "86303"),
        note="hard negative: the parish school and the town's high school, both in the counties",
    ),
    case("Byford Center", "MI", "SYN-MI-BYFC", note=PLACE + ": a school noun in a town's name"),
    case("Byford Center High School", "MI", "SYN-MI-BYFCH"),
    case("Hamlow", "MI", "SYN-MI-HAMT", note=PLACE + ": a Michigan city's district"),
    case("Hamlow Public Schools", "MI", "SYN-MI-HAMT", note="of the City of"),
    case("Hamlow City Schools", "MI", "SYN-MI-HAMT", note="of the City of"),
    case("Hamlow High School", "MI", "SYN-MI-HAMHS"),
    case("Tinsley Park", "IL", None, note=PLACE_NEGATIVE + ": not its high school"),
    case("Tinsley Park", "IL", None, counties="86501", note=PLACE_NEGATIVE + ": not its school"),
    case("TINSLEY PARK - Closed", "IL", None, note=PLACE_NEGATIVE + ": not its high school"),
    case("Tinsley Park High School", "IL", "SYN-IL-TINHS"),
    case("Oswell", "IL", None, note=PLACE_NEGATIVE + ": its district is named by number"),
    case("Oswell (Closed)", "IL", None, note=PLACE_NEGATIVE + ": its district is named by number"),
    case("Oswell High School", "IL", "SYN-IL-OSWHS"),
    case("CUSD 309", "IL", "SYN-IL-CU309"),
    case("Montfort", "VT", "SYN-VT-MONRU", note=PLACE + ": its union district, not its school"),
    case("Montfort High School", "VT", "SYN-VT-MONHS"),
    case("Renwick", "NV", None, note=PLACE_NEGATIVE + ": its high school is the county's"),
    case("RENWICK", "NV", None, counties="86701", note=PLACE_NEGATIVE + ": not its high school"),
    case("Renwick High School", "NV", "SYN-NV-RENHS"),
    case("Saint Albury", "NY", None, note=PLACE_NEGATIVE + ": a saint's town, not its school"),
    case("St. Albury", "NY", None, counties="86801", note=PLACE_NEGATIVE + ": not its school"),
    case("Saint Albury Elementary", "NY", "SYN-NY-STALB"),
    case("Burlmoor", "NJ", None, note=PLACE_NEGATIVE + ": a city and a township of one name"),
    case("Burlmoor City", "NJ", "SYN-NJ-BURC", note=PLACE),
    case("Burlmoor Township", "NJ", "SYN-NJ-BURT", note=PLACE),
    case("Brackville School", "KY", None, note="hard negative: not the Village School of it"),
    case("Pellmont, Daywood", "OH", "SYN-OH-PELES", note="its city beside it: a school, no place"),
    case(
        "Falmont",
        "VA",
        "SYN-VA-FALC",
        note=PLACE + ": the city's district, not the county's school",
    ),
    case("Falmont High", "VA", "SYN-VA-FALHS"),
    case("Kingsford", "MO", "SYN-MO-KING", note=PLACE),
    case(
        "Kingsford",
        "AR",
        None,
        note=PLACE_NEGATIVE + ": its high school is another town's district's",
    ),
    case(
        "Kingsford", ("MO", "AR"), None, note=PLACE_NEGATIVE + ": a town of that name in each state"
    ),
    case("Kesselby", "MI", None, note=PLACE_NEGATIVE + ": not a charter school's own district"),
    case("Kesselby Academy", "MI", "SYN-MI-KESAS", note="the school, named as its own district"),
    case("Kesselby High School", "MI", "SYN-MI-KESHS"),
    # A charter network across a state: a listing from one market names its
    # campus there, never its schools in other cities; two campuses there that
    # the listing fits alike go to the queue, even beside a point much nearer
    # one of them: both are the market's, and its point says nothing of which.
    case(
        "Crestline High School",
        "TX",
        None,
        counties=(TALBERT_CO, MOSSBURG_CO),
        note=NETWORK_NEGATIVE + ": two campuses in the market",
    ),
    case(
        "Crestline High School",
        "TX",
        None,
        counties=(TALBERT_CO, MOSSBURG_CO),
        near=TALBERT,
        note=NETWORK_NEGATIVE + ": two campuses in the market, one beside the point",
    ),
    case(
        "Crestline High School",
        "TX",
        None,
        counties=(CANTRELL_CO, AMBERLY_CO),
        note=NETWORK_NEGATIVE + ": two campuses in the market",
    ),
    case(
        "CRESTLINE HIGH SCHOOL (Closed)",
        "TX",
        None,
        counties=(CANTRELL_CO, AMBERLY_CO),
        near=AMBERLY,
        note=NETWORK_NEGATIVE + ": two campuses in the market, one beside the point",
    ),
    case(
        "Crestline High School",
        "TX",
        "SYN-TX-CRWYN",
        counties=WYNNE_CO,
        note=NETWORK + ": its one campus in the market",
    ),
    case(
        "Crestline High Schools",
        "TX",
        "SYN-TX-CRWYN",
        counties=WYNNE_CO,
        note=NETWORK + ": its one campus in the market",
    ),
    case(
        "Crestline High School - Talbert",
        "TX",
        "SYN-TX-CRTAL",
        counties=(TALBERT_CO, MOSSBURG_CO),
        note=NETWORK + ": the campus by name",
    ),
    case(
        "Crestline High School Mossburg",
        "TX",
        "SYN-TX-CRMOS",
        counties=(TALBERT_CO, MOSSBURG_CO),
        note=NETWORK + ": the campus by name",
    ),
    case(
        "Crestline High School",
        "TX",
        None,
        counties=CRESTLINE_HQ,
        note=NETWORK_NEGATIVE + ": its office, no campus, in the market",
    ),
    case(
        "Vantage Schools",
        "TX",
        None,
        counties=ODELL_CO,
        note=NETWORK_NEGATIVE + ": two campuses in the market",
    ),
    case(
        "Vantage Public Schools",
        "TX",
        None,
        counties=ODELL_CO,
        note=NETWORK_NEGATIVE + ": two campuses in the market",
    ),
    case(
        "Vantage Public Schools",
        "TX",
        None,
        counties=RIVERBEND_CO,
        note=NETWORK_NEGATIVE + ": most campuses in the market, three far away",
    ),
    case(
        "Vantage Schools",
        "TX",
        "SYN-TX-VAGAR",
        counties=GARRISON_CO,
        note=NETWORK + ": its one campus in the market",
    ),
    case("Vantage Odell Academy", "TX", "SYN-TX-VAODA", counties=ODELL_CO, note=NETWORK),
    case(
        "Vantage Odell College Prep",
        "TX",
        "SYN-TX-VAODC",
        counties=ODELL_CO,
        note=NETWORK + ": the campus by name",
    ),
    case(
        "Quillon Academy",
        "TX",
        "SYN-TX-QUBRO",
        counties=BROOKHOLLOW_CO,
        note=NETWORK + ": its one campus in the market",
    ),
    case(
        "Quillon Academy",
        "TX",
        None,
        counties=MEADOW_GLEN_CO,
        note=NETWORK_NEGATIVE + ": two campuses in the market",
    ),
    case(
        "Quillon Academy",
        "TX",
        None,
        counties=MEADOW_GLEN_CO,
        near=SOUTHGATE,
        note=NETWORK_NEGATIVE + ": two campuses in the county, one beside the point",
    ),
    case(
        "Halcyon Academy",
        "TX",
        "SYN-TX-HANOR",
        counties=NORTHPARK_CO,
        note=NETWORK + ": its one campus in the market",
    ),
    case(
        "Halcyon Academy",
        "TX",
        None,
        counties=BELLTOWN_CO,
        note=NETWORK_NEGATIVE + ": its campus in the market is of another kind",
    ),
    case(
        "Halcyon College Prep - Belltown",
        "TX",
        "SYN-TX-HABEL",
        counties=BELLTOWN_CO,
        note=NETWORK + ": the campus by name",
    ),
    # A district that straddles the market's edge is whole, however many of its
    # schools lie outside the counties; so is one with a stray virtual school
    # across the state.
    case(
        "Tiberton Area School District",
        "PA",
        "SYN-PA-TIBR",
        counties=PELLSVILLE_CO,
        note="straddles the market: most schools just outside",
    ),
    case("Tiberton Area SD", "PA", "SYN-PA-TIBR", counties=(PELLSVILLE_CO, TIBERTON_CO)),
    case(
        "Halloran County Schools",
        "FL",
        "SYN-FL-HALL",
        counties=HALLORAN_CO,
        note="one stray virtual school across the state",
    ),
    case("Halloran Virtual Franchise", "FL", "SYN-FL-HALVS", counties=FAR_CO),
    # A charter district named as one academy: its name, word for word, is the
    # district, never the one of its schools that adds only a level to it; a
    # school's own name is that school.
    case("Wyndhaven Academy", "TX", "SYN-TX-WYND", counties=WYNDHAVEN_CO, note=OWN_NAME),
    case("Wyndhaven Academy", "TX", "SYN-TX-WYND", note=OWN_NAME),
    case("WYNDHAVEN ACADEMY (Closed)", "TX", "SYN-TX-WYND", counties=WYNDHAVEN_CO, note=OWN_NAME),
    case("Wyndhaven Academy - 2 Hour Delay", "TX", "SYN-TX-WYND", note=OWN_NAME),
    case("Wyndhaven Academy Middle", "TX", "SYN-TX-WYNMS", counties=WYNDHAVEN_CO),
    case("Wyndhaven Academy Middle School", "TX", "SYN-TX-WYNMS"),
    case("Wyndhaven Academy Upper Elementary", "TX", "SYN-TX-WYNUE", counties=WYNDHAVEN_CO),
    case("Wyndhaven Academy Lower El.", "TX", "SYN-TX-WYNLE"),
    case("Wyndhaven Academy", "OK", None, note=OWN_NAME_NEGATIVE + ": other state"),
    case("Wyndhaven Academy", "TX", None, counties=TALBERT_CO, note=OWN_NAME_NEGATIVE + ": county"),
    case("Orvelle Academy", "MO", "SYN-MO-ORVA", counties=ORVELLE_CO, note=OWN_NAME),
    case("Orvelle Academy", "MO", "SYN-MO-ORVA", note=OWN_NAME),
    case("ORVELLE ACADEMY: Closed", "MO", "SYN-MO-ORVA", note=OWN_NAME),
    case("Orvelle Academy Middle School", "MO", "SYN-MO-ORVMS", counties=ORVELLE_CO),
    case("Orvelle Academy Upper", "MO", "SYN-MO-ORVUP"),
    case("Orvelle Academy", "KS", None, note=OWN_NAME_NEGATIVE + ": other state"),
    case("Tamsin PCS", "DC", "SYN-DC-TAMS", note=OWN_NAME),
    case("Tamsin Public Charter School", "DC", "SYN-DC-TAMS", note=OWN_NAME),
    case("Tamsin PCS", "DC", "SYN-DC-TAMS", counties=TAMSIN_CO, note=OWN_NAME),
    case("Tamsin PCS - MS", "DC", "SYN-DC-TAMMS"),
    case("Tamsin PCS Middle School", "DC", "SYN-DC-TAMMS"),
    case("Tamsin PCS International High School", "DC", "SYN-DC-TAMHS"),
    case("Quenmore Academy", "MI", "SYN-MI-QUEN", counties=QUENMORE_CO, note=OWN_NAME),
    case("Quenmore Academy", "MI", "SYN-MI-QUEN", note=OWN_NAME),
    case("Quenmore Academy Elementary", "MI", "SYN-MI-QUENE", counties=QUENMORE_CO),
    case("Vespera Academy", "UT", "SYN-UT-VESP", counties=VESPERA_CO, note=OWN_NAME),
    case("Vespera Academy", "UT", "SYN-UT-VESP", note=OWN_NAME),
    case("VESPERA ACADEMY - All Schools", "UT", "SYN-UT-VESP", note=OWN_NAME),
    case("Vespera Academy Elementary", "UT", "SYN-UT-VESPE", counties=VESPERA_CO),
    case("Vespera Academy Middle School", "UT", "SYN-UT-VESPM"),
    case("Vespera Academy High School", "UT", None, note=OWN_NAME_NEGATIVE + ": no such level"),
    case("Trellis Academy", "MN", "SYN-MN-TREL", counties=TRELLIS_CO, note=OWN_NAME),
    case("Trellis Academy", "MN", "SYN-MN-TREL", note=OWN_NAME),
    case("Trellis Academy Elementary", "MN", "SYN-MN-TRELE", counties=TRELLIS_CO),
    case("Trellis Academy Charter School", "MN", "SYN-MN-TRELC"),
    case(
        "Aldern Village School",
        "MO",
        None,
        note=OWN_NAME_NEGATIVE + ": the district, or its high school, cannot tell",
    ),
    case("Aldern Village Schools", "MO", "SYN-MO-ALDV", note=OWN_NAME),
    case("Aldern Village High School", "MO", "SYN-MO-ALDVH", counties=ALDERN_CO),
    case(
        "Pellwyn Academy",
        "TX",
        "SYN-TX-PELW",
        note=OWN_NAME + ": one school has it, the other adds only a level",
    ),
    case("Pellwyn Academy Middle", "TX", "SYN-TX-PELWM", counties=PELLWYN_CO),
    case("Orenway Charter School", "MN", "SYN-MN-OREN", note=OWN_NAME),
    case(
        "Orenway Charter School",
        "MN",
        None,
        counties=ORENWAY_CO,
        note=OWN_NAME_NEGATIVE + ": its one campus there it fits says a level more",
    ),
    case(
        "Orenway Charter School",
        "MN",
        "SYN-MN-ORENF",
        counties=FARPORT_CO,
        note=NETWORK + ": its one campus there it fits says only its town more",
    ),
    case("Orenway Charter Elementary", "MN", "SYN-MN-ORENE", counties=ORENWAY_CO),
    case("OCS High School", "MN", "SYN-MN-ORENH", counties=ORENWAY_CO),
    # A town's name names the town's district only where the listing's
    # counties hold the town, or its market lies near it: San Arvello's
    # "EDGEMERE ISD" is not the town of Edgemere's, 440 km away.
    case(
        "Edgemere",
        "TX",
        "SYN-TX-EDGS",
        near=SAN_ARVELLO,
        note=NAMESAKE_NEGATIVE + ": the town lies 440 km from the market",
    ),
    case(
        "Edgemere - Closed",
        "TX",
        "SYN-TX-EDGS",
        near=SAN_ARVELLO,
        note=NAMESAKE_NEGATIVE + ": the town lies 440 km from the market",
    ),
    case(
        "Edgemere",
        "TX",
        "SYN-TX-EDGS",
        counties=SAN_ARVELLO_CO,
        note=NAMESAKE_NEGATIVE + ": the town lies outside the counties",
    ),
    case(
        "EDGEMERE",
        "TX",
        "SYN-TX-EDGS",
        counties=SAN_ARVELLO_CO,
        near=SAN_ARVELLO,
        note=NAMESAKE_NEGATIVE + ": the town lies outside the counties",
    ),
    case("Edgemere ISD", "TX", "SYN-TX-EDGS", near=SAN_ARVELLO, note=NAMESAKE),
    case("Edgemere", "TX", "SYN-TX-EDGT", near=EDGEMERE, note=NAMESAKE + ": the town's own"),
    case("Edgemere", "TX", "SYN-TX-EDGT", counties=EDGEMERE_CO, note=NAMESAKE + ": the town's own"),
    case("Edgemere", "TX", None, note=NAMESAKE_NEGATIVE + ": two districts of the name"),
    case(
        "Brennan",
        "OH",
        "SYN-OH-BRENL",
        near=HARWOOD_SPRINGS,
        note=NAMESAKE_NEGATIVE + ": the town of Brennan lies 230 km from the market",
    ),
    case(
        "Brennan - 2 Hour Delay",
        "OH",
        "SYN-OH-BRENL",
        counties=HARWOOD_SPRINGS_CO,
        note=NAMESAKE_NEGATIVE + ": the town of Brennan lies outside the counties",
    ),
    case("Brennan", "OH", "SYN-OH-BRENC", note=NAMESAKE + ": statewide, the town's own"),
    case("Brennan", "OH", "SYN-OH-BRENC", near=BRENNAN, note=NAMESAKE + ": the town's own"),
    case("Brennan Local Schools", "OH", "SYN-OH-BRENL"),
    case("Edgemere ISD", "TX", None, note=NAMESAKE_NEGATIVE + ": two districts of the name"),
    # A plural is another name: "Oakhurst Hills" is not the town of Oakhurst Hill.
    case("Oakhurst Hills", "OH", "SYN-OH-OAKHS", note=SPELLING_NEGATIVE + ": not the town's"),
    case("Oakhurst Hills", "OH", "SYN-OH-OAKHS", near=CINDALE, note=SPELLING_NEGATIVE),
    case("Oakhurst Hills", "OH", "SYN-OH-OAKHS", counties=CINDALE_CO, note=SPELLING),
    case("Oakhurst Hills Schools", "OH", "SYN-OH-OAKHS", note=SPELLING),
    case(
        "Oakhurst Hill Schools", "OH", "SYN-OH-OAKHU", note=SPELLING_NEGATIVE + ": not the hills'"
    ),
    case("Oakhurst Hill Schools", "OH", "SYN-OH-OAKHU", near=OAKHURST_HILL, note=SPELLING),
    case("Oakhurst Hill", "OH", "SYN-OH-OAKHU", note=SPELLING + ": the town's district"),
    case("Oakhurst Hill Union Local Schools", "OH", "SYN-OH-OAKHU"),
    case(
        "Tarrow Valley",
        "CA",
        "SYN-CA-TARV",
        near=FORT_KELLAN,
        note=SPELLING_NEGATIVE + ": not the town of Tarrows Valley",
    ),
    case("Tarrow Valley", "CA", "SYN-CA-TARV", note=SPELLING_NEGATIVE + ": not Tarrows Valley"),
    case("Tarrows Valley", "CA", "SYN-CA-TARSV", note=SPELLING + ": the town's district"),
    case("Tarrow Valley Unified", "CA", "SYN-CA-TARV", note=SPELLING),
    case("Tarrows Valley Unified School District", "CA", "SYN-CA-TARSV", note=SPELLING),
    # A district whose name is the listing's, word for word, is never ranked
    # below the town's other districts.
    case(
        "Kentmoor",
        "MI",
        "SYN-MI-KENT",
        counties=GRAND_MAREN_CO,
        note=NAMESAKE + ": its name, though the town's school is another district's",
    ),
    case("Kentmoor", "MI", "SYN-MI-KENT", note=NAMESAKE + ": its name, word for word"),
    case("Kentmoor Public Schools", "MI", "SYN-MI-KENT"),
    case("Grand Maren", "MI", "SYN-MI-GMAR", note=PLACE + ": the city's own district"),
    case("Brookvale Elementary", "MI", "SYN-MI-BROOK"),
    case(
        "Leemont",
        "FL",
        "SYN-FL-LEEM",
        counties=LEEMONT_CO,
        note=NAMESAKE + ": the county's district, not the town's",
    ),
    case("Leemont", "FL", "SYN-FL-LEEM", note=NAMESAKE + ": the county's district, not the town's"),
    case("Leemont County Schools", "FL", "SYN-FL-LEEM"),
    case(
        "Leemont",
        "FL",
        None,
        counties=MADDOCK_CO,
        note=NAMESAKE_NEGATIVE + ": the town's one school is another county's district's",
    ),
    case("Maddock", "FL", "SYN-FL-MADD"),
    # Legal forms a list leaves out or says otherwise.
    case("Sablemoor Community Schools", "OH", "SYN-OH-SABC", note="Community City"),
    case("Sablemoor City Schools", "OH", "SYN-OH-SABC", note="Community City"),
    case("Sablemoor Schools", "OH", "SYN-OH-SABC", note="Community City"),
    case("Sablemoor", "OH", "SYN-OH-SABC", note="Community City"),
    case("Varrow Hill Schools", "OH", "SYN-OH-VARU", note="Union Local"),
    case("Varrow Hill Local Schools", "OH", "SYN-OH-VARU", note="Union Local"),
    case("Varrow Hill", "OH", "SYN-OH-VARU", note=PLACE + ": Union Local"),
    case("Genmoor ISD", "MI", "SYN-MI-GENI", note="ISD names the one whose name says it"),
    case(
        "Genmoor Intermediate School District",
        "MI",
        "SYN-MI-GENI",
        note="Michigan's intermediate school district, which NCES calls ISD",
    ),
    # One county's intermediate district beside the township's: a listing that
    # does not say ISD names the township's.
    case("Genmoor Schools", "MI", "SYN-MI-GENS", note="not the county's intermediate district"),
    case("Genmoor School District", "MI", "SYN-MI-GENS", note="not the county's ISD"),
    case("Genmoor Public Schools", "MI", "SYN-MI-GENS", note="not the county's ISD"),
    case("Genmoor", "MI", "SYN-MI-GENS", note=PLACE + ": the township's, not the county's ISD"),
    case("Genmoor Elementary School", "MI", "SYN-MI-GENES", counties=GENMOOR_CO),
    case("Kessford ISD", "MI", "SYN-MI-KESI", note="its name, word for word"),
    case("Kessford City Schools", "MI", "SYN-MI-KESC"),
    case("Kessford City", "MI", "SYN-MI-KESC", note=PLACE),
    case("Saint Pellam", "MN", "SYN-MN-STPEL", note=PLACE + ": the system, not the charter"),
    case("St. Pellam", "MN", "SYN-MN-STPEL", note=PLACE + ": the system, not the charter"),
    case("Yarrowstown", "OH", "SYN-OH-YARC", note=PLACE + ": the city's, not the charter's"),
    case("Yarrowstown City Schools", "OH", "SYN-OH-YARC"),
    case("Yarrowstown Community School", "OH", "SYN-OH-YARCSS", note="the charter school"),
    case("Mattley", "MI", "SYN-MI-MATT", note=PLACE + ": a district of three named as a school"),
    case("Mattley Consolidated Schools", "MI", "SYN-MI-MATT"),
    case(
        "Wexley",
        "CA",
        "SYN-CA-WEXU",
        near=QUARTZ_GLEN,
        note=NAMESAKE_NEGATIVE + ": Union is a legal form; the other lies 260 km away",
    ),
    case("Wexley", "CA", "SYN-CA-WEXE", near=FIVE_PINES, note=NAMESAKE),
    case("Wexley", "CA", None, note=NAMESAKE_NEGATIVE + ": two districts of the name"),
    case("Wexley Union Elementary", "CA", "SYN-CA-WEXU", note="Union names the one that says it"),
    case("Wexley Union School District", "CA", "SYN-CA-WEXU", note="Union"),
    case("Wexley Elementary", "CA", None, note=NAMESAKE_NEGATIVE + ": two districts of the name"),
    # A county in brackets tells namesakes apart; a listing may say it or not.
    case(
        "Everbrook Public Schools",
        "WA",
        "SYN-WA-EVBT",
        counties=TALLIS_CO,
        note=BRACKET + ": the county's",
    ),
    case("Everbrook School District", "WA", "SYN-WA-EVBT", counties=TALLIS_CO, note=BRACKET),
    case(
        "Everbrook",
        "WA",
        "SYN-WA-EVBT",
        counties=TALLIS_CO,
        note=BRACKET + ": the district, not its high school",
    ),
    case("Everbrook", "WA", "SYN-WA-EVBQ", counties=QUENBY_CO, note=BRACKET),
    case("Everbrook Schools", "WA", "SYN-WA-EVBQ", near=GIFFMOOR, note=BRACKET + ": nearest"),
    case(
        "Everbrook School District",
        "WA",
        None,
        note=BRACKET_NEGATIVE + ": two namesakes, the county not said",
    ),
    case("Everbrook", "WA", None, note=BRACKET_NEGATIVE + ": two namesakes"),
    case("Everbrook School District (Tallis)", "WA", "SYN-WA-EVBT", note=BRACKET + ": as NCES"),
    case("Everbrook Public Schools - Quenby County", "WA", "SYN-WA-EVBQ", note=BRACKET),
    case("Everbrook High School", "WA", "SYN-WA-EVBTHS", counties=TALLIS_CO),
    case("Tallis School District", "WA", None, note=BRACKET_NEGATIVE + ": a county's name"),
    case("Everbrook County Schools", "WA", None, note=BRACKET_NEGATIVE + ": no such county"),
    case(
        "Madley",
        "MI",
        None,
        counties=(ORRIN_CO, OAKMERE_CO),
        near=ADRAMOOR,
        note=BRACKET_NEGATIVE + ": two namesakes in the counties, one beside the point",
    ),
    case(
        "Madley",
        "MI",
        None,
        counties=(ORRIN_CO, OAKMERE_CO),
        near=MADLEY_HEIGHTS,
        note=BRACKET_NEGATIVE + ": two namesakes in the counties, one beside the point",
    ),
    case(
        "Madley",
        "MI",
        "SYN-MI-MADO",
        near=ADRAMOOR,
        note=BRACKET + ": its county said nothing against it; nearest, the other 100 km off",
    ),
    case(
        "Madley",
        "MI",
        "SYN-MI-MADH",
        near=MADLEY_HEIGHTS,
        note=BRACKET + ": nearest, the other 100 km off",
    ),
    case("Madley School District", "MI", "SYN-MI-MADO", counties=ORRIN_CO, note=BRACKET),
    case("Madley Schools", "MI", None, note=BRACKET_NEGATIVE + ": two namesakes"),
    case("Madley (Orrin)", "MI", "SYN-MI-MADO", note=BRACKET + ": as NCES"),
    case("Madley Public Schools", "MI", "SYN-MI-MADH", counties=OAKMERE_CO, note=BRACKET),
    case("Masonby Public Schools", "MI", "SYN-MI-MASI", counties=INGRAM_CO, note=BRACKET),
    case("Masonby", "MI", "SYN-MI-MASM", counties=MONROW_CO, note=BRACKET),
    case("Masonby Schools", "MI", None, note=BRACKET_NEGATIVE + ": two namesakes"),
    case(
        "Monrow Public Schools",
        "MI",
        "SYN-MI-MONR",
        note=BRACKET_NEGATIVE + ": the county another district's bracket names",
    ),
    case("Monrow", "MI", "SYN-MI-MONR", note=BRACKET_NEGATIVE + ": the town's district"),
    case("Jeffrow Schools", "MI", "SYN-MI-JEFM", note=BRACKET),
    case("Jeffrow County Schools", "MI", None, note=BRACKET_NEGATIVE + ": no such county"),
    # A second name in brackets names the district, never only its high school.
    case(
        "North Rockmere",
        "NY",
        "SYN-NY-CARV",
        counties=ROCKMERE_CO,
        note=BRACKET + ": a second name, not its high school",
    ),
    case("North Rockmere CSD", "NY", "SYN-NY-CARV", note=BRACKET + ": a second name"),
    case("North Rockmere Central School District", "NY", "SYN-NY-CARV", note=BRACKET),
    case("Carverton-Stony Mill CSD", "NY", "SYN-NY-CARV", note=BRACKET + ": its own name"),
    case("North Rockmere High School", "NY", "SYN-NY-CARVHS", note=BRACKET),
    case("Rockmere CSD", "NY", None, note=BRACKET_NEGATIVE + ": North Rockmere is not Rockmere"),
    case("South Rockmere Schools", "NY", None, note=BRACKET_NEGATIVE + ": another direction"),
    case("Lake Vestry CSD", "NY", "SYN-NY-EVAN", note=BRACKET + ": a second name"),
    case("Lake Vestry Central Schools", "NY", "SYN-NY-EVAN", note=BRACKET),
    case("Evander-Brantly CSD", "NY", "SYN-NY-EVAN", note=BRACKET + ": its own name"),
    case("Kestrequa", "NY", "SYN-NY-DALN", note=BRACKET + ": a second name alone"),
    case("Kestrequa CSD", "NY", "SYN-NY-DALN", note=BRACKET),
    case("Kestrequa Schools", "NY", "SYN-NY-DALN", note=BRACKET + ": a second name"),
    case("Everbrook - All Schools", "WA", "SYN-WA-EVBQ", counties=QUENBY_CO, note=BRACKET),
    case("Madley", "MI", "SYN-MI-MADO", counties=ORRIN_CO, note=BRACKET),
    case("Madley (Orrin) - Closed", "MI", "SYN-MI-MADO", note=BRACKET + ": as NCES"),
    case("EVERBROOK (Quenby)", "WA", "SYN-WA-EVBQ", note=BRACKET + ": as NCES"),
    case("Berrow-Millan", "OH", "SYN-OH-EDVL", note=BRACKET + ": a former name"),
    case("Berrow-Millan Local Schools", "OH", "SYN-OH-EDVL", note=BRACKET + ": a former name"),
    case("Edvale Local Schools", "OH", "SYN-OH-EDVL", note=BRACKET + ": its own name"),
    case(
        "Killoway ISD",
        "TX",
        "SYN-TX-KILL",
        note=BRACKET_NEGATIVE + ": the town's district, not a charter's second name",
    ),
    case("Killoway", "TX", "SYN-TX-KILL", note=BRACKET_NEGATIVE + ": the town's district"),
    case("Richard Malburn Alter High School", "TX", "SYN-TX-MALBS", note=BRACKET),
    # A legal form, "(THE)" and Arizona's entity number are no part of a name.
    case("Comandra Academy", "OK", "SYN-OK-COMAS", note=BRACKET + ": a legal form"),
    case("Comandra Academy Charter School", "OK", "SYN-OK-COMAS", note=BRACKET),
    case("The Brackendale Charter School", "NY", "SYN-NY-BRKNS", note=BRACKET),
    case("Flagmoor Unified", "AZ", "SYN-AZ-FLAG", note=BRACKET + ": an entity number"),
    case(
        "Flagmoor Unified School District #1",
        "AZ",
        "SYN-AZ-FLAG",
        note=BRACKET + ": an entity number is no district number",
    ),
    case("Flagmoor USD", "AZ", "SYN-AZ-FLAG", note=BRACKET),
    case("Flagmoor Schools", "AZ", "SYN-AZ-FLAG", note=BRACKET),
    case("USD 4192", "AZ", None, note=BRACKET_NEGATIVE + ": an entity number names no district"),
    case("Flagmoor Junior Academy", "AZ", "SYN-AZ-FLJAS", note=BRACKET),
    case(
        "Southmoor Technical Education District of Varnell",
        "AZ",
        "SYN-AZ-SWTE",
        note=BRACKET + ": cut open",
    ),
    case("Friendmoor House Inc.", "AZ", "SYN-AZ-FRND", note="its own name, Inc. and all"),
    case("Friendmoor House", "AZ", "SYN-AZ-FRND", note=BRACKET),
    case("Friendmoor Hauling Inc.", "AZ", None, note="hard negative: a business"),
    case("Brightmoor-School Inc.", "AZ", "SYN-AZ-BRTI", note="the holder whose name says Inc."),
    case(
        "Harrowvale Charter Schools Inc.",
        "AZ",
        None,
        note=BRACKET_NEGATIVE + ": two holders told apart by entity number alone",
    ),
    case(
        "Harrowvale Charter Schools Inc. (81078)",
        "AZ",
        "SYN-AZ-HRV2",
        note=BRACKET + ": the entity number names the holder",
    ),
    case("Harrowvale Charter Schools Inc. (6361)", "AZ", "SYN-AZ-HRV1", note=BRACKET),
    case(
        "Harrowvale Charter Schools Inc. (9999)",
        "AZ",
        None,
        note=BRACKET_NEGATIVE + ": an entity number no holder of the name has",
    ),
    case("Brightmoor-School", "AZ", "SYN-AZ-BRTJS", note="the school of that very name"),
    # A listing that gives a name as NCES writes it, brackets and all.
    case(
        "Masonby Consolidated Schools (Monrow)",
        "MI",
        "SYN-MI-MASM",
        note=BRACKET + ": as NCES, a county a town shares its name with",
    ),
    case("Masonby Public Schools (Ingram)", "MI", "SYN-MI-MASI", note=BRACKET + ": as NCES"),
    case(
        "CARVERTON-STONY MILL CSD (NORTH ROCKMERE)", "NY", "SYN-NY-CARV", note=BRACKET + ": as NCES"
    ),
    case("Flagmoor Unified District (4192)", "AZ", "SYN-AZ-FLAG", note=BRACKET + ": as NCES"),
    case("Comandra Academy (Charter)", "OK", "SYN-OK-COMAS", note=BRACKET + ": as NCES"),
    case("Edvale Local (formerly Berrow-Millan)", "OH", "SYN-OH-EDVL", note=BRACKET + ": as NCES"),
    case(
        "Everbrook School District (Quenby)",
        "WA",
        None,
        counties=TALLIS_CO,
        note=BRACKET_NEGATIVE + ": another county's",
    ),
    case(
        "Masonby Public Schools (Harrowgate)",
        "MI",
        None,
        counties=INGRAM_CO,
        note=BRACKET_NEGATIVE + ": a word the district does not answer to",
    ),
    # A town's system and a district of one school beside it, one name in one town.
    case(
        "Glenmoor Falls",
        "NY",
        None,
        note=NAMESAKE_NEGATIVE + ": the city's system or the common school district",
    ),
    case("Glenmoor Falls City Schools", "NY", "SYN-NY-GLNC"),
    case("Glenmoor Falls Common School District", "NY", "SYN-NY-GLNM"),
    # A school's grades in brackets are no part of its name.
    case("Shellmoor Lake Elementary", "WI", "SYN-WI-SHELE", note=BRACKET + ": grades"),
    case("Shellmoor Lake Primary School", "WI", "SYN-WI-SHELP", note=BRACKET + ": grades"),
    case("Shellmoor Lake Schools", "WI", "SYN-WI-SHEL"),
    # "Common" is a legal form. Two districts of the name in a market's
    # counties are both the market's, whichever lies beside its point; read in
    # whole states, the other lies beyond a market's reach of it.
    case(
        "Tuckermoor",
        "NY",
        None,
        counties=(WESTMOOR_CO, SUFFMOOR_CO),
        near=TUCKERMOOR_SOUTH,
        note=NAMESAKE_NEGATIVE + ": both in the counties, one beside the point",
    ),
    case(
        "Tuckermoor",
        "NY",
        None,
        counties=(WESTMOOR_CO, SUFFMOOR_CO),
        near=TUCKERMOOR_EAST,
        note=NAMESAKE_NEGATIVE + ": both in the counties, one beside the point",
    ),
    case(
        "Tuckermoor",
        "NY",
        "SYN-NY-TUCKC",
        near=TUCKERMOOR_SOUTH,
        note="Common is a legal form; nearest, the other 120 km off",
    ),
    case(
        "Tuckermoor",
        "NY",
        "SYN-NY-TUCKU",
        near=TUCKERMOOR_EAST,
        note="nearest, the other 120 km off",
    ),
    case("Tuckermoor Common School District", "NY", "SYN-NY-TUCKC", note="Common names it"),
    case("Tuckermoor UFSD", "NY", "SYN-NY-TUCKU", note="Union Free names it"),
    case("Tuckermoor", "NY", None, note=NAMESAKE_NEGATIVE + ": two districts of the name"),
    # A level word that names a place.
    case("High Township", "NJ", "SYN-NJ-HIGHT", note=PLACE + ": a level word names a township"),
    case("High Township Schools", "NJ", "SYN-NJ-HIGHT"),
    case("High Township Public School District", "NJ", "SYN-NJ-HIGHT"),
    case("High Township Middle School", "NJ", "SYN-NJ-HIGHTM"),
    case("High Township High School", "NJ", "SYN-NJ-HIGHTH"),
    case("High Township Elementary #1", "NJ", "SYN-NJ-HIGHTE"),
    # A listing of an abbreviation alone, or of another state's district code.
    case("St.", "TX", None, note="hard negative: an abbreviation alone"),
    case("Mt.", "TX", None, note="hard negative: an abbreviation alone"),
    case("Ft", "TX", None, note="hard negative: an abbreviation alone"),
    case("Street Elementary", "TX", "SYN-TX-STREL", counties=COLDMOOR_CO),
    case("Mount Elementary", "TX", "SYN-TX-MTEL", counties=COLDMOOR_CO),
    case("MSAD 51", "IL", None, note=CODE_NEGATIVE + ": Maine's series in Illinois"),
    case("Consolidated SD 51", "IL", "SYN-IL-CSD51"),
    # A state beside the name tells namesakes of a market's states apart, wherever
    # it stands: before the designator, in brackets, after a comma or a hyphen.
    case("Salmere MA Public", ("MA", "NH"), "SYN-MA-SALM", note=STATE),
    case("Salmere NH Public", ("MA", "NH"), "SYN-NH-SALM", note=STATE),
    case("Salmere Public (MA)", ("MA", "NH"), "SYN-MA-SALM", note=STATE),
    case("SALMERE SCHOOLS-NH", ("MA", "NH"), "SYN-NH-SALM", note=STATE),
    case("Salmere, N.H.", ("MA", "NH"), "SYN-NH-SALM", note=STATE + ": abbreviated"),
    case("Salmere High School NH", ("MA", "NH"), "SYN-NH-SALMH", note=STATE),
    case("Salmere High School, Salmere MA", ("MA", "NH"), "SYN-MA-SALMH", note=STATE),
    case("Salmere Public", ("MA", "NH"), None, note=STATE_NEGATIVE + ": namesakes, no state"),
    case("Salmere MA Public", "NH", None, note=STATE_NEGATIVE + ": another state never widens"),
    case("Salmere NH Public", "MA", None, note=STATE_NEGATIVE + ": another state never widens"),
    case("Salmere Public (ME)", ("MA", "NH"), None, note=STATE_NEGATIVE + ": another state"),
    case("Knoxmere County, TN Schools", ("TN", "KY"), "SYN-TN-KNXC", note=STATE),
    case("Knoxmere County, KY Schools", ("TN", "KY"), "SYN-KY-KNXC", note=STATE),
    case("Knoxmere County, Ky Schools", ("TN", "KY"), "SYN-KY-KNXC", note=STATE),
    case("KNOXMERE COUNTY SCHOOLS-KY", ("TN", "KY"), "SYN-KY-KNXC", note=STATE),
    case("Knoxmere Co. KY Schools", ("TN", "KY"), "SYN-KY-KNXC", note=STATE),
    case("Knoxmere County Schools, Tennessee", ("TN", "KY"), "SYN-TN-KNXC", note=STATE),
    case("Knoxmere County, Kentucky Schools", ("TN", "KY"), "SYN-KY-KNXC", note=STATE),
    case("Knoxmere County Schools", ("TN", "KY"), None, note=STATE_NEGATIVE + ": no state"),
    case("Knoxmere County Schools, TN", "KY", None, note=STATE_NEGATIVE + ": another state"),
    case("Collinsby (TX) ISD", ("TX", "OK"), "SYN-TX-COLL", note=STATE),
    case("Collinsby (OK) Public Schools", ("TX", "OK"), "SYN-OK-COLL", note=STATE),
    case("Collinsby (OK) Public Schools", "TX", None, note=STATE_NEGATIVE + ": another state"),
    case("Madmere County NC Schools", ("NC", "SC", "GA"), "SYN-NC-MADC", note=STATE),
    case("Madmere County GA Schools", ("NC", "SC", "GA"), "SYN-GA-MADC", note=STATE),
    case("Madmere County Schools (N.C.)", ("NC", "SC", "GA"), "SYN-NC-MADC", note=STATE),
    case(
        "Madmere County SC Schools",
        ("NC", "SC", "GA"),
        None,
        note=STATE_NEGATIVE + ": no namesake in that state",
    ),
    case("Pocamere Co. WV Schools", ("VA", "WV"), "SYN-WV-POCA", note=STATE),
    case("Pocamere Co. VA Schools", ("VA", "WV"), "SYN-VA-POCA", note=STATE),
    case("Oarkby, Ark.", ("MO", "AR"), "SYN-AR-OARK", note=STATE + ": abbreviated"),
    case("Oarkby (Ark.)", ("MO", "AR"), "SYN-AR-OARK", note=STATE + ": abbreviated"),
    case("Oarkby (MO) R-80", ("MO", "AR"), "SYN-MO-OARK", note=STATE),
    # The Kansas City lists: "<district> R-n School <town> MO", "<town> KS Schools -
    # USD n", "<city> MO Public Schools".
    case("Holdenby R-III School Holdenby MO", ("MO", "KS"), "SYN-MO-HOLD", note=STATE),
    case("Holdenby R-3 Schools Holdenby MO", ("MO", "KS"), "SYN-MO-HOLD", note=STATE),
    case("Holdenby Casmere MO R-III School", ("MO", "KS"), "SYN-MO-HOLD", note=STATE),
    case("Holdenby R-III School", "MO", "SYN-MO-HOLD", note="a district's number says district"),
    case("Holdenby KS Schools - USD 461", ("MO", "KS"), "SYN-KS-HOLD", note=STATE),
    case("Ballmere R-II School Butterby MO", ("MO", "KS"), "SYN-MO-BALL", note=STATE),
    case("Ballmere R-II Sch. Butterby, MO", ("MO", "KS"), "SYN-MO-BALL", note=STATE),
    case("Trinity Church Holdenby MO", ("MO", "KS"), None, note=STATE_NEGATIVE + ": a church"),
    case("Kessby City MO Public Schools", ("MO", "KS"), "SYN-MO-KESS", note=STATE),
    case("Kessby City KS Public Schools-USD 500", ("MO", "KS"), "SYN-KS-KESS", note=STATE),
    case("Kessby City KS USD500", ("MO", "KS"), "SYN-KS-KESS", note=STATE),
    case("Kessby City, Kansas Public Schools", ("MO", "KS"), "SYN-KS-KESS", note=STATE),
    case(
        "Kessby City, Kansas Public Schools",
        "MO",
        None,
        note=STATE_NEGATIVE + ": another state, by its name",
    ),
    case("Tonganby KS Schools - USD 464", ("MO", "KS"), "SYN-KS-TONG", note=STATE),
    case("Tonganby MO R-I Schools", ("MO", "KS"), "SYN-MO-TONG", note=STATE),
    case(
        "Jonmere County KS Meals on Wheels",
        ("MO", "KS"),
        None,
        note=STATE_NEGATIVE + ": a meals program",
    ),
    case(
        "Jonmere County KS Nutrition Centers",
        ("MO", "KS"),
        None,
        note=STATE_NEGATIVE + ": a code before a name word",
    ),
    case("Jonmere County KS Schools", ("MO", "KS"), "SYN-KS-JONC", note=STATE),
    # Codes that are also words: "MS" after a name is Middle School, "Co." County.
    case("Germanby MS", ("TN", "MS"), "SYN-TN-GERMS", note=STATE_NEGATIVE + ": Middle School"),
    case("Germanby, MS", ("TN", "MS"), "SYN-MS-GERM", note=STATE + ": after a comma"),
    case("Germanby (MS)", ("TN", "MS"), "SYN-MS-GERM", note=STATE + ": in brackets"),
    case("Germanby, TN", ("TN", "MS"), "SYN-TN-GERD", note=STATE),
    case(
        "Idamere Academy ES/MS",
        ("TN", "MS"),
        "SYN-TN-IDAES",
        note=STATE_NEGATIVE + ": a slash joins levels",
    ),
    case(
        "Freemere Prep Academy - MS",
        ("TN", "MS"),
        "SYN-TN-FREMS",
        note=STATE_NEGATIVE + ": Middle School after a hyphen",
    ),
    case("Brenmere Co. Schools", "CO", "SYN-CO-BRENC", note=STATE_NEGATIVE + ": Co. is County"),
    case("BRENMERE CO SCHOOLS", "CO", "SYN-CO-BRENC", note=STATE_NEGATIVE + ": CO is County"),
    case(
        "Putmere-In-Bay Local Schools",
        ("OH", "IN"),
        "SYN-OH-PUTB",
        note=STATE_NEGATIVE + ": hyphens join a name",
    ),
    case(
        "Westmere-Washington Schools",
        ("IN", "WA"),
        "SYN-IN-WESW",
        note=STATE_NEGATIVE + ": hyphens join a name",
    ),
    case(
        "Evermere Montessori School - AR",
        "CA",
        "SYN-CA-EVAR",
        note=STATE_IN_NAME + ": the school's own name ends with it",
    ),
    # A state that is part of a name: read as the name, spelled either way.
    case("Southern NH Brightmere Academy", ("MA", "NH"), "SYN-NH-SNHB", note=STATE_IN_NAME),
    case(
        "Southern New Hampshire Brightmere Academy",
        ("MA", "NH"),
        "SYN-NH-SNHB",
        note=STATE_IN_NAME + ": spelled out",
    ),
    case("Southern Brightmere Academy", "NH", "SYN-NH-SBRI", note=STATE_IN_NAME_NEGATIVE),
    case("Western PA Wexmere School for the Deaf", "PA", "SYN-PA-WPWD", note=STATE_IN_NAME),
    case("Western Pa. Wexmere School for the Deaf", "PA", "SYN-PA-WPWD", note=STATE_IN_NAME),
    case("GST MI Works - Baxmere", "MI", None, note=STATE_IN_NAME_NEGATIVE + ": a job center"),
    case("GST MI Works-Baxmere", "MI", None, note=STATE_IN_NAME_NEGATIVE + ": a job center"),
    case("Baxmere MI Public Schools", ("MI", "WI"), "SYN-MI-BAXM", note=STATE),
    # More of a list's ways: a county named as a state is, dotted initials, a
    # town after a level or a district's code, and the town and state in brackets.
    case("WASHINGTON COUNTY SCHOOLS-KY", ("TN", "KY"), "SYN-KY-WASC", note=STATE),
    case("Washington County, TN Schools", ("TN", "KY"), "SYN-TN-WASC", note=STATE),
    case("Washington Co. KY Schools", ("TN", "KY"), "SYN-KY-WASC", note=STATE),
    case("Washington County Schools", ("TN", "KY"), None, note=STATE_NEGATIVE + ": no state"),
    case(
        "WASHINGTON COUNTY SCHOOLS-KY",
        "TN",
        None,
        note=STATE_NEGATIVE + ": another state never widens",
    ),
    case("Collinsby TX I.S.D.", ("TX", "OK"), "SYN-TX-COLL", note=STATE + ": dotted initials"),
    case("Salmere High School Salmere NH", ("MA", "NH"), "SYN-NH-SALMH", note=STATE),
    case("Tonganby Schools - USD 464 Tonganby KS", ("MO", "KS"), "SYN-KS-TONG", note=STATE),
    case("Holdenby Schools (Holdenby, KS)", ("MO", "KS"), "SYN-KS-HOLD", note=STATE),
    case("Holdenby R-III (MO)", ("MO", "KS"), "SYN-MO-HOLD", note=STATE),
    case("Millmere Middle KY", ("TN", "KY"), "SYN-KY-MILMS", note=STATE),
    case("Millmere Middle, Tenn.", ("TN", "KY"), "SYN-TN-MILMS", note=STATE),
    case("Millmere Middle", ("TN", "KY"), None, note=STATE_NEGATIVE + ": namesakes, no state"),
    # A state outside the market never widens the search, however it is written.
    case(
        "Salmere High School NH",
        "MA",
        None,
        note=STATE_NEGATIVE + ": another state never widens",
    ),
    case(
        "Holdenby R-III School Holdenby MO",
        "KS",
        None,
        note=STATE_NEGATIVE + ": another state never widens",
    ),
    case(
        "Tonganby KS Schools - USD 464",
        "MO",
        None,
        note=STATE_NEGATIVE + ": another state never widens",
    ),
    case(
        "Madmere County GA Schools",
        ("NC", "SC"),
        None,
        note=STATE_NEGATIVE + ": another state never widens",
    ),
    case(
        "Pocamere Co. VA Schools", "WV", None, note=STATE_NEGATIVE + ": another state never widens"
    ),
    case("Oarkby, Ark.", "MO", None, note=STATE_NEGATIVE + ": another state never widens"),
    case("Millmere Middle KY", "TN", None, note=STATE_NEGATIVE + ": another state never widens"),
    case("Germanby, MS", "TN", None, note=STATE_NEGATIVE + ": another state never widens"),
    # A town and its state beside what is no school, as the Kansas City lists write
    # them.
    case(
        "Salmere NH Chamber of Commerce",
        ("MA", "NH"),
        None,
        note=STATE_NEGATIVE + ": a code before a name word",
    ),
    case("Holdenby MO Public Library", ("MO", "KS"), None, note=STATE_NEGATIVE + ": a library"),
    case(
        "Kessby City KS Community College", ("MO", "KS"), None, note=STATE_NEGATIVE + ": a college"
    ),
    case(
        "Kessby City MO Municipal Court",
        ("MO", "KS"),
        None,
        note=STATE_NEGATIVE + ": a court",
    ),
    case(
        "Jonmere County KS Home-Delivered Meals",
        ("MO", "KS"),
        None,
        note=STATE_NEGATIVE + ": a meals program",
    ),
    # The state between the name and its town; a qualifier after the state; a
    # code that is also a word, after "County" and before "Schools"; a county's
    # numbered district without "Co.".
    case("Shawby R-3 MO Chilby", ("MO", "KS"), "SYN-MO-SHAW", note=STATE + ": then its town"),
    case("Shawby R-III MO Chilby", ("MO", "KS"), "SYN-MO-SHAW", note=STATE + ": then its town"),
    case("Shawby KS Schools", ("MO", "KS"), "SYN-KS-SHAW", note=STATE),
    case("Shawby R-3 MO Chilby", "KS", None, note=STATE_NEGATIVE + ": another state"),
    case("Westmoor R-2 Schools MO", ("MO", "KS"), "SYN-MO-WESTM", note=STATE + ": Co. left out"),
    case("Westmoor R-2", "MO", "SYN-MO-WESTM", note="a county's numbered district, Co. left out"),
    case("Westmoor Co. R-II", "MO", "SYN-MO-WESTM"),
    case("Westmoor Schools", "MO", None, note="hard negative: county and number left out"),
    case("Westmoor KS Schools", ("MO", "KS"), "SYN-KS-WESTM", note=STATE),
    case("Nortonby, VA City Schools", ("VA", "TN"), "SYN-VA-NORC", note=STATE + ": then City"),
    case("Nortonby, TN City Schools", ("VA", "TN"), "SYN-TN-NORC", note=STATE + ": then City"),
    case("Nortonby City Schools", ("VA", "TN"), None, note=STATE_NEGATIVE + ": no state"),
    case("Randby Co. AL Schools", ("GA", "AL"), "SYN-AL-RANC", note=STATE + ": AL after Co."),
    case("Randby Co. GA Schools", ("GA", "AL"), "SYN-GA-RANC", note=STATE),
    case("Randby County Schools", ("GA", "AL"), None, note=STATE_NEGATIVE + ": no state"),
    case("Harrby County MS Schools", ("MS", "AL"), "SYN-MS-HARC", note=STATE + ": MS after County"),
    case("Harrby County AL Schools", ("MS", "AL"), "SYN-AL-HARC", note=STATE),
    case(
        "Harrby County MS",
        ("MS", "AL"),
        None,
        note=STATE_NEGATIVE + ": MS may be a middle school",
    ),
    # A town a list joins to the name with a hyphen.
    case("Southbrook Local SD-Ravenby", "OH", "SYN-OH-SBRR", note="a town joined by a hyphen"),
    case("Southbrook Local SD-Appleby", "OH", "SYN-OH-SBRA", note="a town joined by a hyphen"),
    case("Southbrook Local SD", "OH", None, note="hard negative: two districts of the name"),
    case("Sacred Heart School-Troyby MO", ("MO", "IL"), "SYN-MO-SHTR", note=STATE + ": its town"),
    case("Sacred Heart School MO", ("MO", "IL"), None, note=STATE_NEGATIVE + ": two in MO"),
    case("Sacred Heart School (IL)", ("MO", "IL"), "SYN-IL-SHSP", note=STATE),
    # A county's court, and a county's district that runs virtual schools across
    # the state, which is still the market's whole.
    case("Hertby Co NC District Court", ("NC", "VA"), None, note=CIVIC + ": a court"),
    case("Hertby General District Court", "NC", None, note=CIVIC + ": a court"),
    case("Hertby Co NC Schools", ("NC", "VA"), "SYN-NC-HERC", note=STATE),
    case(
        "Johnsmere County, TN Schools",
        ("TN", "VA"),
        "SYN-TN-JOHC",
        counties=JOHNSMERE_CO,
        note=STATE + ": a district with virtual schools elsewhere",
    ),
    case(
        "JOHNSMERE CO. SCHOOLS",
        "TN",
        "SYN-TN-JOHC",
        counties=JOHNSMERE_CO,
        note="a district with virtual schools elsewhere",
    ),
    # A state's code that is no state, in a school's own name: it names that school.
    case(
        "Tomas Cigarmoor MD Elementary",
        ("VA", "MD", "DC"),
        "SYN-VA-CIGMD",
        note=STATE_IN_NAME + ": a doctor, not Maryland",
    ),
    case(
        "Jonesmere Int SC",
        ("NC", "SC"),
        "SYN-NC-JONSC",
        note=STATE_IN_NAME + ": School, not South Carolina",
    ),
    case(
        "Jonesmere Int SC",
        "NC",
        "SYN-NC-JONSC",
        note=STATE_IN_NAME + ": School, not a state outside the market",
    ),
    case(
        "Cigarmoor MD Schools",
        ("VA", "MD", "DC"),
        None,
        note=STATE_NEGATIVE + ": Maryland has no Cigarmoor",
    ),
    # A Kansas City-like market whose lists carry churches: a church's listing
    # never names its parish's school.
    *(
        case(listing, MO_KS, None, counties=KC, note=PARISH_NEGATIVE)
        for listing in (
            "St. Peter's Parish: No Mass",
            "St. Peter's Parish",
            "St. Peter's Catholic Church",
            "St. Peter's Church - Services Cancelled",
            "St. Peter's Bible Study",
            "Christ the King Church - services cancelled",
            "Christ the King Parish",
            "Christ the King Parish - No Masses",
            "Christ the King Sunday School",
            "Church of the Visitation",
            "Visitation Parish",
            "St. Elizabeth Parish: Mass canceled",
            "St. Elizabeth Religious Education",
            "Our Lady of Sorrows Parish",
            "Holy Spirit Catholic Church",
        )
    ),
    # Filed among churches, a parish's name alone is its church's.
    case("Visitation", MO_KS, None, counties=KC, note=PARISH_NEGATIVE, category="Churches"),
    case(
        "St. Peter's School",
        MO_KS,
        "SYN-MO-KSTPE",
        counties=KC,
        note=PARISH + ": a school's word, wherever it is filed",
        category="Church",
    ),
    case(
        "St. Peter's Parish School",
        MO_KS,
        "SYN-MO-KSTPE",
        counties=KC,
        note=PARISH + ": a school's word, wherever it is filed",
        category="Religious",
    ),
    case(
        "Holy Spirit",
        MO_KS,
        None,
        counties=KC,
        note=PARISH_NEGATIVE,
        category="Pre-Schools/Daycare",
    ),
    # A saint's or a devotion's name alone is the church's as much as the
    # school's: the unmatched queue, whatever town it adds.
    *(
        case(listing, MO_KS, None, counties=KC, note=PARISH_NEGATIVE + ": church or school")
        for listing in (
            "St. Peter's",
            "Christ the King",
            "Visitation",
            "St. Elizabeth",
            "Our Lady of Sorrows",
            "Holy Spirit",
            "St. Peter's - Kanby",
            "Visitation (Kanby)",
            "St. Peter's Catholic",
        )
    ),
    case(
        "Christ the King",
        MO_KS,
        None,
        counties=KC,
        note=PARISH_NEGATIVE + ": a section that says nothing",
        category="Closings",
    ),
    # Filed among schools, the one school of the name in the market's counties.
    case("Christ the King", MO_KS, "SYN-KS-KCTK", counties=KC, note=PARISH, category="Schools"),
    case("Visitation", MO_KS, "SYN-MO-KVIS", counties=KC, note=PARISH, category="Parochial School"),
    case("St. Elizabeth", MO_KS, "SYN-MO-KSTEL", counties=KC, note=PARISH, category="Schools"),
    case("Our Lady of Sorrows", MO_KS, "SYN-KS-KOLS", counties=KC, note=PARISH, category="SCHOOLS"),
    case("Holy Spirit", MO_KS, "SYN-KS-KHSP", counties=KC, note=PARISH, category="School"),
    case("St. Peter's", MO_KS, "SYN-MO-KSTPE", counties=KC, note=PARISH, category="Schools"),
    case(
        "St. Peter's",
        MO_KS,
        "SYN-KS-LSTPE",
        counties=LEABY_KS_CO,
        note=PARISH + ": the other market's",
        category="Schools",
    ),
    case(
        "St. Peter's",
        MO_KS,
        None,
        counties=(*KC, LEABY_KS_CO),
        note=PARISH_NEGATIVE + ": two in the market",
        category="Schools",
    ),
    # A school's word says the school, whatever its church.
    case("St. Peter's School", MO_KS, "SYN-MO-KSTPE", counties=KC, note=PARISH),
    case("St. Peter's Catholic School", MO_KS, "SYN-MO-KSTPE", counties=KC, note=PARISH),
    case("Christ the King School", MO_KS, "SYN-KS-KCTK", counties=KC, note=PARISH),
    case("Christ the King Parish School", MO_KS, "SYN-KS-KCTK", counties=KC, note=PARISH),
    case("Christ the King Catholic School", MO_KS, "SYN-KS-KCTK", counties=KC, note=PARISH),
    case("Visitation School", MO_KS, "SYN-MO-KVIS", counties=KC, note=PARISH),
    case("St. Elizabeth School", MO_KS, "SYN-MO-KSTEL", counties=KC, note=PARISH),
    case("Our Lady of Sorrows Catholic School", MO_KS, "SYN-KS-KOLS", counties=KC, note=PARISH),
    case(
        "Holy Cross Catholic School",
        MO_KS,
        "SYN-KS-KHCRC",
        counties=KC,
        note=PARISH + ": the one that says its faith",
    ),
    case(
        "Holy Cross School",
        MO_KS,
        None,
        counties=KC,
        note=PARISH_NEGATIVE + ": two Holy Cross schools",
    ),
    case(
        "St. Paul's Catholic School",
        MO_KS,
        None,
        counties=KC,
        note=PARISH_NEGATIVE + ": its St. Paul's is another church's",
    ),
    # A parish school just past the market's counties bears the name of one in
    # them: the counties do not say which the list means.
    case("Holy Family School", MO_KS, None, counties=KC, note=JUST_PAST),
    case("Holy Family Catholic School", MO_KS, None, counties=KC, note=JUST_PAST),
    case("Holy Family", MO_KS, None, counties=KC, note=JUST_PAST, category="Schools"),
    case("Holy Family School", MO_KS, None, counties=OTTABY_KS_CO, note=JUST_PAST),
    case("Holy Family Parish: No Mass", MO_KS, None, counties=KC, note=PARISH_NEGATIVE),
    case(
        "Holy Family School",
        MO_KS,
        "SYN-MO-KHFAM",
        counties=KC,
        near=KANBY,
        note=PARISH + ": a point in the market says which",
    ),
    case(
        "Holy Family Catholic School",
        "MO",
        "SYN-MO-KHFAM",
        counties=KC,
        note=PARISH + ": its namesake's state is not the list's",
    ),
    # A twin in a state of the market just past its counties: New Hampshire's
    # "Hanbury School District" is the listing word for word, Massachusetts's
    # "Hanbury", in the counties, is shorter; neither is the listing's.
    *(
        case(listing, ("MA", "NH"), None, counties=BOSBY, note=JUST_PAST)
        for listing in (
            "Hanbury School District",
            "Hanbury SD",
            "Hanbury Public Schools",
            "Hanbury Schools",
            "HANBURY SCHOOL DISTRICT - ALL SCHOOLS",
            "Hanbury High School",
            "Hanbury High",
            "Hanbury HS",
            "Russet Elementary School",
            "Russet Elem.",
        )
    ),
    case(
        "Hanbury School District",
        ("MA", "NH"),
        None,
        counties=(*BOSBY, HANBY_NH_CO),
        note="hard negative: both in the counties",
    ),
    case("Hanbury School District", ("MA", "NH"), None, note="hard negative: two in the states"),
    # Only the market's states hold a listing's namesakes.
    case("Hanbury School District", "MA", "SYN-MA-HAN", counties=BOSBY, note="one state"),
    case("Hanbury High School", "MA", "SYN-MA-HANHS", counties=BOSBY, note="one state"),
    case("Russet Elementary School", "MA", "SYN-MA-RUSES", counties=BOSBY, note="one state"),
    # From New Hampshire's side, Massachusetts's Hanbury lies far off.
    case("Hanbury School District", ("MA", "NH"), "SYN-NH-HANSD", counties=HANBY_NH_CO),
    case("Hanbury High School", ("MA", "NH"), "SYN-NH-HANHS", counties=HANBY_NH_CO),
    # A point in the market says which, as it does between namesakes in it.
    case(
        "Hanbury High School",
        ("MA", "NH"),
        "SYN-MA-HANHS",
        counties=BOSBY,
        near=HANBURY_MA,
        note="a namesake just past the counties, and a point that says which",
    ),
    # A twin far beyond the counties, 160 km north, is none of the listing's.
    case("Lyttleby School District", ("MA", "NH"), "SYN-MA-LYT", counties=BOSBY, note="far twin"),
    case("Lyttleby Public Schools", ("MA", "NH"), "SYN-MA-LYT", counties=BOSBY, note="far twin"),
    case("Lyttleby High School", ("MA", "NH"), "SYN-MA-LYTHS", counties=BOSBY, note="far twin"),
    case("Lyttleby High School", ("MA", "NH"), None, note="hard negative: two in the states"),
    # A district's number names a district, never a school no district runs.
    case(
        "St. Jarvis R-1",
        "MO",
        None,
        counties=JARVIS_PARISH_CO,
        note="hard negative: a district's number, and a private school of the name",
    ),
    case("St. Jarvis R-I", "MO", None, counties=JARVIS_PARISH_CO, note="hard negative: R-I"),
    case("St. Jarvis R-1", "MO", "SYN-MO-JARD", note="the numbered district"),
    case("St. Jarvis R-I School District", "MO", "SYN-MO-JARD", counties=JARVIS_CO),
    case("St. Jarvis Catholic School", "MO", "SYN-MO-JARC", counties=JARVIS_PARISH_CO),
    # NCES naming habits a closings list reads the other way.
    # Tennessee: "<city> City Schools" for the district NCES names by the city.
    case("Murrowby City Schools", "TN", "SYN-TN-MURB", note=HABIT),
    case("Murrowby City School District", "TN", "SYN-TN-MURB", note=HABIT),
    case("MURROWBY CITY SCHOOLS - Closed", "TN", "SYN-TN-MURB", note=HABIT),
    case("Murrowby City Schools", "TN", "SYN-TN-MURB", counties=HABIT_TN_CO, note=HABIT),
    case("Murrowby Schools", "TN", "SYN-TN-MURB"),
    case("Murrowby City", "TN", None, note=HABIT_NEGATIVE + ": the city, no school's word"),
    case("Murrowby, City of", "TN", None, note=CIVIC),
    case("Rutherby County Schools", "TN", "SYN-TN-RUTC"),
    case("Tullby City Schools", "TN", None, note=HABIT_NEGATIVE + ": its county's bears it too"),
    case("Tullby County Schools", "TN", "SYN-TN-TULC"),
    case("Tullby Schools", "TN", "SYN-TN-TULB", note="the city's, not the county's"),
    # Michigan: an intermediate school district, which NCES calls ISD.
    case("Washby Intermediate School District", "MI", "SYN-MI-WASI", note=HABIT),
    case("Washby Int. School District", "MI", "SYN-MI-WASI", note=HABIT),
    case("Washby Intermediate SD", "MI", "SYN-MI-WASI", note=HABIT),
    case("Washby Intermediate District", "MI", "SYN-MI-WASI", note=HABIT),
    case("WASHBY ISD", "MI", "SYN-MI-WASI"),
    case("Washby Public Schools", "MI", "SYN-MI-WASP"),
    case("Washby Schools", "MI", "SYN-MI-WASP", note="the township's, not the county's ISD"),
    case("Washby Intermediate School", "MI", None, note=HABIT_NEGATIVE + ": a school's level"),
    # Indiana: NCES's "Com", "Con", "Cnt" and "Co" spelled out.
    case("South Ripton Community Schools", "IN", "SYN-IN-SRIP", note=HABIT),
    case("South Ripton Community School Corporation", "IN", "SYN-IN-SRIP", note=HABIT),
    case("South Ripton Comm. Schools", "IN", "SYN-IN-SRIP", note=HABIT),
    case("South Ripton High School", "IN", "SYN-IN-SRIPH", counties=HABIT_IN_A),
    case("Bartley Consolidated School Corp", "IN", "SYN-IN-BART", note=HABIT),
    case("Bartley Consolidated Schools", "IN", "SYN-IN-BART", note=HABIT),
    case("Brownsby Central Community Schools", "IN", "SYN-IN-BROW", note=HABIT),
    case("Brownsby Central Community School Corporation", "IN", "SYN-IN-BROW", note=HABIT),
    case("Huntley County Community Schools", "IN", "SYN-IN-HUNT", note=HABIT),
    case("Huntley Co. Community Schools", "IN", "SYN-IN-HUNT", note=HABIT),
    case("Southwestern Jeffery County Consolidated Schools", "IN", "SYN-IN-JEFF", note=HABIT),
    case("Norwester Consolidated School Corporation", "IN", "SYN-IN-NWC", note=HABIT),
    case(
        "Norwester School Corporation",
        "IN",
        None,
        note=HABIT_NEGATIVE + ": two of one name, one Consolidated, two counties apart",
    ),
    case("Norwester School Corporation", "IN", "SYN-IN-NWS", counties=HABIT_IN_C),
    # Pennsylvania: a township's district without "Township"; a township's and a
    # borough's of one name; a township's beside one whose "Central" names it.
    case("Bensby School District", "PA", "SYN-PA-BENT", note=HABIT),
    case("Bensby Schools", "PA", "SYN-PA-BENT", note=HABIT),
    case("Bensby Township School District", "PA", "SYN-PA-BENT"),
    case("Bensby Twp. SD", "PA", "SYN-PA-BENT"),
    case("Bensby Borough", "PA", None, note=HABIT_NEGATIVE + ": a borough, no school's word"),
    case("Bensby, Township of", "PA", None, note=CIVIC),
    case(
        "Bristow School District",
        "PA",
        None,
        note=HABIT_NEGATIVE + ": a township's and a borough's",
    ),
    case("Bristow Township School District", "PA", "SYN-PA-BRIT"),
    case("Bristow Borough School District", "PA", "SYN-PA-BRIB"),
    case(
        "Mannby School District",
        "PA",
        None,
        note=HABIT_NEGATIVE + ": a township's, and one whose Central names it",
    ),
    case("Mannby Central School District", "PA", "SYN-PA-MANC"),
    case("Mannby Central Schools", "PA", "SYN-PA-MANC"),
    case("Mannby Township School District", "PA", "SYN-PA-MANT"),
    # New Jersey: "Township" NCES leaves out; a city's and a township's.
    case("Cherrow Hill Township School District", "NJ", "SYN-NJ-CHER", note=HABIT),
    case("Cherrow Hill Twp. Public Schools", "NJ", "SYN-NJ-CHER", note=HABIT),
    case(
        "Cherrow Hill Township", "NJ", None, note=HABIT_NEGATIVE + ": a township, no school's word"
    ),
    case("Unionby Schools", "NJ", None, note=HABIT_NEGATIVE + ": a city's and a township's"),
    case("Unionby City Schools", "NJ", "SYN-NJ-UNIC"),
    case("Unionby Township Schools", "NJ", "SYN-NJ-UNIT"),
    case(
        "Unionby Borough School District",
        "NJ",
        None,
        note=HABIT_NEGATIVE + ": both say another municipality",
    ),
    # Texas: "MT" ends one name of a pair; an ISD and its intermediate school.
    case("Eagleby Mountain Saginow ISD", "TX", "SYN-TX-EAGM", note=HABIT),
    case("Eagleby Mountain-Saginow ISD", "TX", "SYN-TX-EAGM", note=HABIT),
    case("Eagleby Mt. Saginow ISD", "TX", "SYN-TX-EAGM", note=HABIT),
    case("Braxby Intermediate", "TX", "SYN-TX-BRAXI", counties=HABIT_TX_CO),
    case("Braxby Intermediate School", "TX", "SYN-TX-BRAXI"),
    case("Braxby ISD", "TX", "SYN-TX-BRAX"),
    # Ohio: a city's district NCES names "Local".
    case("Lockby City Schools", "OH", "SYN-OH-LOCK", note=HABIT),
    case("Lockby Local Schools", "OH", "SYN-OH-LOCK"),
    # A direction the NCES name does not say, beside a municipal word it leaves out.
    case(
        "W. Cherrow Hill Township School District",
        "NJ",
        None,
        note=DIRECTION_NEGATIVE + ": no West Cherrow Hill",
    ),
    case("E. Cherrow Hill Twp. Public Schools", "NJ", None, note=DIRECTION_NEGATIVE),
    case("N. Eagleby Mountain Saginow ISD", "TX", None, note=DIRECTION_NEGATIVE),
    case("S. Brownsby Central Community Schools", "IN", None, note=DIRECTION_NEGATIVE),
    case("E. South Ripton Community Schools", "IN", None, note=DIRECTION_NEGATIVE),
    case("W. Southwestern Jeffery County Consolidated", "IN", None, note=DIRECTION_NEGATIVE),
    # A private "Independent School", and a cooperative school.
    case("The Stonby Independent School", "PA", "SYN-PA-STONE", note="not an ISD"),
    case("Stonby Independent School", "PA", "SYN-PA-STONE", note="not an ISD"),
    case("Hillby Coop. Charter Public School", "MA", "SYN-MA-HILCS", note=HABIT),
    case("Hillby Co-op Charter Public School", "MA", "SYN-MA-HILCS", note=HABIT),
    # Missouri's state schools; a university's initials; "CS" inside a name; a
    # charter school NCES does not call one.
    case("Mapleby Valley State School", "MO", "SYN-MO-MAPV", note=HABIT),
    case("Mapleby Valley State School", "MO", "SYN-MO-MAPV", counties=HABIT_MO_CO, note=HABIT),
    case("Mapleby Valley School", "MO", "SYN-MO-MAPV"),
    case("TEXBY A&M", "TX", None, note="hard negative: a university's initials"),
    case("Texby A&M University", "TX", None, note="hard negative: a university"),
    case("Texby City ISD", "TX", "SYN-TX-TEXC"),
    case("Pennby Hills Charter School of Enterprise", "PA", "SYN-PA-PENCS", note=HABIT),
    case("Memby Merit Academy Charter School", "TN", "SYN-TN-MERIT", note=HABIT),
    case("Memby Merit Academy", "TN", "SYN-TN-MERIT"),
    case("Univby Academy Charter School", "MO", "SYN-MO-UNIV", note=HABIT + ": the district"),
    case("Univby Academy", "MO", "SYN-MO-UNIV", note=OWN_NAME),
    case(
        "Memby Merritt Academy Charter School",
        "TN",
        None,
        counties=HABIT_MO_CO,
        note="hard negative: no academy of the name in the counties",
    ),
    # A county NCES ends a name with is no word of it.
    case("Rivenby (Harlan)", "MI", "SYN-MI-RIVO", note=BRACKET + ": as NCES"),
    case("Rivenby (Harlan) - Closed", "MI", "SYN-MI-RIVO", note=BRACKET + ": as NCES"),
    case("Rivenby School District", "MI", "SYN-MI-RIVO", counties=HABIT_MI_B, note=BRACKET),
    case("Rivenby", "MI", "SYN-MI-RIVO", counties=HABIT_MI_B, note=BRACKET),
    case("Rivenby Schools", "MI", None, note=BRACKET_NEGATIVE + ": two namesakes"),
    case("Rivenby Public Schools", "MI", "SYN-MI-RIVH", counties=HABIT_MI_C, note=BRACKET),
    # A list's section that names a state of the market.
    case(
        "Scitby Public Schools",
        ("MA", "RI"),
        "SYN-RI-SCIT",
        category="RI Public Schools",
        note="the section names the state",
    ),
    case(
        "Scitby Public Schools",
        ("MA", "RI"),
        "SYN-MA-SCIT",
        category="MA Public Schools",
        note="the section names the state",
    ),
    case("Scitby Public Schools", ("MA", "RI"), "SYN-RI-SCIT", category="Schools-RI"),
    case(
        "Scitby Public Schools",
        ("MA", "RI"),
        None,
        note="hard negative: one town's district in each state",
    ),
    case(
        "Scitby Public Schools",
        ("MA", "RI"),
        None,
        category="CT Public Schools",
        note="hard negative: a section names a state outside the market",
    ),
    # A town's elementary and high school districts of one name, at one office:
    # the town's school system is both.
    case("Tamsby Public Schools", "MT", "SYN-MT-TAMSE", also=TAMSBY_SYSTEM, note=SYSTEM),
    case(
        "Tamsby Schools",
        "MT",
        "SYN-MT-TAMSE",
        counties=SYSTEM_MT_A,
        also=TAMSBY_SYSTEM,
        note=SYSTEM,
    ),
    case("Tamsby", "MT", "SYN-MT-TAMSE", also=TAMSBY_SYSTEM, note=SYSTEM + ": a town's name"),
    case("TAMSBY SCHOOL DISTRICT", "MT", "SYN-MT-TAMSE", also=TAMSBY_SYSTEM, note=SYSTEM),
    case("Tamsby Public Schools - All Schools", "MT", "SYN-MT-TAMSE", also=TAMSBY_SYSTEM),
    case(
        "Tamsby School District 2",
        "MT",
        "SYN-MT-TAMSE",
        also=TAMSBY_SYSTEM,
        note=SYSTEM + ": a number NCES does not give either district",
    ),
    case("Tamsby Elementary", "MT", "SYN-MT-TAMSE", note=SYSTEM_NEGATIVE + ": a level"),
    case("Tamsby Elem. District", "MT", "SYN-MT-TAMSE", note=SYSTEM_NEGATIVE + ": a level"),
    case("Tamsby Sr High School", "MT", "SYN-MT-TAMHS", note=SYSTEM_NEGATIVE + ": a school"),
    case("Tamsby Middle School", "MT", "SYN-MT-TAMMS", note=SYSTEM_NEGATIVE + ": a school"),
    case(
        "Tamsby Public Schools",
        ("MT", "OK"),
        None,
        note=SYSTEM_NEGATIVE + ": a town's district of the name in the other state",
    ),
    case("Tamsby Public Schools", "OK", "SYN-OK-TAMS", note="the other state's town"),
    # An elementary district named for its town and a high school district of
    # another name, at one office; another elementary district of the town.
    case("Kellby Public Schools", "MT", "SYN-MT-KELE", also=KELLBY_SYSTEM, note=SYSTEM),
    case("Kellby", "MT", "SYN-MT-KELE", counties=SYSTEM_MT_A, also=KELLBY_SYSTEM, note=SYSTEM),
    case("Kellby Schools", "MT", "SYN-MT-KELE", also=KELLBY_SYSTEM, note=SYSTEM),
    case("Kellby Elementary", "MT", "SYN-MT-KELE", note=SYSTEM_NEGATIVE + ": a level"),
    case("Glacierby High School", "MT", "SYN-MT-GLAHS", note=SYSTEM_NEGATIVE + ": a school"),
    case("Evermont", "MT", "SYN-MT-EVRE", note=SYSTEM_NEGATIVE + ": another district of the town"),
    case("Evermont School District", "MT", "SYN-MT-EVRE", note=SYSTEM_NEGATIVE),
    case("Mileby City Public Schools", "MT", "SYN-MT-MILE", also=MILEBY_SYSTEM, note=SYSTEM),
    case("Mileby City", "MT", "SYN-MT-MILE", counties=SYSTEM_MT_B, also=MILEBY_SYSTEM, note=SYSTEM),
    case("Mileby Public Schools", "MT", "SYN-MT-MILE", also=MILEBY_SYSTEM, note=SYSTEM),
    case("Mileby City Elementary", "MT", "SYN-MT-MILE", note=SYSTEM_NEGATIVE + ": a level"),
    case("Custerby County", "MT", "SYN-MT-CUSH", note=SYSTEM_NEGATIVE + ": the county's name"),
    # The same pair with an office each, run apart: no system.
    case(
        "Boulby Public Schools",
        "MT",
        "SYN-MT-BOUE",
        note=SYSTEM_NEGATIVE + ": a high school district with an office of its own",
    ),
    case("Boulby", "MT", "SYN-MT-BOUE", counties=SYSTEM_MT_B, note=SYSTEM_NEGATIVE),
    case("Jeffby High School", "MT", "SYN-MT-JEFHS", note=SYSTEM_NEGATIVE + ": a school"),
    case(
        "Harlby Public Schools",
        "MT",
        None,
        note=SYSTEM_NEGATIVE + ": two elementary districts of one name",
    ),
    # Arizona: one name, an office each; a legal-form word one of them says.
    case("Phenby Public Schools", "AZ", "SYN-AZ-PHNE", also=PHENBY_SYSTEM, note=SYSTEM),
    case(
        "Phenby Schools", "AZ", "SYN-AZ-PHNE", counties=SYSTEM_AZ, also=PHENBY_SYSTEM, note=SYSTEM
    ),
    case("Phenby", "AZ", "SYN-AZ-PHNE", also=PHENBY_SYSTEM, note=SYSTEM),
    case("Phenby Union", "AZ", "SYN-AZ-PHNH", note=SYSTEM_NEGATIVE + ": Union"),
    case("Phenby Union High School District", "AZ", "SYN-AZ-PHNH", note=SYSTEM_NEGATIVE),
    case("Phenby Elementary", "AZ", "SYN-AZ-PHNE", note=SYSTEM_NEGATIVE + ": a level"),
    case("Phenby Elementary District", "AZ", "SYN-AZ-PHNE", note=SYSTEM_NEGATIVE),
    # California: one name at one office, the elementary district's "City" and all.
    case("Petalby City Schools", "CA", "SYN-CA-PETE", also=PETALBY_SYSTEM, note=SYSTEM),
    case("Petalby Schools", "CA", "SYN-CA-PETE", also=PETALBY_SYSTEM, note=SYSTEM),
    case("Petalby", "CA", "SYN-CA-PETE", counties=SYSTEM_CA, also=PETALBY_SYSTEM, note=SYSTEM),
    case("Petalby Joint Union", "CA", "SYN-CA-PETH", note=SYSTEM_NEGATIVE + ": Joint Union"),
    case("Petalby City Elementary", "CA", "SYN-CA-PETE", note=SYSTEM_NEGATIVE + ": a level"),
    # A city's elementary district beside a union high school district of the
    # name in another town: no system.
    case(
        "Mercby City Schools",
        "CA",
        "SYN-CA-MERE",
        note=SYSTEM_NEGATIVE + ": the high school district's office is in another town",
    ),
    case("Mercby", "CA", "SYN-CA-MERE", note=SYSTEM_NEGATIVE + ": the town's own district"),
    case("Mercby Union High School District", "CA", "SYN-CA-MERH", note=SYSTEM_NEGATIVE),
    case("Mercby Schools", "CA", None, note=SYSTEM_NEGATIVE + ": two towns' districts"),
    case("Rosaby City Schools", "CA", "SYN-CA-ROSE", also=("SYN-CA-ROSH",), note=SYSTEM + ": City"),
    case("Rosaby Schools", "CA", "SYN-CA-ROSE", also=("SYN-CA-ROSH",), note=SYSTEM),
    case("Rosaby Academy", "CA", "SYN-CA-ROSAS", note=SYSTEM_NEGATIVE + ": a charter of the name"),
    case(
        "Salinby City Schools",
        "CA",
        "SYN-CA-SALE",
        note=SYSTEM_NEGATIVE + ": City, which only the elementary district says",
    ),
    case("Salinby Schools", "CA", "SYN-CA-SALE", also=("SYN-CA-SALH",), note=SYSTEM),
    case("Salinby Union High School District", "CA", "SYN-CA-SALH", note=SYSTEM_NEGATIVE),
    # Illinois: an elementary and a township high school district of one town.
    case("Strebby Schools", "IL", "SYN-IL-STRE", also=STREBBY_SYSTEM, note=SYSTEM),
    case("Strebby Public Schools", "IL", "SYN-IL-STRE", counties=SYSTEM_IL, also=STREBBY_SYSTEM),
    case("Strebby ESD 44", "IL", "SYN-IL-STRE", note=SYSTEM_NEGATIVE + ": a number"),
    case("Strebby Twp HSD 40", "IL", "SYN-IL-STRH", note=SYSTEM_NEGATIVE + ": a number"),
    case("Strebby School District 45", "IL", None, note=SYSTEM_NEGATIVE + ": another number"),
    # New York: a city's geographic districts and its district 75, in two counties.
    case("Bronby City Public Schools", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM, note=SYSTEM),
    case("Bronby City Schools", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM, note=SYSTEM),
    case("Bronby City Department of Education", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM),
    case("Bronby City DOE", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM, note=SYSTEM),
    case("Bronby City Dept. of Ed.", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM, note=SYSTEM),
    case("Bronby City", "NY", "SYN-NY-BC01", also=BRONBY_SYSTEM, note=SYSTEM + ": a city's name"),
    case(
        "Bronby City Public Schools",
        "NY",
        "SYN-NY-BC01",
        counties=SYSTEM_NY_B,
        also=BRONBY_SYSTEM,
        note=SYSTEM + ": from a market that holds part of it",
    ),
    case(
        "Bronby City Geographic District 10",
        "NY",
        "SYN-NY-BC10",
        note=SYSTEM_NEGATIVE + ": a number",
    ),
    case("Bronby City District 2", "NY", "SYN-NY-BC02", note=SYSTEM_NEGATIVE + ": a number"),
    case("Bronby City District 75", "NY", "SYN-NY-BC75", note=SYSTEM_NEGATIVE + ": a number"),
    case("Bronby City Special Schools", "NY", "SYN-NY-BC75", note=SYSTEM_NEGATIVE),
    case(
        "Bronby City Charter School of the Arts",
        "NY",
        "SYN-NY-BCCAS",
        note=SYSTEM_NEGATIVE + ": a charter school of the city's name",
    ),
    case("Bronby Public Schools", "NY", None, note=SYSTEM_NEGATIVE + ": the city's City left out"),
    case("Bronby", "NY", None, note=SYSTEM_NEGATIVE + ": the city's City left out"),
    case(
        "Bronby City Geographic District 7",
        "NY",
        None,
        note=SYSTEM_NEGATIVE + ": a district it does not have",
    ),
    case("Bronby City Public Schools", "NJ", None, note=SYSTEM_NEGATIVE + ": another state"),
    case("PS 101 Ada Lane - Bronby City", "NY", "SYN-NY-PS101", note="a school in its system"),
    # Namesakes across a state line that each state writes its own way (as
    # Missouri's "KANSAS CITY 33" and Kansas's "Kansas City", Tennessee's
    # "Bristol" and Virginia's "Bristol City Public Schools"): which one's name is
    # the listing's word for word, legal form or spelling says how the states
    # write names, not which the listing means. Only a point much nearer one of
    # them, or the state the listing names, tells.
    case("Kessby City Public Schools", MO_KS, None, note=ACROSS_NEGATIVE),
    case("Kessby City Schools", MO_KS, None, note=ACROSS_NEGATIVE),
    case("Kessby City School District", MO_KS, None, note=ACROSS_NEGATIVE),
    case("Kessby City", MO_KS, None, note=ACROSS_NEGATIVE + ": the city's name"),
    case("KESSBY CITY PUBLIC SCHOOLS - All Schools", MO_KS, None, note=ACROSS_NEGATIVE),
    case(
        "Kessby City Public Schools",
        MO_KS,
        None,
        near=BETWEEN_KESSBY,
        note=ACROSS_NEGATIVE + ": a point between the two",
    ),
    case(
        "Kessby City Public Schools",
        MO_KS,
        None,
        near=KESSBY_MO,
        note=ACROSS_NEGATIVE + ": a point at one, the other 4 km away",
    ),
    case("Kessby City Public Schools", "MO", "SYN-MO-KESS", note=ACROSS + ": one state"),
    case("Kessby City Public Schools", "KS", "SYN-KS-KESS", note=ACROSS + ": one state"),
    case("Kessby City Kansas Public Schools", MO_KS, "SYN-KS-KESS", note=ACROSS + ": its state"),
    case("Kessby City Missouri Public Schools", MO_KS, "SYN-MO-KESS", note=ACROSS + ": its state"),
    case("Kessby City 33", MO_KS, "SYN-MO-KESS", note=ACROSS + ": its number"),
    case("Bristmoor", ("TN", "VA"), None, note=ACROSS_NEGATIVE + ": the city's name"),
    case("Bristmoor City Schools", ("TN", "VA"), None, note=ACROSS_NEGATIVE),
    case("Bristmoor Public Schools", ("TN", "VA"), None, note=ACROSS_NEGATIVE),
    case("Bristmoor City Public Schools", ("TN", "VA"), None, note=ACROSS_NEGATIVE),
    case("BRISTMOOR SCHOOLS (Closed)", ("TN", "VA"), None, note=ACROSS_NEGATIVE),
    case("Bristmoor High School", ("TN", "VA"), None, note=ACROSS_NEGATIVE + ": a school"),
    case(
        "Bristmoor City Schools",
        ("TN", "VA"),
        None,
        near=BRISTMOOR_TN,
        note=ACROSS_NEGATIVE + ": a point at one, the other 3 km away",
    ),
    case(
        "Bristmoor Virginia Public Schools",
        ("TN", "VA"),
        "SYN-VA-BRIS",
        note=ACROSS + ": its state",
    ),
    case(
        "Bristmoor Tennessee City Schools", ("TN", "VA"), "SYN-TN-BRIS", note=ACROSS + ": its state"
    ),
    case("Bristmoor TN City Schools", ("TN", "VA"), "SYN-TN-BRIS", note=ACROSS + ": its state"),
    case("Bristmoor City Schools", "TN", "SYN-TN-BRIS", note=ACROSS + ": one state"),
    case("Bristmoor City Schools", "VA", "SYN-VA-BRIS", note=ACROSS + ": one state"),
    case("Escambry", ("FL", "AL"), None, note=ACROSS_NEGATIVE + ": the county's name"),
    case("Escambry Schools", ("FL", "AL"), None, note=ACROSS_NEGATIVE + ": County implied"),
    case("Escambry County Schools", ("FL", "AL"), None, note=ACROSS_NEGATIVE),
    case("Escambry County Public Schools", ("FL", "AL"), None, note=ACROSS_NEGATIVE),
    case("Escambry County School District", ("FL", "AL"), None, note=ACROSS_NEGATIVE),
    case(
        "Escambry Schools",
        ("FL", "AL"),
        None,
        near=ESCAMBRY_AL,
        note=ACROSS_NEGATIVE + ": a point at the one that fits worse",
    ),
    case(
        "Escambry County Schools",
        ("FL", "AL"),
        None,
        near=ESCAMBRY_FL,
        note=ACROSS_NEGATIVE + ": a point at one, the other 74 km away, within reach",
    ),
    case(
        "Escambry County Schools",
        ("FL", "AL"),
        None,
        near=ESCAMBRY_AL,
        note=ACROSS_NEGATIVE + ": a point at one, the other 74 km away, within reach",
    ),
    case(
        "Escambry Schools",
        ("FL", "AL"),
        None,
        near=ESCAMBRY_FL,
        note=ACROSS_NEGATIVE + ": a point at one, the other 74 km away, within reach",
    ),
    case("Escambry County, AL Schools", ("FL", "AL"), "SYN-AL-ESCA", note=ACROSS + ": its state"),
    case("Escambry County (FL)", ("FL", "AL"), "SYN-FL-ESCA", note=ACROSS + ": its state"),
    case("Escambry County Schools", "FL", "SYN-FL-ESCA", note=ACROSS + ": one state"),
    case("Escambry County Schools", "AL", "SYN-AL-ESCA", note=ACROSS + ": one state"),
    case("Covermoor", ("KY", "OH"), None, note=ACROSS_NEGATIVE + ": the city's name"),
    case("Covermoor Schools", ("KY", "OH"), None, note=ACROSS_NEGATIVE),
    case("Covermoor Public Schools", ("KY", "OH"), None, note=ACROSS_NEGATIVE),
    case(
        "Covermoor Independent Schools",
        ("KY", "OH"),
        None,
        note=ACROSS_NEGATIVE + ": a legal form one state writes",
    ),
    case(
        "Covermoor Exempted Village Schools",
        ("KY", "OH"),
        None,
        note=ACROSS_NEGATIVE + ": a legal form one state writes",
    ),
    case(
        "Covermoor Schools",
        ("KY", "OH"),
        "SYN-KY-COVI",
        near=COVERMOOR_KY,
        note=ACROSS + ": a point at one, the other 115 km away",
    ),
    case("Covermoor Schools", "OH", "SYN-OH-COVE", note=ACROSS + ": one state"),
    case(
        "Covermoor High School", ("KY", "OH"), "SYN-OH-COVEH", note=ACROSS + ": one state's school"
    ),
    # A county's district and a town's are two names, which a list tells apart by
    # "County".
    case(
        "Madmoor Schools", ("KY", "IN"), "SYN-IN-MADT", note=ACROSS + ": a town's, not a county's"
    ),
    case("Madmoor County Schools", ("KY", "IN"), "SYN-KY-MADC", note=ACROSS + ": a county's"),
    # A private school NCES names with its campus; one of two campuses.
    case("Pellbrook Hill", MO_KS, "SYN-MO-PELL", note=CAMPUS),
    case("Pellbrook Hill School", MO_KS, "SYN-MO-PELL", note=CAMPUS),
    case("The Pellbrook Hill School", MO_KS, "SYN-MO-PELL", note=CAMPUS),
    case("Hollowby Day School", MO_KS, None, note=CAMPUS_NEGATIVE),
    case("Hollowby Day School - North Campus", MO_KS, "SYN-KS-HOLN", note=CAMPUS),
    # A school a list's name says word for word, when its district's name does
    # not: the listing says a word, a level or a legal form the district's name
    # lacks. The school, or, when a word marks it down or a sibling school is
    # as close, the queue; never the district, which would mark every other
    # school of it.
    case("Cheddby Co Central", "TN", "SYN-TN-CHDCC", note=OWN_SCHOOL),
    case("Cheddby Co. Central", "TN", "SYN-TN-CHDCC", note=OWN_SCHOOL),
    case("CHEDDBY CO CENTRAL", "TN", "SYN-TN-CHDCC", counties=CHEDDBY_CO, note=OWN_SCHOOL),
    case("Lakeby Central", "OH", "SYN-OH-LAKLC", note=OWN_SCHOOL),
    case("CYPRBY-FAIRMONT J J A E P", "TX", "SYN-TX-CYFJ", note=OWN_SCHOOL),
    case("Cyprby-Fairmont JJAEP", "TX", "SYN-TX-CYFJ", note=OWN_SCHOOL),
    case("Selmby Independent", "CA", None, note=OWN_SCHOOL_NEGATIVE + ": marked down"),
    case("Waterby Junior", "CA", None, note=OWN_SCHOOL_NEGATIVE + ": its high school as close"),
    case("WHITBY A E P", "TX", None, note=OWN_SCHOOL_NEGATIVE + ": its high school as close"),
    case("District 917 - ALC - IS", "MN", None, note=OWN_SCHOOL_NEGATIVE + ": not read in parts"),
    case(
        "Petalby Community",
        "CA",
        None,
        note=OWN_SCHOOL_NEGATIVE + ": never the city's system",
    ),
    # The district's own name stays the district's.
    case("Cheddby County Schools", "TN", "SYN-TN-CHDC", note=OWN_SCHOOL + ": the district's"),
    case("Cheddby County", "TN", "SYN-TN-CHDC", note=OWN_SCHOOL + ": the district's"),
    case("Lakeby Local Schools", "OH", "SYN-OH-LAKL", note=OWN_SCHOOL + ": the district's"),
    case("Selmby Unified", "CA", "SYN-CA-SELU", note=OWN_SCHOOL + ": the district's"),
    case(
        "Selmby Unified School District", "CA", "SYN-CA-SELU", note=OWN_SCHOOL + ": the district's"
    ),
    case("Waterby Unified", "CA", "SYN-CA-WATU", note=OWN_SCHOOL + ": the district's"),
    case("Cyprby-Fairmont ISD", "TX", "SYN-TX-CYFA", note=OWN_SCHOOL + ": the district's"),
    case("Minerby Wells Schools", "TX", "SYN-TX-MINW", note=OWN_SCHOOL + ": the district's"),
    case("Minerby Wells ISD", "TX", "SYN-TX-MINW", note=OWN_SCHOOL + ": the district's"),
    case(
        "Intermediate School District 917",
        "MN",
        "SYN-MN-I917",
        note=OWN_SCHOOL + ": the district's",
    ),
    case(
        "Petalby City Schools",
        "CA",
        "SYN-CA-PETE",
        counties=SYSTEM_CA,
        also=PETALBY_SYSTEM,
        note=OWN_SCHOOL + ": the city's system",
    ),
    case("Petalby Community School", "CA", "SYN-CA-SONOP", note=OWN_SCHOOL + ": the county's"),
    # A district of one school is that school already.
    case("Craftby Schools", "VT", "SYN-VT-CRAF", note=OWN_SCHOOL + ": a district of one school"),
    # Two townships of one name in two counties: the word order, the legal form
    # and a Township NCES leaves out tell them no more apart than a coin.
    case("Unionmere Township Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Township of Unionmere Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Unionmere Twp. Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("UNIONMERE TOWNSHIP SCHOOLS", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Unionmere Township School District", "NJ", None, note=TOWNSHIP_NEGATIVE + ": B's name"),
    case(
        "Township of Unionmere School District", "NJ", None, note=TOWNSHIP_NEGATIVE + ": A's name"
    ),
    case("Unionmere Township", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case(
        "Unionmere Township Public Schools",
        "NJ",
        None,
        counties=(UNIONMERE_A_CO, UNIONMERE_B_CO),
        note=TOWNSHIP_NEGATIVE + ": both in the counties",
    ),
    case("Unionmere Township Public Schools", "NJ", "SYN-NJ-UNIA", near=UNIONMERE_A, note=TOWNSHIP),
    case("Unionmere Township Public Schools", "NJ", "SYN-NJ-UNIB", near=UNIONMERE_B, note=TOWNSHIP),
    case(
        "Township of Unionmere Public Schools", "NJ", "SYN-NJ-UNIB", near=UNIONMERE_B, note=TOWNSHIP
    ),
    case("Unionmere Township", "NJ", "SYN-NJ-UNIA", near=UNIONMERE_A, note=TOWNSHIP),
    case(
        "Unionmere Twp Schools",
        "NJ",
        "SYN-NJ-UNIA",
        counties=UNIONMERE_A_CO,
        note=TOWNSHIP + ": the other beyond the counties' reach",
    ),
    case(
        "Township of Unionmere Schools",
        "NJ",
        "SYN-NJ-UNIB",
        counties=UNIONMERE_B_CO,
        note=TOWNSHIP + ": the other beyond the counties' reach",
    ),
    case(
        "Unionmere Public Schools",
        "NJ",
        "SYN-NJ-UNIA",
        counties=UNIONMERE_A_CO,
        note=TOWNSHIP + ": Township left out, alone in the counties",
    ),
    case(
        "Franklinmere Schools",
        "NJ",
        "SYN-NJ-FRAA",
        counties=FRANKLINMERE_A_CO,
        note=TOWNSHIP + ": Township left out, alone in the counties",
    ),
    case(
        "Oceanmere Public Schools",
        "NJ",
        None,
        counties=OCEANMERE_A_CO,
        note=TOWNSHIP_NEGATIVE + ": Township left out, the other just past the counties",
    ),
    case("Unionmere", "NJ", None, note=TOWNSHIP_NEGATIVE + ": a place's name, either township's"),
    case(
        "Unionmere",
        "NJ",
        None,
        counties=(UNIONMERE_A_CO, UNIONMERE_B_CO),
        note=TOWNSHIP_NEGATIVE + ": a place's name, either township's",
    ),
    case("Unionmere", "NJ", "SYN-NJ-UNIA", near=UNIONMERE_A, note=TOWNSHIP + ": a place's name"),
    case("Unionmere", "NJ", "SYN-NJ-UNIB", near=UNIONMERE_B, note=TOWNSHIP + ": a place's name"),
    case("Springmere", "NJ", None, note=TOWNSHIP_NEGATIVE + ": a place's name, either township's"),
    case("Springmere", "NJ", "SYN-NJ-SPRB", near=SPRINGMERE_B, note=TOWNSHIP + ": a place's name"),
    case("Franklinmere", "NJ", None, note=TOWNSHIP_NEGATIVE + ": a place's name, five districts'"),
    case("Township of Unionmere", "NJ", None, note=CIVIC),
    case("Township of Unionmere", "NJ", None, near=UNIONMERE_A, note=CIVIC),
    case(
        "Township of Unionmere",
        "NJ",
        None,
        near=UNIONMERE_A,
        category="Government",
        note=CIVIC + ": filed among governments",
    ),
    case(
        "Township of Unionmere",
        "NJ",
        None,
        category="Public Schools",
        note=TOWNSHIP_NEGATIVE + ": filed among schools, a district's name",
    ),
    case(
        "Township of Unionmere",
        "NJ",
        "SYN-NJ-UNIA",
        near=UNIONMERE_A,
        category="Public Schools",
        note=TOWNSHIP + ": filed among schools, a district's name",
    ),
    case("Oceanmere Township Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Township of Oceanmere Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Oceanmere Twp. Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case(
        "Oceanmere Township Schools",
        "NJ",
        None,
        counties=OCEANMERE_A_CO,
        note=TOWNSHIP_NEGATIVE + ": the other just past the counties",
    ),
    case(
        "Oceanmere Township Schools",
        "NJ",
        None,
        near=OCEANMERE_A,
        note=TOWNSHIP_NEGATIVE + ": a point at one, the other 53 km away, within reach",
    ),
    case(
        "Oceanmere Township Schools",
        "NJ",
        None,
        near=OCEANMERE_B,
        note=TOWNSHIP_NEGATIVE + ": a point at one, the other 53 km away, within reach",
    ),
    case("Oceanmere Township High School", "NJ", "SYN-NJ-OCEA1", note=TOWNSHIP + ": a school"),
    case("Lawrencemere Township Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Lawrencemere Township School District", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Lawrencemere Twp. Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case(
        "Lawrencemere Township Public Schools",
        "NJ",
        "SYN-NJ-LAWA",
        near=LAWRENCEMERE_A,
        note=TOWNSHIP,
    ),
    case("Lawrencemere Township Schools", "NJ", "SYN-NJ-LAWB", near=LAWRENCEMERE_B, note=TOWNSHIP),
    case("Monroemere Township Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Monroemere Township Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case(
        "Monroemere Township Schools",
        "NJ",
        None,
        counties=(MONROEMERE_A_CO, MONROEMERE_B_CO),
        note=TOWNSHIP_NEGATIVE + ": both in the counties",
    ),
    case(
        "Monroemere Township Schools",
        "NJ",
        "SYN-NJ-MONA",
        counties=MONROEMERE_A_CO,
        note=TOWNSHIP + ": the other beyond the counties' reach",
    ),
    case("Monroemere Township Schools", "NJ", "SYN-NJ-MONB", near=MONROEMERE_B, note=TOWNSHIP),
    case("Franklinmere Township Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Township of Franklinmere Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Franklinmere Township Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Franklinmere Twp School District", "NJ", None, note=TOWNSHIP_NEGATIVE),
    case("Franklinmere Schools", "NJ", None, note=TOWNSHIP_NEGATIVE + ": a borough's too"),
    case("Franklinmere Township Schools", "NJ", "SYN-NJ-FRAA", near=FRANKLINMERE_A, note=TOWNSHIP),
    case(
        "Township of Franklinmere Schools",
        "NJ",
        None,
        near=FRANKLINMERE_C,
        note=TOWNSHIP_NEGATIVE + ": a point at one, another 47 km away, within reach",
    ),
    case("Franklinmere Borough Schools", "NJ", "SYN-NJ-FRAD", note=TOWNSHIP + ": the borough's"),
    case("Borough of Franklinmere Schools", "NJ", "SYN-NJ-FRAD", note=TOWNSHIP + ": the borough's"),
    case("Springmere Public Schools", "NJ", None, note=TOWNSHIP_NEGATIVE + ": Township left out"),
    case("Springmere Schools", "NJ", None, note=TOWNSHIP_NEGATIVE + ": Township left out"),
    case("Springmere Schools", "NJ", "SYN-NJ-SPRA", near=SPRINGMERE_A, note=TOWNSHIP),
    case(
        "Springmere Schools",
        "NJ",
        "SYN-NJ-SPRB",
        near=SPRINGMERE_B,
        note=TOWNSHIP + ": the point, not the Township, tells it",
    ),
    case(
        "Springmere Township Schools",
        "NJ",
        "SYN-NJ-SPRB",
        note=TOWNSHIP + ": says Township, which only one name says",
    ),
    case(
        "Springmere Public Schools",
        "NJ",
        "SYN-NJ-SPRA",
        counties=SPRINGMERE_A_CO,
        note=TOWNSHIP + ": the other beyond the counties' reach",
    ),
    # Schools of one name in one market's counties: a point beside one of them
    # says nothing of which one a list means. Only a namesake outside the
    # counties (with counties given) or beyond a market's reach of the point
    # (with none) is told apart by it.
    case(
        "St. John School",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        category="Schools",
        note=SAME_NAME_NEGATIVE + ": two in the counties, 1 km and 17 km from the point",
    ),
    case(
        "St. John School",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE + ": two in the counties, 1 km and 17 km from the point",
    ),
    case(
        "Saint John School",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE,
    ),
    case(
        "ST JOHN SCHOOL (Closed)",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE,
    ),
    case(
        "St. John School - Remote Learning",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE,
    ),
    case(
        "St. John School",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        note=SAME_NAME_NEGATIVE + ": no point",
    ),
    case(
        "St. John School",
        ("MA", "NH"),
        None,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE + ": the other 17 km off, within reach of the point",
    ),
    case(
        "St. John School",
        "MA",
        "SYN-MA-SJHA",
        counties=HARBOURNE_CO,
        near=HARBOURNE,
        note=SAME_NAME + ": the other just past the county, the point beside this one",
    ),
    case("St. John School", "MA", None, counties=HARBOURNE_CO, note=JUST_PAST),
    case(
        "St. John the Baptist School",
        ("MA", "NH"),
        "SYN-MA-SJBP",
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note="its own name, beside two of a shorter one",
    ),
    case(
        "Sacred Heart",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        category="Schools",
        note=SAME_NAME_NEGATIVE + ": Sacred Heart and Sacred Hearts",
    ),
    case(
        "Sacred Heart School",
        ("MA", "NH"),
        None,
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE + ": Sacred Heart and Sacred Hearts",
    ),
    case(
        "St. Brendan School",
        ("MA", "NH"),
        "SYN-MA-SBWM",
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME + ": the other just past the counties, much farther from the point",
    ),
    case(
        "Saint Brendan School",
        ("MA", "NH"),
        "SYN-MA-SBWM",
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME + ": the other just past the counties, much farther from the point",
    ),
    case("St. Brendan School", ("MA", "NH"), None, counties=HARBOURNE_COUNTIES, note=JUST_PAST),
    case(
        "St. Brendan School",
        ("MA", "NH"),
        None,
        near=HARBOURNE,
        note=SAME_NAME_NEGATIVE + ": the other 68 km off, within reach of the point",
    ),
    case(
        "St. Cecilia School",
        ("MA", "NH"),
        "SYN-MA-SCHA",
        near=HARBOURNE,
        note=SAME_NAME + ": the other 134 km off, beyond reach of the point",
    ),
    case(
        "St. Cecilia School",
        ("MA", "NH"),
        "SYN-MA-SCPT",
        near=PITTSMOOR,
        note=SAME_NAME + ": the other 134 km off, beyond reach of the point",
    ),
    case(
        "St. Cecilia School",
        ("MA", "NH"),
        "SYN-MA-SCHA",
        counties=HARBOURNE_COUNTIES,
        note=SAME_NAME + ": the other far beyond the counties",
    ),
    case(
        "St. Cecilia School",
        ("MA", "NH"),
        "SYN-MA-SCHA",
        counties=HARBOURNE_COUNTIES,
        near=HARBOURNE,
        note=SAME_NAME + ": the other far beyond the counties",
    ),
    case("St. Cecilia School", ("MA", "NH"), None, note=SAME_NAME_NEGATIVE + ": no point"),
    case(
        "St. Cecilia School",
        ("MA", "NH"),
        None,
        near=(42.49, -72.43),
        note=SAME_NAME_NEGATIVE + ": a point between them",
    ),
    case(
        "Walsh Elem School", ("IL", "IN"), None, counties=LAKEPORT_COUNTIES, note=SAME_NAME_NEGATIVE
    ),
    case(
        "Walsh Elementary School",
        ("IL", "IN"),
        None,
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note=SAME_NAME_NEGATIVE + ": three districts' schools, one 3 km from the point",
    ),
    case(
        "WALSH ELEMENTARY",
        ("IL", "IN"),
        None,
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        category="Schools",
        note=SAME_NAME_NEGATIVE,
    ),
    case(
        "Walsh Elementary School",
        "IL",
        None,
        near=LAKEPORT,
        note=SAME_NAME_NEGATIVE + ": the others within reach of the point",
    ),
    case(
        "Liberty Elementary School",
        ("IL", "IN"),
        None,
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note=SAME_NAME_NEGATIVE + ": two districts' schools, one 4 km from the point",
    ),
    case(
        "Liberty Elem",
        ("IL", "IN"),
        None,
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note=SAME_NAME_NEGATIVE,
    ),
    case(
        "Lakeport SD 299 - Walsh Elementary",
        ("IL", "IN"),
        "SYN-IL-LKWA",
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note="one of three by its district, said beside it",
    ),
    case(
        "Walsh Elementary School - Orland Grove",
        ("IL", "IN"),
        "SYN-IL-ORWA",
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note="one of three by its town, said beside it",
    ),
    case(
        "Liberty Elementary - Lakeport",
        ("IL", "IN"),
        "SYN-IL-LKLB",
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note="one of two by its town, said beside it",
    ),
    case(
        "Harmon Elementary School",
        ("IL", "IN"),
        "SYN-IL-LKHA",
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
        note="the only one of its name",
    ),
    case(
        "Downsmere Middle School",
        ("IL", "IN"),
        "SYN-IL-DWMS",
        counties=LAKEPORT_COUNTIES,
        near=LAKEPORT,
    ),
    # A saint's epithet and a pope's numeral are their names' words: "St. John
    # the Baptist" is not "ST JOHN LUTHERAN", "St. John" not "ST JOHN XXIII".
    case("St. John School", "OH", None, counties=POPE_CO, note=SAINT_NEGATIVE + ": a pope's"),
    case("St. John XXIII School", "OH", "SYN-OH-SJ23", counties=POPE_CO, note=SAINT),
    case("Saint John XXIII Catholic School", "OH", "SYN-OH-SJ23", counties=POPE_CO, note=SAINT),
    case("St. Paul School", "OH", None, counties=PAUL_VI_CO, note=SAINT_NEGATIVE + ": a pope's"),
    case("Paul VI High School", "OH", "SYN-OH-PVI", counties=PAUL_VI_CO, note=SAINT),
    case("Paul VI Catholic High School", "OH", "SYN-OH-PVI", counties=PAUL_VI_CO, note=SAINT),
    case(
        "St. John the Baptist School",
        "OH",
        None,
        counties=LUTHERAN_JOHN_CO,
        note=SAINT_NEGATIVE + ": the Baptist is not a Lutheran St. John",
    ),
    case(
        "St. John the Baptist Catholic School",
        "OH",
        None,
        counties=LUTHERAN_JOHN_CO,
        note=SAINT_NEGATIVE + ": the Baptist is not a Lutheran St. John",
    ),
    case("St. John Lutheran School", "OH", "SYN-OH-SJLU", counties=LUTHERAN_JOHN_CO, note=SAINT),
    case("St. John the Baptist School", "OH", "SYN-OH-SJBA", counties=TWO_JOHNS_CO, note=SAINT),
    case("St. John the Baptist", "OH", "SYN-OH-SJBA", counties=TWO_JOHNS_CO, category="Schools"),
    case("St. John the Evangelist School", "OH", "SYN-OH-SJEV", counties=TWO_JOHNS_CO, note=SAINT),
    case(
        "St. John School",
        "OH",
        None,
        counties=TWO_JOHNS_CO,
        note=SAINT_NEGATIVE + ": the Baptist's or the Evangelist's",
    ),
    # A level a school's NCES name leaves out, whose grades are of it: "St. Joseph
    # Elementary" names the PK-8 "ST JOSEPH SCHOOL"s as surely as the "ST JOSEPH
    # ELEMENTARY SCHOOL" beside them, and "Lincoln Elementary" the K-5 "Lincoln"
    # as surely as the "Lincoln Elementary" a town away: all of them, so none.
    _level("St. Joseph Elementary", None, LEVEL_NEGATIVE + ": two PK-8 ST JOSEPH SCHOOLs"),
    _level("St Joseph Elementary School", None, LEVEL_NEGATIVE + ": two PK-8 ST JOSEPH SCHOOLs"),
    _level("ST. JOSEPH ELEMENTARY", None, LEVEL_NEGATIVE + ": two PK-8 ST JOSEPH SCHOOLs"),
    _level("St. Joseph's Elementary School", None, LEVEL_NEGATIVE),
    _level("Saint Joseph Elem.", None, LEVEL_NEGATIVE),
    _level("St. Joseph Catholic Elementary", None, LEVEL_NEGATIVE + ": the faith, implied"),
    _level("St. Joseph Elementary (Closed)", None, LEVEL_NEGATIVE + ": no point", near=False),
    _level("St. Joseph School", None, LEVEL_NEGATIVE + ": no level said"),
    _level("Lincoln Elementary", None, LEVEL_NEGATIVE + ': a K-5 "Lincoln" in the county'),
    _level("Lincoln Elementary School", None, LEVEL_NEGATIVE + ': a K-5 "Lincoln"'),
    _level("LINCOLN ELEM.", None, LEVEL_NEGATIVE + ': a K-5 "Lincoln"'),
    _level("Lincoln ES - 2 Hour Delay", None, LEVEL_NEGATIVE + ': a K-5 "Lincoln"'),
    _level("Lincoln Elementary", None, LEVEL_NEGATIVE + ": no point", near=False),
    _level(
        "Lincoln Middle School",
        None,
        LEVEL_NEGATIVE + ": K-5 schools are none, and a PK-8 one not surely",
    ),
    _level("Hallby Elementary", None, LEVEL_NEGATIVE + ": a K-12 HALLBY SCHOOL may be meant"),
    _level("Hallby Elementary School", None, LEVEL_NEGATIVE + ": a K-12 HALLBY SCHOOL"),
    _level("Hallby High School", None, LEVEL_NEGATIVE + ": a K-12 school, not surely"),
    _level("Winstowe Middle School", None, LEVEL_NEGATIVE + ": a K-5 school is none"),
    _level("Winstowe High School", None, LEVEL_NEGATIVE + ": a K-5 school is none"),
    _level("Devonby High School", None, LEVEL_NEGATIVE + ": K-5 and 6-8 schools are none"),
    _level("Devonmoor Elementary School", None, LEVEL_NEGATIVE, chicago=True),
    _level("DEVONMOOR ELEMENTARY", None, LEVEL_NEGATIVE, chicago=True),
    _level("Devonmoor Elementary", None, LEVEL_NEGATIVE + ": no point", chicago=True, near=False),
    _level(
        "St. John Lutheran Preschool",
        None,
        LEVEL_NEGATIVE + ": the PK-8 schools' preschools as much as the PK-1 school",
        chicago=True,
    ),
    _level("ST. JOHN LUTHERAN PRESCHOOL", None, LEVEL_NEGATIVE, chicago=True),
    _level("St John Lutheran Pre-K", None, LEVEL_NEGATIVE, chicago=True),
    _level(
        "Northby Junior High School",
        None,
        LEVEL_NEGATIVE + ": a 5-8 Northby School beside it",
        chicago=True,
    ),
    _level("Christ Lutheran High School", None, LEVEL_NEGATIVE + ": a PK-K school", chicago=True),
    # The same schools named by their towns, or by a level that only one of them
    # is, or alone of their name.
    _level("St. Joseph Elementary - Medby", "SYN-MA-SJMD", LEVEL + ": its town said"),
    _level("St. Joseph School - Wakeby", "SYN-MA-SJWK", LEVEL + ": its town said"),
    _level("St. Joseph Elementary (Needby)", "SYN-MA-SJND", LEVEL + ": its town said"),
    _level("Lincoln Elementary - Melby", "SYN-MA-MBLN", LEVEL + ": its town said"),
    _level("Lincoln Elementary School, Winby", "SYN-MA-WBLN", LEVEL + ": its town said"),
    _level("Devonby Elementary", "SYN-MA-SKDV", LEVEL + ": the other is a 6-8 school"),
    _level("Devonby Middle School", "SYN-MA-PLDV", LEVEL + ": a 6-8 school"),
    _level("Devonby Junior High", "SYN-MA-PLDV", LEVEL + ": a 6-8 school"),
    _level("Winstowe Elementary", "SYN-MA-PLWS", LEVEL + ": a K-5 school alone of its name"),
    _level("Winstowe Elementary School", "SYN-MA-PLWS", LEVEL + ": alone of its name"),
    _level("Winstowe Primary School", "SYN-MA-PLWS", LEVEL + ": a K-5 school is a primary"),
    _level("Winstowe Elementary", "SYN-MA-PLWS", LEVEL + ": no point", near=False),
    _level(
        "Devonmoor Elementary - Orland Grove", "SYN-IL-ORDV", LEVEL + ": its town", chicago=True
    ),
    _level(
        "St. John's Lutheran Preschool - Elby", "SYN-IL-SJLE", LEVEL + ": its town", chicago=True
    ),
    _level("Christ Lutheran Preschool", "SYN-IL-CHLU", LEVEL + ": a PK-K school", chicago=True),
    _level("Christ Lutheran Pre-K", "SYN-IL-CHLU", LEVEL + ": a PK-K school", chicago=True),
    _level("Northby Middle School", "SYN-IL-MDNB", LEVEL + ": a 5-8 school", chicago=True),
    # A surname alone names every school of it whose person's forenames it leaves
    # out, spelled or as initials alike, and one of the surname alone: so none.
    case("Kennaby Middle School", "MA", None, counties=TAMBY_COUNTIES, note=PERSON_NEGATIVE),
    case("Kennaby Middle", "MA", None, counties=TAMBY_COUNTIES, note=PERSON_NEGATIVE),
    case("KENNABY MIDDLE SCHOOL", "MA", None, note=PERSON_NEGATIVE + ": statewide"),
    case(
        "Kennaby Middle School - Early Dismissal",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        near=TAMBY,
        note=PERSON_NEGATIVE + ": the point is no evidence",
    ),
    case(
        "J.F. Kennaby Middle School",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        note=PERSON_NEGATIVE + ": J. is John as much",
    ),
    case(
        "John F. Kennaby Middle School",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        note=PERSON_NEGATIVE + ": J F is John F as much",
    ),
    case("John Kennaby Middle School", "MA", None, counties=TAMBY_COUNTIES, note=PERSON_NEGATIVE),
    case(
        "Kennaby Middle School",
        "MA",
        None,
        counties=TAMBY_CO,
        note=PERSON_NEGATIVE + ": alone in the county, its namesakes just past it",
    ),
    case(
        "Kennaby Middle School - Natby",
        "MA",
        "SYN-MA-JFKN",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": its town said",
    ),
    case(
        "Reedby Elementary",
        "MA",
        "SYN-MA-REED",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": the school of the surname, word for word, before a person's",
    ),
    case(
        "Reedby School",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        note=PERSON_NEGATIVE + ": the level left out, the school of the surname is no closer",
    ),
    case(
        "Charles Reedby Elementary",
        "MA",
        "SYN-MA-CREED",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": the person's name",
    ),
    case("Fryby School", "MA", None, counties=TAMBY_COUNTIES, note=PERSON_NEGATIVE),
    case("Harry E. Fryby School", "MA", "SYN-MA-HFRY", counties=TAMBY_COUNTIES, note=PERSON),
    case(
        "W.W. Walkby School",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        note=PERSON_NEGATIVE + ": the school of the surname may be meant",
    ),
    case(
        "J.B. Nelby School",
        "MA",
        "SYN-MA-JBNL",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": V H is another person",
    ),
    case(
        "V.H. Nelby Elementary",
        "MA",
        "SYN-MA-VHNL",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": J B is another person",
    ),
    case("Nelby Elementary", "MA", None, counties=TAMBY_COUNTIES, note=PERSON_NEGATIVE),
    case(
        "F.C. Boydby Christian School",
        "MA",
        "SYN-MA-FCBD",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": initials NCES runs together",
    ),
    case(
        "Pingby School",
        "MA",
        None,
        counties=TAMBY_COUNTIES,
        note=PERSON_NEGATIVE + ": a surname and School alone, no level",
    ),
    case(
        "Pingby Elementary School",
        "MA",
        "SYN-MA-PNGB",
        counties=TAMBY_COUNTIES,
        note=PERSON + ": its level said",
    ),
    case("Johnby Elementary", "TX", None, counties=HIDBY_CO, note=PERSON_NEGATIVE),
    case("JOHNBY EL", "TX", None, counties=HIDBY_CO, note=PERSON_NEGATIVE),
    case(
        "L B Johnby Elementary",
        "TX",
        None,
        counties=HIDBY_CO,
        note=PERSON_NEGATIVE + ": L B is Lyndon B as much",
    ),
    case(
        "Lyndon B. Johnby Elementary",
        "TX",
        None,
        counties=HIDBY_CO,
        note=PERSON_NEGATIVE + ": Lyndon B is L B as much",
    ),
    case("Garzby Middle School", "TX", None, counties=HIDBY_CO, note=PERSON_NEGATIVE),
    case(
        "B L Garzby Middle School",
        "TX",
        "SYN-TX-BLGZ",
        counties=HIDBY_CO,
        note=PERSON + ": Beatriz G is another person",
    ),
    case(
        "Beatriz G. Garzby Middle",
        "TX",
        "SYN-TX-BGGZ",
        counties=HIDBY_CO,
        note=PERSON + ": B L is another person",
    ),
    case("Whitby Elementary", "TX", None, counties=HARBY_CO, note=PERSON_NEGATIVE),
    case(
        "Mark Whitby Elementary",
        "TX",
        "SYN-TX-MRKW",
        counties=HARBY_CO,
        note=PERSON + ": the person's name",
    ),
    case("Whiteby Elementary", "CA", None, counties=LOSBY_CO, note=PERSON_NEGATIVE),
    case(
        "R. D. Whiteby Elementary",
        "CA",
        "SYN-CA-RDWH",
        counties=LOSBY_CO,
        note=PERSON + ": Charles is another person",
    ),
    case(
        "Charles Whiteby Elementary",
        "CA",
        "SYN-CA-CHWH",
        counties=LOSBY_CO,
        note=PERSON + ": R. D. is another person",
    ),
    case(
        "Whiteby Oak Elementary", "CA", "SYN-CA-WHOK", counties=LOSBY_CO, note=PERSON + ": a place"
    ),
    case(
        "Kenby Elementary",
        "CA",
        None,
        counties=LOSBY_CO,
        note=PERSON_NEGATIVE + ": NCES's bracket, and Robert F.",
    ),
    case(
        "John F. Kenby Elementary",
        "CA",
        "SYN-CA-KNJF",
        counties=LOSBY_CO,
        note=PERSON + ": the forenames NCES bracketed",
    ),
    case(
        "Robert Kenby Elementary",
        "CA",
        "SYN-CA-RFKB",
        counties=LOSBY_CO,
        note=PERSON + ": John F. is another person",
    ),
    case(
        "Burbby Elementary",
        "CA",
        "SYN-CA-BRBL",
        counties=LOSBY_CO,
        note=PERSON + ": a forename NCES bracketed is surely one",
    ),
    case("Luther Burbby Elementary", "CA", "SYN-CA-BRBL", counties=LOSBY_CO, note=PERSON),
    case("Watby Elementary", "LA", None, counties=CALBY_CO, note=PERSON_NEGATIVE),
    case(
        "J. I. Watby Elementary",
        "LA",
        "SYN-LA-JIWT",
        counties=CALBY_CO,
        note=PERSON + ": dotted initials, not a district's number",
    ),
    case(
        "Pearl Watby Elementary",
        "LA",
        "SYN-LA-PRWT",
        counties=CALBY_CO,
        note=PERSON + ": J. I. is another person",
    ),
    case(
        "Koogby Middle School",
        "LA",
        "SYN-LA-CVKG",
        counties=CALBY_CO,
        note=PERSON + ": C. V., initials, alone of its surname",
    ),
    case("Chipby Middle School", "DE", "SYN-DE-WTCH", counties=KENTBY_CO, note=PERSON),
    case("W.T. Chipby Middle School", "DE", "SYN-DE-WTCH", counties=KENTBY_CO, note=PERSON),
    case("REDBY MIDDLE SCHOOL", "DE", "SYN-DE-LLRD", counties=KENTBY_CO, note=PERSON),
    case(
        "Charby Elementary",
        "MT",
        "SYN-MT-CHRB",
        counties=BLACKBY_CO,
        note=PERSON + ": a title alone is no forename; the town's elementary district",
    ),
    # A word written with a plural's "s" on one side only is another word.
    case("Park Elementary", "TX", None, counties=HARBY_CO, note=PLURAL_NEGATIVE),
    case("Parks Elementary", "TX", "SYN-TX-PRKS", counties=HARBY_CO, note=PLURAL),
    case("Grove Elementary", "TX", None, counties=HARBY_CO, note=PLURAL_NEGATIVE),
    case("Brook Elementary", "MA", None, counties=TAMBY_COUNTIES, note=PLURAL_NEGATIVE),
    case("Brooks School", "MA", "SYN-MA-BRKS", counties=TAMBY_COUNTIES, note=PLURAL),
    case("Oak Elementary", "CA", None, counties=LOSBY_CO, note=PLURAL_NEGATIVE),
    case("The Oaks School", "CA", "SYN-CA-OAKS", counties=LOSBY_CO, note=PLURAL),
    case("Lake Elementary", "DE", None, counties=KENTBY_CO, note=PLURAL_NEGATIVE),
    case(
        "Welsby Hill School",
        "DE",
        None,
        counties=KENTBY_CO,
        note=PLURAL_NEGATIVE + ": the queue, though a list may misspell it",
    ),
    case(
        "Terrys Montessori School",
        "DE",
        "SYN-DE-TRRY",
        counties=KENTBY_CO,
        note=PLURAL + ": a possessive NCES wrote apart",
    ),
    case(
        "Clevby Art & Social Science",
        "DE",
        "SYN-DE-CLVA",
        counties=KENTBY_CO,
        note=PLURAL + ": words that say the school's kind",
    ),
)
