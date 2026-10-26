from pydantic import Field

from core.schemas.baseschema import BaseSchema


class ServiceAuthorizationAccessTokenOutDto(BaseSchema):
    """DTO выдачи зашифрованного access токена доверенному сервису ya-metrica."""

    enc_access_token: str = Field(..., description="Сохранённый зашифрованный access токен пользователя Яндекс")
