from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.entities.base import Entity


class BaseRepositoryProtocol[E: Entity](Protocol):
    async def get_all(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[E]: ...

    async def get_by_id(self, id: UUID) -> E | None: ...

    async def get_by_ids(self, ids: Sequence[UUID]) -> dict[UUID, E]: ...

    async def update(self, entity: E) -> E: ...

    async def create(self, entity: E) -> E: ...

    async def bulk_create(self, entities: list[E]) -> list[E]: ...

    async def delete(self, id: UUID) -> None: ...

    async def bulk_delete(self, ids: Sequence[UUID]) -> None: ...
