from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from settings import settings

engine: AsyncEngine | None = None
async_session_maker: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    """Get or create database engine."""
    global engine
    if engine is None:
        engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
    return engine


def get_session_maker() -> async_sessionmaker:
    """Get or create async session maker."""
    global async_session_maker
    if async_session_maker is None:
        async_session_maker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
        )
    return async_session_maker


async def close_database() -> None:
    """Close database connections."""
    global engine
    if engine is not None:
        await engine.dispose()
        engine = None
