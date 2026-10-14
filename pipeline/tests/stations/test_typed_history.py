"""Undated typed rows judged against the page's earlier reads (stations.typed_history).

Fixtures are real bodies of KSTU's closings page (fixtures/groups/README.md records each
one's URL, capture time and SHA-256): archived captures of 2023-02-22 and 2023-02-26
(the Utah snow days, rows under day headings), 2025-02-11 (empty), 2025-05-20 and
2025-12-17 (the Provo late start of an unnamed Tuesday), and the live read of
2026-09-28 (the same Provo row). Observations are made from those bodies at their own
capture times; read times and observation times not taken from a capture are named
``synthetic_*``.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import fetch, scripps_typed, typed, typed_history
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingRead,
    ListingState,
    ParsedRow,
    ReadMode,
)
from snowlight.sources.stations.registry import StationStatus, load_registry
from snowlight.sources.stations.typed_history import (
    Seen,
    TypedHistory,
    TypedHistoryError,
    Verdict,
)

FIXTURES = Path(__file__).parent / "fixtures" / "groups" / "scripps-typed"
REGISTRY = load_registry()
PAGE = "https://www.fox13now.com/weather/closings"
KSTU = "scripps-typed-kstu"

CAPTURES = {
    "20230222072846": datetime(2023, 2, 22, 7, 28, 46, tzinfo=UTC),
    "20230226220604": datetime(2023, 2, 26, 22, 6, 4, tzinfo=UTC),
    "20250211130945": datetime(2025, 2, 11, 13, 9, 45, tzinfo=UTC),
    "20250520013553": datetime(2025, 5, 20, 1, 35, 53, tzinfo=UTC),
    "20251217132420": datetime(2025, 12, 17, 13, 24, 20, tzinfo=UTC),
}
LIVE_AT = datetime(2026, 9, 28, 0, 5, 13, tzinfo=UTC)
"""The live fixture's read time (kstu-page-20260928000513.html)."""


def listing(stamp: str) -> Listing:
    return scripps_typed.parse((FIXTURES / f"kstu-page-{stamp}.html").read_bytes())


def seen(stamp: str, at: datetime | None = None, mode: ReadMode = ReadMode.ARCHIVE) -> Seen:
    """An observation of one fixture, at its capture time unless ``at`` is given."""
    when = at if at is not None else CAPTURES[stamp]
    body = (FIXTURES / f"kstu-page-{stamp}.html").read_bytes()
    keys = frozenset(typed_history.parsed_key(row) for row in listing(stamp).rows)
    return Seen(when, mode, PAGE, f"{len(body):064x}", keys)


def test_an_adapter_row_and_its_stamped_row_have_one_key() -> None:
    rows = listing("20251217132420").rows
    stamped = fetch.stamp_rows(KSTU, CAPTURES["20251217132420"], listing("20251217132420"))
    assert [typed_history.parsed_key(row) for row in rows] == [
        typed_history.raw_key(row) for row in stamped
    ]
    # The key is the row's whole content: another status is another row.
    (row,) = rows
    other = row.model_copy(update={"status": row.status + " (updated)"})
    assert typed_history.parsed_key(other) != typed_history.parsed_key(row)
    # Whitespace and case do not make a row new.
    spaced = row.model_copy(update={"name": "  PROVO  City School   District"})
    assert typed_history.row_key(
        spaced.name.strip(), row.status, None, row.extra
    ) == typed_history.parsed_key(row)


def test_the_provo_note_is_one_row_in_every_read_since_may_2025() -> None:
    # Read by eye: one bold name, then the sentence, then two nested details.
    for stamp in ("20250520013553", "20251217132420", "20260928000513"):
        (row,) = listing(stamp).rows
        assert row.name == "Provo City School District"
        assert row.status.startswith(
            "will operate on a Two Hour Late Start schedule on Tuesday. This means that school "
            "will start two hours later than normal"
        )
        assert row.extra["split"] == "bold"
        assert "section" not in row.extra
        assert str(row.extra["details"]).endswith(
            "There will be NO AM-only half-day kindergarten or preschool."
        )
    keys = [
        {typed_history.parsed_key(row) for row in listing(stamp).rows}
        for stamp in ("20250520013553", "20251217132420", "20260928000513")
    ]
    assert keys[0] == keys[1] == keys[2]
    assert len(keys[0]) == 1
    assert listing("20250211130945").rows == ()


