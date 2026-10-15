"""Shared fakes that preserve HTTP request construction and scoped DI cleanup."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from dependency_injector import providers

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def mock_http_transport(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.AsyncClient]:
    """Patch only a client's module namespace; return clients for close assertions.

    Example: mock_http_transport(monkeypatch, oauth_module, handler).
    Production's async-with closes each client and its MockTransport.
    """
    clients: list[httpx.AsyncClient] = []

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        client = _REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    # Both clients import httpx as a module. Replacing that local reference avoids
    # modifying httpx.AsyncClient used by ASGI fixtures or the other client.
    namespace = vars(httpx).copy()
    namespace["AsyncClient"] = factory
    monkeypatch.setattr(module, "httpx", SimpleNamespace(**namespace))
    return clients


@contextmanager
def override_providers(overrides: Mapping[providers.Provider, Any]) -> Iterator[None]:
    """Use the wired runtime providers as keys, and fake instances as values."""
    with ExitStack() as stack:
        for provider, replacement in overrides.items():
            stack.enter_context(provider.override(providers.Object(replacement)))
        yield
