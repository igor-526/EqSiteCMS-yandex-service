from uuid import UUID

from sqlalchemy import ColumnElement, Table, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from core.entities import YandexUser
from core.exceptions import RepositoryError
from models import yandex_user

from .abstract_repository import AbstractRepository


class YandexUserRepository(AbstractRepository[YandexUser]):
    table: Table = yandex_user
    entity = YandexUser

    def _filter_conditions(self, *, equestrian_id: UUID, search: str | None) -> list[ColumnElement[bool]]:
        conditions = [self.table.c.equestrian_id == equestrian_id]
        if search is not None:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    self.table.c.yandex_login.ilike(pattern),
                    self.table.c.display_name.ilike(pattern),
                    self.table.c.email.ilike(pattern),
                )
            )
        return conditions

    async def count_filtered(self, *, equestrian_id: UUID, search: str | None = None) -> int:
        """Count matching accounts without pagination."""
        stmt = (
            select(func.count())
            .select_from(self.table)
            .where(*self._filter_conditions(equestrian_id=equestrian_id, search=search))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_filtered(
        self, *, equestrian_id: UUID, search: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[YandexUser]:
        stmt = select(self.table).where(*self._filter_conditions(equestrian_id=equestrian_id, search=search))

        stmt = stmt.order_by(self.table.c.created_at.desc()).limit(limit).offset(offset)
        rows = await self.session.execute(stmt)
        return [self.entity.model_validate(dict(row)) for row in rows.mappings().all()]

    async def get_by_yandex_id(self, *, equestrian_id: UUID, yandex_id: str) -> YandexUser | None:
        try:
            stmt = select(self.table).where(
                self.table.c.equestrian_id == equestrian_id,
                self.table.c.yandex_id == yandex_id,
            )
            row = await self.session.execute(stmt)
            mapping = row.mappings().first()
            if mapping is None:
                return None
            return self.entity.model_validate(dict(mapping))
        except SQLAlchemyError as ex:
            raise RepositoryError("Failed to get Yandex account") from ex

    async def create(self, entity: YandexUser) -> YandexUser:
        try:
            return await super().create(entity)
        except SQLAlchemyError as ex:
            raise RepositoryError("Failed to create Yandex account") from ex

    async def update(self, entity: YandexUser) -> YandexUser:
        try:
            return await super().update(entity)
        except SQLAlchemyError as ex:
            raise RepositoryError("Failed to update Yandex account") from ex
