"""The ingest's directory handshake (spec 8 step 4; T13c, T13d's verdict). SYNTHETIC editions."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from snowlight.directory.deployed import (
    DeployedEdition,
    DeployedEditionError,
    EditionMismatchError,
    LiveDeployment,
)
from snowlight.live.edition import (
    EditionState,
    EditionWatch,
    PagesDeployed,
    check_zones,
    own_edition,
)
from snowlight.schemas.directory import DirectoryEdition, DirectoryStamp

NOW = datetime(2027, 1, 12, 11, 0, tzinfo=UTC)


def edition(day: str = "2026-10-14", digest: str = "a", schools: int = 11) -> DirectoryEdition:
    return DirectoryEdition(
        schema_version=1,
        generated_on=date.fromisoformat(day),
        schools=schools,
        districts=3,
        content_sha256=digest * 64,
    )


OWN = edition()


@dataclass
class Source:
    """A SYNTHETIC deployed-edition reader: returns or raises what it is given, in turn."""

    answers: list[DirectoryEdition | Exception | None] = field(default_factory=list)
    reads: int = 0

    def read(self) -> DeployedEdition:
        self.reads += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        data = None if answer is None else answer.to_json_bytes()
        return DeployedEdition(data=data, source="synthetic")


def test_t13c_equal_content_publishes_with_the_deployed_stamp() -> None:
    # The deployed date differs from the build's own (it was reused, or moved past a
    # mismatch): the ingest publishes with the deployed stamp, never its own date.
    deployed = edition(day="2026-10-12")
    watch = EditionWatch(own=OWN, source=Source([deployed]))
    verdict = watch.check(NOW, published=())
    assert verdict.state is EditionState.EQUAL
    assert verdict.ok
    assert verdict.stamp == deployed.stamp()
    assert verdict.blank is None


def test_t13d_same_stamp_other_content_publishes_one_blank_then_refuses() -> None:
    deployed = edition(digest="b")
    watch = EditionWatch(own=OWN, source=Source([deployed]))
    verdict = watch.check(NOW, published=(deployed.stamp(),))
    assert verdict.state is EditionState.DIFFERENT
    assert not verdict.ok
    assert verdict.blank == deployed.stamp()
    assert verdict.stamp is None


def test_other_content_under_a_new_stamp_refuses_without_a_blank() -> None:
    deployed = edition(day="2026-10-15", digest="b")
    watch = EditionWatch(own=OWN, source=Source([deployed]))
    verdict = watch.check(NOW, published=(OWN.stamp(),))
    assert (verdict.state, verdict.blank, verdict.ok) == (EditionState.DIFFERENT, None, False)
    assert verdict.deployed == deployed.stamp()


def test_other_counts_with_the_same_digest_are_other_content() -> None:
    watch = EditionWatch(own=OWN, source=Source([edition(schools=12)]))
    assert watch.check(NOW, published=()).state is EditionState.DIFFERENT


def test_nothing_deployed_refuses() -> None:
    watch = EditionWatch(own=OWN, source=Source([None]))
    verdict = watch.check(NOW, published=())
    assert (verdict.state, verdict.ok) == (EditionState.NONE_DEPLOYED, False)


def test_a_failed_read_keeps_an_equal_verdict_for_30_minutes_only() -> None:
    source = Source([OWN, DeployedEditionError("GitHub API: HTTP 502")])
    watch = EditionWatch(own=OWN, source=source)
    assert watch.check(NOW, published=()).state is EditionState.EQUAL
    kept = watch.check(NOW + timedelta(minutes=30), published=())
    assert (kept.state, kept.ok, kept.stamp) == (EditionState.KEPT, True, OWN.stamp())
    assert kept.checked_at == NOW
    assert "HTTP 502" in kept.note
    late = watch.check(NOW + timedelta(minutes=30, seconds=1), published=())
    assert (late.state, late.ok) == (EditionState.UNREADABLE, False)


def test_a_failed_read_never_keeps_a_refusal() -> None:
    source = Source([edition(digest="b"), DeployedEditionError("down")])
    watch = EditionWatch(own=OWN, source=source)
    watch.check(NOW, published=())
    assert watch.check(NOW + timedelta(minutes=1), published=()).state is (EditionState.UNREADABLE)


def test_a_failed_read_before_any_verdict_refuses() -> None:
    watch = EditionWatch(own=OWN, source=Source([DeployedEditionError("deploy in progress")]))
    assert watch.check(NOW, published=()).state is EditionState.UNREADABLE


def test_an_edition_that_is_not_one_is_unreadable() -> None:
    @dataclass
    class Garbage:
        def read(self) -> DeployedEdition:
            return DeployedEdition(data=b'{"SYNTHETIC": 1}', source="synthetic")

    watch = EditionWatch(own=OWN, source=Garbage())
    verdict = watch.check(NOW, published=())
    assert verdict.state is EditionState.UNREADABLE
    assert "SYNTHETIC" not in verdict.note


def test_a_deployed_edition_naming_another_directory_is_judged_by_the_meta_served() -> None:
    claimed = edition()
    made = edition(digest="c")
    error = EditionMismatchError("mismatch", claimed=claimed, made=made)
    watch = EditionWatch(own=OWN, source=Source([error]))
    verdict = watch.check(NOW, published=(made.stamp(),))
    assert verdict.state is EditionState.DIFFERENT
    assert verdict.blank == made.stamp()


@dataclass
class FakeReader:
    """A SYNTHETIC deployed-edition reader with a newest deployment that can change."""

    newest: LiveDeployment | None
    reads: int = 0

    def newest_deployment(self) -> LiveDeployment | None:
        return self.newest

    def read(self) -> DeployedEdition:
        self.reads += 1
        return DeployedEdition(data=OWN.to_json_bytes(), source="synthetic")


def test_pages_deployed_reads_again_only_when_the_newest_deployment_changes() -> None:
    reader = FakeReader(LiveDeployment("success", NOW, 1, "f" * 40))
    pages = PagesDeployed(reader)  # type: ignore[arg-type]
    for _ in range(3):
        assert pages.read().data == OWN.to_json_bytes()
    assert reader.reads == 1
    reader.newest = LiveDeployment("success", NOW + timedelta(minutes=9), 2, "e" * 40)
    pages.read()
    assert reader.reads == 2
    reader.newest = None
    pages.read()
    pages.read()
    assert reader.reads == 4


def test_own_edition_and_the_zone_table_check(tmp_path: Path) -> None:
    schools = tmp_path / "schools"
    schools.mkdir()
    (schools / "edition.json").write_bytes(OWN.to_json_bytes())
    assert own_edition(tmp_path) == OWN
    check_zones(OWN, OWN)
    with pytest.raises(ValueError, match="another directory edition"):
        check_zones(OWN, edition(digest="d"))


def test_the_verdict_names_the_deployed_stamp() -> None:
    watch = EditionWatch(own=OWN, source=Source([OWN]))
    assert watch.check(NOW, published=()).deployed == DirectoryStamp(
        generated_on=date(2026, 10, 14), schools=11, districts=3
    )
