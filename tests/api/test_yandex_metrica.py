"""API-01..03: registered Metrica route, DTO response and input validation."""

import pytest

from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi


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
async def test_counters_validation(runtime_api: RuntimeApi, query: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/metrica/counters", params=query)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")
