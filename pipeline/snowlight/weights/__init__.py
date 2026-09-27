"""Closure weights: favor the places whose weather closes schools.

The owner asked (2026-09-26) that the build "favor states that get more school
closings on average, like Rhode Island, versus something like Mississippi that
will rarely ever get school off". This package measures, for every school, how
often closure-type weather happens on school days where the school is, from the
NWS warnings archived by the Iowa Environmental Mesonet, turns it into a weight
whose mean over the schools is 1, and ranks the remaining scraper families by
the closure-weighted schools each would add. Every state is still covered in the
end; the weights set the order of work and a weighted coverage number.

Each school gets the warnings of the public forecast zone its own point lies in,
as that zone stood when each product was issued (schema 3; 2026-09-27). The
earlier rule, which gave every county the warnings of every zone that touches it,
is still computed beside it (``county_rule``): under it, mountain-zone warnings
counted for valley cities.

Modules:

* :mod:`~snowlight.weights.codes`: the closure-type codes and their weights;
* :mod:`~snowlight.weights.archive`: the IEM school-year files;
* :mod:`~snowlight.weights.zonepolys`: each zone row's polygon, as the zone stood
  when its product was issued (the served NWS zone releases and IEM's copies);
* :mod:`~snowlight.weights.schoolzones`: each school in its own zone and time zone;
* :mod:`~snowlight.weights.polygons`: storm-based polygons (the Flash Flood Warning);
* :mod:`~snowlight.weights.schoolcount` and :mod:`~snowlight.weights.perschool`: the
  per-school days, and the school, county and state records;
* :mod:`~snowlight.weights.zones`: the NWS zone-county correlation and county list
  (the county rule);
* :mod:`~snowlight.weights.count`: school days, the 6 AM rule and the county rule's counts;
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
Keys are written sorted; the shapes, in reading order (schema 3 made the weight per
school, the county's the mean of its schools', and moved the county rule's own
figures under ``county_rule``):

``closure-weights.json``::

    {"schema": 3, "generated_at": "...Z", "school_years": ["2015-16", ...],
     "codes": {"WS.W": {"name", "group", "weight"}, ...},
     "normalizer": {"school_weighted_mean_days_per_year": float,  # mean over schools
                    "schools": int,
                    "county_rule_school_weighted_mean_days_per_year": float,
                    "whole_county_school_weighted_mean_days_per_year": float},
     "schools": {"010000500870": {       # NCES id
        "fips": "01095", "state": "AL",  # the NWS county the school is placed in
        "zone": "ALZ010" | null,         # its zone in z_18mr25 (null: fell back to county)
        "placed": "inside" | "nearest" | "county",
        "distance_km": float | null,     # only when not "inside"
        "school_years_outside_zone": {"2015-16": "nearest" | "county" | "not_taken", ...},
                                         # only for a school outside its zone's outline of
                                         # a school year (schoolzones.place_by_year)
        "time_zones": ["America/Chicago"],
        "weight": float,                 # days_per_year / normalizer
        "days_per_year": float,          # the metric: weighted distinct school days / year
        "any_days_per_year": float,      # unweighted, any closure-type code
        "years_counted": int,
        "codes": {"WS.W": float, ...}},  # distinct days per year, codes with any
       ...},
     "counties": [{                      # counties with at least one school
        "fips": "44007", "state": "RI", "name": "Providence",
        "time_zones": ["America/New_York"],
        "schools": int,
        "weight": float,                 # the mean of its schools' weights
        "days_per_year": float, "any_days_per_year": float,  # means of its schools'
        "weighted_days_total": float,    # mean over schools, over their years counted
        "years_counted": int,            # the fewest any of its schools counts
        "schools_with_school_years_left_out": int,
        "codes": {"WS.W": {"days": float, "per_year": float}, ...},  # school means
        "subsets_days_per_year": {"winter", "listed_winter", "listed", "cold",
                                  "tropical", "flood"},
        "by_year": {"2015-16": {"weighted", "days", "schools"} | null, ...},
        "zones": {"RIZ002": int, ...},   # its schools by zone (z_18mr25)
        "schools_placed": {"inside": int, ...},
        "whole_county_days_per_year": float,  # diagnostic (county rule): days every
        "whole_county_weight": float,         # zone of the county was covered
        "county_rule": {"weight", "days_per_year", "any_days_per_year", "years_counted",
                        "school_years_left_out": {"2015-16": ["CAZ096", ...], ...},
                        "by_year": {...}, "codes": {"WS.W": {"days": int, "per_year"}},
                        "top_zones": [{"ugc", "name", "days", "only"}, ...],
                        "left_out_zone_days": {"2015-16": float, ...}}},
      ...],
     "counties_without_schools": ["28055", ...]}

A county's ``weight`` times its ``schools`` is the sum of its schools' weights, so a
reader that gives each school its county's weight (the station coverage) gets the
same county totals. The county rule's per-year figures divide by its own
``years_counted`` (:mod:`snowlight.weights.count`).

``state-weights.json``::

    {"schema": 3, "generated_at", "school_years", "normalizer",
     "states": [{"state", "rank", "schools", "schools_with_school_years_left_out",
                 "schools_placed": {"inside": int, ...},
                 "weight",                          # mean of its schools' weights
                 "days_per_year",                   # mean of its schools' metric
                 "share_of_weighted_closure_days",  # of the national sum over schools
                 "any_days_per_year", "subsets_days_per_year": {...},
                 "code_days_per_year": {...},
                 "county_rule_weight", "county_rule_rank", "county_rule_days_per_year",
                 "whole_county_days_per_year", "whole_county_weight",
                 "partial_day_share"}, ...],        # heaviest first
     "sanity": {"snowy", "mild", "missing_states", "bar", "weights",
                "winter": {"snowy_days_per_year", "mild_days_per_year",
                           "lowest_snowy_over_highest_mild", "passes"},
                "listed_winter": {...}},
     "flags": [{"state", "finding", "reason", "counties": [...]}, ...]}

``station-priority.json`` (weighted schools are sums of the schools' own weights)::

    {"schema": 3, "generated_at", "school_years",
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
"school_years", "zone_county_releases", "county_release", "zone_releases": {"served",
"iem_full_resolution"}, "storm_polygons", "references", "directory",
"adopted_from_other_caches"}, "checks": {"rows", "zone_mapping",
"zone_names_before_first_release", "zone_outlines", "years_counted", "day_files",
"code_changes", "schools", "zone_polygons", "school_zones", "school_counting",
"storm_polygons"}}``, every downloaded file with its URL, retrieval time and SHA-256.
``zone_polygons`` gives every zone version's source (the IEM ones listed with their
``area2d``); ``school_zones`` lists every school not placed inside a zone polygon, and
(``by_school_year``) every school year in which a school lay outside its own zone's
outline of that year, with the versions, distances and what the school took;
``zone_outlines.school_years_left_out`` lists every county-year the county rule leaves
out and why; ``schools.address_state_elsewhere`` lists the schools whose directory
address is in another state than the county they are placed in (they count in the
county's state, :mod:`snowlight.weights.schools`).

Also ``method.md``, ``station-priority.md`` and ``closure-weights.png``.
"""
