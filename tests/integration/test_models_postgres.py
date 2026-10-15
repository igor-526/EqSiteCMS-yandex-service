from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import RepositoryError
from models import yandex_metrica_counters, yandex_user
from repositories.yandex_user_repository import YandexUserRepository
from tests.integration.test_repository_postgres import account

pytestmark = pytest.mark.infrastructure


async def test_composite_unique_rejects_same_tenant_and_accepts_another(pg_session: AsyncSession) -> None:
    repository = YandexUserRepository(pg_session)
    user = account()
    await repository.create(user)
    with pytest.raises(RepositoryError) as caught:
        async with pg_session.begin_nested():
            await repository.create(account(equestrian_id=user.equestrian_id, yandex_id=user.yandex_id))
    assert isinstance(caught.value.__cause__, IntegrityError)
    other = account(yandex_id=user.yandex_id)
    await repository.create(other)
    assert await repository.get_by_id(user.id) == user
    assert await repository.get_by_id(other.id) == other


async def test_counter_foreign_key_and_cascade(pg_session: AsyncSession) -> None:
    repository = YandexUserRepository(pg_session)
    user = account()
    await repository.create(user)
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(insert(yandex_metrica_counters).values(yandex_user_id=uuid4(), counter_id="404"))
    row = (
        (
            await pg_session.execute(
                insert(yandex_metrica_counters)
                .values(yandex_user_id=user.id, counter_id="42")
                .returning(yandex_metrica_counters)
            )
        )
        .mappings()
        .one()
    )
    assert isinstance(row["id"], UUID)
    assert row["created_at"].tzinfo is not None
    assert row["updated_at"] is None
    assert row["yandex_user_id"] == user.id
    await repository.delete(user.id)
    assert (await pg_session.execute(select(func.count()).select_from(yandex_metrica_counters))).scalar_one() == 0


async def test_user_server_defaults_uuid_timestamp_and_optional_columns(pg_session: AsyncSession) -> None:
    row = (
        (
            await pg_session.execute(
                insert(yandex_user)
                .values(
                    yandex_id="default",
                    yandex_login="login",
                    display_name="Name",
                    enc_access_token="encrypted-access",
                    enc_refresh_token="encrypted-refresh",
                )
                .returning(yandex_user)
            )
        )
        .mappings()
        .one()
    )
    assert isinstance(row["id"], UUID) and isinstance(row["equestrian_id"], UUID)
    assert row["created_at"].tzinfo is not None and row["token_expires_at"].tzinfo is not None
    for column in ("updated_at", "email", "yandex_avatar_id", "yandex_phone"):
        assert row[column] is None
