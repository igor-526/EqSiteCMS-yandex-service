import logging
from uuid import UUID

from pydantic import ValidationError

from core.entities import YandexMetricaCounter
from core.exceptions import ClientError
from core.protocols.repositories import YandexMetricaCounterRepositoryProtocol, YandexUserRepositoryProtocol
from core.protocols.repositories.metrica_lifecycle_repository import MetricaLifecycleRepositoryProtocol
from core.schemas.api import (
    YandexAccountOutDto,
    YandexMetricaBindingItemOutDto,
    YandexMetricaBindingListOutDto,
    YandexMetricaConnectedCounterOutDto,
    YandexMetricaSetCounterInDto,
    YandexMetricaSetCounterOutDto,
)

logger = logging.getLogger("Yandex Metrica Counter Service")


class YandexMetricaCounterService:
    def __init__(
        self,
        yandex_metrica_counter_repository: YandexMetricaCounterRepositoryProtocol,
        yandex_user_repository: YandexUserRepositoryProtocol,
        metrica_lifecycle_repository: MetricaLifecycleRepositoryProtocol,
    ) -> None:
        self.yandex_metrica_counter_repository = yandex_metrica_counter_repository
        self._lifecycle = metrica_lifecycle_repository
        self._yandex_user_repository = yandex_user_repository

    async def list_bindings(self, *, limit: int = 100, offset: int = 0) -> YandexMetricaBindingListOutDto:
        if not 1 <= limit <= 500 or offset < 0:
            raise ClientError("Некорректные параметры пагинации")
        counters = await self.yandex_metrica_counter_repository.list_paginated(limit=limit, offset=offset)
        total = await self.yandex_metrica_counter_repository.count()
        return YandexMetricaBindingListOutDto(
            total=total,
            items=[
                YandexMetricaBindingItemOutDto(equestrian_id=counter.equestrian_id, counter_id=counter.counter_id)
                for counter in counters
            ],
        )

    async def get_counter(self, *, equestrian_id: UUID) -> YandexMetricaConnectedCounterOutDto:
        snapshot = await self._lifecycle.get_binding_snapshot(equestrian_id=equestrian_id)
        return YandexMetricaConnectedCounterOutDto(
            counter=await self._counter_response(snapshot.counter) if snapshot.counter is not None else None,
            binding_generation=snapshot.lifecycle.binding_generation,
            cleanup_requested_seq=snapshot.lifecycle.cleanup_requested_seq,
            cleanup_completed_seq=snapshot.lifecycle.cleanup_completed_seq,
        )

    async def set_counter(self, *, data: YandexMetricaSetCounterInDto) -> YandexMetricaSetCounterOutDto:
        try:
            counter = YandexMetricaCounter.model_validate(
                {
                    "equestrian_id": data.equestrian_id,
                    "yandex_user_id": data.yandex_account_id,
                    "counter_id": data.counter_id,
                }
            )
            # Validate account before mutation; storage rechecks it under lock.
            response = await self._counter_response(counter)
            counter = await self._lifecycle.set_binding(counter=counter)
            response = response.model_copy(update={"id": counter.id})
        except ValidationError as ex:
            raise ClientError("Некорректные данные счётчика") from ex
        logger.info("Set Yandex Metrica counter %s for equestrian %s", counter.counter_id, counter.equestrian_id)
        return response

    async def delete_counter(self, *, counter_id: UUID) -> None:
        await self._lifecycle.delete_binding(counter_id=counter_id)
        logger.info("Deleted Yandex Metrica counter %s", counter_id)

    async def _counter_response(self, counter: YandexMetricaCounter) -> YandexMetricaSetCounterOutDto:
        account = await self._yandex_user_repository.get_by_id(id=counter.yandex_user_id)
        if account is None:
            raise ClientError("Аккаунт не найден")
        return YandexMetricaSetCounterOutDto(
            id=counter.id,
            equestrian_id=counter.equestrian_id,
            counter_id=counter.counter_id,
            yandex_account=YandexAccountOutDto.model_validate(account),
        )
