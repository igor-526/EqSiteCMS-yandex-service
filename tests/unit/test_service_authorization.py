"""UT-YS-01/04: ciphertext passthrough without decryption or unsafe logging."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from dependency_injector import providers

from containers import services_container
from core.entities import YandexUser
from core.exceptions import ClientError, RepositoryError
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import EncryptionService
from core.services.yandex_service_authorization_service import YandexServiceAuthorizationService
from tests.helpers import override_providers


def account(token: str) -> YandexUser:
    return YandexUser(
        equestrian_id=uuid4(),
        yandex_id="user",
        yandex_login="login",
        display_name="Name",
        enc_access_token=token,
        enc_refresh_token="refresh",
        token_expires_at=datetime.now(UTC),
    )


async def test_token_returns_stored_ciphertext(caplog: pytest.LogCaptureFixture) -> None:
    encryption = EncryptionService(secret_key="test-secret")
    plaintext = "private-access-token"
    user = account(encryption.encrypt(data=plaintext))
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = user
    service = YandexServiceAuthorizationService(repository)
    with caplog.at_level(logging.DEBUG), patch.object(EncryptionService, "decrypt") as decrypt:
        token = await service.get_token(account_id=user.id)
        assert token == user.enc_access_token
        assert token != plaintext
        decrypt.assert_not_called()
    assert encryption.decrypt(data=token) == plaintext
    repository.get_by_id.assert_awaited_once_with(id=user.id)
    assert plaintext not in caplog.text
    assert user.enc_access_token not in caplog.text


async def test_missing_account_is_safe(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = None
    with caplog.at_level(logging.DEBUG), patch.object(EncryptionService, "decrypt") as decrypt:
        with pytest.raises(ClientError, match="^Аккаунт не найден$"):
            await YandexServiceAuthorizationService(repository).get_token(account_id=uuid4())
        decrypt.assert_not_called()
    assert not caplog.records


async def test_opaque_token_is_not_validated_or_decrypted() -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = account("opaque-stored-ciphertext")
    with patch.object(EncryptionService, "decrypt", side_effect=AssertionError("must not decrypt")) as decrypt:
        token = await YandexServiceAuthorizationService(repository).get_token(account_id=uuid4())
    assert token == "opaque-stored-ciphertext"
    decrypt.assert_not_called()


async def test_repository_failure_propagates_without_logging_secrets(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    error = RepositoryError("database unavailable: private-access-token opaque-stored-ciphertext")
    repository.get_by_id.side_effect = error
    with caplog.at_level(logging.DEBUG), patch.object(EncryptionService, "decrypt") as decrypt:
        with pytest.raises(RepositoryError) as caught:
            await YandexServiceAuthorizationService(repository).get_token(account_id=uuid4())
        decrypt.assert_not_called()
    assert caught.value is error
    assert not caplog.records


async def test_provider_does_not_resolve_encryption_service() -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    user = account("stored-ciphertext")
    repository.get_by_id.return_value = user
    encryption = Mock(side_effect=AssertionError("encryption dependency must not be resolved"))
    with override_providers(
        {
            services_container.repositories_container.yandex_user_repository: repository,
            services_container.encryption_service: providers.Callable(encryption),
        }
    ):
        service = services_container.yandex_service_authorization_service()
        assert await service.get_token(account_id=user.id) == user.enc_access_token
    encryption.assert_not_called()
