"""Listed coverage: which K-12 schools have actually appeared on a real closings list.

Area coverage (``coverage.json``) counts a school as covered when some working
station's list covers its county; it says nothing of whether this school ever
reports there. This package measures it school by school:

SEEN
    An accepted match of the committed name matcher (:mod:`snowlight.match`) ties
    at least one real row to the school itself, or to its district (NCES LEAID), in
    which case every school of that district counts. The row comes from a recorded
    read, live or an archived capture, whose SHA-256 is in the stations'
    ``reads.jsonl`` files (the rows in the ``rows.jsonl`` beside them). Any status
    counts: the question is whether the school reports to that list at all. The
    matcher's context (states, counties, alias market) is the station's registry
    entry. Queued and ambiguous matches never count. Rows of a district's own
    website alerts are not list entries and are left out
    (:mod:`snowlight.listed.scope`). A guard only ever takes matches away: when a
    row's own list writes where the organization is (a state, a county, a town)
    and the matched record is not there, the match of that listing does not count
    (:mod:`snowlight.listed.located`).
ROSTER
    The school's organization (the school, or its district) appears on a list's
    published roster of registered organizations, with nothing closed:
    FlashAlert's participants (school categories), WRAL's organizations (public
    and private schools) and CBS6 Albany's SchoolWatch county pages
    (:mod:`snowlight.listed.rosters`), matched with the same matcher.
LISTED
    SEEN or ROSTER. No county-level inference and no guessing.

Commands (:mod:`snowlight.listed.cli`): ``snowlight listed rosters`` reads the
rosters (network, polite, cached); ``snowlight listed build`` snapshots every
input, matches and measures; ``snowlight listed audit`` draws the stratified
sample of accepted matches a person checks for precision.

Outputs, all internal (``pipeline/out/internal/listed/``, never published)::

    listed.json
        {"generated_at": newest retrieval time among the evidence,
         "definitions": {"seen", "roster", "listed"},
         "evidence": {name: {"path", "source", "sha256", "bytes"}, ...,
                      "nws_counties": {"url", "sha256", "bytes"}},
         "matcher": {"sources_sha256", "threshold", "aliases"},
         "placement": {"schools_placed", "unplaced"},
         "rows": {"in_files", "tied_to_a_read", "left_out": {reason: n},
                  "from_excluded_sources", "from_unregistered_sources", "counted"},
         "row_outcomes": {matcher reason (or "place_conflict"): rows},
         "place_guard": {"listings", "rows"}, "roster_reads": n,
         "roster_entries": n, "roster_outcomes": {matcher reason: entries},
         "excluded_sources": {station id: reason},
         "national": Tally, "states": {"AL": Tally, ...},
         "coverage": {"generated_at", "national": {"area": S, "proven": S},
                      "states": {"AL": {"area": S, "proven": S}, ...}},
         "gaps": [{"state", "area_share", "listed_share", "gap"}, ...],  # 10 widest
         "stations": {id or "<id>/roster": {"rows", "accepted_rows", "other_rows",
                      "entries", ..., "schools", "first_capture", "last_capture"}}}
        Tally = {"schools", "weighted_schools",
                 "seen" | "roster" | "listed": {"count", "share", "weighted",
                                                "weighted_share"}}
        S = {"share", "weighted_share"} (coverage.json's, copied for comparison)

    schools.parquet
        one row per directory school, in directory order: id, state, seen (bool),
        roster (bool), basis ("school" | "district" | "roster" | null), source_ids
        (list: station ids of the rows, "<station id>/roster" for a roster),
        first_seen and last_seen (UTC capture times of the rows; null when not
        SEEN), rows_seen (rows that reach the school).

    unmatched.json
        {"generated_at", "national": {"names", "rows", "queued_names", "queued_rows",
                                      "unmatched_names", "unmatched_rows", "roster_names"},
         "top": [Miss, ...],  # the 50 names with the most rows
         "stations": {id: {"names", "count", "entries": [Miss, ...]}},
         "rosters": {"<id>/roster": {"names", "count", "entries": [Miss, ...]}}}
        Miss = {"source_id" | "roster", "name", "section", "reason",
                "kind": "queued" | "unmatched", "level", "count", "best"}
        Rows and entries the matcher did not accept whose words, by its reading,
        name a school or a district (not those it says name something else).

    matches.jsonl
        one line per distinct listing (source, name, section) with the matcher's
        outcome, the records it names, its rows, capture times and read SHA-256s:
        the audit's input.

    snapshot/
        the copied inputs and ``snapshot.json`` (their SHA-256s).
"""
