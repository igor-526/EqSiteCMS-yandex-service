from pydantic import Field

from core.schemas.baseschema import BaseSchema


class ServiceAuthorizationAccessTokenOutDto(BaseSchema):
    """DTO выдачи access токена для авторизации пользователя в других сервисах."""

    access_token: str = Field(..., description="Access токен пользователя Яндекс")