def test_a_row_unchanged_since_an_archived_capture_is_an_old_note() -> None:
    earlier = [seen("20250211130945"), seen("20250520013553"), seen("20251217132420")]
    judgement = typed_history.judge(listing("20260928000513").rows, LIVE_AT, earlier)
    (verdict,) = judgement.rows
    assert verdict.verdict is Verdict.OLD
    assert verdict.since is not None
    assert verdict.since.at == CAPTURES["20250520013553"]
    assert verdict.lacking is not None
    assert verdict.lacking.at == CAPTURES["20250211130945"]
    assert judgement.kept == ()
    assert judgement.all_old
    assert judgement.earlier == 3
    assert judgement.summary() == "1 old"
    assert judgement.oldest() is verdict


def test_a_row_an_earlier_read_within_the_window_lacked_is_new_and_kept() -> None:
    synthetic_read_at = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)
    synthetic_empty_read = seen("20250211130945", at=synthetic_read_at - timedelta(hours=10))
    rows = listing("20251217132420").rows
    judgement = typed_history.judge(rows, synthetic_read_at, [synthetic_empty_read])
    assert [item.verdict for item in judgement.rows] == [Verdict.NEW]
    assert judgement.kept == rows
    assert not judgement.all_old


def test_a_row_no_read_dates_cannot_be_told_from_an_old_note() -> None:
    rows = listing("20260928000513").rows
    # No earlier read at all.
    assert [item.verdict for item in typed_history.judge(rows, LIVE_AT, []).rows] == [
        Verdict.UNKNOWN
    ]
    # First seen within the window, and the last read without it is older than that.
    synthetic_first_seen = seen("20260928000513", at=LIVE_AT - timedelta(hours=5))
    judgement = typed_history.judge(rows, LIVE_AT, [seen("20250211130945"), synthetic_first_seen])
    assert [item.verdict for item in judgement.rows] == [Verdict.UNKNOWN]
    assert judgement.kept == ()
    assert not judgement.all_old
    # Reads made at or after the read are passed over.
    later = seen("20251217132420", at=LIVE_AT + timedelta(days=1))
    assert typed_history.judge(rows, LIVE_AT, [later]).earlier == 0


def test_rows_under_a_heading_dated_near_the_read_are_kept_whatever_the_history() -> None:
    storm = listing("20230222072846")
    old_copy = seen("20230222072846", at=CAPTURES["20230222072846"] - timedelta(days=5))
    judgement = typed_history.judge(storm.rows, CAPTURES["20230222072846"], [old_copy])
    assert {item.verdict for item in judgement.rows} == {Verdict.DATED}
    assert judgement.kept == storm.rows


def test_rows_under_headings_of_days_gone_are_past() -> None:
    # On Sunday 26 February 2023 the page still held the rows of Tuesday to Thursday.
    leftover = listing("20230226220604")
    judgement = typed_history.judge(leftover.rows, CAPTURES["20230226220604"], [])
    assert {item.verdict for item in judgement.rows} == {Verdict.PAST}
    assert len(judgement.rows) == 41
    assert judgement.all_old
    assert judgement.oldest() is None


def test_named_days_of_a_row() -> None:
    row = ParsedRow(
        name="Synthetic School District",
        status="closed",
        extra={"section": "THURSDAY, FEB. 23"},
    )
    on_the_day = datetime(2023, 2, 23, 13, 0, tzinfo=UTC)
    assert typed.row_named_days(row, on_the_day) == [on_the_day.date()]
    assert typed.row_names_day_near(row, on_the_day)
    assert not typed.row_names_only_past_days(row, on_the_day)
    assert typed.row_names_only_past_days(row, on_the_day + timedelta(days=3))
    undated = row.model_copy(update={"extra": {}})
    assert not typed.row_names_only_past_days(undated, on_the_day)


def test_compaction_keeps_the_verdicts() -> None:
    synthetic_reads = [
        seen("20250211130945", at=datetime(2025, 3, 1, tzinfo=UTC) + timedelta(days=day))
        for day in range(5)
    ] + [
        seen("20251217132420", at=datetime(2025, 6, 1, tzinfo=UTC) + timedelta(days=day))
        for day in range(30)
    ]
    history = TypedHistory({KSTU: synthetic_reads})
    kept = history.by_source[KSTU]
    assert len(kept) == 4  # the first and last of each run
    rows = listing("20260928000513").rows
    full = typed_history.judge(rows, LIVE_AT, synthetic_reads)
    compact = typed_history.judge(rows, LIVE_AT, kept)
    assert [(i.verdict, i.since, i.lacking) for i in full.rows] == [
        (i.verdict, i.since, i.lacking) for i in compact.rows
    ]


