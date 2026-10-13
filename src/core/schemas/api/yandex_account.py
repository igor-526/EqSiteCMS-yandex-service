from uuid import UUID

from pydantic import Field

from core.schemas.baseschema import BaseSchema


class YandexAccountOutDto(BaseSchema):
    """DTO выдачи аккаунта Яндекс."""

    id: UUID = Field(default=..., description="UUID записи аккаунта Яндекс в системе")
    yandex_id: str = Field(default=..., description="Уникальный идентификатор пользователя Яндекса")
    yandex_login: str = Field(default=..., description="Логин пользователя на Яндексе")
    display_name: str = Field(
        default=...,
        description="Отображаемое имя пользователя Яндекса",
    )
    email: str | None = Field(
        default=None,
        description="Основной адрес электронной почты пользователя",
    )
    yandex_phone: str | None = Field(
        default=None,
        description="Основной номер телефона пользователя",
    )
