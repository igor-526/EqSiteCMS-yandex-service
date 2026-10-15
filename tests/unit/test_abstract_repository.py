from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from core.entities import Entity, TimestampMixin
from repositories.abstract_repository import AbstractRepository


class Item(Entity):
    slug: str = "a"
    name: str = "A"


class TimedItem(Item, TimestampMixin):
    pass


class ItemRepository(AbstractRepository[Item]):
    entity = Item
    table = Table("item", MetaData(), Column("id", postgresql.UUID), Column("slug", String), Column("name", String))


@pytest.fixture
def repository() -> ItemRepository:
    return ItemRepository(AsyncMock(spec=AsyncSession))


def rows(repository: ItemRepository, items: list[Item]) -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = [item.model_dump() for item in items]
    result.mappings.return_value.first.return_value = items[0].model_dump() if items else None
    repository.session.execute.return_value = result  # type: ignore[attr-defined]


def statement(repository: ItemRepository) -> tuple[str, dict]:
    stmt = repository.session.execute.call_args.args[0]  # type: ignore[attr-defined]
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


@pytest.mark.parametrize("limit,offset", [(None, None), (0, 0), (2, 3)])
async def test_get_all_maps_rows_and_optional_pagination(
    repository: ItemRepository, limit: int | None, offset: int | None
) -> None:
    item = Item()
    rows(repository, [item])
    assert await repository.get_all(limit=limit, offset=offset) == [item]
    sql, params = statement(repository)
    assert ("LIMIT" in sql) == (limit is not None)
    assert ("OFFSET" in sql) == (offset is not None)
    if limit is not None:
        assert limit in params.values()
    if offset is not None:
        assert offset in params.values()


@pytest.mark.parametrize("found", [False, True])
async def test_get_by_id_maps_optional_row(repository: ItemRepository, found: bool) -> None:
    item = Item()
    rows(repository, [item] if found else [])
    assert await repository.get_by_id(item.id) == (item if found else None)
    sql, params = statement(repository)
    assert "item.id =" in sql
    assert item.id in params.values()


async def test_get_by_ids_short_circuits_and_keys_by_uuid(repository: ItemRepository) -> None:
    assert await repository.get_by_ids([]) == {}
    repository.session.execute.assert_not_awaited()  # type: ignore[attr-defined]
    items = [Item(), Item(slug="b")]
    rows(repository, items)
    assert await repository.get_by_ids([item.id for item in items]) == {item.id: item for item in items}
    sql, params = statement(repository)
    assert "item.id IN" in sql
    assert [item.id for item in items] in params.values()


@pytest.mark.parametrize("method", ["create", "update"])
async def test_write_flushes_and_preserves_identity(repository: ItemRepository, method: str) -> None:
    item = Item()
    assert await getattr(repository, method)(item) is item
    sql, params = statement(repository)
    assert sql.startswith("INSERT" if method == "create" else "UPDATE")
    assert item.id in params.values()
    assert item.slug in params.values()
    if method == "update":
        assert "WHERE item.id =" in sql
    repository.session.flush.assert_awaited_once_with()  # type: ignore[attr-defined]
    repository.session.commit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.parametrize("timestamp_mixin", [False, True])
async def test_update_timestamp_column_with_and_without_mixin(timestamp_mixin: bool) -> None:
    repository = ItemRepository(AsyncMock(spec=AsyncSession))
    repository.table = Table(
        "timed",
        MetaData(),
        Column("id", postgresql.UUID),
        Column("slug", String),
        Column("name", String),
        Column("created_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True)),
    )
    item = TimedItem() if timestamp_mixin else Item()
    before = datetime.now(UTC)
    assert await repository.update(item) is item
    _, params = statement(repository)
    assert before <= params["updated_at"] <= datetime.now(UTC)
    if isinstance(item, TimedItem):
        assert item.updated_at == params["updated_at"]


async def test_bulk_create_empty_and_returning_mapping(repository: ItemRepository) -> None:
    assert await repository.bulk_create([]) == []
    repository.session.execute.assert_not_awaited()  # type: ignore[attr-defined]
    repository.session.flush.assert_not_awaited()  # type: ignore[attr-defined]
    items = [Item(), Item(slug="b")]
    rows(repository, items)
    assert await repository.bulk_create(items) == items
    sql, _ = statement(repository)
    assert "INSERT INTO item" in sql and "RETURNING item.id" in sql
    passed_values = repository.session.execute.call_args.args[1]  # type: ignore[attr-defined]
    assert passed_values == [item.model_dump() for item in items]
    repository.session.flush.assert_awaited_once_with()  # type: ignore[attr-defined]


@pytest.mark.parametrize("bulk,empty", [(False, False), (True, False), (True, True)])
async def test_delete_predicates_and_no_flush(repository: ItemRepository, bulk: bool, empty: bool) -> None:
    ids = [] if empty else [uuid4()]
    if bulk:
        await repository.bulk_delete(ids)
    else:
        await repository.delete(ids[0])
    sql, params = statement(repository)
    assert sql.startswith("DELETE FROM item WHERE item.id")
    assert (" IN " in sql) == bulk
    assert (ids if bulk else ids[0]) in params.values()
    repository.session.flush.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "method,value,column",
    [
        ("get_by_slug", "a", "slug"),
        ("find_by_slug", "a", "slug"),
        ("find_by_name", "A", "name"),
        ("get_by_slug_or_id", "a", "slug"),
    ],
)
@pytest.mark.parametrize("found", [False, True])
async def test_helpers_map_optional_rows(
    repository: ItemRepository, method: str, value: str, column: str, found: bool
) -> None:
    item = Item()
    rows(repository, [item] if found else [])
    assert await getattr(repository, method)(value) == (item if found else None)
    sql, params = statement(repository)
    assert f"item.{column} =" in sql
    assert value in params.values()


async def test_uuid_helper_selects_id(repository: ItemRepository) -> None:
    item = Item()
    rows(repository, [item])
    assert await repository.get_by_slug_or_id(item.id) == item
    sql, params = statement(repository)
    assert "item.id =" in sql
    assert item.id in params.values()


@pytest.mark.parametrize(
    "method,column",
    [("get_by_slug", "slug"), ("find_by_slug", "slug"), ("get_by_slug_or_id", "slug"), ("find_by_name", "name")],
)
async def test_helper_guards_missing_columns(repository: ItemRepository, method: str, column: str) -> None:
    repository.table = Table("bare", MetaData(), Column("id", postgresql.UUID))
    with pytest.raises(AttributeError, match=f"bare does not have a '{column}' column"):
        await getattr(repository, method)("missing")
    repository.session.execute.assert_not_awaited()  # type: ignore[attr-defined]
