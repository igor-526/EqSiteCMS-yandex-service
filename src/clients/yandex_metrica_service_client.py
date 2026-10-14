from collections.abc import Mapping
from typing import Any

import httpx

from core.exceptions import YandexClientException

mock_response = [
    {
        "id": 0,
        "status": "example",
        "owner_login": "example",
        "activity_status": "example",
        "name": "example",
        "type": "example",
        "favorite": True,
        "permission": "example",
        "goals": [None],
        "filters": [
            {
                "id": 0,
                "attr": "example",
                "type": "example",
                "value": "example",
                "action": "example",
                "status": "example",
                "start_ip": "example",
                "end_ip": "example",
                "with_subdomains": True,
            }
        ],
        "operations": [{"id": 0, "action": "example", "attr": "example", "value": "example", "status": "example"}],
        "grants": [
            {
                "user_login": "example",
                "perm": "example",
                "created_at": "2025-01-01T00:00:00Z",
                "comment": "example",
                "partner_data_access": True,
            }
        ],
        "labels": [{"id": 0, "name": "example"}],
        "webvisor": {
            "urls": "example",
            "arch_enabled": True,
            "arch_type": "example",
            "load_player_type": "example",
            "wv_version": 0,
            "wv_forms": True,
        },
        "code_options": {
            "async": True,
            "informer": {
                "enabled": True,
                "type": "example",
                "size": 1,
                "indicator": "example",
                "color_start": "FFFFFFFF.",
                "color_end": "EFEFEFFF",
                "color_text": 0,
                "color_arrow": 0,
            },
            "visor": True,
            "track_hash": True,
            "xml_site": True,
            "clickmap": True,
            "in_one_line": True,
            "ecommerce": True,
            "alternative_cdn": True,
            "ytm": True,
        },
        "create_time": "2025-01-01T00:00:00Z",
        "time_zone_name": "example",
        "time_zone_offset": 0,
        "partner_id": 0,
        "source": "example",
        "site2": {"site": "example"},
        "gdpr_agreement_accepted": True,
        "mirrors2": [None],
    }
]


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
        async with httpx.AsyncClient(base_url=self.ya_metrica_service_url) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                params=params,
                headers=headers,
                data=data,
                json=json,
                auth=auth,
                timeout=request_timeout,
            )
        response_data = response.json()
        if not isinstance(response_data, dict):
            raise YandexClientException(status=response.status_code, error="Empty response")
        if not 200 <= response.status_code < 300:
            raise YandexClientException(
                status=response.status_code,
                error=response_data.get("error", None),
                error_description=response_data.get("error_description", None),
            )
        return response_data

    async def get_metrica_counters(self, *, search: str | None = None, access_token: str) -> Any:
        return mock_response
