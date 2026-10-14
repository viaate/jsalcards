"""``archive-wanted-s4.json``: the coverage gate's archive requests, as they were sent.

Each run records the commit that changed ``pipeline/config/archive-requests.json``,
the workflow run it started, and the listings and captures it asked for, with a
note per capture (the station it is meant to prove and why that capture). The
request must be one the archive-captures workflow accepts, and every capture
must name a registered station or say, in parentheses, that it names none yet.
"""

import json
import re
from typing import cast

from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, load_registry

PATH = DEFAULT_REGISTRY_DIR / "archive-wanted-s4.json"
DATA = cast("dict[str, object]", json.loads(PATH.read_text(encoding="utf-8")))
STAMP = re.compile(r"^\d{14}$")
DAY = re.compile(r"^\d{8}$")
# The workflow's own checks (.github/workflows/archive-captures.yml, its archive reader).
PATTERN = re.compile(r"^[^\s]+$")
FILTER = re.compile(r"^!?(?:urlkey|timestamp|original|mimetype|statuscode|digest|length):[^\s]+$")
COLLAPSE = re.compile(r"^(?:urlkey|timestamp(?::[0-9]{1,2})?|original|digest|statuscode)$")
MAX_SNAPSHOTS = 254
"""The most any run asked for: the piece's instruction is about 250 a run."""


def _items(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [cast("dict[str, object]", item) for item in value if isinstance(item, dict)]


def test_each_run_is_a_request_the_workflow_accepts() -> None:
    runs = _items(DATA["runs"])
    assert runs
    for run in runs:
        assert re.fullmatch(r"[0-9a-f]{7,40}", str(run["commit"]))
        assert isinstance(run["run"], int)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(run["pushed_at"]))
        for listing in _items(run["cdx"]):
            assert PATTERN.match(str(listing["url"])), listing
            assert DAY.match(str(listing["from"]))
            assert DAY.match(str(listing["to"]))
            assert all(
                FILTER.match(str(item)) for item in cast("list[object]", listing.get("filter", []))
            )
            if "collapse" in listing:
                assert COLLAPSE.match(str(listing["collapse"]))
        snapshots = _items(run["snapshots"])
        # "At most about 250 snapshots per run": one run (d61161b) asked for 254, the
        # last four unread captures of NBC 6 Miami's list folded into its last request.
        assert len(snapshots) <= MAX_SNAPSHOTS
        assert len({(item["timestamp"], item["url"]) for item in snapshots}) == len(snapshots)
        for item in snapshots:
            assert STAMP.match(str(item["timestamp"])), item
            assert str(item["url"]).startswith(("https://", "http://")), item
            assert PATTERN.match(str(item["url"])), item
            assert str(item["why"])


def test_every_capture_names_its_station() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    wanted = [item for run in _items(DATA["runs"]) for item in _items(run["snapshots"])]
    wanted += _items(DATA["still_wanted"])
    for item in wanted:
        station = str(item["station"])
        assert station in registry.stations or station.startswith("("), station
    for run in _items(DATA["runs"]):
        result = run["result"]
        if not isinstance(result, dict):
            continue
        for key in ("proved", "read_empty", "not_proving"):
            named = cast("dict[str, object]", result.get(key) or {})
            assert all(station in registry.stations for station in named), key
