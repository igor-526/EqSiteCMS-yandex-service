"""API-01..03: OAuth entrypoints use the registered app and real DI wiring."""

from typing import Any

import pytest

from core.schemas.api import YandexAuthCodeInDto
from tests.api.conftest import ACCOUNT, AUTH_HEADERS, TENANT_ID, RuntimeApi


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_auth_link(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/auth/link", params={"equestrian_id": str(TENANT_ID)}, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"auth_link": "https://oauth.example.test/authorize"}
    runtime_api.oauth.get_auth_link.assert_called_once_with(equestrian_id=TENANT_ID)
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_auth_code_returns_account_without_secrets(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    runtime_api.oauth.authenticate.return_value = {**ACCOUNT, "access_token": "secret", "refresh_token": "secret"}
    async with runtime_api.client() as client:
        response = await client.post(
            "/api/auth/code", json={"code": "code-123", "equestrian_id": str(TENANT_ID)}, headers=headers
        )
    assert response.status_code == 200
    assert response.json() == ACCOUNT
    runtime_api.oauth.authenticate.assert_awaited_once_with(
        data=YandexAuthCodeInDto(code="code-123", equestrian_id=TENANT_ID)
    )
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("params", [{}, {"equestrian_id": "bad-uuid"}])
async def test_link_validation(runtime_api: RuntimeApi, params: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/auth/link", params=params)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize(
    "body",
    [{}, {"code": "abc"}, {"code": 123, "equestrian_id": str(TENANT_ID)}, {"code": "abc", "equestrian_id": "bad"}],
)
async def test_code_body_validation(runtime_api: RuntimeApi, body: dict[str, Any]) -> None:
    async with runtime_api.client() as client:
        response = await client.post("/api/auth/code", json=body)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("body", [b"{", b""])
async def test_invalid_or_missing_json(runtime_api: RuntimeApi, body: bytes) -> None:
    async with runtime_api.client() as client:
        response = await client.post("/api/auth/code", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")
