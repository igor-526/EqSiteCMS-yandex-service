from typing import Annotated
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from containers.services import ServicesContainer
from core.entities import PaginatedEntities
from core.schemas.api import YandexAccountOutDto
from core.services import YandexAccountsService
from utils.transactional_route import TransactionalRoute

router = APIRouter(route_class=TransactionalRoute)


@router.get("/", response_model=PaginatedEntities[YandexAccountOutDto])
@inject
async def list_filtered(
    service: Annotated[YandexAccountsService, Depends(Provide[ServicesContainer.yandex_accounts_service])],
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
@inject
async def delete(
    service: Annotated[YandexAccountsService, Depends(Provide[ServicesContainer.yandex_accounts_service])],
    account_id: UUID,
) -> None:
    await service.delete_account(
        account_id=account_id,
    )
