"""How long the learning step's inputs are kept (advisory-sane L0): the morning record and the
weather-class snapshots keep 45 days, one past what ``predict learn`` reads back (44), so a day
it can still label always has its record, the record of the day before, and its snapshot. A
snapshot dropped before its day was labeled would freeze that day with every district unknown.
SYNTHETIC classes only."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from predict.test_learn import DAY, built, snapshots_for
from snowlight.live import morning
from snowlight.live.d1 import Answer, Statement
from snowlight.live.evidence import DATABASES, DISTRICTS, LABELS, SNAPSHOT, EvidenceStore
from snowlight.live.kept import PredictKept, contents_of, fold_predict, snapshot_sha256
from snowlight.predict import cli, learn
from snowlight.predict.config import PredictConfig
from snowlight.predict.live_labels import SNAPSHOT_KEEP_DAYS, pending_tables, record_snapshots
from snowlight.predict.situations import WeatherClass, Window

CONFIG = PredictConfig.load()
NOW = datetime(2026, 1, 9, 12, tzinfo=UTC)


class FakeD1:
    """D1 as in-memory SQLite, one connection per database (see tests/live/test_evidence.py)."""

    def __init__(self) -> None:
        self.dbs: dict[str, sqlite3.Connection] = {}

    def databases(self, name: str) -> list[tuple[str, str]]:
        return [(n, n) for n in self.dbs if name in n]

    def create(self, name: str) -> str:
        self.dbs[name] = sqlite3.connect(":memory:")
        return name

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        db = self.dbs[database]
        answers = []
        for sql, params in statements:
            before = db.total_changes
            cursor = db.execute(sql, params)
            names = [column[0] for column in cursor.description or ()]
            rows = tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
            db.commit()
            answers.append(Answer(rows=rows, rows_written=db.total_changes - before))
        return answers


def test_the_learning_step_never_reads_past_what_is_kept() -> None:
    reads = CONFIG.learn.morning_reads_days
    assert reads == 44
    assert morning.KEEP_DAYS == 45
    # the oldest day read and the school day before it are both still in the record
    assert reads < morning.KEEP_DAYS
    assert reads < SNAPSHOT_KEEP_DAYS
    assert reads > morning.FLOOR_DAYS


WINDOW = Window(
    CONFIG.weather.window_from, CONFIG.weather.window_until, CONFIG.weather.snapshot_hour
)
ZONES = ["America/Chicago"]
CLASSES = np.zeros((1, 1), dtype=np.int64)


def _snapshot(content: str = "c") -> dict[str, object]:
    day = date(2026, 10, 27)
    eve = datetime(2026, 10, 27, 1, 30, tzinfo=UTC)  # 20:30 Central on Oct 26
    return record_snapshots(
        {}, content=content, zones=ZONES, classes=CLASSES, days=[day], now=eve, window=WINDOW
    )


def _later(
    record: dict[str, object], now: datetime, known: PredictKept | None = None
) -> dict[str, object]:
    return record_snapshots(
        record, content="c", zones=ZONES, classes=CLASSES, days=[], now=now, window=WINDOW,
        kept=known,
    )  # fmt: skip


def _held(record: dict[str, object], databases: tuple[str, ...] = DATABASES) -> PredictKept:
    """The state's record when every database answered and ``databases`` hold the snapshots
    and their tables."""
    held = {
        name: {
            **{
                (SNAPSHOT, day): frozenset({snapshot_sha256(entry)})
                for day, entry in record.items()
            },
            **{(DISTRICTS, content): frozenset({"t"}) for content in contents_of(record)},
        }
        if name in databases
        else {}
        for name in DATABASES
    }
    return fold_predict(PredictKept(NOW), held, record, contents_of(record))


def test_a_snapshot_is_kept_45_days_and_after_that_until_a_database_holds_it() -> None:
    record = _snapshot()
    assert list(record) == ["2026-10-27"]
    later = datetime(2026, 12, 11, 12, tzinfo=UTC)  # 45 days on
    assert list(_later(record, later, _held(record))) == ["2026-10-27"]
    day_46 = later + timedelta(days=1)
    # no record of the evidence store, or one that holds nothing: it stays, however old
    assert list(_later(record, day_46)) == ["2026-10-27"]
    assert list(_later(record, day_46 + timedelta(days=400), _held(record, ()))) == ["2026-10-27"]
    # held whole (the snapshot and its district table) in one database: it goes
    assert _later(record, day_46, _held(record, (DATABASES[1],))) == {}
    # a database holding other bytes than the snapshot now does not count
    entry = record["2026-10-27"]
    assert isinstance(entry, dict)
    changed: dict[str, object] = {"2026-10-27": {**entry, "classes": "1"}}
    assert list(_later(changed, day_46, _held(record))) == ["2026-10-27"]
    # nor does the snapshot held without the district table it indexes
    known = _held(record)
    known.tables.clear()
    assert list(_later(record, day_46, known)) == ["2026-10-27"]


def test_the_state_keeps_a_district_table_until_a_database_holds_it() -> None:
    record = {**_snapshot("old"), "2026-10-28": _snapshot("c")["2026-10-27"]}
    tables = {"old": ["2900001", "2900002"], "gone": ["2900003"]}
    found = pending_tables(tables, record, content="c", district_ids=["2900009"])
    # this pass's table, and the old content's (a snapshot still indexes it); not "gone"
    assert found == {"c": ["2900009"], "old": ["2900001", "2900002"]}
    known = _held(record)
    assert pending_tables(found, record, content="c", district_ids=["2900009"], kept=known) == {}
    # a content no longer deployed whose table nobody kept is never dropped for its age
    only_c = PredictKept(NOW, {}, {"c": DATABASES})
    assert pending_tables(found, record, content="c", district_ids=["2900009"], kept=only_c) == {
        "old": ["2900001", "2900002"]
    }


def test_the_pass_state_carries_the_evidence_record_and_is_unchanged_without_it() -> None:
    from snowlight.predict.publish import State  # noqa: PLC0415

    plain = State(snapshots=_snapshot())
    assert set(plain.as_json()) == set(State.from_json(plain.as_json()).as_json())
    assert "evidence" not in plain.as_json()
    assert "tables" not in plain.as_json()
    full = State(evidence=_held(_snapshot()).as_json(), tables={"c": ["2900009"]})
    again = State.from_json(json.loads(json.dumps(full.as_json())))
    assert again.evidence == full.evidence
    assert again.tables == full.tables
    assert PredictKept.of(again.evidence) == _held(_snapshot())
    assert PredictKept.of({"snapshots": "nonsense"}) == PredictKept()


def test_a_database_that_does_not_answer_keeps_what_was_known_of_it() -> None:
    record = _snapshot()
    known = _held(record)
    # only the primary answers, and holds nothing: the silent backup keeps its copies
    after = fold_predict(known, {DATABASES[0]: {}}, record, contents_of(record))
    assert after.snapshots["2026-10-27"].databases == (DATABASES[1],)
    assert after.tables["c"] == (DATABASES[1],)
    # a day no longer in the state is forgotten
    assert fold_predict(known, {DATABASES[0]: {}}, {}, ()).snapshots == {}


def test_predict_evidence_keeps_the_finished_snapshots_their_district_table_and_the_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = built()
    content = learn.content_key(model.directory)
    record = snapshots_for(DAY)
    assert record[DAY.isoformat()]["content"] == content  # type: ignore[index]
    # predict learn leaves the table it read and the labels it published; the evidence step,
    # after the passes, reads them back (neither the site nor the live host again)
    folder = tmp_path / "evidence"
    labels = b'{"SYNTHETIC": "labels"}'
    cli.leave_for_evidence(folder, directory=model.directory)
    cli.leave_for_evidence(folder, labels=labels)
    tables, left = cli.left_for_evidence(folder)
    assert tables == {content: tuple(model.directory.district_ids)}
    assert left == labels
    assert cli.left_for_evidence(tmp_path / "none") == ({}, None)
    api = FakeD1()
    store = EvidenceStore(api, {"GITHUB_WORKFLOW": "predict"}, lambda: NOW)
    now = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=13)
    assert cli.keep_evidence(store, record, tables, now, labels) == 0
    out = capsys.readouterr().out
    assert (
        "predict evidence snowlight-evidence: 3 finished files offered, 0 held before, 3 kept"
        in out
    )
    assert "::warning::" not in out
    table = store.pull(DISTRICTS)[content].decode().split()
    assert table == list(model.directory.district_ids)
    assert json.loads(store.pull(SNAPSHOT)[DAY.isoformat()]) == record[DAY.isoformat()]
    assert store.pull(LABELS) == {"learn": labels}
    # a later run under another content: its table is kept at once, and a finished snapshot
    # whose content has a kept table raises no warning
    other = {"d" * 64: ("2900009",)}
    assert cli.keep_evidence(store, record, other, now) == 0
    assert "::warning::" not in capsys.readouterr().out
    assert set(store.pull(DISTRICTS)) == {content, "d" * 64}
    # a snapshot whose content no database holds a table of is named in a warning
    fresh = EvidenceStore(FakeD1(), {"GITHUB_WORKFLOW": "predict"}, lambda: NOW)
    assert cli.keep_evidence(fresh, record, other, now) == 0
    assert "::warning::predict evidence: no district table is kept" in capsys.readouterr().out
    # the live reader's run may not keep them, and says so
    refused = EvidenceStore(api, {"GITHUB_WORKFLOW": "live-read"}, lambda: NOW)
    assert cli.keep_evidence(refused, record, tables, now) == 1
    assert cli.snapshots_of(Path("/nonexistent/state.json")) == {}


def test_the_live_scoring_rules_are_pre_registered() -> None:
    from snowlight.predict.config import LIVE_SCORE_SHA256, live_score_sha256  # noqa: PLC0415

    # S7 addendum h records this sha256; the block changes only with it, by a reviewed commit
    assert live_score_sha256(CONFIG) == LIVE_SCORE_SHA256
    score = CONFIG.live_score
    assert score["prior"]["advisory"] == {"target": 0.10, "alpha_mean": -2.953, "alpha_sd": 0.85}
    assert score["prior"]["warning"] == {"target": 0.45, "alpha_mean": -0.284, "alpha_sd": 1.20}
    assert score["shrink"] == {
        "ece_above": 0.10,
        "nights": 3,
        "min_rows": 100,
        "keep_share": 0.5,
        "release_nights": 3,
        "pooled": True,
    }
    assert score["plausibility"]["advisory_mean"] == 1.0
    assert score["plausibility"]["district_max"] == 6.0
    assert score["read"]["open_if_unnamed"] is True
    assert score["scoring"]["bootstrap_seed"] == 20261101
    # every weather class has its scored class: ice and blizzard inside warning, under its
    # prior, until a kind has 5 live dates of its own (then it starts from the warning prior)
    classes = score["classes"]
    assert set(classes) == {w.label for w in WeatherClass} | {"advisory_after", "none_after"}
    assert {classes[k] for k in ("snow_warning", "lake_snow", "ice", "blizzard", "tropical")} == {
        "warning"
    }
    assert classes["advisory_after"] == "advisory"
    assert classes["none"] == classes["none_after"] == "chain"
    assert {c for c in classes.values() if c != "chain"} <= set(score["prior"])
    assert score["split"] == {"min_live_dates": 5, "prior": "warning"}
    # the freeze times and the date-clustered bin interval are numbers of the block
    assert score["scoring"]["freeze_local"] == ["20:07", "05:07"]
    assert score["scoring"]["freeze_day_offsets"] == [-1, 0]
    assert score["scoring"]["horizons"] == [1, 0]
    assert score["calibration"]["bin_interval"] == 0.95
    assert score["live_update"]["prior_weight"] == "alpha_sd"
    # fitted on every label the morning record holds (Oct 27 on), scored only from Nov 1 on
    assert score["live_update"]["fit_from"] == "2026-10-27"
    assert score["live_update"]["score_from"] == "2026-11-01"
    assert "first_day" not in score["live_update"]
    # the exposure reference and its winters, the G6 pull and the shrink's pooling are numbers
    # of the block too
    assert score["standing"]["f_ref"] == "national_median_nonzero"
    assert score["standing"]["seasons"] == ["2015-16", "2024-25"]
    plausible = score["plausibility"]
    assert (plausible["pull_scale"], plausible["pull_step"]) == ("log_odds", 0.05)
    assert plausible["pull_until"] == "district_max"
    assert plausible["pull_aggregate"] == "largest_first"
    assert score["shrink"]["pooled"] is True
    assert score["forecast_adjustment"] == {"registered": False, "addendum": "i"}


def test_the_label_rules_are_inside_the_pre_registration() -> None:
    from snowlight.predict.config import live_score_sha256  # noqa: PLC0415

    base = live_score_sha256(CONFIG)
    # a label threshold, a weather-class rule or the snapshot slack changed: another sha256
    for change in (
        {"labels": CONFIG.labels.model_copy(update={"no_school_share": 0.6})},
        {"labels": CONFIG.labels.model_copy(update={"audience_days": 3})},
        {"weather": CONFIG.weather.model_copy(update={"covered_share": 0.4})},
        {"learn": CONFIG.learn.model_copy(update={"snapshot_slack_minutes": 90})},
    ):
        assert live_score_sha256(CONFIG.model_copy(update=change)) != base
    # an operating setting outside the rules is not part of it
    other = CONFIG.model_copy(
        update={"learn": CONFIG.learn.model_copy(update={"morning_reads_days": 40})}
    )
    assert live_score_sha256(other) == base


class BrokenD1(FakeD1):
    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        from snowlight.live.d1 import D1Error  # noqa: PLC0415

        del database, statements
        raise D1Error("query: HTTP 500")


def test_predict_evidence_notes_what_is_kept_and_its_check_opens_the_issue_when_it_is_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from snowlight.predict.publish import State  # noqa: PLC0415

    model = built()
    content = learn.content_key(model.directory)
    record = snapshots_for(DAY)
    state = tmp_path / "state.json"
    pending = pending_tables({}, record, content=content, district_ids=model.directory.district_ids)
    cli.save_state(state, State(digest="d", snapshots=record, tables=pending))
    before = json.loads(state.read_bytes())
    now = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=13)
    # The first check starts the grace; nothing kept yet is not late yet.
    assert cli.check_kept(state, now) == 0
    assert "predict evidence check: 0 of 1 finished snapshots in both databases" in (
        capsys.readouterr().out
    )
    # The evidence step fails (the databases refuse) for 2 days: the check fails, the issue opens.
    broken = EvidenceStore(BrokenD1(), {"GITHUB_WORKFLOW": "predict"}, lambda: NOW)
    late = now + timedelta(days=2, hours=1)
    assert cli.keep_evidence(broken, record, cli.tables_of(state), late) == 1
    known = cli.ask_kept(broken, record, cli.tables_of(state), cli.kept_of(state), late)
    assert cli.note_kept(state, known)
    assert cli.check_kept(state, late) == 1
    out = capsys.readouterr().out
    assert "; 1 waited over 2 days" in out
    assert "::error::predict evidence: 1 finished weather-class snapshots" in out
    # The next run keeps it in both: noted in the state, the check passes.
    store = EvidenceStore(FakeD1(), {"GITHUB_WORKFLOW": "predict"}, lambda: NOW)
    assert cli.keep_evidence(store, record, cli.tables_of(state), late) == 0
    known = cli.ask_kept(store, record, cli.tables_of(state), cli.kept_of(state), late)
    assert cli.note_kept(state, known)
    assert cli.check_kept(state, late) == 0
    assert "1 of 1 finished snapshots in both databases" in capsys.readouterr().out
    # Only the evidence entry changed in the state.
    after = json.loads(state.read_bytes())
    assert {k: v for k, v in after.items() if k != "evidence"} == before
    # The next passes let the table go, and the snapshot once it is 46 days old.
    kept = cli.kept_of(state)
    assert pending_tables(pending, record, content=content, district_ids=(), kept=kept) == {}
    day_46 = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC) + timedelta(days=46)
    assert record_snapshots(
        record, content=content, zones=model.time_zone, classes=np.zeros((0, 0), dtype=np.int64),
        days=[], now=day_46, window=WINDOW, kept=kept,
    ) == {}  # fmt: skip
    # No state: nothing written, the check says so.
    assert not cli.note_kept(tmp_path / "none.json", kept)
    assert cli.check_kept(tmp_path / "none.json", late) == 0
