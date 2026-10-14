from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.entities import PaginatedEntities
from core.schemas.api import YandexAccountOutDto
from core.services import YandexAccountsService
from depends.services import get_yandex_accounts_service

router = APIRouter()


@router.get("/{slug_or_id}", response_model=PaginatedEntities[YandexAccountOutDto])
async def list_filtered(
    service: Annotated[YandexAccountsService, Depends(get_yandex_accounts_service)],
    equestrian_id: Annotated[UUID, Query(description="UUID конюшни, для которой запрашиваются аккаунты")],
    search: Annotated[str | None, Query(description="Регистронезависимый поиск по регулярному выражению")] = None,
    limit: Annotated[int, Query(description="Кол-во записей")] = 20,
    offset: Annotated[int, Query(description="Смещение")] = 0,
) -> PaginatedEntities[YandexAccountOutDto]:
    return await service.list_filtered(
        equestrian_id=equestrian_id,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.delete("/{account_id}", status_code=204)
async def delete(
    service: Annotated[YandexAccountsService, Depends(get_yandex_accounts_service)],
    account_id: UUID,
) -> None:
    await service.delete_account(
        account_id=account_id,
    )
