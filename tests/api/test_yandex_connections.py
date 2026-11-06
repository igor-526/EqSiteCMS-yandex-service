from unittest.mock import AsyncMock

import pytest

from api import yandex_connections
from containers import services_container
from core.entities import YandexMetricaCounter
from core.entities.metrica_lifecycle import MetricaBindingSnapshot, MetricaTenantLifecycle
from core.exceptions import AlreadyExistsError
from core.protocols.repositories import YandexMetricaCounterRepositoryProtocol, YandexUserRepositoryProtocol
from core.protocols.repositories.metrica_lifecycle_repository import MetricaLifecycleRepositoryProtocol
from core.services.yandex_metrica_counter_service import YandexMetricaCounterService
from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, TENANT_ID
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("found", [False, True])
@pytest.mark.parametrize("numbers", [(0, 0, 0), (3, 2, 1), (4, 2, 2)])
async def test_get_connected_counter_returns_200(runtime_api, headers, found, numbers):
    user = account()
    counter = YandexMetricaCounter(equestrian_id=user.equestrian_id, yandex_user_id=user.id, counter_id="42")
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    repository.get_by_equestrian.return_value = counter if found else None
    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    generation, requested, completed = numbers
    state = MetricaTenantLifecycle(
        equestrian_id=user.equestrian_id,
        binding_generation=generation,
        cleanup_requested_seq=requested,
        cleanup_completed_seq=completed,
    )
    lifecycle.get_binding_snapshot.return_value = MetricaBindingSnapshot(
        lifecycle=state, counter=counter if found else None
    )
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    users.get_by_id.return_value = user
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])

    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/connections/metrica/{user.equestrian_id}", headers=headers)

    assert response.status_code == 200
    if found:
        body = response.json()["counter"]
        assert body["id"] == str(counter.id)
        assert body["counter_id"] == "42"
        assert body["yandex_account"]["id"] == str(user.id)
    else:
        assert response.json()["counter"] is None
        users.get_by_id.assert_not_awaited()
    assert {
        key: response.json()[key] for key in ("binding_generation", "cleanup_requested_seq", "cleanup_completed_seq")
    } == state.model_dump(exclude={"equestrian_id"})
    assert set(response.json()) == {"counter", "binding_generation", "cleanup_requested_seq", "cleanup_completed_seq"}
    assert "enc_access_token" not in response.text and "enc_refresh_token" not in response.text
    lifecycle.get_binding_snapshot.assert_awaited_once_with(equestrian_id=user.equestrian_id)
    repository.get_by_equestrian.assert_not_awaited()
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("outcome", ["foreign", "absent", "conflict"])
async def test_set_counter_access(runtime_api, headers, outcome):
    user = account()  # Foreign account has no cookie-based owner override in this peer.
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    repository.get_by_equestrian.return_value = None

    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    users.get_by_id.return_value = None if outcome == "absent" else user
    if outcome == "conflict":
        lifecycle.set_binding.side_effect = AlreadyExistsError("SECRET-conflict")
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])
    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            response = await client.post(
                "/api/connections/metrica",
                json={
                    "equestrian_id": str(TENANT_ID),
                    "yandex_account_id": str(user.id),
                    "counter_id": "42",
                },
                headers=headers,
            )
    status = 200 if outcome == "foreign" else 400
    assert response.status_code == status
    assert "SECRET-conflict" not in response.text
    users.get_by_id.assert_awaited_once_with(id=user.id)
    if outcome == "foreign":
        assert response.json()["yandex_account"]["id"] == str(user.id)
        lifecycle.set_binding.assert_awaited_once()
    elif outcome == "absent":
        lifecycle.set_binding.assert_not_awaited()
    runtime_api.assert_transaction(status, "commit" if status == 200 else "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_delete_absent_counter_is_idempotent(runtime_api, headers):
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])
    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            for _ in range(2):
                response = await client.delete(f"/api/connections/metrica/{ACCOUNT_ID}", headers=headers)
                assert response.status_code == 204
                assert response.content == b""
    assert lifecycle.delete_binding.await_count == 2
    lifecycle.delete_binding.assert_awaited_with(counter_id=ACCOUNT_ID)
    users.get_by_id.assert_not_awaited()
    assert runtime_api.events.count("response:204") == 2
    assert runtime_api.events.count("1:commit") == runtime_api.events.count("2:commit") == 1


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/connections/metrica/bad", None),
        ("delete", "/api/connections/metrica/bad", None),
        ("post", "/api/connections/metrica", {}),
        (
            "post",
            "/api/connections/metrica",
            {"equestrian_id": str(TENANT_ID), "yandex_account_id": "SECRET-input", "counter_id": "SECRET-input"},
        ),
    ],
)
async def test_connection_validation(runtime_api, headers, method, path, body):
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])
    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            response = await client.request(method, path, json=body, headers=headers)
    assert response.status_code == 400
    assert "SECRET-input" not in response.text
    assert repository.mock_calls == users.mock_calls == lifecycle.mock_calls == []
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("query,limit,offset", [("", 100, 0), ("?limit=1&offset=3", 1, 3), ("?limit=500", 500, 0)])
@pytest.mark.parametrize("found", [False, True])
async def test_list_bindings_y10_contract(runtime_api, headers, query, limit, offset, found):
    """UT-YB-01: credential-less Y10 exposes identifiers, never account data."""
    user = account()
    counter = YandexMetricaCounter(equestrian_id=user.equestrian_id, yandex_user_id=user.id, counter_id="42")
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    repository.list_paginated.return_value = [counter] if found else []
    repository.count.return_value = 250 if found else 0
    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])
    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/connections/metrica{query}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "total": 250 if found else 0,
        "items": [{"equestrian_id": str(user.equestrian_id), "counter_id": "42"}] if found else [],
    }
    repository.list_paginated.assert_awaited_once_with(limit=limit, offset=offset)
    repository.count.assert_awaited_once_with()
    assert len(repository.mock_calls) == 2
    assert users.mock_calls == []
    runtime_api.assert_transaction(200, "commit")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=-1",
        "limit=501",
        "offset=-1",
        "limit=SECRET-input",
        "offset=SECRET-input",
        "limit=1.5",
        "offset=1.5",
        "limit=",
        "offset=",
    ],
)
async def test_list_bindings_y10_validation(runtime_api, headers, query):
    """UT-YB-01: all invalid pagination yields safe 400 before repository calls."""
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    lifecycle = AsyncMock(spec=MetricaLifecycleRepositoryProtocol)
    lifecycle.set_binding.side_effect = lambda *, counter: counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    service = YandexMetricaCounterService(repository, users, lifecycle)
    services_container.wire(modules=[yandex_connections])
    with override_providers({services_container.yandex_metrica_counter_service: service}):
        async with runtime_api.client() as client:
            response = await client.get(f"/api/connections/metrica?{query}", headers=headers)
    assert response.status_code == 400
    assert "SECRET-input" not in response.text
    assert repository.mock_calls == users.mock_calls == lifecycle.mock_calls == []
    runtime_api.assert_transaction(400, "rollback")


def test_list_bindings_openapi_contract():
    from main import app

    schema = app.openapi()
    operation = schema["paths"]["/api/connections/metrica"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/YandexMetricaBindingListOutDto"
    }
    params = {param["name"]: param for param in operation["parameters"]}
    assert params["limit"]["schema"]["default"] == 100
    assert params["offset"]["schema"]["default"] == 0
    assert set(schema["components"]["schemas"]["YandexMetricaBindingItemOutDto"]["properties"]) == {
        "equestrian_id",
        "counter_id",
    }
    assert "get" in schema["paths"]["/api/connections/metrica/{equestrian_id}"]
    assert not operation.get("security")
