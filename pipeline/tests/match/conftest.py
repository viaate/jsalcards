"""Fixtures for the matcher tests.

Every directory here is SYNTHETIC (see :mod:`match.synthetic` and
:mod:`match.handmade`): generated or hand-written names in NCES's shape, with
``SYN-`` ids and made-up county codes and coordinates. No real school appears.
"""

import pytest

from match import handmade, synthetic
from snowlight.match import Directory, Matcher

BACKGROUND_SEED = 2026
CASES_SEED = 20260925


@pytest.fixture(scope="session")
def background() -> list[synthetic.SyntheticRecord]:
    """A generated directory of about 15,000 districts and schools in every state."""
    return synthetic.build_directory(
        districts_per_state=40, private_per_state=20, seed=BACKGROUND_SEED
    )


@pytest.fixture(scope="session")
def background_matcher(background: list[synthetic.SyntheticRecord]) -> Matcher:
    """A matcher over the generated directory alone, for the generated cases."""
    return Matcher(Directory(item.record for item in background))


@pytest.fixture(scope="session")
def generated_cases(background: list[synthetic.SyntheticRecord]) -> list[synthetic.Case]:
    """Listings written for the generated directory, labelled by its identities."""
    return synthetic.build_cases(background, count=3950, seed=CASES_SEED)


@pytest.fixture(scope="session")
def fixture_directory(background: list[synthetic.SyntheticRecord]) -> Directory:
    """The hand-written records together with the generated background."""
    return Directory([*handmade.RECORDS, *(item.record for item in background)])


@pytest.fixture(scope="session")
def fixture_matcher(fixture_directory: Directory) -> Matcher:
    """A matcher over the hand-written records and the generated background."""
    return Matcher(fixture_directory)


@pytest.fixture(scope="session")
def handmade_directory() -> Directory:
    """Just the hand-written records."""
    return Directory(handmade.RECORDS)


@pytest.fixture(scope="session")
def handmade_matcher(handmade_directory: Directory) -> Matcher:
    """A matcher over just the hand-written records."""
    return Matcher(handmade_directory)
