from uuid import UUID

from sqlalchemy import Table, select

from core.entities import YandexMetricaCounter
from models import yandex_metrica_counters

from .abstract_repository import AbstractRepository


class YandexMetricaCounterRepository(AbstractRepository[YandexMetricaCounter]):
    table: Table = yandex_metrica_counters
    entity = YandexMetricaCounter

    async def get_by_equestrian(self, *, equestrian_id: UUID) -> YandexMetricaCounter | None:
        stmt = select(self.table).where(self.table.c.equestrian_id == equestrian_id)
        row = await self.session.execute(stmt)
        mapping = row.mappings().first()
        if mapping is None:
            return None
        return self.entity.model_validate(dict(mapping))
