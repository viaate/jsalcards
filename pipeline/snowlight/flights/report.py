"""The held-out report (Markdown, for people) and the track record file (for the site, D9)."""

from collections.abc import Sequence
from datetime import date, datetime

from snowlight.flights.model import (
    AFTER_DRAWS,
    AFTER_MIN_EVENTS,
    AFTER_STORM_HOURS,
    HEAVY_FLIGHTS,
    HEAVY_SHARE,
    MIN_TARGET_SKILL,
    TARGETS,
    UNDER_FACTOR,
    UNDER_RARE,
    Score,
    after_storm_ok,
)
from snowlight.flights.train import Tested
from snowlight.schemas.flights import (
    FlightsAirportGate,
    FlightsBin,
    FlightsMonthScore,
    FlightsTarget,
    FlightsTargetTest,
    FlightsTrackRecord,
)

TARGET_WORDS = {
    "dep_canc": "a departure is cancelled",
    "dep_late": "a departure leaves 45+ minutes late",
    "arr_canc": "an arrival is cancelled",
    "arr_late": "an arrival comes 45+ minutes late",
    "rough": "a rough day (10%+ of departures cancelled)",
}
LEAD_WORDS = {
    1: "the 00Z run of the evening before the block's day (lead 1)",
    2: "the 00Z run two evenings before (lead 2)",
    3: "the 00Z run three evenings before (lead 3)",
}


def _bound(lower: float) -> str:
    """A skill's lower bound as the report gives it (none without rows)."""
    return f"{100 * lower:+.1f}%" if lower > float("-inf") else "none"


def _permille(value: float) -> int:
    return max(0, min(1000, round(value * 1000)))


def _skill(value: float) -> float:
    return round(max(-100.0, min(1.0, value)), 4)


def _count(value: float) -> int:
    return max(0, round(value))


def target_test(test: Tested, published: int) -> FlightsTargetTest:
    """One target and lead's pooled test, for the track record."""
    pooled = test.pooled
    return FlightsTargetTest(
        target=FlightsTarget(TARGETS.index(test.target)),
        lead=test.lead,
        units=_count(pooled.units),
        events=_count(pooled.events),
        expected=_count(pooled.expected),
        brier=round(min(1.0, pooled.brier), 6),
        brier_usual=round(min(1.0, pooled.brier_base), 6),
        skill=_skill(pooled.skill),
        skill_published=_skill(test.as_published.skill),
        skill_confirmed=_skill(test.confirmed.skill),
        published=published,
        tested=len(test.airports),
        bins=tuple(
            FlightsBin(
                low=_permille(row["low"]),
                high=_permille(row["high"]),
                units=_count(row["units"]),
                said=_permille(row["said"]),
                seen=_permille(row["seen"]),
            )
            for row in test.reliability_published
        ),
    )


def track_record(
    tests: Sequence[Tested],
    gates: dict[str, list[int]],
    generated_at: datetime,
    usual: tuple[date, date],
    months: Sequence[FlightsMonthScore] = (),
) -> FlightsTrackRecord:
    """The track record file: the held-out year, the dated window of the usual rates, and
    every month scored since."""
    first = tests[0]
    split = first.split
    return FlightsTrackRecord(
        schema_version=1,
        generated_at=generated_at,
        test_first=split[0],
        test_last=split[1],
        usual_first=usual[0],
        usual_last=usual[1],
        tests=tuple(
            target_test(
                test,
                sum(
                    1
                    for masks in gates.values()
                    if masks[TARGETS.index(test.target)] >> (test.lead - 1) & 1
                ),
            )
            for test in tests
        ),
        airports=tuple(
            FlightsAirportGate(code=code, passed=(masks[0], masks[1], masks[2], masks[3], masks[4]))
            for code, masks in sorted(gates.items())
        ),
        months=tuple(months),
    )


def _row(score: Score) -> str:
    return (
        f"{score.units:,.0f} | {score.events:,.0f} | {score.expected:,.0f} | {score.brier:.5f} | "
        f"{score.brier_base:.5f} | {100 * score.skill:+.1f}%"
    )


