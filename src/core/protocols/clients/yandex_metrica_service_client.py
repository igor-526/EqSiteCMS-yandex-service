from typing import Protocol

from core.schemas.api import YandexMetricaCounterResponseOutDto


class YaMetricaServiceClientProtocol(Protocol):
    async def get_metrica_counters(
        self, *, search: str | None = None, access_token: str, limit: int = 20, offset: int = 0
    ) -> YandexMetricaCounterResponseOutDto:
        """Return the validated peer DTO, preserving its total and partial items.

        Raises local YandexClientException on ordinary request/response failures,
        including peer HTTP 400 and invalid DTO. Cancellation/BaseException propagate.
        """
        ...
