from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.entities import YandexUser
from core.exceptions import AppError, ClientError, RepositoryError, YandexClientException
from core.schemas.api import YandexAuthCodeInDto
from core.schemas.clients import YandexClientAuthResponse, YandexClientUserResponse, YandexClientUserResponsePhone
from core.services import EnctryptionService, YandexOauthService


class FakeYandexClient:
    def get_init_oauth_link(self, *, state: str | None = None) -> str:
        return f"https://example.test/oauth?state={state}"

    async def authenticate(self, *, code: str) -> YandexClientAuthResponse:
        return YandexClientAuthResponse(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_in=3600,
        )

    async def get_user_info(self, *, access_token: str) -> YandexClientUserResponse:
        return YandexClientUserResponse(
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


class FakeYandexUserRepository:
    def __init__(self, existing_user: YandexUser | None = None) -> None:
        self.existing_user = existing_user
        self.created: YandexUser | None = None
        self.updated: YandexUser | None = None

    async def get_by_yandex_id(self, *, equestrian_id, yandex_id):
        return self.existing_user

    async def create(self, entity: YandexUser) -> YandexUser:
        self.created = entity
        return entity

    async def update(self, entity: YandexUser) -> YandexUser:
        self.updated = entity
        return entity


class FailingAuthClient(FakeYandexClient):
    async def authenticate(self, *, code: str) -> YandexClientAuthResponse:
        raise YandexClientException(status=400, error="invalid_grant")


class FailingUserInfoClient(FakeYandexClient):
    async def get_user_info(self, *, access_token: str) -> YandexClientUserResponse:
        raise YandexClientException(status=401, error="unauthorized")


class FailingYandexUserRepository(FakeYandexUserRepository):
    async def get_by_yandex_id(self, *, equestrian_id, yandex_id):
        raise RepositoryError("database unavailable")


def make_service(repository: FakeYandexUserRepository) -> tuple[YandexOauthService, EnctryptionService]:
    encryption_service = EnctryptionService(secret_key="test-secret")
    service = YandexOauthService(
        client=FakeYandexClient(),  # type: ignore[arg-type]
        encryption_service=encryption_service,
        yandex_user_repository=repository,  # type: ignore[arg-type]
    )
    return service, encryption_service


def make_service_with_client(
    client: FakeYandexClient,
    repository: FakeYandexUserRepository,
) -> YandexOauthService:
    return YandexOauthService(
        client=client,  # type: ignore[arg-type]
        encryption_service=EnctryptionService(secret_key="test-secret"),
        yandex_user_repository=repository,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_authenticate_creates_new_yandex_user() -> None:
    repository = FakeYandexUserRepository()
    service, encryption_service = make_service(repository)
    equestrian_id = uuid4()
    before_authentication = datetime.now(UTC)

    result = await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=equestrian_id))

    assert repository.created is not None
    assert repository.updated is None
    assert repository.created.equestrian_id == equestrian_id
    assert result.id == repository.created.id
    assert result.yandex_id == "yandex-user-id"
    assert result.yandex_login == "new-login"
    assert encryption_service.decrypt(data=repository.created.enc_access_token) == "new-access-token"
    assert encryption_service.decrypt(data=repository.created.enc_refresh_token) == "new-refresh-token"
    assert repository.created.token_expires_at >= before_authentication


@pytest.mark.asyncio
async def test_authenticate_updates_existing_yandex_user() -> None:
    existing_id = uuid4()
    existing_user = YandexUser(
        id=existing_id,
        equestrian_id=uuid4(),
        yandex_id="yandex-user-id",
        yandex_login="old-login",
        display_name="Old name",
        email="old@example.com",
        enc_access_token="old-access-token",
        enc_refresh_token="old-refresh-token",
        token_expires_at=datetime.now(UTC),
    )
    repository = FakeYandexUserRepository(existing_user=existing_user)
    service, encryption_service = make_service(repository)

    result = await service.authenticate(
        data=YandexAuthCodeInDto(code="code", equestrian_id=existing_user.equestrian_id)
    )

    assert repository.created is None
    assert repository.updated is existing_user
    assert result.id == existing_id
    assert result.yandex_login == "new-login"
    assert result.display_name == "New name"
    assert result.email == "new@example.com"
    assert result.yandex_phone == "+79990000000"
    assert encryption_service.decrypt(data=existing_user.enc_access_token) == "new-access-token"
    assert encryption_service.decrypt(data=existing_user.enc_refresh_token) == "new-refresh-token"


@pytest.mark.asyncio
async def test_authenticate_converts_token_exchange_error_to_client_error() -> None:
    service = make_service_with_client(FailingAuthClient(), FakeYandexUserRepository())

    with pytest.raises(ClientError, match="Не удалось выполнить аутентификацию"):
        await service.authenticate(data=YandexAuthCodeInDto(code="invalid", equestrian_id=uuid4()))


@pytest.mark.asyncio
async def test_authenticate_converts_user_info_error_to_client_error() -> None:
    service = make_service_with_client(FailingUserInfoClient(), FakeYandexUserRepository())

    with pytest.raises(ClientError, match="Не удалось получить данные"):
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))


@pytest.mark.asyncio
async def test_authenticate_converts_repository_error_to_app_error() -> None:
    service = make_service_with_client(FakeYandexClient(), FailingYandexUserRepository())

    with pytest.raises(AppError, match="Не удалось сохранить аккаунт"):
        await service.authenticate(data=YandexAuthCodeInDto(code="code", equestrian_id=uuid4()))
