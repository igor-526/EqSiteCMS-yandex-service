from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from core.exceptions import YandexClientException
from core.schemas.api import YandexMetricaCounterResponseOutDto


class YaMetricaServiceClient:
    ya_metrica_service_url: str

    def __init__(self, *, ya_metrica_service_url: str) -> None:
        self.ya_metrica_service_url = ya_metrica_service_url

    async def make_request(
        self,
        *,
        method: str = "GET",
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any | None = None,
        auth: httpx.Auth | None = None,
        request_timeout: float | httpx.Timeout | None = 10.0,
    ) -> dict:
        status = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method.upper(),
                    url=f"{self.ya_metrica_service_url}/api/{url}",
                    params=params,
                    headers=headers,
                    data=data,
                    json=json,
                    auth=auth,
                    timeout=request_timeout,
                )
                status = response.status_code
            if not 200 <= status < 300:
                raise YandexClientException(status, category="http")
            response_data = response.json()
            if not isinstance(response_data, dict):
                raise ValueError("Expected a JSON object")
            return response_data
        except YandexClientException:
            raise
        except httpx.TimeoutException as ex:
            raise YandexClientException(status, category="timeout") from ex
        except httpx.TransportError as ex:
            raise YandexClientException(status, category="transport") from ex
        except (ValueError, TypeError) as ex:
            raise YandexClientException(status, category="response") from ex
        except Exception as ex:
            raise YandexClientException(status) from ex

    async def get_metrica_counters(
        self, *, access_token: str, search: str | None = None, limit: int = 20, offset: int = 0
    ) -> YandexMetricaCounterResponseOutDto:
        try:
            response = await self.make_request(
                method="GET",
                url="metrica/counters",
                params={"access_token": access_token, "search": search, "limit": limit, "offset": offset},
            )
            return YandexMetricaCounterResponseOutDto.model_validate(response)
        except YandexClientException:
            raise
        except ValidationError as ex:
            raise YandexClientException(None, category="response") from ex
        except Exception as ex:
            raise YandexClientException(None) from ex
