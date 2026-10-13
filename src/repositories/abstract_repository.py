from abc import ABC
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities import Entity, TimestampMixin


class AbstractRepository[E: Entity](ABC):
    table: Table
    entity: type[E]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all(self, *, limit: int | None = None, offset: int | None = None) -> list[E]:
        stmt = select(self.table)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        rows = await self.session.execute(stmt)
        return [self.entity.model_validate(dict(row)) for row in rows.mappings().all()]

    async def get_by_id(self, id: UUID) -> E | None:
        stmt = select(self.table).where(self.table.c.id == id)
        row = await self.session.execute(stmt)
        mapping = row.mappings().first()
        if mapping is None:
            return None
        return self.entity.model_validate(dict(mapping))

    async def get_by_ids(self, ids: Sequence[UUID]) -> dict[UUID, E]:
        if not ids:
            return {}
        stmt = select(self.table).where(self.table.c.id.in_(ids))
        rows = await self.session.execute(stmt)
        return {row["id"]: self.entity.model_validate(dict(row)) for row in rows.mappings().all()}

    async def update(self, entity: E) -> E:
        data = entity.model_dump()
        if "updated_at" in self.table.c:
            now = datetime.now(UTC)
            data["updated_at"] = now
            if isinstance(entity, TimestampMixin):
                entity.updated_at = now
        stmt = update(self.table).where(self.table.c.id == entity.id).values(**data)
        await self.session.execute(stmt)
        await self.session.flush()
        return entity

    async def create(self, entity: E) -> E:
        stmt = insert(self.table).values(**entity.model_dump())
        await self.session.execute(stmt)
        await self.session.flush()
        return entity

    async def bulk_create(self, entities: list[E]) -> list[E]:
        if not entities:
            return []
        values = [e.model_dump() for e in entities]
        stmt = insert(self.table).returning(self.table)
        rows = await self.session.execute(stmt, values)
        await self.session.flush()
        return [self.entity.model_validate(dict(row)) for row in rows.mappings().all()]

    async def delete(self, id: UUID) -> None:
        stmt = delete(self.table).where(self.table.c.id == id)
        await self.session.execute(stmt)

    async def bulk_delete(self, ids: Sequence[UUID]) -> None:
        stmt = delete(self.table).where(self.table.c.id.in_(ids))
        await self.session.execute(stmt)

    async def get_by_slug(self, slug: str) -> E | None:
        """Получить сущность по slug. Работает только для таблиц с колонкой slug."""
        if "slug" not in self.table.c:
            raise AttributeError(f"Table {self.table.name} does not have a 'slug' column")
        stmt = select(self.table).where(self.table.c.slug == slug)
        row = await self.session.execute(stmt)
        mapping = row.mappings().first()
        if mapping is None:
            return None
        return self.entity.model_validate(dict(mapping))

    async def get_by_slug_or_id(self, slug_or_id: str | UUID) -> E | None:
        """Получить по slug или UUID. Работает только для таблиц с колонкой slug."""
        if isinstance(slug_or_id, UUID):
            return await self.get_by_id(slug_or_id)
        return await self.get_by_slug(slug_or_id)

    async def find_by_slug(self, slug: str) -> E | None:
        """Проверить существование slug. Работает только для таблиц с колонкой slug."""
        return await self.get_by_slug(slug)

    async def find_by_name(self, name: str) -> E | None:
        """Проверить существование name. Работает только для таблиц с колонкой name."""
        if "name" not in self.table.c:
            raise AttributeError(f"Table {self.table.name} does not have a 'name' column")
        stmt = select(self.table).where(self.table.c.name == name)
        row = await self.session.execute(stmt)
        mapping = row.mappings().first()
        if mapping is None:
            return None
        return self.entity.model_validate(dict(mapping))
