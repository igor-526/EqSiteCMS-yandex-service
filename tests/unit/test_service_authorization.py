import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from core.entities import YandexUser
from core.exceptions import ClientError, RepositoryError
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import EncryptionService
from core.services.yandex_service_authorization_service import YandexServiceAuthorizationService


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


async def test_token_decrypts_only_selected_account(caplog: pytest.LogCaptureFixture) -> None:
    encryption = EncryptionService(secret_key="test-secret")
    user = account(encryption.encrypt(data="private-access-token"))
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = user
    service = YandexServiceAuthorizationService(encryption, repository)
    with caplog.at_level(logging.DEBUG):
        assert await service.get_token(account_id=user.id) == "private-access-token"
    repository.get_by_id.assert_awaited_once_with(id=user.id)
    assert "private-access-token" not in caplog.text
    assert user.enc_access_token not in caplog.text


async def test_missing_account_does_not_decrypt() -> None:
    encryption = Mock(spec=EncryptionService)
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = None
    with pytest.raises(ClientError, match="Аккаунт не найден"):
        await YandexServiceAuthorizationService(encryption, repository).get_token(account_id=uuid4())
    encryption.decrypt.assert_not_called()


async def test_corrupt_token_becomes_client_error(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = account("corrupted-private-token")
    with pytest.raises(ClientError, match="Ошибка расшифровки") as caught:
        await YandexServiceAuthorizationService(EncryptionService("test-secret"), repository).get_token(
            account_id=uuid4()
        )
    assert isinstance(caught.value.__cause__, ValueError)
    assert "corrupted-private-token" not in caplog.text


async def test_unexpected_decrypt_error_preserves_cause() -> None:
    error = RuntimeError("cipher unavailable")
    encryption = Mock(spec=EncryptionService)
    encryption.decrypt.side_effect = error
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = account("encrypted")
    with pytest.raises(ClientError, match="Ошибка: cipher unavailable") as caught:
        await YandexServiceAuthorizationService(encryption, repository).get_token(account_id=uuid4())
    assert caught.value.__cause__ is error


async def test_repository_failure_propagates_without_decrypt() -> None:
    encryption = Mock(spec=EncryptionService)
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    error = RepositoryError("database unavailable")
    repository.get_by_id.side_effect = error
    with pytest.raises(RepositoryError) as caught:
        await YandexServiceAuthorizationService(encryption, repository).get_token(account_id=uuid4())
    assert caught.value is error
    encryption.decrypt.assert_not_called()
