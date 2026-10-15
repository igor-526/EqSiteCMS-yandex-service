from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities import YandexUser
from core.exceptions import RepositoryError
from repositories.yandex_user_repository import YandexUserRepository


@pytest.mark.parametrize("search", [None, "", "Some.Login", "_%"])
@pytest.mark.parametrize("total", [0, 17])
async def test_count_filtered_uses_same_tenant_and_search_without_pagination(search: str | None, total: int) -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one.return_value = total
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    repository = YandexUserRepository(session=session)
    equestrian_id = uuid4()

    assert await repository.count_filtered(equestrian_id=equestrian_id, search=search) == total
    count_stmt = session.execute.call_args.args[0]
    await repository.get_filtered(equestrian_id=equestrian_id, search=search, limit=1, offset=100)
    page_stmt = session.execute.call_args.args[0]

    dialect = postgresql.dialect()
    count_sql = str(count_stmt.compile(dialect=dialect))
    page_sql = str(page_stmt.compile(dialect=dialect))
    assert count_sql.startswith("SELECT count(*)")
    assert "LIMIT" not in count_sql
    assert "OFFSET" not in count_sql
    assert "ORDER BY" not in count_sql
    assert "LIMIT" in page_sql
    assert "OFFSET" in page_sql
    count_where = count_stmt.whereclause.compile(dialect=dialect)
    page_where = page_stmt.whereclause.compile(dialect=dialect)
    assert str(count_where) == str(page_where)
    assert count_where.params == page_where.params
    assert equestrian_id in count_where.params.values()
    assert "equestrian_id =" in str(count_where)
    if search is not None:
        for column in ("yandex_login", "display_name", "email"):
            assert f"{column} ILIKE" in str(count_where)
        assert list(count_where.params.values()).count(f"%{search}%") == 3
    else:
        assert "ILIKE" not in str(count_where)
    result.scalar_one.assert_called_once_with()


def account() -> YandexUser:
    return YandexUser(
        equestrian_id=uuid4(),
        yandex_id="123",
        yandex_login="horse",
        display_name="Horse",
        enc_access_token="encrypted-access",
        enc_refresh_token="encrypted-refresh",
        token_expires_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("found", [False, True])
async def test_get_by_yandex_id_tenant_mapping(found: bool) -> None:
    session = AsyncMock(spec=AsyncSession)
    user = account()
    result = MagicMock()
    result.mappings.return_value.first.return_value = user.model_dump() if found else None
    session.execute.return_value = result
    repository = YandexUserRepository(session)
    assert await repository.get_by_yandex_id(equestrian_id=user.equestrian_id, yandex_id=user.yandex_id) == (
        user if found else None
    )
    stmt = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "equestrian_id =" in str(stmt) and "yandex_id =" in str(stmt)
    assert user.equestrian_id in stmt.params.values() and user.yandex_id in stmt.params.values()


async def test_filtered_mapping_descending_order_and_pagination() -> None:
    session = AsyncMock(spec=AsyncSession)
    user = account()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [user.model_dump()]
    session.execute.return_value = result
    repository = YandexUserRepository(session)
    assert await repository.get_filtered(equestrian_id=user.equestrian_id, search="Конь", limit=3, offset=4) == [user]
    stmt = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "ORDER BY yandex_user.created_at DESC" in str(stmt)
    assert 3 in stmt.params.values() and 4 in stmt.params.values()
    assert list(stmt.params.values()).count("%Конь%") == 3


@pytest.mark.parametrize(
    "method,stage",
    [
        ("get_by_yandex_id", "execute"),
        ("create", "execute"),
        ("create", "flush"),
        ("update", "execute"),
        ("update", "flush"),
    ],
)
async def test_wrapped_database_errors_preserve_cause(method: str, stage: str) -> None:
    session = AsyncMock(spec=AsyncSession)
    error = SQLAlchemyError("test database failure")
    getattr(session, stage).side_effect = error
    repository = YandexUserRepository(session)
    user = account()
    with pytest.raises(RepositoryError) as caught:
        if method == "get_by_yandex_id":
            await repository.get_by_yandex_id(equestrian_id=user.equestrian_id, yandex_id=user.yandex_id)
        else:
            await getattr(repository, method)(user)
    assert caught.value.__cause__ is error
    assert str(caught.value) == f"Failed to {'get' if method == 'get_by_yandex_id' else method} Yandex account"
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("method", ["get_all", "get_filtered", "count_filtered", "delete"])
async def test_unwrapped_database_errors_propagate(method: str) -> None:
    session = AsyncMock(spec=AsyncSession)
    error = SQLAlchemyError("test database failure")
    session.execute.side_effect = error
    repository = YandexUserRepository(session)
    with pytest.raises(SQLAlchemyError) as caught:
        if method in ("get_filtered", "count_filtered"):
            await getattr(repository, method)(equestrian_id=uuid4())
        elif method == "delete":
            await repository.delete(uuid4())
        else:
            await repository.get_all()
    assert caught.value is error
