"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_fixture():
    """Sample fixture for tests."""
    return {"test": "data"}
