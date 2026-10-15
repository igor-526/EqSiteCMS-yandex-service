"""A caller-provided test database; runtime settings are never consulted."""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from models import yandex_metrica_counters, yandex_user
from utils.basemodel import metadata


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is required for dedicated PostgreSQL tests")
    url = make_url(raw_url)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg")
    schema = f"test_yandex_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}})
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: metadata.create_all(conn, tables=[yandex_user, yandex_metrica_counters])
            )
        yield engine
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(pg_engine) as session:
        yield session
        await session.rollback()
