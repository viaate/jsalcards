"""Closure weights: favor the places whose weather closes schools.

The owner asked (2026-09-26) that the build "favor states that get more school
closings on average, like Rhode Island, versus something like Mississippi that
will rarely ever get school off". This package measures, per county, how often
closure-type weather happens on school days, from the NWS warnings archived by
the Iowa Environmental Mesonet, turns it into a weight whose school-weighted
national mean is 1, and ranks the remaining scraper families by the
closure-weighted schools each would add. Every state is still covered in the
end; the weights set the order of work and a weighted coverage number.

Modules:

* :mod:`~snowlight.weights.codes`: the closure-type codes and their weights;
* :mod:`~snowlight.weights.archive`: the IEM school-year files;
* :mod:`~snowlight.weights.zones`: the NWS zone-county correlation and county list;
* :mod:`~snowlight.weights.count`: school days and the 6 AM rule;
* :mod:`~snowlight.weights.schools`: schools placed in NWS counties;
* :mod:`~snowlight.weights.crosscheck`: checks against the day-file client and
  IEM's zone names;
* :mod:`~snowlight.weights.outlines`: checks against IEM's archived zone outlines;
* :mod:`~snowlight.weights.markets`: television markets (DMAs) as county FIPS
  codes, from the pinned crosswalk, the 2025 Gazetteer and the Connecticut
  crosswalk;
* :mod:`~snowlight.weights.priority`: the scraper families and their gains;
* :mod:`~snowlight.weights.registered`: a read-only look at the station registry,
  for two optional checks of the priority;
* :mod:`~snowlight.weights.build`, :mod:`~snowlight.weights.notes`,
  :mod:`~snowlight.weights.render` and :mod:`~snowlight.weights.cli`: the
  ``python -m snowlight.weights build`` command and its files.

Outputs (internal, in ``pipeline/out/internal/weights/``; none is published, so
they may name sources; the provenance of every input is in ``manifest.json``).
Keys are written sorted; the shapes, in reading order (schema 2 added
``years_counted`` and ``school_years_left_out``, and ``null`` years in ``by_year``):

``closure-weights.json``::

    {"schema": 2, "generated_at": "...Z", "school_years": ["2015-16", ...],
     "codes": {"WS.W": {"name", "group", "weight"}, ...},
     "normalizer": {"school_weighted_mean_days_per_year": float, "schools": int},
     "counties": [{
        "fips": "44007", "state": "RI", "name": "Providence",
        "time_zones": ["America/New_York"],
        "schools": int,                     # directory schools placed in the county
        "years_counted": int,               # school years averaged (all 11 but those left out)
        "school_years_left_out": {"2015-16": ["CAZ096", ...], ...},  # incomplete years and
                                            # the zones whose rows could not be counted there
        "days_per_year": float,             # the metric: weighted distinct school days / year
        "weight": float,                    # days_per_year / normalizer
        "weighted_days_total": float,       # over the school years counted
        "any_days_per_year": float,         # unweighted, any closure-type code
        "codes": {"WS.W": {"days": int, "per_year": float}, ...},  # unweighted, per code
        "subsets_days_per_year": {"winter", "listed_winter", "listed", "cold",
                                  "tropical", "flood"},  # weighted, those codes only
        "by_year": {"2015-16": {"weighted": float, "days": int} | null, ...},  # null: left out
        "whole_county_days_per_year": float,  # diagnostic: days every zone was covered
        "whole_county_weight": float,         # the same, normalized the same way
        "top_zones": [{"ugc", "name", "days", "only"}, ...],  # the UGCs behind the days
        "left_out_zone_days": {"2015-16": float, ...}},  # diagnostic: days the left-out zone
      ...]}                                               # rows would add (not in the metric)

Every per-year figure of a county (``days_per_year``, ``any_days_per_year``,
``codes.*.per_year``, ``subsets_days_per_year``, ``whole_county_days_per_year``)
divides by its ``years_counted``; the per-code ``days``, ``weighted_days_total``
and ``top_zones`` cover those years only (:mod:`snowlight.weights.count`).

``state-weights.json``::

    {"schema": 2, "generated_at", "school_years", "normalizer",
     "states": [{"state", "rank", "schools",
                 "schools_in_counties_with_school_years_left_out",
                 "weight",                          # school-weighted mean weight
                 "days_per_year",                   # school-weighted mean metric
                 "share_of_weighted_closure_days",  # of the national school-weighted sum
                 "any_days_per_year", "whole_county_days_per_year", "whole_county_weight",
                 "partial_day_share", "subsets_days_per_year": {...},
                 "code_days_per_year": {...}}, ...],   # heaviest first
     "sanity": {"snowy", "mild", "missing_states", "bar", "weights",
                "winter": {"snowy_days_per_year", "mild_days_per_year",
                           "lowest_snowy_over_highest_mild", "passes"},
                "listed_winter": {...}},
     "flags": [{"state", "finding", "reason", "counties": [...]}, ...]}

``station-priority.json``::

    {"schema": 2, "generated_at", "school_years",
     "baseline": {"what", "counties", "schools", "weighted_schools", "share",
                  "weighted_share", "counties_any_gray_hearst_station_lists",
                  "working_stations_by_group": {"gray": int, ...},
                  "every_working_source": {"counties", "schools", "weighted_schools",
                                           "share", "weighted_share"}},
     "schools", "weighted_schools",
     "families": [{"rank", "id", "name", "sources", "sources_robots_blocked",
                   "market_counties", "market_schools", "market_weighted_schools",
                   "standalone": {"new_counties", "new_schools", "new_weighted_schools"},
                   "standalone_beyond_every_working_source": {...the same three},
                   "standalone_without_stale_members": {"stale_members", "new_schools",
                                                        "new_weighted_schools"},
                   "in_order": {"new_counties", "new_schools", "new_weighted_schools",
                                "cumulative_schools", "cumulative_share",
                                "cumulative_weighted_share"},
                   "rank_without_stale_members",
                   "rank_if_every_listed_gray_hearst_county_counted",
                   "rank_with_whole_county_weights", "rank_by_schools_unweighted",
                   "rank_beyond_every_working_source",
                   "members": [{"name", "group", "variant", "market", "states", "markets",
                                "basis", "found_by", "note", "robots_blocked", "stale_since",
                                "counted_because", "counties", "research_file"}]}, ...],
     "records": {"counted", "left_out", "left_out_by_reason": {reason: [names]},
                 "left_out_as_gray_checked_in_registry":
                     [{"name", "variant", "reason", "registry_station",
                       "registry_platform", "registry_status", "registry_counties",
                       "found_by"}, ...] | "not read" | "the registry could not be read: ..."},
     "market_counties_checked_in_registry":
         {"stations_with_dma_county_lists", "agreeing",
          "differing": [{"station", "dma", "in_crosswalk", "registry_counties",
                         "market_counties", "only_in_registry", "only_in_market"}, ...]}
         | "not read" | "the registry could not be read: ..."}

``manifest.json``: ``{"schema", "generated_at", "school_years", "sources": {
"school_years", "zone_county_releases", "county_release", "references",
"directory", "adopted_from_other_caches"}, "checks": {"rows", "zone_mapping",
"zone_names_before_first_release", "zone_outlines", "years_counted", "day_files",
"code_changes", "schools"}}``, every downloaded file with its URL, retrieval time and
SHA-256. ``zone_outlines.school_years_left_out`` lists every county-year left out
and why; ``years_counted`` compares the years each group of counties keeps with the
whole period; ``schools.address_state_elsewhere`` lists the schools whose directory
address is in another state than the county they are placed in (they count in the
county's state, :mod:`snowlight.weights.schools`).

Also ``method.md``, ``station-priority.md`` and ``closure-weights.png``.
"""
