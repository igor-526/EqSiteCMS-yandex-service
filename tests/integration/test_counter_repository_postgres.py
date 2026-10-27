from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities import YandexMetricaCounter
from repositories.yandex_metrica_counter_repository import YandexMetricaCounterRepository
from repositories.yandex_user_repository import YandexUserRepository
from tests.integration.test_repository_postgres import account

pytestmark = pytest.mark.infrastructure


async def test_counter_lookup_and_equestrian_uniqueness(pg_session: AsyncSession) -> None:
    user = account()
    await YandexUserRepository(pg_session).create(user)
    repository = YandexMetricaCounterRepository(pg_session)
    counter = YandexMetricaCounter(equestrian_id=user.equestrian_id, yandex_user_id=user.id, counter_id="42")
    other = YandexMetricaCounter(equestrian_id=uuid4(), yandex_user_id=user.id, counter_id="42")
    await repository.create(counter)
    await repository.create(other)

    assert await repository.get_by_equestrian(equestrian_id=counter.equestrian_id) == counter
    assert await repository.get_by_equestrian(equestrian_id=other.equestrian_id) == other
    assert await repository.get_by_equestrian(equestrian_id=uuid4()) is None

    duplicate = YandexMetricaCounter(equestrian_id=counter.equestrian_id, yandex_user_id=user.id, counter_id="43")
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await repository.create(duplicate)

    other.equestrian_id = counter.equestrian_id
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await repository.update(other)


async def test_binding_list_pagination_and_total(pg_session: AsyncSession) -> None:
    """IT-YB-01: stable UUID ordering and 100/100/50 pages on real PostgreSQL."""
    from uuid import UUID

    from sqlalchemy import event

    repository = YandexMetricaCounterRepository(pg_session)
    assert await repository.count() == 0
    assert await repository.list_paginated(limit=100, offset=0) == []
    user = account()
    await YandexUserRepository(pg_session).create(user)
    # Reverse insert order deliberately differs from the expected UUID order.
    counters = [
        YandexMetricaCounter(equestrian_id=UUID(int=i), yandex_user_id=user.id, counter_id=str(i))
        for i in range(250, 0, -1)
    ]
    await repository.bulk_create(counters)
    statements: list[str] = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = pg_session.bind
    assert engine is not None
    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    try:
        pages = []
        for offset in (0, 100, 200):
            before = len(statements)
            page = await repository.list_paginated(limit=100, offset=offset)
            assert await repository.count() == 250
            assert len(statements) - before == 2  # No per-binding account queries/N+1.
            pages.append(page)
        assert [len(page) for page in pages] == [100, 100, 50]
        flattened = [counter for page in pages for counter in page]
        assert flattened == sorted(counters, key=lambda counter: counter.equestrian_id)
        assert len({counter.equestrian_id for counter in flattened}) == 250
        assert await repository.list_paginated(limit=100, offset=250) == []
        assert await repository.list_paginated(limit=100, offset=1000) == []
        assert await repository.count() == 250
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe)
