import logging
from uuid import UUID

from core.exceptions import ClientError
from core.protocols.repositories import YandexUserRepositoryProtocol

from .encryption_service import EncryptionService

logger = logging.getLogger("Yandex Service Authoriaztion Service")


class YandexServiceAuthorizationService:
    def __init__(
        self,
        encryption_service: EncryptionService,
        yandex_user_repository: YandexUserRepositoryProtocol,
    ) -> None:
        self._encryption_service = encryption_service
        self._yandex_user_repository = yandex_user_repository

    async def get_token(self, *, account_id: UUID) -> str:
        yandex_account = await self._yandex_user_repository.get_by_id(id=account_id)
        if yandex_account is None:
            raise ClientError("Аккаунт не найден")
        try:
            decrypted = self._encryption_service.decrypt(data=yandex_account.enc_access_token)
            return decrypted
        except ValueError as ve:
            logger.error("Error while decrypting access token")
            raise ClientError("Ошибка расшифровки токена") from ve
        except Exception as ex:
            logger.error(f"Error: {ex}")
            raise ClientError(f"Ошибка: {ex}") from ex
