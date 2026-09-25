"""U.S. Census Bureau source files used to build city and ZIP search records.

* :mod:`snowlight.sources.census.listing` reads the Apache directory indexes on
  ``www2.census.gov`` so the build can find the newest release instead of
  hard-coding a year.
* :mod:`snowlight.sources.census.gazetteer` finds and parses the national
  Gazetteer files for places and ZIP Code Tabulation Areas (ZCTAs).
* :mod:`snowlight.sources.census.popest` finds and parses the Population
  Estimates Program's city and town totals (``sub-est<vintage>.csv``).
* :mod:`snowlight.sources.census.lsad` parses the official Legal/Statistical Area
  Description code list, which says which words of a place's full name are the
  descriptor ("city", "CDP", ...) rather than the name itself.
* :mod:`snowlight.sources.census.zcta_county` parses the 2020 ZCTA-to-county
  relationship file, which places every ZCTA in one or more states.

Every parser keeps values exactly as published: codes stay strings, coordinates
come from the published decimal text, and a row that does not fit the documented
layout raises :class:`CensusFormatError` rather than being skipped.
"""


class CensusFormatError(ValueError):
    """Raised when a Census file does not match its documented layout."""


__all__ = ["CensusFormatError"]
