"""API-01..03: OAuth entrypoints use the registered app and real DI wiring."""

from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from clients.yandex_oauth_client import YandexOAuthClient
from containers import services_container
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexAuthCodeInDto
from core.services import YandexOauthService
from tests.api.conftest import ACCOUNT, AUTH_HEADERS, TENANT_ID, RuntimeApi
from tests.helpers import override_providers


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


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("stage", ["exchange", "profile"])
@pytest.mark.parametrize("failure", ["timeout", "transport", "http", "json", "dto"])
async def test_real_oauth_failure_chain(
    runtime_api: RuntimeApi,
    mock_upstream,
    headers: dict[str, str],
    stage: str,
    failure: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SECRET-oauth-code-token"
    tokens = {"access_token": secret, "refresh_token": secret, "expires_in": 3600}

    def upstream(request: httpx.Request) -> httpx.Response:
        if stage == "profile" and request.url.path == "/token":
            return httpx.Response(200, json=tokens)
        if failure == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if failure == "transport":
            raise httpx.ConnectError(secret, request=request)
        if failure == "http":
            return httpx.Response(503, json={"error_description": secret})
        if failure == "json":
            return httpx.Response(200, content=secret)
        return httpx.Response(200, json={"access_token": secret})  # Incomplete OAuth DTO.

    requests = mock_upstream(upstream)
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    encryption = Mock()
    service = YandexOauthService(
        client=YandexOAuthClient(client_id="test", client_secret=secret, redirect_url="https://callback.test"),
        encryption_service=encryption,
        yandex_user_repository=repository,
    )
    with override_providers({services_container.yandex_oauth_service: service}):
        async with runtime_api.client() as client:
            response = await client.post(
                "/api/auth/code", json={"code": secret, "equestrian_id": str(TENANT_ID)}, headers=headers
            )
    assert response.status_code == 400
    assert secret not in response.text + caplog.text + str(capsys.readouterr())
    assert len(requests) == (2 if stage == "profile" else 1)
    assert repository.mock_calls == []  # No lookup/create/update before valid profile.
    assert encryption.mock_calls == []
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("params", [{}, {"equestrian_id": "bad-uuid"}])
@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_link_validation(runtime_api: RuntimeApi, params: dict[str, str], headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/auth/link", params=params, headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    assert "SECRET-validation" not in response.text
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize(
    "body",
    [{}, {"code": "abc"}, {"code": 123, "equestrian_id": str(TENANT_ID)}, {"code": "abc", "equestrian_id": "bad"}],
)
@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_code_body_validation(runtime_api: RuntimeApi, body: dict[str, Any], headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.post("/api/auth/code", json=body, headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    assert "SECRET-validation" not in response.text
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("body", [b"{", b"", b'{"code":"SECRET-validation", "equestrian_id":"SECRET-validation"}'])
@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_invalid_or_missing_json(runtime_api: RuntimeApi, body: bytes, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.post(
            "/api/auth/code", content=body, headers={**headers, "Content-Type": "application/json"}
        )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    assert "SECRET-validation" not in response.text
    runtime_api.assert_transaction(400, "rollback")
