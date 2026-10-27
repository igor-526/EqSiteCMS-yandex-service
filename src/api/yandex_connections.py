from typing import Annotated
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from containers.services import ServicesContainer
from core.schemas.api import (
    YandexMetricaBindingListOutDto,
    YandexMetricaConnectedCounterOutDto,
    YandexMetricaSetCounterInDto,
    YandexMetricaSetCounterOutDto,
)
from core.services import YandexMetricaCounterService
from utils.transactional_route import TransactionalRoute

router = APIRouter(route_class=TransactionalRoute)


@router.get("/metrica", response_model=YandexMetricaBindingListOutDto)
@inject
async def list_bindings(
    service: Annotated[
        YandexMetricaCounterService, Depends(Provide[ServicesContainer.yandex_metrica_counter_service])
    ],
    limit: Annotated[int, Query(description="Количество привязок (1..500)")] = 100,
    offset: Annotated[int, Query(description="Смещение (не меньше 0)")] = 0,
) -> YandexMetricaBindingListOutDto:
    return await service.list_bindings(limit=limit, offset=offset)


@router.get("/metrica/{equestrian_id}", response_model=YandexMetricaConnectedCounterOutDto)
@inject
async def get_counter(
    service: Annotated[
        YandexMetricaCounterService, Depends(Provide[ServicesContainer.yandex_metrica_counter_service])
    ],
    equestrian_id: UUID,
) -> YandexMetricaConnectedCounterOutDto:
    return await service.get_counter(
        equestrian_id=equestrian_id,
    )


@router.post("/metrica", response_model=YandexMetricaSetCounterOutDto)
@inject
async def set_counter(
    service: Annotated[
        YandexMetricaCounterService, Depends(Provide[ServicesContainer.yandex_metrica_counter_service])
    ],
    data: YandexMetricaSetCounterInDto,
) -> YandexMetricaSetCounterOutDto:
    return await service.set_counter(data=data)


@router.delete("/metrica/{counter_id}", status_code=204)
@inject
async def delete_counter(
    service: Annotated[
        YandexMetricaCounterService, Depends(Provide[ServicesContainer.yandex_metrica_counter_service])
    ],
    counter_id: UUID,
) -> None:
    return await service.delete_counter(
        counter_id=counter_id,
    )
