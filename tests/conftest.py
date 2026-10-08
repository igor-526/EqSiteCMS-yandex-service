"""Pytest configuration and fixtures."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def sample_fixture():
    """Sample fixture for tests."""
    return {"test": "data"}


@pytest.fixture
async def client():
    """
    Async test client for integration tests.
    
    Usage:
        async def test_endpoint(client):
            response = await client.get("/health")
            assert response.status_code == 200
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
