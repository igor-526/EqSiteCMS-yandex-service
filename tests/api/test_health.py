import pytest
from fastapi.testclient import TestClient

from main import app
from settings import Settings
from tests.api.conftest import AUTH_HEADERS, RuntimeApi


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_routes_are_not_registered() -> None:
    response = TestClient(app).post("/api/auth/register")

    assert response.status_code == 404


def test_template_runtime_has_no_cors_configuration_or_headers() -> None:
    assert not hasattr(Settings(), "cors_origins")

    response = TestClient(app).get("/health", headers={"Origin": "https://frontend.example"})

    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_health_public_without_database(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert runtime_api.sessions == []
    runtime_api.assert_no_service_calls()
