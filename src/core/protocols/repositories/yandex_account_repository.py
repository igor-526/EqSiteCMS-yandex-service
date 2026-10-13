from typing import Protocol
from uuid import UUID

from core.entities import YandexUser

from .base_repository import BaseRepositoryProtocol


class YandexUserRepositoryProtocol(BaseRepositoryProtocol[YandexUser], Protocol):
    async def get_filtered(
        self, *, equestrian_id: UUID, search: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[YandexUser]: ...

    async def get_by_yandex_id(self, *, equestrian_id: UUID, yandex_id: str) -> YandexUser | None: ...
