"""Shared fixtures for the schema tests."""

import pytest

from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile


@pytest.fixture(params=PUBLISHED_FILES, ids=lambda entry: entry.name)
def entry(request: pytest.FixtureRequest) -> PublishedFile:
    """Each published file in turn."""
    value: PublishedFile = request.param
    return value
