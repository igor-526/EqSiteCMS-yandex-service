import logging
from uuid import UUID

from core.entities import PaginatedEntities
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexAccountOutDto

logger = logging.getLogger("Yandex Accounts Service")


class YandexAccountsService:
    def __init__(
        self,
        yandex_user_repository: YandexUserRepositoryProtocol,
    ) -> None:
        self._yandex_user_repository = yandex_user_repository

    async def list_filtered(
        self, *, equestrian_id: UUID, search: str | None = None, limit: int = 20, offset: int = 0
    ) -> PaginatedEntities[YandexAccountOutDto]:
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
        if offset < 0:
            offset = 0
        accounts = await self._yandex_user_repository.get_filtered(
            equestrian_id=equestrian_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        total = await self._yandex_user_repository.count_filtered(equestrian_id=equestrian_id, search=search)
        return PaginatedEntities[YandexAccountOutDto](
            items=[YandexAccountOutDto.model_validate(account) for account in accounts],
            total=total,
        )

    async def delete_account(self, *, account_id: UUID) -> None:
        await self._yandex_user_repository.delete(id=account_id)
        logger.info("Deleted Yandex account %s", account_id)
