from datetime import datetime
from uuid import UUID

from pydantic import Field

from .base import Entity, TimestampMixin


class YandexUser(Entity, TimestampMixin):
    """Привязанный к конюшне аккаунт пользователя Яндекса."""

    equestrian_id: UUID = Field(description="UUID конюшни, к которой привязан аккаунт")
    yandex_id: str = Field(max_length=63, description="Уникальный идентификатор пользователя Яндекса")
    yandex_login: str = Field(max_length=127, description="Логин пользователя на Яндексе")
    display_name: str = Field(
        max_length=127,
        description="Отображаемое имя пользователя Яндекса",
    )
    email: str | None = Field(
        default=None,
        max_length=320,
        description="Основной адрес электронной почты пользователя",
    )
    yandex_avatar_id: str | None = Field(
        default=None,
        max_length=63,
        description="Идентификатор аватара пользователя Яндекса",
    )
    yandex_phone: str | None = Field(
        default=None,
        max_length=31,
        description="Основной номер телефона пользователя",
    )
    enc_access_token: str = Field(max_length=511, description="Зашифрованный OAuth access-токен")
    enc_refresh_token: str = Field(max_length=511, description="Зашифрованный OAuth refresh-токен")
    token_expires_at: datetime = Field(description="Дата и время истечения срока действия access-токена")
