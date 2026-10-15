from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities import YandexMetricaCounter
from models import yandex_metrica_counters
from repositories.yandex_metrica_counter_repository import YandexMetricaCounterRepository


@pytest.mark.parametrize("found", [False, True])
async def test_get_by_equestrian_mapping_and_filter(found: bool) -> None:
    session = AsyncMock(spec=AsyncSession)
    counter = YandexMetricaCounter(equestrian_id=uuid4(), yandex_user_id=uuid4(), counter_id="42")
    result = MagicMock()
    result.mappings.return_value.first.return_value = counter.model_dump() if found else None
    session.execute.return_value = result
    repository = YandexMetricaCounterRepository(session)

    assert await repository.get_by_equestrian(equestrian_id=counter.equestrian_id) == (counter if found else None)

    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "WHERE yandex_metrica_counters.equestrian_id =" in str(stmt)
    assert list(stmt.params.values()) == [counter.equestrian_id]
    session.commit.assert_not_awaited()


async def test_get_by_equestrian_database_error_propagates() -> None:
    session = AsyncMock(spec=AsyncSession)
    error = SQLAlchemyError("test database failure")
    session.execute.side_effect = error
    repository = YandexMetricaCounterRepository(session)

    with pytest.raises(SQLAlchemyError) as caught:
        await repository.get_by_equestrian(equestrian_id=uuid4())

    assert caught.value is error


def test_equestrian_id_has_unique_constraint() -> None:
    assert any(
        isinstance(constraint, UniqueConstraint) and list(constraint.columns.keys()) == ["equestrian_id"]
        for constraint in yandex_metrica_counters.constraints
    )
