"""NCES naming habits read the other way, swept over a synthetic directory.

The labelled fixture measures the matcher on the forms its generator writes; the
real directory has habits of its own, state by state, that a list reads the
other way (:mod:`match.habits`): Tennessee's city districts named by the city
alone, Michigan's ``ISD`` for an intermediate school district, Indiana's ``Com``,
``Con``, ``Cnt`` and ``Co``, the ``Township`` Pennsylvania's NCES names say and
its lists leave out (and New Jersey's the other way round), Texas's ``MT-``,
Ohio's city districts named ``Local``. Each habit's listings must be found
nearly always, and a listing whose district has a namesake that the municipal
word or the legal form alone tells apart must never be taken for either.
"""

from collections import Counter

import pytest

from match import habits
from snowlight.match import Directory, Matcher

HABIT_SEED = 20260927
MIN_PRECISION = 0.99
MIN_RECALL = 0.95
MIN_HARD_NEGATIVES = 20


@pytest.fixture(scope="module")
def sweep() -> tuple[Matcher, list[habits.HabitCase]]:
    records, cases = habits.build(HABIT_SEED)
    return Matcher(Directory(records)), cases


def _got(matcher: Matcher, case: habits.HabitCase) -> str | None:
    result = matcher.match(case.listing, states=[case.state], counties=case.counties)
    return result.target.id if result.target is not None else None


def test_the_sweep_is_synthetic_and_covers_every_habit(
    sweep: tuple[Matcher, list[habits.HabitCase]],
) -> None:
    matcher, cases = sweep
    assert all(record.id.startswith("SYN-HAB-") for record in matcher.directory)
    assert all(
        record.county_fips is not None and record.county_fips.startswith("7")
        for record in matcher.directory
    )
    by_habit = Counter(case.habit for case in cases)
    assert set(by_habit) == set(habits.HABITS)
    assert all(count >= MIN_HARD_NEGATIVES for count in by_habit.values()), by_habit
    hard = [case for case in cases if case.expected is None]
    assert len(hard) >= MIN_HARD_NEGATIVES


@pytest.mark.parametrize("habit", habits.HABITS)
def test_each_habit_is_read_the_other_way(
    sweep: tuple[Matcher, list[habits.HabitCase]], habit: str
) -> None:
    matcher, cases = sweep
    positives = [case for case in cases if case.habit == habit and case.expected is not None]
    missed = [
        (case.listing, case.counties, _got(matcher, case))
        for case in positives
        if _got(matcher, case) != case.expected
    ]
    recall = 1 - len(missed) / len(positives)
    assert recall >= MIN_RECALL, (habit, recall, missed[:10])


def test_a_namesake_the_habit_alone_tells_apart_leaves_no_answer(
    sweep: tuple[Matcher, list[habits.HabitCase]],
) -> None:
    matcher, cases = sweep
    wrong = [
        (case.listing, case.counties, case.note, got)
        for case in cases
        if case.expected is None and (got := _got(matcher, case)) is not None
    ]
    assert not wrong


def test_precision_and_recall_over_the_sweep(
    sweep: tuple[Matcher, list[habits.HabitCase]],
) -> None:
    matcher, cases = sweep
    true_positives = false_positives = positives = 0
    for case in cases:
        got = _got(matcher, case)
        positives += case.expected is not None
        if got is None:
            continue
        if got == case.expected:
            true_positives += 1
        else:
            false_positives += 1
    precision = true_positives / (true_positives + false_positives)
    recall = true_positives / positives
    assert precision >= MIN_PRECISION, precision
    assert recall >= MIN_RECALL, recall
