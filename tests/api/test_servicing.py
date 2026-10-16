"""API-01..03: deliberate token output characterizes GAP-AUTH-02/03."""

from unittest.mock import AsyncMock, Mock

import pytest

from containers import services_container
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import YandexServiceAuthorizationService
from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_is_currently_public(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get(f"/api/servicing/access-token/{ACCOUNT_ID}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"access_token": "deliberate-access-token"}
    runtime_api.authorization.get_token.assert_awaited_once_with(account_id=ACCOUNT_ID)
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_token_uuid_validation(runtime_api: RuntimeApi, headers: dict[str, str]) -> None:
    async with runtime_api.client() as client:
        response = await client.get("/api/servicing/access-token/bad", headers=headers)
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], list)
    runtime_api.assert_no_service_calls()
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("found", [True, False])
async def test_token_foreign_or_absent_account(runtime_api: RuntimeApi, headers: dict[str, str], found: bool) -> None:
    foreign = account()
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = foreign if found else None
    encryption = Mock()
    encryption.decrypt.return_value = "deliberate-access-token"
    service = YandexServiceAuthorizationService(encryption_service=encryption, yandex_user_repository=repository)
    with override_providers({services_container.yandex_service_authorization_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/servicing/access-token/{foreign.id}", headers=headers)
    status = 200 if found else 400
    assert response.status_code == status
    repository.get_by_id.assert_awaited_once_with(id=foreign.id)
    if found:
        assert response.json() == {"access_token": "deliberate-access-token"}
        encryption.decrypt.assert_called_once_with(data=foreign.enc_access_token)
    else:
        encryption.decrypt.assert_not_called()
    runtime_api.assert_transaction(status, "commit" if found else "rollback")
