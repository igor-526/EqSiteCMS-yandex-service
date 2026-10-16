"""API-01..03: registered Metrica route, DTO response and input validation."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from clients.yandex_metrica_service_client import YaMetricaServiceClient
from containers import services_container
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import YandexMetricaService
from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("query", [{}, {"search": "site.*", "limit": "4", "offset": "2"}])
async def test_counters(runtime_api: RuntimeApi, headers: dict[str, str], query: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get(
            "/api/metrica/counters", params={"account_id": str(ACCOUNT_ID), **query}, headers=headers
        )
    assert response.status_code == 200
    assert response.json() == {"total": 1, "items": [{"counter_id": 7, "site": "site.test"}]}
    runtime_api.metrica.get_counters.assert_awaited_once_with(
        account_id=ACCOUNT_ID,
        search=query.get("search"),
        limit=int(query.get("limit", 20)),
        offset=int(query.get("offset", 0)),
    )
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("total,offset", [(0, 0), (9, 12)])
async def test_counters_empty_page(runtime_api: RuntimeApi, headers: dict[str, str], total: int, offset: int) -> None:
    runtime_api.metrica.get_counters.return_value = {"total": total, "items": []}
    async with runtime_api.client() as client:
        response = await client.get(
            "/api/metrica/counters",
            params={"account_id": str(ACCOUNT_ID), "limit": 3, "offset": offset},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json() == {"total": total, "items": []}
    runtime_api.metrica.get_counters.assert_awaited_once_with(
        account_id=ACCOUNT_ID, search=None, limit=3, offset=offset
    )
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"account_id": "bad"},
        {"account_id": str(ACCOUNT_ID), "limit": "bad"},
        {"account_id": str(ACCOUNT_ID), "offset": "bad"},
    ],
)
@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_counters_validation(runtime_api: RuntimeApi, query: dict[str, str], headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/metrica/counters", params=query, headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("outcome", ["timeout", "transport", "http", "json", "dto", "absent", "partial", "empty"])
async def test_real_peer_chain(
    runtime_api: RuntimeApi,
    mock_upstream,
    headers: dict[str, str],
    outcome: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SECRET-peer-response"
    payload = {"total": 9, "items": [{"counter_id": 42, "site": "site.test"}] if outcome == "partial" else []}

    def upstream(request: httpx.Request) -> httpx.Response:
        if outcome == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if outcome == "transport":
            raise httpx.ConnectError(secret, request=request)
        if outcome == "http":
            return httpx.Response(400, json={"detail": secret})
        if outcome == "json":
            return httpx.Response(200, content=secret)
        if outcome == "dto":
            return httpx.Response(200, json={"total": secret, "items": []})
        # Peer has already skipped bad counters; preserve its total and valid items.
        return httpx.Response(200, json=payload)

    requests = mock_upstream(upstream)
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    foreign = account()  # Another tenant is a selector, not a new permission from cookies.
    repository.get_by_id.return_value = None if outcome == "absent" else foreign
    service = YandexMetricaService(
        encryption_service=Mock(),
        yandex_user_repository=repository,
        yandex_metrica_client=YaMetricaServiceClient(ya_metrica_service_url="http://peer.test"),
    )
    with override_providers({services_container.ya_metrica_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(
                "/api/metrica/counters", params={"account_id": str(foreign.id)}, headers=headers
            )
    success = outcome in {"partial", "empty"}
    status = 200 if success else 400
    assert response.status_code == status
    assert secret not in response.text + caplog.text + str(capsys.readouterr())
    repository.get_by_id.assert_awaited_once_with(id=foreign.id)
    assert len(requests) == (0 if outcome == "absent" else 1)
    if success:
        assert response.json() == payload
    runtime_api.assert_transaction(status, "commit" if success else "rollback")
