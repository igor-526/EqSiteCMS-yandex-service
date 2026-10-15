"""API-01..03: account selector, output filtering and GAP-AUTH-01/03."""

import pytest

from tests.api.conftest import ACCOUNT, ACCOUNT_ID, AUTH_HEADERS, TENANT_ID, RuntimeApi


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("query", [{}, {"search": "Лошадь.*", "limit": "3", "offset": "7"}])
async def test_accounts_list(runtime_api: RuntimeApi, headers: dict[str, str], query: dict[str, str]) -> None:
    runtime_api.accounts.list_filtered.return_value = {
        "total": 9,
        "items": [{**ACCOUNT, "access_token": "secret", "refresh_token": "secret"}],
    }
    async with runtime_api.client() as client:
        response = await client.get(
            "/api/accounts/", params={"equestrian_id": str(TENANT_ID), **query}, headers=headers
        )
    assert response.status_code == 200
    assert response.json() == {"total": 9, "items": [ACCOUNT]}
    runtime_api.accounts.list_filtered.assert_awaited_once_with(
        equestrian_id=TENANT_ID,
        search=query.get("search"),
        limit=int(query.get("limit", 20)),
        offset=int(query.get("offset", 0)),
    )
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("total,offset", [(0, 0), (9, 12)])
async def test_accounts_empty_page(runtime_api: RuntimeApi, headers: dict[str, str], total: int, offset: int) -> None:
    runtime_api.accounts.list_filtered.return_value = {"total": total, "items": []}
    async with runtime_api.client() as client:
        response = await client.get(
            "/api/accounts/",
            params={"equestrian_id": str(TENANT_ID), "limit": 3, "offset": offset},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json() == {"total": total, "items": []}
    runtime_api.accounts.list_filtered.assert_awaited_once_with(
        equestrian_id=TENANT_ID, search=None, limit=3, offset=offset
    )
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_delete_is_currently_public_and_has_no_tenant_selector(
    runtime_api: RuntimeApi, headers: dict[str, str]
) -> None:
    # GAP-AUTH-01/03: caller headers are ignored; no ownership argument exists.
    async with runtime_api.client() as client:
        response = await client.delete(f"/api/accounts/{ACCOUNT_ID}", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    runtime_api.accounts.delete_account.assert_awaited_once_with(account_id=ACCOUNT_ID)
    runtime_api.assert_transaction(204, "commit")


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"equestrian_id": "bad"},
        {"equestrian_id": str(TENANT_ID), "limit": "bad"},
        {"equestrian_id": str(TENANT_ID), "offset": "bad"},
    ],
)
async def test_list_validation(runtime_api: RuntimeApi, query: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/accounts/", params=query)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


async def test_delete_uuid_validation(runtime_api: RuntimeApi) -> None:
    async with runtime_api.client() as client:
        response = await client.delete("/api/accounts/not-a-uuid")
    assert response.status_code == 400
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")
