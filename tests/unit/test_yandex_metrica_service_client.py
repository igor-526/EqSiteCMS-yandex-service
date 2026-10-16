import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from clients import yandex_metrica_service_client as client_module
from clients.yandex_metrica_service_client import YaMetricaServiceClient
from core.exceptions import YandexClientException
from tests.helpers import mock_http_transport

EXPECTED_RESOURCE_URL = "https://metrica.test/api/RESOURCE"


@pytest.fixture
def client() -> YaMetricaServiceClient:
    return YaMetricaServiceClient(ya_metrica_service_url="https://metrica.test")


@pytest.mark.parametrize("request_timeout", [10.0, None, httpx.Timeout(3.0, connect=1.0)])
@pytest.mark.parametrize("body_kind", ["form", "json"])
async def test_generic_request_wire_contract(monkeypatch, client, request_timeout, body_kind: str) -> None:
    """UT-HTTP-03: assert the real request, including timeout extensions."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": "ok"})

    clients = mock_http_transport(monkeypatch, client_module, handler)
    kwargs = {body_kind if body_kind == "json" else "data": {"value": "a & b"}}
    result = await client.make_request(
        method="post",
        url="RESOURCE",
        params={"search": "a & b", "limit": 2},
        headers={"X-Test": "sent"},
        auth=httpx.BasicAuth("user", "secret"),
        request_timeout=request_timeout,
        **kwargs,
    )
    assert result == {"result": "ok"}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url).split("?")[0] == EXPECTED_RESOURCE_URL
    assert dict(request.url.params) == {"search": "a & b", "limit": "2"}
    assert request.headers["X-Test"] == "sent"
    assert request.headers["Authorization"] == "Basic dXNlcjpzZWNyZXQ="
    if body_kind == "form":
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert parse_qs(request.content.decode()) == {"value": ["a & b"]}
    else:
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"value": "a & b"}
    assert request.extensions["timeout"] == httpx.Timeout(request_timeout).as_dict()
    assert len(clients) == 1 and clients[0].is_closed


async def test_default_get_and_timeout(monkeypatch, client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.extensions["timeout"] == httpx.Timeout(10.0).as_dict()
        assert not request.content
        return httpx.Response(200, json={})

    clients = mock_http_transport(monkeypatch, client_module, handler)
    assert await client.make_request(url="RESOURCE") == {}
    assert clients[0].is_closed


@pytest.mark.parametrize("status", [199, 200, 299, 300, 400, 401, 403, 429, 500, 503])
@pytest.mark.parametrize("payload", [{}, {"error": "invalid_token", "error_description": "Expired"}])
async def test_status_boundaries_and_error_fields(monkeypatch, client, status: int, payload: dict) -> None:
    """UT-HTTP-04: JSON is decoded for every status, only 2xx succeeds."""
    clients = mock_http_transport(monkeypatch, client_module, lambda request: httpx.Response(status, json=payload))
    if 200 <= status < 300:
        assert await client.make_request(url="RESOURCE") == payload
    else:
        with pytest.raises(YandexClientException) as caught:
            await client.make_request(url="RESOURCE")
        assert caught.value.status == status
        assert caught.value.category == "http"
        assert caught.value.message == str(caught.value)
        assert "invalid_token" not in caught.value.message
        assert "Expired" not in caught.value.message
    assert clients[0].is_closed


@pytest.mark.parametrize("status", [200, 400])
@pytest.mark.parametrize("payload", [[], None, "text", 7, True])
async def test_non_dict_json_is_rejected(monkeypatch, client, status: int, payload) -> None:
    # Explicit content keeps null as JSON instead of an empty httpx response.
    clients = mock_http_transport(
        monkeypatch, client_module, lambda request: httpx.Response(status, content=json.dumps(payload))
    )
    with pytest.raises(YandexClientException) as caught:
        await client.make_request(url="RESOURCE")
    assert caught.value.status == status
    assert caught.value.category == ("response" if status == 200 else "http")
    assert clients[0].is_closed


@pytest.mark.parametrize("body", ["", "<html>secret-marker</html>"])
@pytest.mark.parametrize("status", [200, 199, 300, 400, 401, 403, 429, 500, 503])
async def test_invalid_json_is_normalized_after_close(monkeypatch, client, status: int, body: str) -> None:
    """UT-C-04/05: status takes precedence over decoding."""
    clients = mock_http_transport(monkeypatch, client_module, lambda request: httpx.Response(status, content=body))
    with pytest.raises(YandexClientException) as caught:
        await client.make_request(url="RESOURCE")
    assert caught.value.status == status
    assert caught.value.category == ("response" if status == 200 else "http")
    if status == 200:
        assert isinstance(caught.value.__cause__, json.JSONDecodeError)
    assert clients[0].is_closed


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
async def test_transport_error_is_normalized_and_closes(monkeypatch, client, error_type) -> None:
    """UT-C-02/03: all transport failures preserve their cause."""
    errors = []

    def handler(request: httpx.Request) -> httpx.Response:
        error = error_type("simulated transport failure", request=request)
        errors.append(error)
        raise error

    clients = mock_http_transport(monkeypatch, client_module, handler)
    with pytest.raises(YandexClientException) as caught:
        await client.make_request(url="RESOURCE")
    assert caught.value.__cause__ is errors[0]
    assert caught.value.status is None
    assert caught.value.category == ("timeout" if issubclass(error_type, httpx.TimeoutException) else "transport")
    assert clients[0].is_closed


@pytest.mark.parametrize("custom_query", [False, True])
async def test_counters_wire_query_and_dto(monkeypatch, client, custom_query: bool) -> None:
    """UT-HTTP-06: transport receives actual query parameters, including None."""
    expected = {"access_token": "token &+", "search": "", "limit": "20", "offset": "0"}
    if custom_query:
        expected.update(search="Сайт & тест", limit="5", offset="7")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (request.url.scheme, request.url.host, request.url.path) == (
            "https",
            "metrica.test",
            "/api/metrica/counters",
        )
        assert dict(request.url.params) == expected
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"total": 1, "items": [{"counter_id": 42, "site": "example.test"}]})

    clients = mock_http_transport(monkeypatch, client_module, handler)
    kwargs = {"search": "Сайт & тест", "limit": 5, "offset": 7} if custom_query else {}
    dto = await client.get_metrica_counters(access_token="token &+", **kwargs)
    assert dto.model_dump() == {"total": 1, "items": [{"counter_id": 42, "site": "example.test"}]}
    assert clients[0].is_closed


@pytest.mark.parametrize("payload", [{}, {"total": "bad"}, {"total": 1, "items": [{"counter_id": 42}]}])
async def test_counter_response_dto_validation(monkeypatch, client, payload: dict) -> None:
    clients = mock_http_transport(monkeypatch, client_module, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(YandexClientException) as caught:
        await client.get_metrica_counters(access_token="token")
    assert isinstance(caught.value.__cause__, ValidationError)
    assert caught.value.category == "response"
    assert clients[0].is_closed


async def test_counter_response_defaults_to_empty_items(monkeypatch, client) -> None:
    clients = mock_http_transport(monkeypatch, client_module, lambda request: httpx.Response(200, json={"total": 0}))
    dto = await client.get_metrica_counters(access_token="token")
    assert dto.total == 0 and dto.items == []
    assert clients[0].is_closed


@pytest.mark.parametrize("phase", ["construct", "enter", "request", "exit"])
@pytest.mark.parametrize("error_type", [RuntimeError, httpx.ReadTimeout])
async def test_lifecycle_failure(monkeypatch, client, phase, error_type) -> None:
    """UT-C-03: constructor, enter, request and close are within the boundary."""
    original = error_type("secret-marker")
    closed = []

    class LifecycleClient:
        async def __aenter__(self):
            if phase == "enter":
                raise original
            return self

        async def request(self, **kwargs):
            if phase == "request":
                raise original
            return httpx.Response(200, json={})

        async def __aexit__(self, *args):
            closed.append(True)
            if phase == "exit":
                raise original

    def factory(**kwargs):
        if phase == "construct":
            raise original
        return LifecycleClient()

    namespace = vars(httpx).copy()
    namespace["AsyncClient"] = factory
    monkeypatch.setattr(client_module, "httpx", SimpleNamespace(**namespace))
    with pytest.raises(YandexClientException) as caught:
        await client.make_request(url="RESOURCE")
    assert caught.value.__cause__ is original
    assert caught.value.status == (200 if phase == "exit" else None)
    assert "secret-marker" not in str(caught.value)
    assert bool(closed) == (phase in {"request", "exit"})


@pytest.mark.parametrize("original", [asyncio.CancelledError(), BaseException("system"), YandexClientException(403)])
async def test_request_cancellation_and_typed_failure(monkeypatch, client, original) -> None:
    """UT-C-08: cancellation/system errors and already typed failures retain identity."""

    def handler(request):
        raise original

    clients = mock_http_transport(monkeypatch, client_module, handler)
    with pytest.raises(type(original)) as caught:
        await client.make_request(url="RESOURCE")
    assert caught.value is original
    assert clients[0].is_closed


@pytest.mark.parametrize("kind", ["http", "json", "transport", "dto"])
async def test_safe_diagnostics(monkeypatch, client, caplog, capsys, kind) -> None:
    """UT-C-09: body, URL, token, exception and invalid DTO are never printed."""
    marker = "secret-marker"

    def handler(request):
        if kind == "transport":
            raise httpx.ConnectError(marker, request=request)
        if kind == "json":
            return httpx.Response(200, content=marker)
        if kind == "dto":
            return httpx.Response(200, json={"total": marker, "access_token": marker})
        return httpx.Response(400, json={"error": marker, "error_description": marker})

    clients = mock_http_transport(monkeypatch, client_module, handler)
    with pytest.raises(YandexClientException) as caught:
        await client.get_metrica_counters(access_token="secret-marker")
    assert marker not in caught.value.message
    assert marker not in str(caught.value)
    assert marker not in repr(caught.value)
    assert marker not in caplog.text
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert clients[0].is_closed


@pytest.mark.parametrize(
    "original", [asyncio.CancelledError(), YandexClientException(None), RuntimeError("secret-marker")]
)
async def test_high_level_boundary(monkeypatch, client, original) -> None:
    """UT-C-08: high-level methods also guard ordinary failures without double wrapping."""
    monkeypatch.setattr(client, "make_request", AsyncMock(side_effect=original))
    expected_type = type(original) if not isinstance(original, RuntimeError) else YandexClientException
    with pytest.raises(expected_type) as caught:
        await client.get_metrica_counters(access_token="secret-marker")
    if isinstance(original, RuntimeError):
        assert caught.value.__cause__ is original
    else:
        assert caught.value is original
