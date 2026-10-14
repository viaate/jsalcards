"""District numbers a state gives its districts that their NCES names leave out.

Kansas numbers every unified school district, and the closings lists name a
district by its number (``"Blue Valley USD 229"``, ``"USD #229"``, ``"Leavenworth
USD453"``), but NCES names it without (``"Blue Valley"``). The number is what
tells namesakes apart: Blue Valley USD 229, in Johnson County, and Blue Valley USD
384, in Riley County, share their NCES name. A district's number here is one its
name answers to without saying it: a listing that gives it names the district, a
listing that gives another number does not, and a listing that gives none costs
the district nothing (see :class:`~snowlight.match.index.NameIndex`).

The numbers are the state's own ids for its districts, which the CCD school
directory (``ccd_sch_029_2425_w_1a_073025``, the directory's source) carries as
``ST_LEAID``: ``KS-D0229`` is USD 229. Kansas's state schools and agencies
(``KS-S0604``, the School for the Blind) are numbered in another series and are
left out. Keyed by NCES district id (``LEAID``).
"""

from collections.abc import Mapping
from typing import Final

UNSAID_NUMBERS: Final[Mapping[str, str]] = {
    "2000001": "306",  # Southeast Of Saline
    "2000002": "400",  # Smoky Valley
    "2000003": "320",  # Wamego
    "2000004": "323",  # Rock Creek
    "2000006": "415",  # Hiawatha
    "2000007": "237",  # Smith Center
    "2000012": "223",  # Barnes
    "2000013": "275",  # Triplains
    "2000014": "288",  # Central Heights
    "2000015": "290",  # Ottawa
    "2000016": "364",  # Marysville
    "2000017": "466",  # Scott County
    "2000020": "106",  # Western Plains
    "2000023": "105",  # Rawlins County
    "2000028": "108",  # Washington Co. Schools
    "2000029": "107",  # Rock Hills
    "2000030": "109",  # Republic County
    "2000346": "110",  # Thunder Ridge Schools
    "2000348": "111",  # Doniphan West Schools
    "2000349": "112",  # Central Plains
    "2000350": "113",  # Prairie Hills
    "2000351": "114",  # Riverside
    "2000353": "115",  # Nemaha Central
    "2003180": "435",  # Abilene
    "2003200": "437",  # Auburn-Washburn
    "2003210": "251",  # North Lyon County
    "2003240": "329",  # Wabaunsee
    "2003270": "212",  # Northern Valley
    "2003300": "506",  # Labette County
    "2003360": "385",  # Andover
    "2003390": "361",  # Chaparral Schools
    "2003430": "359",  # Argonia Public Schools
    "2003450": "470",  # Arkansas City
    "2003480": "246",  # Northeast
    "2003510": "220",  # Ashland
    "2003540": "409",  # Atchison Public Schools
    "2003570": "511",  # Attica
    "2003630": "402",  # Augusta
    "2003720": "348",  # Baldwin City
    "2003780": "458",  # Basehor-Linwood
    "2003810": "508",  # Baxter Springs
    "2003870": "273",  # Beloit
    "2003900": "357",  # Belle Plaine
    "2003960": "240",  # Twin Valley
    "2004020": "403",  # Otis-Bison
    "2004050": "204",  # Bonner Springs
    "2004080": "314",  # Brewster
    "2004140": "459",  # Bucklin
    "2004170": "387",  # Altoona-Midway
    "2004200": "313",  # Buhler
    "2004230": "462",  # Central
    "2004260": "454",  # Burlingame Public School
    "2004290": "244",  # Burlington
    "2004350": "369",  # Burrton
    "2004380": "360",  # Caldwell
    "2004410": "436",  # Caney Valley
    "2004440": "419",  # Canton-Galva
    "2004470": "272",  # Waconda
    "2004500": "285",  # Cedar Vale
    "2004560": "380",  # Vermillion
    "2004590": "413",  # Chanute Public Schools
    "2004620": "473",  # Chapman
    "2004650": "401",  # Chase-Raymond
    "2004670": "268",  # Cheney
    "2004710": "247",  # Cherokee
    "2004740": "447",  # Cherryvale
    "2004770": "505",  # Chetopa-St. Paul
    "2004790": "103",  # Cheylin
    "2004800": "102",  # Cimarron-Ensign
    "2004830": "335",  # North Jackson
    "2004890": "379",  # Clay County
    "2004920": "264",  # Clearwater
    "2004950": "224",  # Clifton-Clyde
    "2004980": "445",  # Coffeyville
    "2005010": "315",  # Colby Public Schools
    "2005040": "300",  # Comanche County
    "2005070": "493",  # Columbus
    "2005100": "333",  # Concordia
    "2005130": "356",  # Conway Springs
    "2005190": "476",  # Copeland
    "2005250": "284",  # Chase County
    "2005280": "417",  # Morris County
    "2005310": "426",  # Pike Valley
    "2005370": "332",  # Cunningham
    "2005400": "216",  # Deerfield
    "2005460": "260",  # Derby
    "2005490": "232",  # De Soto
    "2005520": "471",  # Dexter
    "2005550": "482",  # Dighton
    "2005580": "443",  # Dodge City
    "2005610": "396",  # Douglass Public Schools
    "2005640": "449",  # Easton
    "2005700": "377",  # Atchison Co Comm Schools
    "2005730": "490",  # El Dorado
    "2005760": "283",  # Elk Valley
    "2005790": "218",  # Elkhart
    "2005800": "307",  # Ell-Saline
    "2005820": "355",  # Ellinwood Public Schools
    "2005850": "388",  # Ellis
    "2005870": "327",  # Ellsworth
    "2005940": "253",  # Emporia
    "2006000": "101",  # Erie-Galesburg
    "2006060": "330",  # Mission Valley
    "2006090": "491",  # Eudora
    "2006120": "389",  # Eureka
    "2006180": "234",  # Fort Scott
    "2006210": "225",  # Fowler
    "2006240": "206",  # Remington-Whitewater
    "2006270": "484",  # Fredonia
    "2006300": "249",  # Frontenac Public Schools
    "2006330": "207",  # Fort Leavenworth
    "2006360": "499",  # Galena
    "2006390": "457",  # Garden City
    "2006420": "231",  # Gardner Edgerton
    "2006450": "365",  # Garnett
    "2006480": "248",  # Girard
    "2006510": "334",  # Southern Cloud
    "2006540": "265",  # Goddard
    "2006570": "411",  # Goessel
    "2006580": "352",  # Goodland
    "2006630": "292",  # Wheatland
    "2006660": "428",  # Great Bend
    "2006690": "200",  # Greeley County Schools
    "2006720": "422",  # Kiowa County
    "2006780": "291",  # Grinnell Public Schools
    "2006840": "440",  # Halstead
    "2006870": "390",  # Hamilton
    "2006930": "252",  # Southern Lyon County
    "2006960": "312",  # Haven Public Schools
    "2006990": "474",  # Haviland
    "2007020": "489",  # Hays
    "2007050": "261",  # Haysville
    "2007080": "468",  # Healy Public Schools
    "2007110": "487",  # Herington
    "2007170": "460",  # Hesston
    "2007260": "281",  # Graham County
    "2007290": "410",  # Durham-Hillsboro-Lehigh
    "2007320": "431",  # Hoisington
    "2007350": "363",  # Holcomb
    "2007380": "336",  # Holton
    "2007440": "481",  # Rural Vista
    "2007470": "430",  # South Brown County
    "2007500": "282",  # West Elk
    "2007530": "412",  # Hoxie Community Schools
    "2007560": "210",  # Hugoton Public Schools
    "2007590": "258",  # Humboldt
    "2007620": "308",  # Hutchinson Public Schools
    "2007650": "446",  # Independence
    "2007680": "477",  # Ingalls
    "2007710": "448",  # Inman
    "2007740": "257",  # Iola
    "2007750": "346",  # Jayhawk
    "2007800": "227",  # Hodgeman County
    "2007860": "452",  # Stanton County
    "2007890": "475",  # Geary County Schools
    "2007950": "500",  # Kansas City
    "2007970": "321",  # Kaw Valley
    "2008040": "479",  # Crest
    "2008070": "331",  # Kingman - Norwich
    "2008100": "347",  # Kinsley-Offerle
    "2008130": "255",  # South Barber
    "2008190": "483",  # Kismet-Plains
    "2008220": "395",  # LaCrosse
    "2008250": "362",  # Prairie View
    "2008280": "215",  # Lakin
    "2008310": "310",  # Fairfield
    "2008340": "469",  # Lansing
    "2008370": "495",  # Ft Larned
    "2008400": "497",  # Lawrence
    "2008430": "453",  # Leavenworth
    "2008550": "205",  # Bluestem
    "2008610": "467",  # Leoti
    "2008670": "245",  # LeRoy-Gridley
    "2008700": "502",  # Lewis
    "2008730": "480",  # Liberal
    "2008790": "298",  # Lincoln
    "2008880": "444",  # Little River
    "2008910": "326",  # Logan
    "2008940": "397",  # Centre
    "2008970": "416",  # Louisburg
    "2009000": "421",  # Lyndon
    "2009030": "405",  # Lyons
    "2009060": "351",  # Macksville
    "2009090": "386",  # Madison-Virgil
    "2009140": "266",  # Maize
    "2009180": "383",  # Manhattan-Ogden
    "2009240": "408",  # Marion-Florence
    "2009320": "337",  # Royal Valley
    "2009360": "342",  # McLouth
    "2009390": "418",  # McPherson
    "2009420": "226",  # Meade
    "2009450": "254",  # Barber County North
    "2009480": "456",  # Marais Des Cygnes Valley
    "2009510": "340",  # Jefferson West
    "2009570": "239",  # North Ottawa County
    "2009600": "219",  # Minneola
    "2009630": "371",  # Montezuma
    "2009660": "256",  # Marmaton Valley
    "2009720": "209",  # Moscow Public Schools
    "2009780": "423",  # Moundridge
    "2009840": "263",  # Mulvane
    "2009850": "399",  # Paradise
    "2009900": "461",  # Neodesha
    "2009930": "303",  # Ness City
    "2009960": "373",  # Newton
    "2009990": "309",  # Nickerson
    "2010020": "211",  # Norton Community Schools
    "2010050": "274",  # Oakley
    "2010080": "294",  # Oberlin
    "2010140": "233",  # Olathe
    "2010170": "322",  # Onaga-Havensville-Wheaton
    "2010230": "420",  # Osage City
    "2010260": "367",  # Osawatomie
    "2010290": "392",  # Osborne County
    "2010320": "341",  # Oskaloosa Public Schools
    "2010350": "504",  # Oswego
    "2010410": "434",  # Santa Fe Trail
    "2010440": "358",  # Oxford
    "2010470": "269",  # Palco
    "2010500": "368",  # Paola
    "2010560": "503",  # Parsons
    "2010590": "398",  # Peabody-Burns
    "2010620": "343",  # Perry Public Schools
    "2010650": "325",  # Phillipsburg
    "2010680": "203",  # Piper-Kansas City
    "2010710": "250",  # Pittsburg
    "2010740": "270",  # Plainville
    "2010770": "344",  # Pleasanton
    "2010800": "287",  # West Franklin
    "2010890": "382",  # Pratt
    "2010920": "311",  # Pretty Prairie
    "2010950": "293",  # Quinter Public Schools
    "2010980": "384",  # Blue Valley
    "2011040": "316",  # Golden Plains
    "2011080": "267",  # Renwick
    "2011100": "378",  # Riley County
    "2011130": "404",  # Riverton
    "2011190": "217",  # Rolla
    "2011220": "492",  # Flinthills
    "2011250": "394",  # Rose Hill Public Schools
    "2011280": "496",  # Pawnee Heights
    "2011310": "407",  # Russell County
    "2011370": "305",  # Salina
    "2011400": "507",  # Satanta
    "2011430": "438",  # Skyline Schools
    "2011490": "345",  # Seaman
    "2011520": "286",  # Chautauqua Co Community
    "2011550": "439",  # Sedgwick Public Schools
    "2011610": "241",  # Wallace County Schools
    "2011640": "512",  # Shawnee Mission Pub Sch
    "2011700": "372",  # Silver Lake
    "2011760": "393",  # Solomon
    "2011790": "509",  # South Haven
    "2011820": "381",  # Spearville
    "2011850": "230",  # Spring Hill
    "2011880": "297",  # St Francis Comm Sch
    "2011910": "350",  # St John-Hudson
    "2011970": "349",  # Stafford
    "2012000": "229",  # Blue Valley
    "2012030": "376",  # Sterling
    "2012060": "271",  # Stockton
    "2012090": "374",  # Sublette
    "2012120": "299",  # Sylvan Grove
    "2012150": "494",  # Syracuse
    "2012180": "450",  # Shawnee Heights
    "2012210": "464",  # Tonganoxie
    "2012260": "501",  # Topeka Public Schools
    "2012300": "375",  # Circle
    "2012330": "429",  # Troy Public Schools
    "2012360": "202",  # Turner-Kansas City
    "2012390": "463",  # Udall
    "2012420": "214",  # Ulysses
    "2012450": "235",  # Uniontown
    "2012510": "262",  # Valley Center Pub Sch
    "2012540": "338",  # Valley Falls
    "2012600": "432",  # Victoria
    "2012630": "208",  # Trego County
    "2012780": "498",  # Valley Heights
    "2012810": "243",  # Lebo-Waverly
    "2012840": "353",  # Wellington
    "2012870": "289",  # Wellsville
    "2012900": "242",  # Weskan
    "2012990": "259",  # Wichita
    "2013020": "339",  # Jefferson County North
    "2013050": "465",  # Winfield
    "2013110": "366",  # Woodson
}
