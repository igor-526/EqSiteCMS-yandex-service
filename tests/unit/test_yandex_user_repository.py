from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

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
