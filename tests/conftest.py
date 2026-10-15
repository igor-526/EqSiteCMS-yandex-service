"""Offline defaults must be set before pytest imports runtime modules."""

import os
import socket
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from dependency_injector import providers

# Override developer .env and exported runtime credentials deterministically.
TEST_ENV = {
    "ENVIRONMENT": "test",
    "DEBUG": "false",
    "APP_TITLE": "Yandex service tests",
    "SENTRY_ENABLED": "false",
    "SENTRY_DSN": "",
    "SENTRY_ENVIRONMENT": "test",
    "SENTRY_TRACES_SAMPLE_RATE": "0",
    "SENTRY_RELEASE": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_HOST": "database.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "test",
    "ENCRYPTION_SERVICE_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "YANDEX_APP_CLIENT_ID": "test-client-id",
    "YANDEX_APP_CLIENT_SECRET": "test-client-secret",
    "YANDEX_APP_REDIRECT_URI": "https://callback.example.test/oauth",
    "YA_METRTICA_SERVICE_URL": "https://metrica.example.test",
}
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def forbid_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow ASGI/MockTransport and Unix event-loop sockets, forbid TCP/DNS."""
    if request.node.get_closest_marker("infrastructure") is not None:
        return

    def no_dns(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Offline test attempted DNS; use ASGITransport or MockTransport")

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def no_connect(sock: socket.socket, address: Any) -> Any:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Offline test attempted TCP; use ASGITransport or MockTransport")
        return original_connect(sock, address)

    def no_connect_ex(sock: socket.socket, address: Any) -> Any:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Offline test attempted TCP; use ASGITransport or MockTransport")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", no_connect_ex)


@pytest.fixture(autouse=True)
def restore_runtime_overrides() -> Iterator[None]:
    """Restore overrides even when a test fails, without importing the app here."""
    main = sys.modules.get("main")
    app = getattr(main, "app", None)
    dependencies = dict(app.dependency_overrides) if app is not None else None
    containers = sys.modules.get("containers")
    snapshots: list[tuple[Any, tuple[Any, ...]]] = []
    if containers is not None:
        for name in ("settings_container", "clients_container", "repositories_container", "services_container"):
            container = getattr(containers, name, None)
            if container is not None:
                snapshots.extend(
                    (provider, provider.overridden)
                    for provider in container.traverse()
                    if not isinstance(provider, providers.DependenciesContainer)
                )
    yield
    for provider, overrides in snapshots:
        if provider.overridden == overrides:
            continue
        provider.reset_override()
        for override in overrides:
            provider.override(override)
    if app is not None and dependencies is not None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(dependencies)
