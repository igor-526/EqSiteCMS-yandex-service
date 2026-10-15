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
