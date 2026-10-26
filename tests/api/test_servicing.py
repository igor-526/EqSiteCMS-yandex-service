"""UT-YS-02/03: sensitive private peer Y5 returns only ciphertext, with or without user auth."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from containers import services_container
from core.exceptions import RepositoryError
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import EncryptionService, YandexServiceAuthorizationService
from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_peer_returns_only_ciphertext(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    runtime_api.authorization.get_token.return_value = "stored-ciphertext"
    async with runtime_api.client() as client:
        response = await client.get(f"/api/servicing/access-token/{ACCOUNT_ID}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"enc_access_token": "stored-ciphertext"}
    assert "access_token" not in response.json()
    assert "deliberate-access-token" not in response.text
    runtime_api.authorization.get_token.assert_awaited_once_with(account_id=ACCOUNT_ID)
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_uuid_validation(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/servicing/access-token/bad", headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    assert "access_token" not in response.json()
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("found", [True, False])
async def test_token_foreign_or_absent_account(runtime_api: RuntimeApi, headers: dict[str, str], found: bool) -> None:
    foreign = account()
    encryption = EncryptionService("test-secret")
    plaintext = "private-foreign-access-token"
    foreign.enc_access_token = encryption.encrypt(data=plaintext)
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = foreign if found else None
    service = YandexServiceAuthorizationService(yandex_user_repository=repository)
    with (
        override_providers({services_container.yandex_service_authorization_service: service}),
        patch.object(EncryptionService, "decrypt") as decrypt,
    ):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/servicing/access-token/{foreign.id}", headers=headers)
        decrypt.assert_not_called()
    status = 200 if found else 400
    assert response.status_code == status
    repository.get_by_id.assert_awaited_once_with(id=foreign.id)
    assert "access_token" not in response.json()
    assert plaintext not in response.text
    if found:
        assert response.json() == {"enc_access_token": foreign.enc_access_token}
    else:
        assert response.json() == {"detail": "Не удалось выполнить запрос"}
        assert foreign.enc_access_token not in response.text
    runtime_api.assert_transaction(status, "commit" if found else "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_repository_error_is_safe(
    runtime_api: RuntimeApi, headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private-access-token-and-ciphertext"
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.side_effect = RepositoryError(f"internal failure: {secret}")
    service = YandexServiceAuthorizationService(yandex_user_repository=repository)
    with (
        override_providers({services_container.yandex_service_authorization_service: service}),
        caplog.at_level(logging.DEBUG),
    ):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/servicing/access-token/{ACCOUNT_ID}", headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Не удалось выполнить запрос"}
    assert secret not in response.text
    assert secret not in caplog.text
    assert "internal failure" not in caplog.text
    runtime_api.assert_transaction(400, "rollback")
