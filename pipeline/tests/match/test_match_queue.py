"""The unmatched queue: what goes in, what stays, what leaves."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from snowlight.match import Aliases, Directory, Matcher, read_queue, update_queue

RUN_1 = datetime(2026, 1, 20, 11, 0, tzinfo=UTC)
RUN_2 = RUN_1 + timedelta(hours=1)


def test_unplaced_listings_are_queued_with_their_candidates(
    tmp_path: Path, handmade_matcher: Matcher
) -> None:
    path = tmp_path / "match" / "unmatched.json"
    results = [
        handmade_matcher.match("Kettleby Schools", states=["OH"], market="wxyz"),
        handmade_matcher.match("Lancaster Schools", states=["SC"], market="wxyz"),
        handmade_matcher.match("Brambleton City Schools", states=["AL"], market="wxyz"),
        handmade_matcher.match("Schools", states=["AL"], market="wxyz"),
        handmade_matcher.match("City of Kettleby", states=["OH"], market="wxyz"),
        handmade_matcher.match(
            "St. Mary's School", states=["PA"], counties=["80101", "80102"], near=(35.0, -80.0)
        ),
    ]
    queue = update_queue(path, results, now=RUN_1)
    assert [(e.market, e.listing, e.reason) for e in queue.entries] == [
        (None, "St. Mary's School", "ambiguous"),
        ("wxyz", "City of Kettleby", "not_school"),
        ("wxyz", "Kettleby Schools", "ambiguous"),
        ("wxyz", "Lancaster Schools", "weak"),
        ("wxyz", "Schools", "empty"),
    ]
    city_hall = queue.entries[1]
    assert city_hall.candidates
    assert city_hall.candidates[0].id == "SYN-OH-KETC"
    assert city_hall.confidence == 0.0
    assert "civic body" in city_hall.detail
    kettleby = queue.entries[2]
    assert [c.id for c in kettleby.candidates][:2] in (
        ["SYN-OH-KETL", "SYN-OH-KETC"],
        ["SYN-OH-KETC", "SYN-OH-KETL"],
    )
    assert kettleby.states == ("OH",)
    assert kettleby.counties is None
    assert kettleby.level == "district"
    assert kettleby.first_seen == kettleby.last_seen == RUN_1
    assert kettleby.times_seen == 1
    st_mary = queue.entries[0]
    assert st_mary.counties == ("80101", "80102")
    assert all(c.distance_km is not None and c.distance_km > 500 for c in st_mary.candidates)
    assert queue.entries[4].candidates == ()
    assert read_queue(path) == queue
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert list(written) == sorted(written)


def test_a_second_run_counts_repeats_and_drops_what_now_matches(
    tmp_path: Path, handmade_directory: Directory
) -> None:
    path = tmp_path / "unmatched.json"
    matcher = Matcher(handmade_directory)
    update_queue(
        path,
        [
            matcher.match("Kettleby Schools", states=["OH"], market="wxyz"),
            matcher.match("Lancaster Schools", states=["SC"], market="wxyz"),
            matcher.match("FCPS", states=["VA"], market="wxyz"),
        ],
        now=RUN_1,
    )
    pinned = Matcher(handmade_directory, aliases=Aliases({"wxyz": {"fcps": "SYN-VA-FAIR"}}))
    queue = update_queue(
        path,
        [
            pinned.match("KETTLEBY  schools", states=["OH"], market="wxyz"),
            pinned.match("FCPS", states=["VA"], market="wxyz"),
        ],
        now=RUN_2,
    )
    assert [(e.listing, e.times_seen, e.first_seen, e.last_seen) for e in queue.entries] == [
        ("KETTLEBY  schools", 2, RUN_1, RUN_2),
        ("Lancaster Schools", 1, RUN_1, RUN_1),
    ]
    assert queue.updated_at == RUN_2


def test_the_same_queue_is_the_same_bytes(tmp_path: Path, handmade_matcher: Matcher) -> None:
    results = [
        handmade_matcher.match(listing, states=["OH"], market="wxyz")
        for listing in ("Kettleby Schools", "Nowhere Academy", "Kettleby Schools")
    ]
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    update_queue(first, results, now=RUN_1)
    update_queue(second, list(reversed(results)), now=RUN_1)
    assert first.read_bytes() == second.read_bytes()


def test_the_queue_needs_an_aware_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        update_queue(tmp_path / "q.json", [], now=datetime(2026, 1, 20, 11, 0))
    assert read_queue(tmp_path / "q.json") is None


def test_a_town_s_name_is_queued_with_the_school_it_is_not(
    tmp_path: Path, handmade_matcher: Matcher
) -> None:
    path = tmp_path / "unmatched.json"
    result = handmade_matcher.match("Brackville", states=["KY"], market="wxyz")
    queue = update_queue(path, [result], now=RUN_1)
    [entry] = queue.entries
    assert (entry.listing, entry.reason, entry.confidence) == ("Brackville", "place", 0.0)
    assert entry.candidates[0].id == "SYN-KY-VSOB"
    assert "one school" in entry.detail


def test_a_network_s_campuses_are_queued_before_the_network(
    tmp_path: Path, handmade_matcher: Matcher
) -> None:
    """Two campuses in the market that the listing fits alike: a person picks one to pin."""
    path = tmp_path / "unmatched.json"
    tied = handmade_matcher.match(
        "Crestline High School", states=["TX"], counties=["87402", "87403"], market="wxyz"
    )
    office = handmade_matcher.match(
        "Crestline High School", states=["TX"], counties=["87401"], market="abcd"
    )
    queue = update_queue(path, [tied, office], now=RUN_1)
    network, campuses = queue.entries
    assert campuses.reason == "ambiguous"
    assert {c.id for c in campuses.candidates[:2]} == {"SYN-TX-CRTAL", "SYN-TX-CRMOS"}
    assert campuses.candidates[2].id == "SYN-TX-CRST"
    assert "named as one school" in campuses.detail
    assert network.reason == "network"
    assert network.confidence == 0.0
    assert network.candidates[0].id == "SYN-TX-CRST"


def test_a_parish_s_name_is_queued_with_its_section(
    tmp_path: Path, handmade_matcher: Matcher
) -> None:
    path = tmp_path / "unmatched.json"
    kc = ("88941", "88942")
    results = [
        handmade_matcher.match("Visitation", states=["MO", "KS"], counties=kc, market="kc"),
        handmade_matcher.match(
            "Christ the King",
            states=["MO", "KS"],
            counties=kc,
            market="kc",
            category="Churches",
        ),
    ]
    queue = update_queue(path, results, now=RUN_1)
    assert [(e.listing, e.reason, e.category) for e in queue.entries] == [
        ("Christ the King", "not_school", "Churches"),
        ("Visitation", "parish", None),
    ]
    assert queue.entries[1].candidates[0].id == "SYN-MO-KVIS"
    assert read_queue(path) == queue


def test_a_namesake_just_past_the_counties_is_queued_beside_the_one_in_them(
    tmp_path: Path, handmade_matcher: Matcher
) -> None:
    """WMUR's case: the queue shows both Hanburys, the market's first, for a person to pin."""
    result = handmade_matcher.match(
        "Hanbury School District", states=["MA", "NH"], counties=["88961", "88962"], market="wmur"
    )
    queue = update_queue(tmp_path / "unmatched.json", [result], now=RUN_1)
    (entry,) = queue.entries
    assert entry.reason == "ambiguous"
    assert [(c.id, c.state) for c in entry.candidates[:2]] == [
        ("SYN-MA-HAN", "MA"),
        ("SYN-NH-HANSD", "NH"),
    ]
    assert "just past them" in entry.detail
