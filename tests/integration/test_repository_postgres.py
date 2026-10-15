from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.entities import YandexUser
from repositories.yandex_user_repository import YandexUserRepository

pytestmark = pytest.mark.infrastructure


def account(**changes: object) -> YandexUser:
    data = dict(
        equestrian_id=uuid4(),
        yandex_id="same-yandex-id",
        yandex_login="Alpha",
        display_name="First",
        email="alpha@example.test",
        enc_access_token="encrypted-access",
        enc_refresh_token="encrypted-refresh",
        token_expires_at=datetime.now(UTC),
    )
    data.update(changes)
    return YandexUser.model_validate(data)


async def test_crud_bulk_uuid_timestamps_and_commit(pg_engine: AsyncEngine, pg_session: AsyncSession) -> None:
    repository = YandexUserRepository(pg_session)
    first = account()
    assert await repository.create(first) is first
    loaded = await repository.get_by_id(first.id)
    assert loaded == first
    assert loaded is not None and loaded.created_at.tzinfo is not None
    assert loaded.token_expires_at.tzinfo is not None
    first.display_name = "Updated"
    before = datetime.now(UTC)
    assert await repository.update(first) is first
    assert first.updated_at is not None and before <= first.updated_at <= datetime.now(UTC)
    assert await repository.get_by_id(first.id) == first
    others = [account(), account()]
    assert await repository.bulk_create(others) == others
    assert await repository.bulk_create([]) == []
    ids = [first.id, *(item.id for item in others)]
    assert await repository.get_by_ids(ids) == {item.id: item for item in [first, *others]}
    assert await repository.get_by_ids([]) == {}
    assert len(await repository.get_all(limit=1, offset=1)) == 1
    assert await repository.get_all(limit=1, offset=100) == []
    await pg_session.commit()
    async with AsyncSession(pg_engine) as observer:
        assert await YandexUserRepository(observer).get_by_id(first.id) == first
    await repository.delete(first.id)
    await repository.bulk_delete([item.id for item in others])
    await repository.bulk_delete([])
    await pg_session.commit()
    assert await repository.get_all() == []
    assert await repository.get_by_id(first.id) is None


async def test_rollback_discards_writes(pg_engine: AsyncEngine, pg_session: AsyncSession) -> None:
    repository = YandexUserRepository(pg_session)
    user = account()
    await repository.create(user)
    await pg_session.rollback()
    async with AsyncSession(pg_engine) as observer:
        assert await YandexUserRepository(observer).get_by_id(user.id) is None
    await repository.create(user)
    await pg_session.commit()
    user.display_name = "Rolled back"
    await repository.update(user)
    await repository.delete(user.id)
    await pg_session.rollback()
    loaded = await repository.get_by_id(user.id)
    assert loaded is not None and loaded.display_name == "First" and loaded.updated_at is None


async def test_tenant_search_count_order_and_postgres_wildcards(pg_session: AsyncSession) -> None:
    repository = YandexUserRepository(pg_session)
    tenant = uuid4()
    now = datetime.now(UTC)
    users = [
        account(equestrian_id=tenant, yandex_id="1", created_at=now - timedelta(days=2)),
        account(
            equestrian_id=tenant,
            yandex_id="2",
            yandex_login="beta",
            display_name="Конь",
            email=None,
            created_at=now - timedelta(days=1),
        ),
        account(
            equestrian_id=tenant,
            yandex_id="3",
            yandex_login="gamma",
            display_name="Third",
            email="MATCH@example.test",
            created_at=now,
        ),
    ]
    foreign = account(yandex_id="1", created_at=now + timedelta(days=1))
    await repository.bulk_create([*users, foreign])
    assert await repository.get_by_yandex_id(equestrian_id=tenant, yandex_id="1") == users[0]
    assert await repository.get_by_yandex_id(equestrian_id=foreign.equestrian_id, yandex_id="1") == foreign
    assert await repository.get_by_yandex_id(equestrian_id=uuid4(), yandex_id="1") is None
    for search, expected in [
        (None, users[::-1]),
        ("", users[::-1]),
        ("ALPHA", [users[0]]),
        ("конь", [users[1]]),
        ("match", [users[2]]),
        ("%", users[::-1]),
        ("_", users[::-1]),
        ("absent", []),
    ]:
        assert await repository.get_filtered(equestrian_id=tenant, search=search) == expected
        assert await repository.count_filtered(equestrian_id=tenant, search=search) == len(expected)
    assert await repository.get_filtered(equestrian_id=tenant, limit=1, offset=1) == [users[1]]
    assert await repository.get_filtered(equestrian_id=tenant, offset=100) == []
    assert await repository.count_filtered(equestrian_id=tenant) == 3
