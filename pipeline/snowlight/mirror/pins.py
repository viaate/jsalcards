"""The pin set the data mirror holds: every pinned file of the directory and places builds."""

import os
from pathlib import Path

from snowlight.directory.config import DEFAULT_CONFIG_PATH, DirectoryConfig, load_config
from snowlight.places.pins import DEFAULT_PLACES_PINS_PATH, PlacesPins, load_places_pins
from snowlight.sources.mirror import (
    ENV_REQUIRE,
    ENV_ROOT,
    Mirror,
    Pin,
    check_pin_set,
    wait_from_env,
)


def directory_pins(config: DirectoryConfig) -> list[Pin]:
    """Every directory source release with a pinned SHA-256.

    An unpinned release (one NCES has not published yet) is not mirrored: a deploy
    skips it as not published and reads the newest pinned release.
    """
    return [
        Pin(candidate.url, candidate.sha256)
        for source in config.sources.values()
        for candidate in source.candidates
        if candidate.sha256 is not None
    ]


def pin_set(directory: DirectoryConfig, places: PlacesPins) -> tuple[Pin, ...]:
    """The mirror's pin set, sorted by URL."""
    return check_pin_set([*directory_pins(directory), *places.pins()])


def load_pin_set(
    directory_path: Path = DEFAULT_CONFIG_PATH, places_path: Path = DEFAULT_PLACES_PINS_PATH
) -> tuple[Pin, ...]:
    """Load both configs and return their pin set."""
    return pin_set(load_config(directory_path), load_places_pins(places_path))


def mirror_root(argument: str | None) -> str | None:
    """The mirror root a build reads: ``--mirror``, else :data:`ENV_ROOT`, else none.

    Raises:
        ValueError: when there is none and :data:`ENV_REQUIRE` is ``1`` (a deploy), so a
            deploy that lost its mirror setting fails closed instead of reading the origins.
    """
    root = argument if argument is not None else os.environ.get(ENV_ROOT, "")
    root = root.strip()
    required = os.environ.get(ENV_REQUIRE, "").strip()
    if required not in {"", "0", "1"}:
        raise ValueError(f"{ENV_REQUIRE} must be 1 or 0, got {required!r}")
    if not root and required == "1":
        raise ValueError(
            f"{ENV_REQUIRE}=1 but no data mirror is set (--mirror or {ENV_ROOT}): "
            "a deploy never reads NCES or Census"
        )
    return root or None


def load_mirror(
    root: str,
    directory_path: Path = DEFAULT_CONFIG_PATH,
    places_path: Path = DEFAULT_PLACES_PINS_PATH,
) -> Mirror:
    """The mirror at ``root`` holding the pin set of both configs."""
    return Mirror(root, load_pin_set(directory_path, places_path), wait_seconds=wait_from_env())
