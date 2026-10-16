"""API-01..03: account selector, output filtering and GAP-AUTH-01/03."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from containers import services_container
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import YandexAccountsService
from tests.api.conftest import ACCOUNT, ACCOUNT_ID, AUTH_HEADERS, TENANT_ID, RuntimeApi
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


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


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_foreign_selector_and_absent_delete(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    foreign = account()
    repository.get_filtered.return_value = [foreign]
    repository.count_filtered.return_value = 1
    service = YandexAccountsService(yandex_user_repository=repository)
    absent = uuid4()
    with override_providers({services_container.yandex_accounts_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(
                "/api/accounts/", params={"equestrian_id": str(foreign.equestrian_id)}, headers=headers
            )
            assert response.status_code == 200
            assert response.json()["items"][0]["id"] == str(foreign.id)
            for _ in range(2):
                response = await client.delete(f"/api/accounts/{absent}", headers=headers)
                assert response.status_code == 204
                assert response.content == b""
    repository.get_filtered.assert_awaited_once_with(
        equestrian_id=foreign.equestrian_id, search=None, limit=20, offset=0
    )
    assert repository.delete.await_count == 2
    repository.delete.assert_awaited_with(id=absent)
    assert runtime_api.events.count("response:204") == 2


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"equestrian_id": "bad"},
        {"equestrian_id": str(TENANT_ID), "limit": "bad"},
        {"equestrian_id": str(TENANT_ID), "offset": "bad"},
    ],
)
@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_list_validation(runtime_api: RuntimeApi, query: dict[str, str], headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/accounts/", params=query, headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_delete_uuid_validation(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.delete("/api/accounts/not-a-uuid", headers=headers)
    assert response.status_code == 400
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")
