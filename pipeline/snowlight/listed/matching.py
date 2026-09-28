"""Run the committed name matcher over every distinct listing, in parallel.

A listing is a name as a list shows it, the section it files it under, and the
context the list is matched in (:class:`~snowlight.listed.scope.Context`). The
matcher answers each distinct listing once (a list repeats most names from one
capture to the next), through its public API: :meth:`snowlight.match.Matcher.match`
with the context's states, counties and market, and :meth:`Matcher.expand` for
the schools an accepted result covers. Only an accepted result
(:attr:`MatchResult.accepted`) ties a listing to schools; a queued or ambiguous one
ties it to none.

An accepted result names districts, schools, or both (an alias may pin several
records). A school it names is reached directly (basis ``school``); the schools
of a district it names are reached through the district (basis ``district``).

Matching is deterministic, so the work can be split over worker processes, each
with its own matcher built from the same directory and aliases
(:class:`MatcherSpec`), and the answers are gathered by listing.
"""

import multiprocessing
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from snowlight.listed.scope import Context
from snowlight.match import Matcher, MatchResult, load_aliases, load_directory

CHUNK: Final = 400


@dataclass(frozen=True, slots=True, order=True)
class Query:
    """One distinct listing: its context, its text and the section it is filed under."""

    context: Context
    name: str
    section: str | None


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the matcher decided for one listing, in the terms this package uses."""

    accepted: bool
    reason: str
    level: str
    confidence: float
    targets: tuple[str, ...]
    """The ids of the records an accepted result names (empty otherwise)."""
    direct: tuple[str, ...]
    """The schools it names itself."""
    via_district: tuple[str, ...]
    """The schools of the districts it names (not also named directly)."""
    best_id: str | None
    best_name: str | None
    best_score: float | None
    detail: str


def outcome_of(matcher: Matcher, result: MatchResult) -> Outcome:
    """Describe a :class:`MatchResult`: its targets, and every school they cover."""
    best = result.best
    direct: list[str] = []
    via: list[str] = []
    if result.accepted:
        for record in result.targets:
            if record.kind == "school":
                direct.append(record.id)
        named = set(direct)
        for school in matcher.expand(result):
            if school.id not in named:
                via.append(school.id)
    return Outcome(
        accepted=result.accepted,
        reason=result.reason.value,
        level=result.level.value,
        confidence=result.confidence,
        targets=tuple(record.id for record in result.targets),
        direct=tuple(direct),
        via_district=tuple(via),
        best_id=best.record.id if best is not None else None,
        best_name=best.record.name if best is not None else None,
        best_score=best.score if best is not None else None,
        detail=result.detail,
    )


def match_one(matcher: Matcher, query: Query) -> Outcome:
    """Match one listing in its context."""
    context = query.context
    result = matcher.match(
        query.name,
        states=context.states,
        counties=context.counties,
        market=context.market,
        category=query.section,
    )
    return outcome_of(matcher, result)


@dataclass(frozen=True, slots=True)
class MatcherSpec:
    """How to build the matcher: the directory folder and the alias file it reads.

    Worker processes are started fresh (``spawn``) and each builds its own matcher
    from this, so no process inherits another's threads or state.
    """

    directory_dir: Path
    aliases_path: Path

    def build(self) -> Matcher:
        """Load the directory and the aliases and index them."""
        return Matcher(load_directory(self.directory_dir), aliases=load_aliases(self.aliases_path))


_WORKER_MATCHER: Matcher | None = None
"""The matcher of a worker process, built once by :func:`_start_worker`."""


def _start_worker(spec: MatcherSpec) -> None:  # pragma: no cover - runs in a worker process
    global _WORKER_MATCHER  # noqa: PLW0603 - one matcher per worker process
    _WORKER_MATCHER = spec.build()


def _run_chunk(chunk: Sequence[Query]) -> list[Outcome]:  # pragma: no cover - in a worker
    matcher = _WORKER_MATCHER
    if matcher is None:
        raise RuntimeError("the worker has no matcher")
    return [match_one(matcher, query) for query in chunk]


def match_all(
    matcher: Matcher,
    queries: Iterable[Query],
    *,
    workers: int = 1,
    spec: MatcherSpec | None = None,
) -> dict[Query, Outcome]:
    """Match every distinct listing once; the answers do not depend on ``workers``.

    With ``workers`` above one and a ``spec``, the listings are split over that
    many worker processes, each with its own matcher built from ``spec`` (the same
    directory and aliases as ``matcher``); otherwise ``matcher`` answers them all.
    """
    ordered = sorted(set(queries), key=_order)
    if workers <= 1 or spec is None or len(ordered) <= CHUNK:
        return {query: match_one(matcher, query) for query in ordered}
    chunks = [ordered[i : i + CHUNK] for i in range(0, len(ordered), CHUNK)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(workers, initializer=_start_worker, initargs=(spec,)) as pool:
        answers = pool.map(_run_chunk, chunks, chunksize=1)
    found: dict[Query, Outcome] = {}
    for chunk, outcomes in zip(chunks, answers, strict=True):
        found.update(zip(chunk, outcomes, strict=True))
    return found


def _order(query: Query) -> tuple[str, tuple[str, ...], tuple[str, ...], str, str]:
    context = query.context
    return (
        context.market,
        context.states,
        context.counties or (),
        query.name,
        query.section or "",
    )
