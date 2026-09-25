"""National Weather Service sources and the archive of NWS warnings.

* :mod:`~snowlight.sources.nws.http`: HTTPS fetches with a User-Agent naming this
  repository (the NWS API requires one), conditional requests, retries and a
  checksummed on-disk cache with a provenance sidecar per file.
* :mod:`~snowlight.sources.nws.shapefile`: a small reader for the zipped
  ESRI shapefiles the NWS and the Iowa Environmental Mesonet publish.
* :mod:`~snowlight.sources.nws.boundaries`: the NWS public forecast zone and
  county boundary releases (www.weather.gov/gis), keyed by UGC code.
* :mod:`~snowlight.sources.nws.vtec`: VTEC strings and codes.
* :mod:`~snowlight.sources.nws.alerts`: active alerts from api.weather.gov.
* :mod:`~snowlight.sources.nws.iem`: the Iowa Environmental Mesonet archive of
  NWS VTEC watches, warnings and advisories: day files, point-in-time snapshots
  and per-office range files, each cached with its provenance.
"""