def test_earlier_reads_are_those_of_the_same_page_before_the_read() -> None:
    other_page = Seen(
        CAPTURES["20250211130945"],
        ReadMode.ARCHIVE,
        "https://www.fox13now.com/weather/school-closings-delays",
        "0" * 64,
        frozenset(),
    )
    history = TypedHistory({KSTU: [seen("20251217132420"), other_page]})
    found = history.earlier(KSTU, "https://fox13now.com/weather/closings/", LIVE_AT)
    assert [item.at for item in found] == [CAPTURES["20251217132420"]]
    assert history.earlier(KSTU, PAGE, CAPTURES["20251217132420"]) == []
    assert history.earlier("nexstar-typed-whnt", PAGE, LIVE_AT) == []


def test_the_history_file_round_trips(tmp_path: Path) -> None:
    history = TypedHistory({KSTU: [seen("20250211130945"), seen("20251217132420")]})
    history.add(KSTU, seen("20260928000513", at=LIVE_AT, mode=ReadMode.LIVE))
    path = tmp_path / typed_history.HISTORY_FILE
    history.write(path, LIVE_AT)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["typed_current_hours"] == 36
    assert [item["mode"] for item in document["sources"][KSTU]] == ["archive", "archive", "live"]
    again = TypedHistory.load(path)
    assert again.by_source[KSTU] == history.by_source[KSTU]
    merged = TypedHistory()
    merged.merge(again)
    merged.merge(again)
    assert merged.by_source[KSTU] == history.by_source[KSTU]
    assert TypedHistory.load(tmp_path / "missing.json").by_source == {}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"sources": []}',
        '{"sources": {"x": {}}}',
        '{"sources": {"x": [1]}}',
        '{"sources": {"x": [{"at": "2026-01-01T00:00:00Z"}]}}',
        '{"sources": {"x": [{"at": "2026-01-01T00:00:00Z", "mode": "live", "url": "u", '
        '"sha256": "s", "keys": [1]}]}}',
    ],
)
def test_a_malformed_history_file_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "typed-history.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TypedHistoryError):
        TypedHistory.load(path)


def _read(stamp: str, state: ListingState, rows: int, url: str = PAGE) -> ListingRead:
    return ListingRead.model_validate(
        {
            "source_id": KSTU,
            "mode": ReadMode.ARCHIVE,
            "url": url,
            "fetched_at": CAPTURES[stamp],
            "retrieved_at": "2026-09-28T00:00:00Z",
            "sha256": "a" * 64,
            "bytes": 1,
            "variant": "scripps-typed-page",
            "state": state,
            "rows": rows,
            "declared_count": None,
            "skipped_rows": 0,
        }
    )


def test_the_archive_parse_gives_the_observations(tmp_path: Path) -> None:
    reads = [
        _read("20250211130945", ListingState.EMPTY, 0),
        _read("20251217132420", ListingState.POPULATED, 1),
        # A populated read whose rows were not written, and a read that did not parse.
        _read("20250520013553", ListingState.POPULATED, 1),
        _read("20230222072846", ListingState.COUNT_ONLY, 0),
        # Two reads made in the same second: their rows cannot be told apart.
        _read("20230226220604", ListingState.POPULATED, 41),
        _read("20230226220604", ListingState.POPULATED, 41, url=PAGE + "/other"),
    ]
    rows = [
        *fetch.stamp_rows(KSTU, CAPTURES["20251217132420"], listing("20251217132420")),
        *fetch.stamp_rows(KSTU, CAPTURES["20230226220604"], listing("20230226220604")),
    ]
    other = fetch.stamp_rows("scripps-typed-krtv", LIVE_AT, listing("20251217132420"))
    (tmp_path / "reads.jsonl").write_text(
        "".join(read.model_dump_json() + "\n" for read in reads), encoding="utf-8"
    )
    (tmp_path / "rows.jsonl").write_text(
        "\n".join(row.model_dump_json() for row in [*rows, *other]) + "\n\n", encoding="utf-8"
    )
    history = TypedHistory.from_archive(tmp_path / "reads.jsonl", tmp_path / "rows.jsonl", [KSTU])
    found = history.by_source[KSTU]
    assert [(item.at, len(item.keys)) for item in found] == [
        (CAPTURES["20250211130945"], 0),
        (CAPTURES["20251217132420"], 1),
    ]
    assert found[1].keys == seen("20251217132420").keys
    assert TypedHistory.from_archive(tmp_path / "x.jsonl", tmp_path / "y", [KSTU]).by_source == {}
    assert TypedHistory.from_archive(tmp_path / "reads.jsonl", tmp_path / "y", []).by_source == {}
    (tmp_path / "bad.jsonl").write_text('{"source_id":"scripps-typed-kstu"}\n', encoding="utf-8")
    with pytest.raises(TypedHistoryError):
        TypedHistory.from_archive(tmp_path / "bad.jsonl", tmp_path / "rows.jsonl", [KSTU])


