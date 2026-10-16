import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.entities import YandexUser
from core.exceptions import AppError, ClientError, RepositoryError, YandexClientException
from core.protocols.clients import YandexOAuthClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexAccountOutDto, YandexAuthCodeInDto

from .encryption_service import EncryptionService

logger = logging.getLogger("Yandex Oauth Service")


class YandexOauthService:
    def __init__(
        self,
        client: YandexOAuthClientProtocol,
        encryption_service: EncryptionService,
        yandex_user_repository: YandexUserRepositoryProtocol,
    ) -> None:
        self._client = client
        self._encryption_service = encryption_service
        self._yandex_user_repository = yandex_user_repository

    def get_token_expires_at(self, *, seconds: int) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=seconds)

    def get_auth_link(self, *, equestrian_id: UUID) -> str:
        auth_link = self._client.get_init_oauth_link(state=str(equestrian_id))
        return auth_link

    async def authenticate(self, *, data: YandexAuthCodeInDto) -> YandexAccountOutDto:
        try:
            tokens = await self._client.authenticate(code=data.code)
        except YandexClientException as ex:
            logger.warning("Yandex OAuth code exchange failed")
            raise ClientError("Не удалось выполнить аутентификацию в Яндекс") from ex

        try:
            user_info = await self._client.get_user_info(access_token=tokens.access_token)
        except YandexClientException as ex:
            logger.warning("Failed to get Yandex user info")
            raise ClientError("Не удалось получить данные аккаунта Яндекс") from ex

        try:
            authenticated_user = YandexUser(
                equestrian_id=data.equestrian_id,
                yandex_id=user_info.id,
                yandex_login=user_info.login,
                display_name=user_info.display_name,
                email=user_info.default_email,
                yandex_avatar_id=user_info.default_avatar_id,
                yandex_phone=user_info.default_phone.number if user_info.default_phone is not None else None,
                enc_access_token=self._encryption_service.encrypt(data=tokens.access_token),
                enc_refresh_token=self._encryption_service.encrypt(data=tokens.refresh_token),
                token_expires_at=self.get_token_expires_at(seconds=tokens.expires_in),
            )
        except (OverflowError, TypeError, ValueError) as ex:
            logger.error("Failed to prepare Yandex account data")
            raise AppError("Яндекс вернул некорректные данные аккаунта") from ex

        try:
            yandex_user = await self._yandex_user_repository.get_by_yandex_id(
                equestrian_id=data.equestrian_id,
                yandex_id=user_info.id,
            )

            if yandex_user is None:
                yandex_user = await self._yandex_user_repository.create(authenticated_user)
                logger.info(
                    "Added Yandex account %s for equestrian %s",
                    authenticated_user.yandex_id,
                    data.equestrian_id,
                )
            else:
                yandex_user.yandex_login = authenticated_user.yandex_login
                yandex_user.display_name = authenticated_user.display_name
                yandex_user.email = authenticated_user.email
                yandex_user.yandex_avatar_id = authenticated_user.yandex_avatar_id
                yandex_user.yandex_phone = authenticated_user.yandex_phone
                yandex_user.enc_access_token = authenticated_user.enc_access_token
                yandex_user.enc_refresh_token = authenticated_user.enc_refresh_token
                yandex_user.token_expires_at = authenticated_user.token_expires_at
                yandex_user = await self._yandex_user_repository.update(yandex_user)
                logger.info(
                    "Updated Yandex account %s for equestrian %s",
                    authenticated_user.yandex_id,
                    data.equestrian_id,
                )
        except RepositoryError as ex:
            logger.error(
                "Failed to save Yandex account %s for equestrian %s",
                user_info.id,
                data.equestrian_id,
            )
            raise AppError("Не удалось сохранить аккаунт Яндекс") from ex

        return YandexAccountOutDto.model_validate(yandex_user)
