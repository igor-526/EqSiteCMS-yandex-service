import logging
from uuid import UUID

from core.exceptions import ClientError, YandexClientException
from core.protocols.clients import YaMetricaServiceClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexMetricaCounterResponseOutDto

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
    ) -> YandexMetricaCounterResponseOutDto:
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
            counters = await self._yandex_metrica_client.get_metrica_counters(
                access_token=yandex_account.enc_access_token, search=search, limit=limit, offset=offset
            )
        except YandexClientException as ex:
            raise ClientError("Не удалось получить счётчики Яндекс Метрики") from ex
        return YandexMetricaCounterResponseOutDto.model_validate(counters)
