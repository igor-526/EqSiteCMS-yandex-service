import logging
from uuid import UUID

from pydantic import ValidationError

from core.entities import YandexMetricaCounter
from core.exceptions import ClientError
from core.protocols.repositories import YandexMetricaCounterRepositoryProtocol, YandexUserRepositoryProtocol
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
    ) -> None:
        self.yandex_metrica_counter_repository = yandex_metrica_counter_repository
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
        counter = await self.yandex_metrica_counter_repository.get_by_equestrian(equestrian_id=equestrian_id)
        if counter is None:
            return YandexMetricaConnectedCounterOutDto(counter=None)
        return YandexMetricaConnectedCounterOutDto(counter=await self._counter_response(counter))

    async def set_counter(self, *, data: YandexMetricaSetCounterInDto) -> YandexMetricaSetCounterOutDto:
        try:
            existing = await self.yandex_metrica_counter_repository.get_by_equestrian(equestrian_id=data.equestrian_id)
            values = existing.model_dump() if existing is not None else {}
            counter = YandexMetricaCounter.model_validate(
                {
                    **values,
                    "equestrian_id": data.equestrian_id,
                    "yandex_user_id": data.yandex_account_id,
                    "counter_id": data.counter_id,
                }
            )
            response = await self._counter_response(counter)
            if existing is None:
                await self.yandex_metrica_counter_repository.create(counter)
            elif existing.counter_id != counter.counter_id or existing.yandex_user_id != counter.yandex_user_id:
                await self.yandex_metrica_counter_repository.update(counter)
        except ValidationError as ex:
            raise ClientError("Некорректные данные счётчика") from ex
        logger.info("Set Yandex Metrica counter %s for equestrian %s", counter.counter_id, counter.equestrian_id)
        return response

    async def delete_counter(self, *, counter_id: UUID) -> None:
        await self.yandex_metrica_counter_repository.delete(id=counter_id)
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
