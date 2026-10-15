from unittest.mock import AsyncMock

import pytest

from api import yandex_connections
from containers import services_container
from core.entities import YandexMetricaCounter
from core.protocols.repositories import YandexMetricaCounterRepositoryProtocol, YandexUserRepositoryProtocol
from core.services.yandex_metrica_counter_service import YandexMetricaCounterService
from tests.api.conftest import AUTH_HEADERS
from tests.helpers import override_providers
from tests.unit.test_yandex_user_repository import account


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("found", [False, True])
async def test_get_connected_counter_returns_200(runtime_api, headers, found):
    user = account()
    counter = YandexMetricaCounter(equestrian_id=user.equestrian_id, yandex_user_id=user.id, counter_id="42")
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    repository.get_by_equestrian.return_value = counter if found else None
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    users.get_by_id.return_value = user
    service = YandexMetricaCounterService(repository, users)
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
        assert response.json() == {"counter": None}
        users.get_by_id.assert_not_awaited()
    repository.get_by_equestrian.assert_awaited_once_with(equestrian_id=user.equestrian_id)
    runtime_api.assert_transaction(200, "commit")
