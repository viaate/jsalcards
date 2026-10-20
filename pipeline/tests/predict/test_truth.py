"""Every base sentence is true of the recorded days of the place it names (addendum d, 4).

The website says a base of ``points`` percent as "almost never", "3 in 4", "more than 3 in
5" or "almost always" (``shareOf``, kept identical to :func:`share_of` by the golden file in
``test_share.py``). Here that sentence is checked, with exact fractions, against the closed
or remote days ``y`` of ``n`` recorded days of the level the base names: in the chain, over
every cell of the committed model, and over every cell a serving pass publishes.
"""

from collections.abc import Iterator
from fractions import Fraction
from math import floor

import numpy as np
import numpy.typing as npt
import pytest

from predict import world
from snowlight.predict.artifact import SITUATION_KEYS, ModelArtifact, load
from snowlight.predict.geography import REGION_OF
from snowlight.predict.pool import (
    SCOPES,
    Chain,
    LevelCounts,
    Strengths,
    chain,
    level_counts,
    make_places,
    named_counts,
)
from snowlight.predict.serve import build_model
from snowlight.predict.share import share_of
from snowlight.predict.situations import SITUATIONS, Situation, WeatherClass
from snowlight.predict.why import base_for, sayable

ALMOST: Fraction = Fraction(1, 20)


def told_true(points: int, y: float, n: float) -> bool:
    """The sentence for ``points``, judged by hand against ``y`` of ``n`` days."""
    if n <= 0:
        return False
    share = Fraction(round(y), round(n))
    if points <= 1:
        return share < ALMOST
    if points >= 99:
        return share > 1 - ALMOST
    told = share_of(points)
    if told.more:
        return share > Fraction(told.some, told.of)
    return floor(share * 100 + Fraction(1, 2)) == points


def cells(
    p: npt.NDArray[np.float64], y: npt.NDArray[np.float64], n: npt.NDArray[np.float64]
) -> Iterator[tuple[int, float, float]]:
    """(points, y, n) per cell, each distinct one once."""
    points = np.round(np.clip(np.round(p, 2), 0.01, 0.99) * 100).astype(np.int64)
    seen = {
        (int(a), float(b), float(c))
        for a, b, c in zip(points.ravel(), y.ravel(), n.ravel(), strict=True)
    }
    yield from sorted(seen)


def committed_chain(artifact: ModelArtifact) -> tuple[LevelCounts, Chain]:
    """The chain over the committed model's districts, nearby being the same county's (up to
    twelve), as a pass would build it with its own neighbors."""
    leaids = sorted(artifact.districts)
    entry = artifact.districts
    states = [entry[d].state for d in leaids]
    counties = [entry[d].county for d in leaids]
    by_county: dict[str, list[str]] = {}
    for leaid, county in zip(leaids, counties, strict=True):
        if county is not None:
            by_county.setdefault(county, []).append(leaid)
    near = {
        d: [e for e in by_county.get(c or "", []) if e != d][:12]
        for d, c in zip(leaids, counties, strict=True)
    }
    places = make_places(
        leaids,
        region=[None if s is None else REGION_OF.get(s) for s in states],
        state=states,
        county=counties,
        neighbors=near,
    )
    shape = (len(leaids), len(SITUATION_KEYS))
    y, n = np.zeros(shape), np.zeros(shape)
    for i, leaid in enumerate(leaids):
        found = entry[leaid]
        if found.y is not None and found.n is not None:
            y[i], n[i] = found.y, found.n
    counts = level_counts(places, y, n)
    strengths = Strengths(artifact.strengths["no_school"])  # type: ignore[arg-type]
    return counts, chain(counts, strengths, rules=artifact.settings.rules())


def test_every_cell_of_the_committed_model_says_a_true_sentence() -> None:
    artifact = load()
    counts, found = committed_chain(artifact)
    y, n = named_counts(counts, found)
    rules = artifact.settings.rules()
    p = rules.published(found.p)
    false = [cell for cell in cells(p, y, n) if not told_true(*cell)]
    assert false == []
    # Every pooled scope is named somewhere, so the check reaches each level's counts.
    named = {SCOPES[int(k)] for k in np.unique(found.scope[~found.own])}
    assert named == set(SCOPES)


def test_every_served_cell_says_a_true_sentence() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    false = [cell for cell in cells(built.p, built.named_y, built.named_n) if not told_true(*cell)]
    assert false == []
    assert built.named_n.shape == built.p.shape
    assert (built.named_n > 0).all()


