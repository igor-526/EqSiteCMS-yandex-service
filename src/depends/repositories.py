from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.protocols.repositories import (
    YandexUserRepositoryProtocol,
)
from depends.utils import get_session
from repositories import YandexUserRepository


async def get_yandex_user_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> YandexUserRepositoryProtocol:
    return YandexUserRepository(session=session)
