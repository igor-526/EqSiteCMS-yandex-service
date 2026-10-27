from typing import Protocol
from uuid import UUID

from core.entities import YandexMetricaCounter

from .base_repository import BaseRepositoryProtocol


class YandexMetricaCounterRepositoryProtocol(BaseRepositoryProtocol[YandexMetricaCounter], Protocol):
    async def get_by_equestrian(self, *, equestrian_id: UUID) -> YandexMetricaCounter | None: ...

    """
    Получение счётчика конюшни
    """

    async def list_paginated(self, *, limit: int, offset: int) -> list[YandexMetricaCounter]: ...

    async def count(self) -> int: ...
