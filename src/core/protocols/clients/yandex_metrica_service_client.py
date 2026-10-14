from typing import Any, Protocol


class YaMetricaServiceClientProtocol(Protocol):
    async def get_metrica_counters(self, *, search: str | None = None, access_token: str) -> Any: ...
