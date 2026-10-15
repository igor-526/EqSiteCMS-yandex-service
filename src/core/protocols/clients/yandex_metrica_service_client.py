from typing import Protocol

from core.schemas.api import YandexMetricaCounterResponseOutDto


class YaMetricaServiceClientProtocol(Protocol):
    async def get_metrica_counters(
        self, *, search: str | None = None, access_token: str, limit: int = 20, offset: int = 0
    ) -> YandexMetricaCounterResponseOutDto: ...
