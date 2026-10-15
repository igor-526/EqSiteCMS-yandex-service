import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from core.entities import YandexUser
from core.exceptions import AppError, ClientError, RepositoryError, YandexClientException
from core.protocols.clients import YandexOAuthClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexAuthCodeInDto
from core.schemas.clients import YandexClientAuthResponse, YandexClientUserResponse, YandexClientUserResponsePhone
from core.services import EncryptionService, YandexOauthService


@pytest.fixture
def oauth() -> tuple[YandexOauthService, AsyncMock, AsyncMock, EncryptionService]:
    client = AsyncMock(spec=YandexOAuthClientProtocol)
    client.get_init_oauth_link.return_value = "https://example.test/oauth"
    client.authenticate.return_value = YandexClientAuthResponse(
        access_token="new-access-token", refresh_token="new-refresh-token", expires_in=3600
    )
    client.get_user_info.return_value = YandexClientUserResponse(
        id="yandex-user-id",
        login="new-login",
        client_id="client-id",
        display_name="New name",
        real_name="New Real Name",
        first_name="New",
        last_name="Name",
        default_email="new@example.com",
        default_avatar_id="avatar-id",
        default_phone=YandexClientUserResponsePhone(id=1, number="+79990000000"),
        psuid="psuid",
    )
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_yandex_id.return_value = None
    repository.create.side_effect = lambda entity: entity
    repository.update.side_effect = lambda entity: entity
    encryption = EncryptionService("test-secret")
    return YandexOauthService(client, encryption, repository), client, repository, encryption


def test_auth_link_delegates_uuid_state(oauth) -> None:
    service, client, _, _ = oauth
    tenant = uuid4()
    assert service.get_auth_link(equestrian_id=tenant) == "https://example.test/oauth"
    client.get_init_oauth_link.assert_called_once_with(state=str(tenant))


@pytest.mark.parametrize("seconds", [-3600, 0, 3600])
def test_expiry_uses_utc_and_exact_duration(oauth, seconds: int) -> None:
    service, _, _, _ = oauth
    before = datetime.now(UTC) + timedelta(seconds=seconds)
    expires = service.get_token_expires_at(seconds=seconds)
    after = datetime.now(UTC) + timedelta(seconds=seconds)
    assert before <= expires <= after
    assert expires.tzinfo is UTC


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("phone", [None, "+79990000000"])
async def test_authentication_persists_encrypted_tokens_and_returns_safe_dto(
    oauth, existing: bool, phone: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    service, client, repository, encryption = oauth
    tenant = uuid4()
    user = YandexUser(
        equestrian_id=tenant,
        yandex_id="yandex-user-id",
        yandex_login="old-login",
        display_name="Old name",
        email="old@example.com",
        yandex_avatar_id="old-avatar",
        yandex_phone="old-phone",
        enc_access_token="old-access",
        enc_refresh_token="old-refresh",
        token_expires_at=datetime.now(UTC),
    )
    if existing:
        repository.get_by_yandex_id.return_value = user
    if phone is None:
        client.get_user_info.return_value.default_phone = None
    before = datetime.now(UTC) + timedelta(seconds=3600)
    with caplog.at_level(logging.INFO, logger="Yandex Oauth Service"):
        result = await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=tenant))
    after = datetime.now(UTC) + timedelta(seconds=3600)
    client.authenticate.assert_awaited_once_with(code="code")
    client.get_user_info.assert_awaited_once_with(access_token="new-access-token")
    repository.get_by_yandex_id.assert_awaited_once_with(equestrian_id=tenant, yandex_id="yandex-user-id")
    if existing:
        repository.create.assert_not_awaited()
        repository.update.assert_awaited_once_with(user)
        persisted = user
        assert result.id == user.id
    else:
        repository.update.assert_not_awaited()
        persisted = repository.create.await_args.args[0]
        assert result.id == persisted.id
    assert persisted.equestrian_id == tenant
    assert persisted.yandex_avatar_id == "avatar-id"
    assert result.yandex_login == "new-login"
    assert result.display_name == "New name"
    assert result.email == "new@example.com"
    assert result.yandex_phone == phone
    assert encryption.decrypt(data=persisted.enc_access_token) == "new-access-token"
    assert encryption.decrypt(data=persisted.enc_refresh_token) == "new-refresh-token"
    assert before <= persisted.token_expires_at <= after
    assert set(result.model_dump()) == {"id", "yandex_id", "yandex_login", "display_name", "email", "yandex_phone"}
    for secret in ("new-access-token", "new-refresh-token", persisted.enc_access_token, persisted.enc_refresh_token):
        assert secret not in result.model_dump_json()
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "stage,message",
    [("authenticate", "Не удалось выполнить аутентификацию"), ("get_user_info", "Не удалось получить данные")],
)
async def test_provider_failures_map_to_client_error_before_writes(oauth, stage: str, message: str) -> None:
    service, client, repository, _ = oauth
    error = YandexClientException(status=400, error="invalid_grant")
    getattr(client, stage).side_effect = error
    with pytest.raises(ClientError, match=message) as caught:
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    assert caught.value.__cause__ is error
    if stage == "authenticate":
        client.get_user_info.assert_not_awaited()
    repository.get_by_yandex_id.assert_not_awaited()
    repository.create.assert_not_awaited()
    repository.update.assert_not_awaited()