def _one(y_own: int, n_own: int, y_rest: int, n_rest: int, strength: float) -> Chain:
    """Two districts in one county: the first with ``y_own`` of ``n_own`` snow warning days,
    the second with the rest (and plenty of plain days, so every situation is modeled)."""
    places = make_places(
        ["0100001", "0100002"],
        region=["south", "south"],
        state=["AL", "AL"],
        county=["01001", "01001"],
        neighbors={"0100001": ["0100002"], "0100002": ["0100001"]},
    )
    snow = SITUATION_KEYS.index("snow_warning")
    y = np.zeros((2, len(SITUATION_KEYS)))
    n = np.zeros((2, len(SITUATION_KEYS)))
    n[:, :] = 40.0
    y[0, snow], n[0, snow] = y_own, n_own
    y[1, snow], n[1, snow] = y_rest, n_rest
    strengths = Strengths.uniform(strength)
    rules = world.SETTINGS.rules()
    return chain(level_counts(places, y, n), strengths, rules=rules)


@pytest.mark.parametrize(
    ("y_own", "n_own", "y_rest", "n_rest"),
    [
        (4, 4, 30, 40),  # the critic's "49 in 50" over 4 of 4
        (3, 4, 30, 40),  # "more than 3 in 4" over exactly 3 of 4
        (15, 17, 40, 40),  # "more than 9 in 10" over 15 of 17
        (77, 82, 36, 40),  # "9 in 10" over 77 of 82
    ],
)
def test_the_chain_never_names_a_record_its_sentence_misstates(
    y_own: int, n_own: int, y_rest: int, n_rest: int
) -> None:
    for strength in (1.0, 4.0, 16.0):
        found = _one(y_own, n_own, y_rest, n_rest, strength)
        counts_y, counts_n = (
            np.array([[y_own], [y_rest]], dtype=float),
            np.array([[n_own], [n_rest]], dtype=float),
        )
        assert counts_y.shape == counts_n.shape
        snow = SITUATION_KEYS.index("snow_warning")
        p = world.SETTINGS.rules().published(found.p)[:, snow]
        for row in range(2):
            if found.own[row, snow]:
                y, n = (y_own, n_own) if row == 0 else (y_rest, n_rest)
            else:
                scope = SCOPES[int(found.scope[row, snow])]
                assert scope in {"nearby", "county", "state", "region", "nation"}
                y, n = (
                    (y_own + y_rest, n_own + n_rest) if scope != "nearby" else
                    ((y_rest, n_rest) if row == 0 else (y_own, n_own))
                )  # fmt: skip
            points = round(float(p[row]) * 100)
            assert told_true(points, y, n), (strength, row, points, y, n)


def test_a_borrowed_base_says_which_days_it_counts() -> None:
    snow = Situation(WeatherClass.SNOW_WARNING)
    ice = Situation(WeatherClass.ICE)
    plain = Situation(WeatherClass.NONE)
    after = Situation(WeatherClass.NONE, after=True)
    lent = base_for(snow, 0.9, own=False, scope="nation", day=ice)
    assert lent.kind == "pooled"
    assert lent.borrowed
    assert lent.alert == "winter_storm_warning"
    assert not base_for(snow, 0.9, own=False, scope="nation").borrowed  # type: ignore[union-attr]
    day = base_for(plain, 0.01, own=True, scope="nation", day=after)
    assert day.kind == "similar_days"
    assert day.borrowed
    # Days with no alert to name can stand only for the same weather without the day after.
    assert not sayable(Situation(WeatherClass.COLD), plain)
    with pytest.raises(ValueError, match="cannot be counted"):
        base_for(plain, 0.01, own=False, scope="nation", day=Situation(WeatherClass.COLD))


def test_every_fallback_the_settings_allow_can_be_said() -> None:
    fallback = world.CONFIG.model.fallback
    for item in SITUATIONS:
        seen = item
        while seen.key in fallback:
            seen = Situation.from_key(fallback[seen.key])
            assert sayable(item, seen), (item.key, seen.key)


def test_a_served_fallback_day_is_borrowed() -> None:
    built = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    ice = SITUATION_KEYS.index("ice")
    assert SITUATIONS[built.effective[ice]].key == "snow_warning"
    assert all(sayable(SITUATIONS[k], SITUATIONS[e]) for k, e in enumerate(built.effective))
