"""API-01..03: deliberate token output characterizes GAP-AUTH-02/03."""

import pytest

from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_is_currently_public(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get(f"/api/servicing/access-token/{ACCOUNT_ID}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"access_token": "deliberate-access-token"}
    runtime_api.authorization.get_token.assert_awaited_once_with(account_id=ACCOUNT_ID)
    runtime_api.assert_transaction(200, "commit")


async def test_token_uuid_validation(runtime_api: RuntimeApi) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/servicing/access-token/bad")
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")
