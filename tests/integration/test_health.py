"""Integration tests for health check endpoint."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import OperationalError


@pytest.mark.asyncio
async def test_health_check_anonymous_success(client):
    """
    Test: Anonymous GET /health → 200 OK (if service is healthy)
    
    Access: Public Read (no authentication required)
    Expected: 200 OK with {"status": "healthy", "timestamp": "..."}
    """
    # Mock successful database connection
    mock_connection = AsyncMock()
    mock_connection.execute = AsyncMock(return_value=None)
    
    # Create proper async context manager
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_engine = AsyncMock()
    mock_engine.connect = MagicMock(return_value=mock_context)
    
    with patch("api.health.get_engine", return_value=mock_engine):
        response = await client.get("/health")
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["timestamp"].endswith("Z")  # ISO 8601 UTC format


@pytest.mark.asyncio
async def test_health_check_authenticated_success(client):
    """
    Test: Authenticated GET /health → 200 OK (if service is healthy)
    
    Note: Health endpoint is Public Read, so authenticated request
    should work the same as anonymous (no 401/403 for valid health check).
    
    Access: Public Read
    Expected: 200 OK with {"status": "healthy", "timestamp": "..."}
    """
    # Mock successful database connection
    mock_connection = AsyncMock()
    mock_connection.execute = AsyncMock(return_value=None)
    
    # Create proper async context manager
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_engine = AsyncMock()
    mock_engine.connect = MagicMock(return_value=mock_context)
    
    with patch("api.health.get_engine", return_value=mock_engine):
        # Симулируем authenticated request (хотя endpoint не требует auth)
        headers = {"Authorization": "Bearer fake-token"}
        response = await client.get("/health", headers=headers)
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_check_database_failure(client):
    """
    Test: GET /health → 503 (if database is unavailable)
    
    Mock database connection to fail and verify proper error handling.
    
    Expected: 503 Service Unavailable with {"status": "unhealthy", "error": "...", "timestamp": "..."}
    """
    # Mock database connection to raise exception
    mock_connection = AsyncMock()
    mock_connection.execute = AsyncMock(side_effect=OperationalError(
        "connection failed", None, None
    ))
    
    # Create proper async context manager that returns the failing connection
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_engine = AsyncMock()
    mock_engine.connect = MagicMock(return_value=mock_context)
    
    with patch("api.health.get_engine", return_value=mock_engine):
        response = await client.get("/health")
    
    assert response.status_code == 503
    
    data = response.json()
    assert data["status"] == "unhealthy"
    assert "error" in data
    assert "timestamp" in data
    assert data["timestamp"].endswith("Z")


@pytest.mark.asyncio
async def test_health_check_database_connection_timeout(client):
    """
    Test: GET /health → 503 (if database connection times out)
    
    Simulate connection timeout scenario.
    
    Expected: 503 Service Unavailable
    """
    # Mock database connection to raise timeout exception
    mock_connection = AsyncMock()
    mock_connection.execute = AsyncMock(side_effect=TimeoutError("Connection timeout"))
    
    # Create proper async context manager
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_engine = AsyncMock()
    mock_engine.connect = MagicMock(return_value=mock_context)
    
    with patch("api.health.get_engine", return_value=mock_engine):
        response = await client.get("/health")
    
    assert response.status_code == 503
    
    data = response.json()
    assert data["status"] == "unhealthy"
    assert "error" in data
