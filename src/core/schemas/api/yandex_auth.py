from uuid import UUID

from pydantic import Field

from core.schemas.baseschema import BaseSchema


class YandexAuthLinkOutDto(BaseSchema):
    """DTO выдачи ссылки на авторизацию Яндекс."""

    auth_link: str = Field(..., description="Ссылка для авторизации в Яндекс")


class YandexAuthCodeInDto(BaseSchema):
    """DTO получения кода авторизации Яндекс."""

    code: str = Field(..., description="Код для получения токенов")
    equestrian_id: UUID = Field(default=..., description="UUID конюшни для привязки аккаунта Яндекс")
