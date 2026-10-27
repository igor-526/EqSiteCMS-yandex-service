from uuid import UUID

from pydantic import Field

from core.schemas.api.yandex_account import YandexAccountOutDto
from core.schemas.baseschema import BaseSchema


class YandexMetricaCounterOutDto(BaseSchema):
    """DTO выдачи счётчика"""

    counter_id: int = Field(default=..., description="ID счётчика Яндекс")
    site: str = Field(default=..., description="Сайт счётчика Яндекс")


class YandexMetricaCounterResponseOutDto(BaseSchema):
    """DTO выдачи счётчиков"""

    total: int = Field(default=..., description="Общее кол-во счётчиков")
    items: list[YandexMetricaCounterOutDto] = Field(default_factory=list, description="Счётчики Яндекс.Метрика")


class YandexMetricaSetCounterInDto(BaseSchema):
    """Привязка счётчика к конюшне"""

    equestrian_id: UUID = Field(default=..., description="UUID конюшни, к которой привязан счётчик")
    yandex_account_id: UUID = Field(default=..., description="UUID аккаунта Яндекс, чей счётчик")
    counter_id: str = Field(default=..., description="Счётчик Яндекс.Метрика")


class YandexMetricaSetCounterOutDto(BaseSchema):
    """DTO счётчика"""

    id: UUID = Field(default=..., description="UUID записи")
    equestrian_id: UUID = Field(default=..., description="UUID конюшни, к которой привязан счётчик")
    counter_id: str = Field(default=..., description="Счётчик Яндекс.Метрика")
    yandex_account: YandexAccountOutDto = Field(default=..., description="DTO пользователя Яндекс")


class YandexMetricaConnectedCounterOutDto(BaseSchema):
    """Ответ на запрос счётчика"""

    counter: YandexMetricaSetCounterOutDto | None = Field(default=None, description="Счётчик метрики")


class YandexMetricaBindingItemOutDto(BaseSchema):
    """Привязка без токенов и данных аккаунта."""

    equestrian_id: UUID = Field(description="UUID конюшни")
    counter_id: str = Field(description="Счётчик Яндекс.Метрика")


class YandexMetricaBindingListOutDto(BaseSchema):
    """Страница внутреннего реестра привязок."""

    total: int = Field(description="Общее количество привязок")
    items: list[YandexMetricaBindingItemOutDto] = Field(default_factory=list)
