from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from core.schemas.api import YandexAccountOutDto, YandexAuthCodeInDto, YandexAuthLinkOutDto
from core.services.yandex_oauth_service import YandexOauthService
from depends.services import (
    get_yandex_oauth_service,
)

router = APIRouter()


@router.get("/link", response_model=YandexAuthLinkOutDto)
async def get_auth_link(
    service: Annotated[YandexOauthService, Depends(get_yandex_oauth_service)],
    equestrian_id: UUID,
) -> YandexAuthLinkOutDto:
    auth_link = service.get_auth_link(equestrian_id=equestrian_id)
    return YandexAuthLinkOutDto(auth_link=auth_link)


@router.post("/code", response_model=YandexAccountOutDto)
async def authenticate(
    service: Annotated[YandexOauthService, Depends(get_yandex_oauth_service)],
    data: YandexAuthCodeInDto,
) -> YandexAccountOutDto:
    return await service.authenticate(data=data)
