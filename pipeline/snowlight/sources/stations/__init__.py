"""Closings lists published by TV stations and other outlets, read live and from archives.

* :mod:`~snowlight.sources.stations.registry`: the per-platform registry in
  ``pipeline/config/sources/*.yaml`` (stations, URLs, counties, terms, robots).
* :mod:`~snowlight.sources.stations.pagecheck` (with ``pagecheck.cjs``): each
  station's ``data_url`` is the list file its page loads, from a browser check.
* :mod:`~snowlight.sources.stations.http`: polite fetching (robots.txt verdicts
  recorded, per-host pacing, conditional requests, timeouts, retries with backoff).
* :mod:`~snowlight.sources.stations.robots`: RFC 9309 robots.txt rules.
* :mod:`~snowlight.sources.stations.model`: raw rows, listings and health.
* :mod:`~snowlight.sources.stations.adapters`: one parser per platform, found by name
  from the platform files present and shared by live bodies and Wayback captures
  (:mod:`~snowlight.sources.stations.gray`, with the pre-Arc page formats in
  :mod:`~snowlight.sources.stations.gray_legacy` and the list files those pages
  framed or loaded in :mod:`~snowlight.sources.stations.gray_files`;
  :mod:`~snowlight.sources.stations.hearst`; and each other platform's module).
* :mod:`~snowlight.sources.stations.fetch`: ``snowlight stations fetch`` (a list file
  not written since the last winter began is read as stale).
* :mod:`~snowlight.sources.stations.archive`: Wayback listings, snapshot plans (storm
  days first: :mod:`~snowlight.sources.stations.storms`), parsing.
* :mod:`~snowlight.sources.stations.fixtures`: sliced real bodies for the tests.
* :mod:`~snowlight.sources.stations.dma` and :mod:`~snowlight.sources.stations.coverage`:
  market county lists and the measured coverage map (plain and closure-weighted);
  :mod:`~snowlight.sources.stations.observed` checks those lists against the counties
  the stations' own archived lists name.

Nothing here classifies a status or matches a school: rows leave as raw text.
"""
