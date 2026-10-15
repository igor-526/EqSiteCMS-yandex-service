from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from utils import database


@pytest.mark.parametrize("null_pool", [True, False])
def test_engine_constructor(monkeypatch: pytest.MonkeyPatch, null_pool: bool) -> None:
    create = Mock()
    monkeypatch.setattr(database, "create_async_engine", create)
    assert database.make_async_engine("postgresql+asyncpg://fake", use_null_pool=null_pool) is create.return_value
    create.assert_called_once_with("postgresql+asyncpg://fake", future=True, poolclass=NullPool if null_pool else None)


def test_engine_defaults_to_null_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    create = Mock()
    monkeypatch.setattr(database, "create_async_engine", create)
    database.make_async_engine("postgresql+asyncpg://fake")
    assert create.call_args.kwargs["poolclass"] is NullPool


def test_session_factory_constructor(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = Mock()
    engine = object()
    monkeypatch.setattr(database, "async_sessionmaker", factory)
    assert database.make_async_session_factory(engine) is factory.return_value
    factory.assert_called_once_with(engine, expire_on_commit=False, autoflush=False)


@pytest.mark.parametrize("failure", ["none", "body", "commit"])
async def test_get_db_transaction_and_cleanup(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.__aenter__.return_value = session
    monkeypatch.setattr(database, "AsyncSessionLocal", Mock(return_value=session))
    error = RuntimeError("transaction failure")
    if failure == "commit":
        session.commit.side_effect = error
    iterator = cast(AsyncGenerator[AsyncSession], database.get_db())
    assert await anext(iterator) is session
    if failure == "none":
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        session.commit.assert_awaited_once_with()
        session.rollback.assert_not_awaited()
    else:
        with pytest.raises(RuntimeError) as exc:
            if failure == "body":
                await iterator.athrow(error)
            else:
                await anext(iterator)
        assert exc.value is error
        session.rollback.assert_awaited_once_with()
        if failure == "body":
            session.commit.assert_not_awaited()
    session.close.assert_awaited_once_with()
    session.__aexit__.assert_awaited_once()


async def test_close_database_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Mock(dispose=AsyncMock())
    monkeypatch.setattr(database, "async_engine", engine)
    await database.close_database()
    engine.dispose.assert_awaited_once_with()
