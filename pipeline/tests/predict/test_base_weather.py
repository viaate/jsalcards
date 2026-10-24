"""The base row names the weather of the days it counts (addendum e, E2): a class whose alerts
have no one alert kind (advisory, cold, lake snow, tropical) says which kind of days they are,
"recorded winter advisory days", instead of "days like this"."""

import json

import pytest

from snowlight.predict.situations import SITUATIONS, WeatherClass
from snowlight.predict.why import ALERT_KIND, WEATHER_NAME, base_for, sayable
from snowlight.schemas.predictions import PooledBase, SimilarDaysBase

BY_KEY = {item.key: item for item in SITUATIONS}


def test_every_class_with_an_alert_names_its_days() -> None:
    """Every class but ``none`` has an alert kind or a weather name, never both."""
    for weather in WeatherClass:
        named = (weather in ALERT_KIND) + (weather in WEATHER_NAME)
        assert named == (0 if weather == WeatherClass.NONE else 1), weather


@pytest.mark.parametrize(
    ("key", "name"),
    [("advisory", "advisory"), ("cold", "cold"), ("lake_snow", "lake_snow"),
     ("tropical", "tropical"), ("none", None)],
)  # fmt: skip
def test_own_and_pooled_bases_carry_the_weather_of_the_days_counted(
    key: str, name: str | None
) -> None:
    """Where the counted days are all the place's days of their weather (``whole``)."""
    situation = BY_KEY[key]
    own = base_for(situation, 0.74, own=True, scope="nation", whole=True)
    pooled = base_for(situation, 0.74, own=False, scope="nation", whole=True)
    assert isinstance(pooled, PooledBase)
    assert isinstance(own, SimilarDaysBase)
    assert (pooled.weather, own.weather) == (name, name)
    assert pooled.alert is None
    # The compact file says it only when there is one.
    value = json.loads(pooled.model_dump_json(exclude_defaults=True))
    assert value.get("weather") == name


@pytest.mark.parametrize("key", ["advisory", "cold", "lake_snow", "tropical"])
def test_a_base_whose_days_are_not_all_the_weathers_says_days_like_this(key: str) -> None:
    """The advisory days that did not follow a snow day are not all of a place's advisory
    days once it has any after one: "of their recorded winter advisory days" would claim the
    share over all of them, so the base says "days like this" (the default)."""
    situation = BY_KEY[key]
    for base in (
        base_for(situation, 0.74, own=True, scope="nation"),
        base_for(situation, 0.74, own=False, scope="nation"),
        base_for(situation, 0.74, own=False, scope="state", whole=False),
    ):
        assert isinstance(base, SimilarDaysBase | PooledBase)
        assert base.weather is None


def test_the_days_after_a_snow_day_never_name_the_weather() -> None:
    """A pooled base counted over the advisory days after a snow day counts those only: it
    says "days like this", whatever ``whole`` says (the critic's E2 B1)."""
    after = BY_KEY["advisory_after"]
    for whole in (True, False):
        pooled = base_for(after, 0.74, own=False, scope="nation", whole=whole)
        assert isinstance(pooled, PooledBase)
        assert (pooled.weather, pooled.borrowed, pooled.alert) == (None, False, None)
        own = base_for(after, 0.74, own=True, scope="nation", whole=whole)
        assert own.kind == "day_after"
    for scope in ("nearby", "county", "state", "region", "nation"):
        pooled = base_for(after, 0.5, own=False, scope=scope, whole=True)
        assert isinstance(pooled, PooledBase)
        assert pooled.weather is None
        assert "weather" not in json.loads(pooled.model_dump_json(exclude_defaults=True))


def test_a_day_after_counted_over_the_class_days_names_them() -> None:
    """Borrowed: the sentence says which days ("winter advisory days that did not follow a
    recorded snow day"), true whatever else the place holds."""
    day = BY_KEY["advisory_after"]
    counted = BY_KEY["advisory"]
    assert sayable(day, counted)
    for whole in (True, False):
        base = base_for(counted, 0.6, own=True, scope="nation", day=day, whole=whole)
        assert isinstance(base, SimilarDaysBase)
        assert base.borrowed
        assert base.weather == "advisory"


def test_a_warning_class_keeps_its_alert_and_names_no_weather() -> None:
    base = base_for(BY_KEY["snow_warning"], 0.5, own=False, scope="state")
    assert isinstance(base, PooledBase)
    assert (base.alert, base.weather) == ("winter_storm_warning", None)


def test_a_pooled_base_never_names_both() -> None:
    with pytest.raises(ValueError, match="not both"):
        PooledBase(
            kind="pooled",
            scope="nation",
            points=74,
            alert="winter_storm_warning",
            weather="advisory",
        )
