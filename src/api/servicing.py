from typing import Annotated
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from containers.services import ServicesContainer
from core.schemas.api import ServiceAuthorizationAccessTokenOutDto
from core.services import YandexServiceAuthorizationService
from utils.transactional_route import TransactionalRoute

router = APIRouter(route_class=TransactionalRoute)


@router.get(
    "/access-token/{account_id}",
    response_model=ServiceAuthorizationAccessTokenOutDto,
    description="Выдача сохранённого ciphertext токена доверенному сервису ya-metrica без расшифровки.",
)
@inject
async def get_account_access_token(
    service: Annotated[
        YandexServiceAuthorizationService,
        Depends(Provide[ServicesContainer.yandex_service_authorization_service]),
    ],
    account_id: UUID,
) -> ServiceAuthorizationAccessTokenOutDto:
    enc_access_token = await service.get_token(account_id=account_id)
    return ServiceAuthorizationAccessTokenOutDto(enc_access_token=enc_access_token)