@pytest.mark.parametrize("stage", ["get_by_yandex_id", "create", "update"])
async def test_repository_failures_map_to_app_error(oauth, stage: str) -> None:
    service, _, repository, _ = oauth
    if stage == "update":
        repository.get_by_yandex_id.return_value = YandexUser(
            equestrian_id=uuid4(),
            yandex_id="user",
            yandex_login="login",
            display_name="Name",
            enc_access_token="encrypted",
            enc_refresh_token="encrypted",
            token_expires_at=datetime.now(UTC),
        )
    error = RepositoryError("database unavailable")
    getattr(repository, stage).side_effect = error
    with pytest.raises(AppError, match="Не удалось сохранить аккаунт") as caught:
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    assert caught.value.__cause__ is error
    if stage == "get_by_yandex_id":
        repository.create.assert_not_awaited()
        repository.update.assert_not_awaited()
    elif stage == "create":
        repository.update.assert_not_awaited()
    else:
        repository.create.assert_not_awaited()


@pytest.mark.parametrize(
    "field,size",
    [("id", 64), ("login", 128), ("display_name", 128), ("default_email", 321), ("default_avatar_id", 64)],
)
async def test_oversized_provider_fields_rejected_before_lookup(oauth, field: str, size: int) -> None:
    service, client, repository, _ = oauth
    setattr(client.get_user_info.return_value, field, "x" * size)
    with pytest.raises(AppError, match="некорректные данные") as caught:
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    assert isinstance(caught.value.__cause__, ValueError)
    repository.get_by_yandex_id.assert_not_awaited()
    repository.create.assert_not_awaited()
    repository.update.assert_not_awaited()


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
async def test_oversized_encrypted_tokens_rejected_before_write(oauth, field: str) -> None:
    service, client, repository, _ = oauth
    setattr(client.authenticate.return_value, field, "x" * 400)
    with pytest.raises(AppError, match="некорректные данные"):
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    repository.get_by_yandex_id.assert_not_awaited()


async def test_expiry_overflow_rejected_before_write(oauth) -> None:
    service, client, repository, _ = oauth
    client.authenticate.return_value.expires_in = 10**100
    with pytest.raises(AppError, match="некорректные данные") as caught:
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    assert isinstance(caught.value.__cause__, OverflowError)
    repository.get_by_yandex_id.assert_not_awaited()


@pytest.mark.parametrize("error", [ValueError("cipher failure"), TypeError("cipher failure")])
async def test_encryption_failure_rejected_before_write(oauth, error: Exception) -> None:
    _, client, repository, _ = oauth
    encryption = Mock(spec=EncryptionService)
    encryption.encrypt.side_effect = error
    with pytest.raises(AppError, match="некорректные данные") as caught:
        await YandexOauthService(client, encryption, repository).authenticate(
            data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4())
        )
    assert caught.value.__cause__ is error
    repository.get_by_yandex_id.assert_not_awaited()


async def test_oversized_phone_rejected_before_write(oauth) -> None:
    service, client, repository, _ = oauth
    client.get_user_info.return_value.default_phone.number = "x" * 32
    with pytest.raises(AppError, match="некорректные данные"):
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
    repository.get_by_yandex_id.assert_not_awaited()
    repository.create.assert_not_awaited()
    repository.update.assert_not_awaited()
