"""API-03: safe central errors after transaction rollback, including debug settings."""

import asyncio
import io
import logging
from typing import cast
from unittest.mock import AsyncMock, Mock

import h11
import pytest
from fastapi import HTTPException
from starlette.types import Message, Receive, Scope, Send
from uvicorn._types import ASGI3Application, HTTPScope
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from core.exceptions import AlreadyExistsError, AppError, ClientError
from main import app
from settings import settings
from tests.api.conftest import ACCOUNT_ID, AUTH_HEADERS, RuntimeApi

SECRET = "SECRET-handler-token-code"


@pytest.mark.parametrize("headers", AUTH_HEADERS)
@pytest.mark.parametrize("service", ["oauth", "accounts", "authorization", "metrica"])
@pytest.mark.parametrize(
    "error",
    [
        ClientError(SECRET),
        AlreadyExistsError(SECRET),
        AppError(SECRET),
        RuntimeError(SECRET),
        HTTPException(status_code=401, detail=SECRET, headers={"WWW-Authenticate": SECRET}),
        HTTPException(status_code=403, detail=SECRET),
        HTTPException(status_code=503, detail=SECRET),
    ],
)
async def test_exception_mapping(
    runtime_api: RuntimeApi,
    service: str,
    error: Exception,
    headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "debug", True)
    assert app.debug is False  # Development settings must never enable traceback responses.
    method, url, mock = {
        "oauth": ("post", "/api/auth/code", runtime_api.oauth.authenticate),
        "accounts": ("delete", f"/api/accounts/{ACCOUNT_ID}", runtime_api.accounts.delete_account),
        "authorization": ("get", f"/api/servicing/access-token/{ACCOUNT_ID}", runtime_api.authorization.get_token),
        "metrica": ("get", f"/api/metrica/counters?account_id={ACCOUNT_ID}", runtime_api.metrica.get_counters),
    }[service]
    mock.side_effect = error
    async with runtime_api.client() as client:
        response = await client.request(
            method, url, json={"code": "abc", "equestrian_id": str(ACCOUNT_ID)}, headers=headers
        )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert SECRET not in response.text + str(response.headers) + caplog.text + str(capsys.readouterr())
    assert "Traceback" not in response.text
    assert "request_failure category=" in caplog.text
    assert mock.call_count == 1
    runtime_api.assert_transaction(400, "rollback")


@pytest.mark.parametrize("headers", AUTH_HEADERS)
async def test_response_validation_is_safe_and_rolls_back(
    runtime_api: RuntimeApi,
    headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime_api.metrica.get_counters.return_value = {"total": SECRET, "items": []}
    async with runtime_api.client() as client:
        response = await client.get(f"/api/metrica/counters?account_id={ACCOUNT_ID}", headers=headers)
    assert response.status_code == 400
    assert SECRET not in response.text + caplog.text
    assert "category=response_validation" in caplog.text
    runtime_api.assert_transaction(400, "rollback")


def http_scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 1),
    }


async def test_uvicorn_unexpected_error_has_safe_response_and_server_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """BE-01: exercise real server rethrow/logging, not just ASGITransport."""
    cause_marker = "SECRET-chained-cause-marker"

    async def fail(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            raise ValueError(cause_marker)
        except ValueError as cause:
            raise RuntimeError(SECRET) from cause

    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    monkeypatch.setattr(route, "app", fail)
    monkeypatch.setattr(settings, "debug", True)
    assert app.debug is False
    stream = io.StringIO()
    server_logger = logging.Logger("test.uvicorn.hermetic")
    handler = logging.StreamHandler(stream)
    server_logger.addHandler(handler)
    transport = Mock()
    transport.is_closing.return_value = False
    flow = Mock()
    flow.write_paused = False
    cycle = RequestResponseCycle(
        scope=cast(HTTPScope, http_scope()),
        conn=h11.Connection(h11.SERVER),
        transport=transport,
        flow=flow,
        logger=server_logger,
        access_logger=server_logger,
        access_log=False,
        default_headers=[],
        message_event=asyncio.Event(),
        on_response=lambda: None,
    )
    try:
        # Starlette and Uvicorn use different static aliases for the same ASGI protocol.
        await cycle.run_asgi(cast(ASGI3Application, app))
        wire = b"".join(call.args[0] for call in transport.write.call_args_list)
        assert wire.split(b"\r\n", 1)[0] == b"HTTP/1.1 400 Bad Request"
        assert cycle.response_complete
        assert "category=unexpected" in caplog.text
        for marker in (SECRET, cause_marker, "Traceback"):
            assert marker not in wire.decode() + stream.getvalue() + caplog.text
        assert all(record.exc_info is None for record in caplog.records)
        # The server logger remains enabled and usable; it wasn't silenced by the fix.
        server_logger.error("server-diagnostic-probe")
        assert "server-diagnostic-probe" in stream.getvalue()
    finally:
        server_logger.removeHandler(handler)
        handler.close()


class ProcessFailure(BaseException):
    pass


@pytest.mark.parametrize("error", [asyncio.CancelledError(), ProcessFailure(), RuntimeError(SECRET)])
async def test_boundary_does_not_replace_started_response_or_base_exception(
    error: BaseException, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    messages: list[Message] = []

    async def fail(scope: Scope, receive: Receive, send: Send) -> None:
        if isinstance(error, Exception):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise error

    async def send(message: Message) -> None:
        messages.append(message)

    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    monkeypatch.setattr(route, "app", fail)
    with pytest.raises(type(error)) as caught:
        await app(http_scope(), AsyncMock(), send)
    assert caught.value is error
    starts = [message["status"] for message in messages if message["type"] == "http.response.start"]
    assert starts == ([200] if isinstance(error, Exception) else [])
    assert "category=unexpected" not in caplog.text