class Ticker:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _client(tmp_path: Path, fixture: str, now: datetime) -> PoliteClient:
    def serve(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /wp-admin/\n")
        assert str(request.url) == PAGE
        return httpx.Response(200, content=(FIXTURES / fixture).read_bytes())

    ticker = Ticker(now)
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_the_live_reader_reads_the_leftover_note_as_an_empty_list(tmp_path: Path) -> None:
    history = TypedHistory(
        {KSTU: [seen("20250211130945"), seen("20250520013553"), seen("20251217132420")]}
    )
    station = REGISTRY.stations[KSTU].model_copy(
        update={"page_url": PAGE, "status": StationStatus.ACTIVE}
    )
    client = _client(tmp_path, "kstu-page-20260928000513.html", LIVE_AT)
    result = fetch.read_station(REGISTRY, station, client, LIVE_AT, fetch.Judges(history=history))
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.EMPTY, 0)
    assert health.reason is not None
    assert "archived capture of 2025-05-20T01:35:53Z" in health.reason
    assert "archived capture of 2025-02-11T13:09:45Z did not hold it" in health.reason
    assert "old notes" in health.reason
    assert result.rows == []
    # The read is evidence for the next one: it is an observation of the page.
    ((source_id, observed),) = result.typed_seen
    assert (source_id, observed.mode, observed.keys) == (
        KSTU,
        ReadMode.LIVE,
        seen("20251217132420").keys,
    )
    (read,) = result.reads
    assert (read.state, read.rows) == (ListingState.POPULATED, 1)


def test_the_live_reader_keeps_a_row_typed_since_its_last_read(tmp_path: Path) -> None:
    synthetic_read_at = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)
    history = TypedHistory(
        {KSTU: [seen("20250211130945", at=synthetic_read_at - timedelta(minutes=15))]}
    )
    station = REGISTRY.stations[KSTU].model_copy(
        update={"page_url": PAGE, "status": StationStatus.ACTIVE}
    )
    client = _client(tmp_path, "kstu-page-20251217132420.html", synthetic_read_at)
    result = fetch.read_station(
        REGISTRY, station, client, synthetic_read_at, fetch.Judges(history=history)
    )
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.OK, 1)
    assert health.reason is not None
    assert "1 of its 1 rows" in health.reason
    (row,) = result.rows
    assert row.raw_name == "Provo City School District"


def test_a_run_adds_each_typed_read_to_the_history(tmp_path: Path) -> None:
    history = TypedHistory({KSTU: [seen("20250211130945"), seen("20250520013553")]})
    assert (REGISTRY.stations[KSTU].page_url, REGISTRY.stations[KSTU].status) == (
        PAGE,
        StationStatus.ACTIVE,
    )
    client = _client(tmp_path, "kstu-page-20260928000513.html", LIVE_AT)
    result = fetch.run(
        REGISTRY,
        client,
        clock=lambda: LIVE_AT,
        only=[KSTU],
        judges=fetch.Judges(history=history),
    )
    assert [entry.status for entry in result.health] == [HealthStatus.EMPTY]
    assert [item.mode for item in history.by_source[KSTU]] == [
        ReadMode.ARCHIVE,
        ReadMode.ARCHIVE,
        ReadMode.LIVE,
    ]
    assert fetch.typed_not_current(
        listing("20260928000513"),
        LIVE_AT + timedelta(minutes=1),
        history.earlier(KSTU, PAGE, LIVE_AT),
    )
