"""Speed: a 130,000-record SYNTHETIC directory indexes in under 5 s, 1,000 listings match in 2 s.

The directory is generated (see :mod:`match.synthetic`) with the naming habits of
NCES records and tens of thousands of distinct names, so the index does real
normalization work rather than hitting its caches.

The bar is the speed of the code as the pipeline runs it. The test suite runs
under coverage, whose line tracer makes every Python line three to four times
slower, so the timed calls run with the tracer paused (the other tests cover
the same lines). ``tests/match/bench_match.py`` measures the same thing in a
plain interpreter.

This machine's four CPUs are shared (other builds, a browser under test), and a
run they slow down says nothing of the code. The timed calls therefore count the
CPU time of this process (``time.process_time``), which other processes waiting
for a CPU do not add to, rather than wall-clock time. The matcher is
single-threaded, so on an idle machine the two agree. A timed step that still
misses its bar is run again, cold, up to :data:`ATTEMPTS` times, and the fastest
run counts, as ``timeit`` takes the best of its repeats.
"""

import functools
import sys
import time
from collections.abc import Callable

import pytest

from match import synthetic
from snowlight.match import Directory, Matcher, MatchResult, normalize

BUILD_SECONDS = 5.0
MATCH_SECONDS = 2.0
RECORDS = 130_000
LISTINGS = 1_000
ATTEMPTS = 3


@pytest.fixture(scope="module")
def big() -> list[synthetic.SyntheticRecord]:
    records = synthetic.build_directory(districts_per_state=340, private_per_state=273, seed=7)
    assert len(records) >= RECORDS
    assert len({item.record.name for item in records}) > 60_000
    return records


def _timed[T](work: Callable[[], T]) -> tuple[T, float]:
    """Run ``work`` untraced; return its result and the CPU seconds it took."""
    tracer = sys.gettrace()
    sys.settrace(None)
    try:
        started = time.process_time()
        result = work()
        return result, time.process_time() - started
    finally:
        sys.settrace(tracer)


def _fastest[S, T](
    setup: Callable[[int], S], work: Callable[[S], T], bar: float
) -> tuple[T, float]:
    """Time ``work`` until a run beats ``bar``, at most :data:`ATTEMPTS` times.

    ``setup(attempt)``, untimed, gives each run what it works on, so a repeat
    is no warmer than the first: every run then starts from empty
    normalization caches. Returns the fastest run's result and seconds.
    """
    best: tuple[T, float] | None = None
    for attempt in range(ATTEMPTS):
        state = setup(attempt)
        normalize.clear_caches()
        result, seconds = _timed(functools.partial(work, state))
        if best is None or seconds < best[1]:
            best = (result, seconds)
        if seconds < bar:
            break
    assert best is not None
    return best


def test_index_build_and_matching_are_fast(big: list[synthetic.SyntheticRecord]) -> None:
    cases = synthetic.build_cases(big, count=LISTINGS, seed=11)

    def build(_nothing: None = None) -> Matcher:
        return Matcher(Directory(item.record for item in big))

    matcher, built = _fastest(lambda _attempt: None, build, BUILD_SECONDS)

    def match_all(fresh: Matcher) -> list[MatchResult]:
        return [
            fresh.match(
                case.listing,
                states=case.states,
                counties=case.counties,
                near=case.near,
                category=case.category,
            )
            for case in cases
        ]

    # A repeat matches with an index of its own, whose towns and vocabularies no
    # earlier run has read yet.
    results, matched = _fastest(
        lambda attempt: matcher if attempt == 0 else build(), match_all, MATCH_SECONDS
    )

    assert len(results) == LISTINGS
    assert built < BUILD_SECONDS, f"index build took {built:.2f} s"
    assert matched < MATCH_SECONDS, f"matching {LISTINGS} listings took {matched:.2f} s"
    correct = sum(
        frozenset(record.id for record in r.targets) == case.targets
        for r, case in zip(results, cases, strict=True)
    )
    assert correct / LISTINGS >= 0.99


def test_timing_restores_the_tracer() -> None:
    def tracer(*_args: object) -> None:
        return None

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        assert _timed(sys.gettrace)[0] is None
        assert sys.gettrace() is tracer
    finally:
        sys.settrace(previous)


def _spin(seconds: float) -> None:
    """Keep this process busy for ``seconds`` of CPU time (sleeping takes none)."""
    until = time.process_time() + seconds
    while time.process_time() < until:
        pass


def test_the_fastest_of_a_few_cold_runs_counts() -> None:
    """A run slowed past the bar is timed again, cold; one under it ends the timing."""
    delays = iter((0.05, 0.0, 0.05))
    runs: list[tuple[int, int]] = []

    def work(attempt: int) -> int:
        runs.append((attempt, len(normalize._PARSED)))
        normalize.record_form("Tollgate Elementary School", district=False)
        _spin(next(delays))
        return attempt

    result, seconds = _fastest(lambda attempt: attempt, work, bar=0.04)
    assert result == 1
    assert seconds < 0.04
    assert runs == [(0, 0), (1, 0)]  # set up afresh and cold each time
    slow, taken = _fastest(lambda _attempt: 0.01, _spin, bar=0.0)
    assert slow is None
    assert taken >= 0.01


def test_waiting_for_a_cpu_is_not_counted() -> None:
    """Time spent off the CPU (here, asleep) does not count against the bar."""
    _, seconds = _timed(functools.partial(time.sleep, 0.2))
    assert seconds < 0.1
