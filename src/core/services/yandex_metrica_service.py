import logging
from typing import Any
from uuid import UUID

from core.exceptions import ClientError
from core.protocols.clients import YaMetricaServiceClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol

from .encryption_service import EncryptionService

logger = logging.getLogger("Yandex Metrica Service")


class YandexMetricaService:
    def __init__(
        self,
        encryption_service: EncryptionService,
        yandex_user_repository: YandexUserRepositoryProtocol,
        yandex_metrica_client: YaMetricaServiceClientProtocol,
    ) -> None:
        self._encryption_service = encryption_service
        self._yandex_user_repository = yandex_user_repository
        self._yandex_metrica_client = yandex_metrica_client

    async def get_counters(
        self, *, account_id: UUID, search: str | None = None, limit: int = 20, offset: int = 0
    ) -> Any:
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
        if offset < 0:
            offset = 0
        yandex_account = await self._yandex_user_repository.get_by_id(id=account_id)
        if yandex_account is None:
            raise ClientError("Аккаунт не найден")
        try:
            access_token = self._encryption_service.decrypt(data=yandex_account.enc_access_token)
        except ValueError as ve:
            logger.error("Error while decrypting access token")
            raise ClientError("Ошибка расшифровки токена") from ve
        except Exception as ex:
            logger.error(f"Error: {ex}")
            raise ClientError(f"Ошибка: {ex}") from ex
        counters = await self._yandex_metrica_client.get_metrica_counters(access_token=access_token, search=search)
        return counters
