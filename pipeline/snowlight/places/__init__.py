"""City and ZIP code records for the site's search box.

``snowlight places build`` writes two JSON Lines files to
``out/site-data/search/`` (one compact, key-sorted JSON object per line, UTF-8,
``\\n`` line ends, sorted by their first key so rebuilding from the same sources
gives byte-identical files). They are the input of the web search index builder;
nothing in them names a source.

``cities.jsonl`` - one line per Census place (incorporated place or census
designated place) in the 48 contiguous states and DC, sorted by ``geoid``::

    {"geoid":"0100124","kind":"city","lat":31.565164,"lon":-85.259165,
     "name":"Abbeville","population":2378,"state":"AL"}

* ``geoid`` (string): 7-digit Census place code, state FIPS + place FIPS.
* ``name`` (string): the place name without its legal/statistical descriptor.
* ``kind`` (string or null): that descriptor, e.g. ``city``, ``town``,
  ``village``, ``borough``, ``CDP``; null when the official name carries none
  (such as "Nashville-Davidson metropolitan government (balance)").
* ``state`` (string): USPS state abbreviation.
* ``lat`` / ``lon`` (numbers): the Census internal point, decimal degrees.
* ``population`` (integer or null): the latest July 1 population estimate, for
  ranking; null for CDPs and for places without an estimate.

``zips.jsonl`` - one line per ZIP Code Tabulation Area with land in the 48
contiguous states or DC, sorted by ``zcta``::

    {"districts":[{"leaid":"2502790","name":"Cambridge School District","share":1.0}],
     "lat":42.364...,"lon":-71.10...,"states":["MA"],"zcta":"02139"}

* ``zcta`` (string): 5-digit ZCTA code.
* ``lat`` / ``lon`` (numbers): the Census internal point, decimal degrees.
* ``states`` (list of strings, at least one): USPS abbreviations of the states the
  ZCTA has land in, most land first.
* ``districts`` (list, possibly empty): every school district with land in the
  ZCTA, largest share first, each as ``leaid`` (7-digit NCES ID), ``name`` and
  ``share`` - the fraction of the ZCTA's land area inside that district, rounded
  to 4 significant digits (so always > 0 and <= 1). Elementary and secondary
  districts overlap in some states, so shares can sum above 1; land in no
  district leaves them below 1.

The internal manifest (``out/manifests/places.json``, never published) records
every source file's URL, retrieval time and SHA-256, the releases used, counts
for each step, and the SHA-256 of both outputs. The pydantic models in
:mod:`snowlight.places.records` validate every record before it is written.
"""
