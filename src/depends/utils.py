from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from utils.database import AsyncSessionLocal


async def get_session() -> AsyncGenerator[AsyncSession]:
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