def markdown(tests: Sequence[Tested], gates: dict[str, list[int]], notes: Sequence[str]) -> str:
    """The held-out report for people: pooled scores, reliability, where a chance is published
    and where only the usual rate is."""
    split = tests[0].split
    lines = [
        "# Flights: the held-out test",
        "",
        f"Test year: {split[0]} to {split[1]} (the newest 12 posted months), never used in "
        "fitting or in setting a gate: every gate (where a chance is published, and after a",
        "storm) is set on the validation year, the 12 months before, by a fit on the years",
        "before it; this year scores the published choice once.",
        "Brier: the mean squared gap between the chance and what happened (lower is better).",
        "Skill: how much lower than each airport's own usual rate for that block and month.",
        "Lead 1 is the 00Z run issued the afternoon or evening before the block's day (by the",
        "airport's own calendar); lead 2 and 3 one and two days earlier (the hours each lead",
        "spans are in the notes). No run issued on the block's own day is used, in the test or",
        "live.",
        "",
        *notes,
        "",
        "## Pooled over airports",
        "",
        "Skill (model): the model's chances at every airport. As published: what the files show,",
        "the chance where it passed on the validation year and the usual rate elsewhere. Out of",
        "selection: the airports the even ISO weeks of the test year would choose, scored on its",
        "odd ones, and the reverse (a second view only: the gates, a target and lead under",
        f"{100 * MIN_TARGET_SKILL:.0f}% out of selection published nowhere among them, are set on "
        "the validation year).",
        "",
        "target | lead | units | events | expected | Brier | Brier usual | skill (model) | "
        "as published | out of selection (chosen) | published at",
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for test in tests:
        index = TARGETS.index(test.target)
        count = sum(1 for masks in gates.values() if masks[index] >> (test.lead - 1) & 1)
        lines.append(
            f"{test.target} | {test.lead} | {_row(test.pooled)} | "
            f"{100 * test.as_published.skill:+.1f}% | {100 * test.confirmed.skill:+.1f}% "
            f"({test.chosen[0]}, {test.chosen[1]}) | {count} of {len(test.airports)}"
        )
    lines += [
        "",
        "## Heavy days and the days after a storm",
        "",
        f"Heavy: a block-day (a day, for the rough day) with {100 * HEAVY_SHARE:.0f}% or more of "
        f"its flights cancelled (late, for the late chances), with {HEAVY_FLIGHTS} flights or",
        f"more. Under said: the chance said was under {UNDER_FACTOR:.2f} of the share that "
        f"happened; an airport whose under-said heavy block-days pass {100 * UNDER_RARE:.0f}% of",
        "its heavy ones (more than one) shows the usual rate. After a storm: the run came after",
        f"{AFTER_STORM_HOURS} or more hours of observed falling snow or freezing rain in the 48 "
        "hours",
        "before it; on the validation year, those rows at the airports that passed, pooled, "
        "must have at least "
        f"{AFTER_MIN_EVENTS} events, a skill whose lower 90% bound (whole days drawn again "
        f"{AFTER_DRAWS:,} times, fixed seed) is above 0, be",
        "calibrated and keep under-said heavy block-days rare, else the files show the usual rate",
        "on such days. The same must hold out of selection: the airports the even ISO weeks",
        "chose, scored on their odd-week rows after a storm, and the reverse.",
        "",
        "target | lead | heavy (model) | under said (model) | heavy (as published) | "
        "under said (as published) | after a storm: units | events | expected | skill | "
        "skill lower bound | out of selection: events | skill | skill lower bound | shown",
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for test in tests:
        after, out = test.after_storm, test.after_out
        shown = (
            test.after_shown
            if test.after_shown is not None
            else after_storm_ok(after, test.after_lower)
            and after_storm_ok(out, test.after_out_lower)
        )
        lines.append(
            f"{test.target} | {test.lead} | {test.pooled.heavy} | {test.pooled.under} | "
            f"{test.as_published.heavy} | {test.as_published.under} | {after.units:,.0f} | "
            f"{after.events:,.0f} | {after.expected:,.0f} | {100 * after.skill:+.1f}% | "
            f"{_bound(test.after_lower)} | {out.events:,.0f} | {100 * out.skill:+.1f}% | "
            f"{_bound(test.after_out_lower)} | {'yes' if shown else 'usual rate'}"
        )
    lines += [
        "",
        "## The usual rates on the test year",
        "",
        "The usual rates are a dated average (the window in the notes and in the track record's",
        "usual_first and usual_last), never the test year's own: their expected events against",
        "what the test year saw.",
        "",
        "target | lead | units | expected (usual) | seen | seen / expected",
        "--- | --- | --- | --- | --- | ---",
    ]
    for test in tests:
        usual = test.usual
        ratio = f"{usual.events / usual.expected:.2f}" if usual.expected > 0 else "none"
        lines.append(
            f"{test.target} | {test.lead} | {usual.units:,.0f} | {usual.expected:,.0f} | "
            f"{usual.events:,.0f} | {ratio}"
        )
    put_back = [test for test in tests if test.with_not_weather is not None]
    if put_back:
        lines += [
            "",
            "## With the non-weather spans put back",
            "",
            "The same tests with the test year's non-weather spans kept in (see the notes): the",
            "model's chances at every airport, then the skill as published and out of selection",
            "(the airports each half of the weather days chose, scored on every row of the other",
            "half), as in the pooled table above.",
            "",
            "target | lead | units | events | expected | Brier | Brier usual | skill (model) | "
            "expected over seen | as published | out of selection",
            "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
        ]
        for test in put_back:
            score = test.with_not_weather
            assert score is not None  # noqa: S101 - filtered above
            shown_back, out_back = test.published_with_not_weather, test.confirmed_with_not_weather
            lines.append(
                f"{test.target} | {test.lead} | {_row(score)} | {score.calibration:.3f} | "
                + (f"{100 * shown_back.skill:+.1f}%" if shown_back is not None else "none")
                + " | "
                + (
                    f"{100 * out_back.skill:+.1f}%"
                    if out_back is not None and out_back.units
                    else "none"
                )
            )
    lines += ["", "## Reliability (pooled): when the chance said X, how often it happened", ""]
    for test in tests:
        if test.lead != 1:
            continue
        lines += [
            f"### {TARGET_WORDS[test.target]}, {LEAD_WORDS[test.lead]}",
            "",
            "chance said | units | mean said | share seen",
            "--- | --- | --- | ---",
        ]
        lines += [
            f"{100 * row['low']:.0f}-{100 * row['high']:.0f}% | {row['units']:,.0f} | "
            f"{100 * row['said']:.1f}% | {100 * row['seen']:.1f}%"
            for row in test.reliability
        ]
        lines += [
            "",
            "As published (the chance where it passed, else the usual rate):",
            "",
            "chance shown | units | mean shown | share seen",
            "--- | --- | --- | ---",
        ]
        lines += [
            f"{100 * row['low']:.0f}-{100 * row['high']:.0f}% | {row['units']:,.0f} | "
            f"{100 * row['said']:.1f}% | {100 * row['seen']:.1f}%"
            for row in test.reliability_published
        ]
        for title, rows in (
            ("The model's chances shown (the usual-rate cells left out):", test.reliability_shown),
            (
                "After an observed storm, at the airports that passed (the model's chances):",
                test.reliability_after,
            ),
        ):
            lines += [
                "",
                title,
                "",
                "chance said | units | mean said | share seen",
                "--- | --- | --- | ---",
            ]
            lines += [
                f"{100 * row['low']:.0f}-{100 * row['high']:.0f}% | {row['units']:,.0f} | "
                f"{100 * row['said']:.1f}% | {100 * row['seen']:.1f}%"
                for row in rows
            ]
        lines += [
            "",
            "The model's chances shown, by month (expected over seen; under 1 said too low):",
            "",
            "month | units | expected | seen | expected over seen",
            "--- | --- | --- | --- | ---",
        ]
        lines += [
            f"{month} | {units:,.0f} | {expected:,.1f} | {seen:,.0f} | "
            + (f"{expected / seen:.2f}" if seen else "none seen")
            for month, units, expected, seen in test.shown_by_month
        ]
        lines.append("")
    lines += [
        "## Where a chance is published",
        "",
        "Per airport, the targets whose chance passed (lead classes in brackets); every other",
        "target shows the usual rate there.",
        "",
        "airport | dep cancel | dep late | arr cancel | arr late | rough day",
        "--- | --- | --- | --- | --- | ---",
    ]
    for code, masks in sorted(gates.items()):
        cells = [
            ",".join(str(lead) for lead in (1, 2, 3) if mask >> (lead - 1) & 1) or "usual"
            for mask in masks
        ]
        lines.append(f"{code} | " + " | ".join(cells))
    return "\n".join(lines) + "\n"
