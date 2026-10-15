"""Real application HTTP harness, with context-local transactions and scoped DI."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from containers import repositories_container, services_container
from depends import utils as session_dependencies
from main import app
from tests.helpers import override_providers

ACCOUNT_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
ACCOUNT = {
    "id": str(ACCOUNT_ID),
    "yandex_id": "123",
    "yandex_login": "rider",
    "display_name": "Всадник",
    "email": None,
    "yandex_phone": None,
}
AUTH_HEADERS = [{}, {"Authorization": "Bearer fake-caller"}]


class RequestSession:
    def __init__(self, number: int, events: list[str]) -> None:
        self.number = number
        self.events = events
        self.fail_commit = False
        self.closed = False

    async def __aenter__(self) -> RequestSession:
        self.events.append(f"{self.number}:open")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True
        self.events.append(f"{self.number}:close")

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        self.events.append(f"{self.number}:begin")
        try:
            yield
            if self.fail_commit:
                raise RuntimeError("commit failed")
            self.events.append(f"{self.number}:commit")
        except BaseException:
            self.events.append(f"{self.number}:rollback")
            raise


class RuntimeApi:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.sessions: list[RequestSession] = []
        self.oauth = Mock()
        self.oauth.get_auth_link = Mock(return_value="https://oauth.example.test/authorize")
        self.oauth.authenticate = AsyncMock(return_value=ACCOUNT)
        self.accounts = Mock()
        self.accounts.list_filtered = AsyncMock(return_value={"total": 1, "items": [ACCOUNT]})
        self.accounts.delete_account = AsyncMock(return_value=None)
        self.authorization = Mock()
        self.authorization.get_token = AsyncMock(return_value="deliberate-access-token")
        self.metrica = Mock()
        self.metrica.get_counters = AsyncMock(
            return_value={"total": 1, "items": [{"counter_id": 7, "site": "site.test"}]}
        )

    def session_factory(self) -> RequestSession:
        session = RequestSession(len(self.sessions) + 1, self.events)
        self.sessions.append(session)
        return session

    def client(self) -> httpx.AsyncClient:
        async def observed_app(scope: Scope, receive: Receive, send: Send) -> None:
            async def observed_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    self.events.append(f"response:{message['status']}")
                await send(message)

            await app(scope, receive, observed_send)

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app, raise_app_exceptions=False), base_url="http://test"
        )

    def assert_transaction(self, status: int, outcome: str) -> None:
        assert self.events == ["1:open", "1:begin", f"1:{outcome}", "1:close", f"response:{status}"]
        assert self.sessions[0].closed
        assert not repositories_container.session.initialized

    def assert_no_service_calls(self) -> None:
        for service in (self.oauth, self.accounts, self.authorization, self.metrica):
            assert service.mock_calls == []


@pytest.fixture
def runtime_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[RuntimeApi]:
    # Synthetic transaction tests wire their own container. Restore the actual
    # application's wiring at the fixture boundary, leaving no fake container.
    from api import servicing, yandex_accounts, yandex_auth, yandex_metrica

    services_container.wire(modules=[servicing, yandex_accounts, yandex_auth, yandex_metrica])
    harness = RuntimeApi()
    monkeypatch.setattr(session_dependencies, "AsyncSessionLocal", harness.session_factory)
    replacements: dict[Any, Any] = {
        services_container.yandex_oauth_service: harness.oauth,
        services_container.yandex_accounts_service: harness.accounts,
        services_container.yandex_service_authorization_service: harness.authorization,
        services_container.ya_metrica_service: harness.metrica,
    }
    with override_providers(replacements):
        yield harness
    assert not repositories_container.session.initialized
