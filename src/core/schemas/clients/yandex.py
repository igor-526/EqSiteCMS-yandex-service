from typing import Literal

from pydantic import Field

from core.schemas.baseschema import BaseSchema


class YandexClientAuthResponse(BaseSchema):
    """DTO Яндекс на запрос обмена кода на access и refresh токены"""

    access_token: str = Field(default=..., description="Access токен")
    expires_in: int = Field(default=..., description="Время жизни токена в секундах")
    refresh_token: str = Field(default=..., description="Refresh токен")
    token_type: str = Field(default="bearer", description="Тип выданного токена. Всегда принимает значение bearer")


class YandexClientUserResponsePhone(BaseSchema):
    id: int = Field(default=..., description="Идентификатор номера телефона пользователя")
    number: str = Field(default=..., description="Номер телефона пользователя")


class YandexClientUserResponse(BaseSchema):
    id: str = Field(default=..., description="Уникальный идентификатор пользователя Яндекса")
    login: str = Field(default=..., description="Логин пользователя на Яндексе")
    client_id: str = Field(
        default=...,
        description="Идентификатор приложения, для которого был выдан OAuth-токен",
    )
    display_name: str = Field(
        default=...,
        description="Имя, отображаемое для учетной записи в интерфейсе Яндекса",
    )
    real_name: str = Field(
        default=...,
        description="Имя и фамилия пользователя, указанные им в Яндекс ID",
    )
    first_name: str = Field(
        default=...,
        description="Имя пользователя, указанное им в Яндекс ID",
    )
    last_name: str = Field(
        default=...,
        description="Фамилия пользователя, указанная им в Яндекс ID",
    )
    sex: Literal["male", "female"] | None = Field(
        default=None,
        description=("Пол пользователя: male — мужской, female — женский; null — пол неизвестен"),
    )
    default_email: str = Field(
        default=...,
        description="E-mail по умолчанию, предназначенный для связи с пользователем",
    )
    emails: list[str] = Field(
        default_factory=list,
        description="Массив электронных адресов пользователя",
    )
    default_avatar_id: str = Field(
        default=...,
        description="Идентификатор портрета пользователя Яндекса",
    )
    is_avatar_empty: bool = Field(
        default=True,
        description=("Признак того, что default_avatar_id содержит идентификатор заглушки портрета"),
    )
    default_phone: YandexClientUserResponsePhone | None = Field(
        default=...,
        description="Телефон по умолчанию, предназначенный для связи с пользователем",
    )
    psuid: str = Field(
        default=...,
        description=(
            "Идентификатор авторизованного пользователя, сформированный Яндексом на основе client_id и user_id"
        ),
    )
