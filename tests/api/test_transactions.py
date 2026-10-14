import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

import httpx
import pytest
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from api import servicing, yandex_accounts, yandex_auth
from containers.repositories import RepositoriesContainer
from containers.services import ServicesContainer
from core.exceptions import AppError, ClientError
from core.services import YandexAccountsService
from depends import utils as session_dependencies
from repositories import YandexUserRepository
from utils import transactional_route


class FakeSession:
    def __init__(self, number: int, events: list[str], stored: list[int]) -> None:
        self.number = number
        self.events = events
        self.stored = stored
        self.fail_commit = False
        self.closed = False

    async def __aenter__(self) -> FakeSession:
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
            self.stored.append(self.number)
            self.events.append(f"{self.number}:commit")
        except BaseException:
            self.events.append(f"{self.number}:rollback")
            raise


class FakeService(YandexAccountsService):
    def __init__(self, yandex_user_repository: YandexUserRepository) -> None:
        super().__init__(yandex_user_repository=yandex_user_repository)
        self.repository = yandex_user_repository


class TransactionApp:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.stored: list[int] = []
        self.sessions: list[FakeSession] = []
        self.arrived = 0
        self.both_arrived = asyncio.Event()

        def session_factory() -> FakeSession:
            session = FakeSession(len(self.sessions) + 1, self.events, self.stored)
            self.sessions.append(session)
            return session

        monkeypatch.setattr(session_dependencies, "AsyncSessionLocal", session_factory)
        self.repositories = RepositoriesContainer()
        self.services = ServicesContainer(repositories_container=self.repositories)
        self.services.yandex_accounts_service.set_provides(FakeService)
        monkeypatch.setattr(transactional_route, "repositories_container", self.repositories)
        self.app = FastAPI()

        @self.app.exception_handler(AppError)
        async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

        router = APIRouter(route_class=transactional_route.TransactionalRoute)

        @router.get("/transaction/{action}")
        @inject
        async def endpoint(
            action: str,
            service: Annotated[FakeService, Depends(Provide[ServicesContainer.yandex_accounts_service])],
        ) -> dict[str, int]:
            session = cast(FakeSession, service.repository.session)
            assert session is await self.repositories.session.async_()
            if action == "concurrent":
                self.arrived += 1
                if self.arrived == 2:
                    self.both_arrived.set()
                await asyncio.wait_for(self.both_arrived.wait(), timeout=5)
            assert not session.closed
            if action == "http_error":
                raise HTTPException(status_code=403, detail="denied")
            if action == "app_error":
                raise ClientError("failed")
            if action == "crash":
                raise ValueError("unexpected failure")
            session.fail_commit = action == "commit_error"
            return {"session": session.number}

        self.app.include_router(router)
        self.services.wire(modules=[sys.modules[__name__]], warn_unresolved=True)

    def client(self) -> httpx.AsyncClient:
        async def observed_app(scope: Scope, receive: Receive, send: Send) -> None:
            async def observed_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    self.events.append(f"response:{message['status']}")
                await send(message)

            await self.app(scope, receive, observed_send)

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=observed_app, raise_app_exceptions=False),
            base_url="http://test",
        )


@pytest.fixture
def transaction_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TransactionApp]:
    app = TransactionApp(monkeypatch)
    yield app
    app.services.unwire()


async def test_success_commits_and_closes_before_response(transaction_app: TransactionApp) -> None:
    async with transaction_app.client() as client:
        response = await client.get("/transaction/ok")

    assert response.status_code == 200
    assert transaction_app.stored == [1]
    assert transaction_app.events == ["1:open", "1:begin", "1:commit", "1:close", "response:200"]
    assert not transaction_app.repositories.session.initialized


@pytest.mark.parametrize(
    ("action", "status"), [("http_error", 403), ("app_error", 400), ("crash", 500), ("commit_error", 500)]
)
async def test_errors_roll_back_and_close(transaction_app: TransactionApp, action: str, status: int) -> None:
    async with transaction_app.client() as client:
        response = await client.get(f"/transaction/{action}")

    assert response.status_code == status
    assert transaction_app.stored == []
    assert transaction_app.events == ["1:open", "1:begin", "1:rollback", "1:close", f"response:{status}"]
    assert not transaction_app.repositories.session.initialized


async def test_concurrent_requests_use_distinct_sessions(transaction_app: TransactionApp) -> None:
    async with transaction_app.client() as client:
        responses = await asyncio.gather(client.get("/transaction/concurrent"), client.get("/transaction/concurrent"))

    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["session"] for response in responses} == {1, 2}
    assert sorted(transaction_app.stored) == [1, 2]
    assert all(session.closed for session in transaction_app.sessions)
    assert not transaction_app.repositories.session.initialized


async def test_sequential_requests_release_context(transaction_app: TransactionApp) -> None:
    async with transaction_app.client() as client:
        first = await client.get("/transaction/ok")
        second = await client.get("/transaction/ok")

    assert first.json()["session"] != second.json()["session"]
    assert transaction_app.stored == [1, 2]
    assert all(session.closed for session in transaction_app.sessions)


def test_all_api_routers_use_transactional_routes() -> None:
    for module in (servicing, yandex_accounts, yandex_auth):
        assert module.router.routes
        assert all(isinstance(route, transactional_route.TransactionalRoute) for route in module.router.routes)


def test_health_does_not_open_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from main import app

    def unexpected_session() -> None:
        pytest.fail("Health must not open a database session")

    monkeypatch.setattr(session_dependencies, "AsyncSessionLocal", unexpected_session)
    response = TestClient(app).get("/health")

    assert response.status_code == 200
