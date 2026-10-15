from typing import Annotated
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from containers.services import ServicesContainer
from core.schemas.api import YandexMetricaCounterResponseOutDto
from core.services import YandexMetricaService
from utils.transactional_route import TransactionalRoute

router = APIRouter(route_class=TransactionalRoute)


@router.get("/counters", response_model=YandexMetricaCounterResponseOutDto)
@inject
async def get_counters(
    service: Annotated[YandexMetricaService, Depends(Provide[ServicesContainer.ya_metrica_service])],
    account_id: Annotated[UUID, Query(description="UUID аккаунта Яндекс, для которой запрашиваются счётчики")],
    search: Annotated[str | None, Query(description="Поиск по счётчикам")] = None,
    limit: Annotated[int, Query(description="Кол-во счётчиков")] = 20,
    offset: Annotated[int, Query(description="Смещение")] = 0,
) -> YandexMetricaCounterResponseOutDto:
    return await service.get_counters(
        account_id=account_id,
        search=search,
        limit=limit,
        offset=offset,
    )
