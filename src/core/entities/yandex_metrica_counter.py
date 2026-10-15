from uuid import UUID

from pydantic import Field

from .base import Entity, TimestampMixin


class YandexMetricaCounter(Entity, TimestampMixin):
    """Привязанный к конюшне счётчик метрики."""

    equestrian_id: UUID = Field(description="UUID конюшни, к которой привязан счётчик")
    yandex_user_id: UUID = Field(description="UUID аккаунта Яндекс, чей счётчик")
    counter_id: str = Field(max_length=31, description="Счётчик Яндекс.Метрика")
