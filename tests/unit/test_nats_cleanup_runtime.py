import asyncio
from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from nats.errors import ConnectionReconnectingError
from nats.js.api import PubAck
from nats.js.errors import BadRequestError, NotFoundError, ServiceUnavailableError

from clients.nats.client import LIFECYCLE_STREAM, NatsJetstreamClient, lifecycle_stream_config
from clients.nats.publisher import CleanupPublisher
from settings import NatsSettings
from tests.unit.test_cleanup_outbox_relay import make_claim


def client_fixture(**kwargs: object) -> tuple[NatsJetstreamClient, AsyncMock]:
    instantiate = cast(Callable[..., NatsSettings], NatsSettings)
    settings = instantiate(_env_file=None, NATS_SETUP_BACKOFF_SECONDS=0, NATS_SETUP_MAX_ATTEMPTS=3, **kwargs)
    client = NatsJetstreamClient(settings)
    jetstream = AsyncMock()
    client._jetstream = jetstream
    return client, jetstream


async def test_owner_creates_only_its_missing_exact_stream() -> None:
    client, js = client_fixture()
    js.stream_info.side_effect = NotFoundError()
    js.add_stream.return_value = MagicMock(config=lifecycle_stream_config())
    await client.setup()
    js.stream_info.assert_awaited_once_with(LIFECYCLE_STREAM)
    config = js.add_stream.await_args.kwargs["config"]
    assert config == lifecycle_stream_config()
    assert config.discard == "new" and config.max_age == 0 and config.retention == "limits"
    js.update_stream.assert_not_called()
    js.add_consumer.assert_not_called()


async def test_restart_reuses_existing_stream_without_rewriting() -> None:
    client, js = client_fixture()
    js.stream_info.return_value = MagicMock(config=lifecycle_stream_config())
    await client.setup()
    await client.setup()
    js.add_stream.assert_not_called()
    js.update_stream.assert_not_called()


@pytest.mark.parametrize("field,value", [("subjects", ["wrong"]), ("discard", "old"), ("max_msgs", 100)])
async def test_incompatible_owner_config_fails_fast(field: str, value: object) -> None:
    client, js = client_fixture()
    config = lifecycle_stream_config()
    setattr(config, field, value)
    js.stream_info.return_value = MagicMock(config=config)
    with pytest.raises(ValueError, match="Incompatible"):
        await client.setup()
    js.update_stream.assert_not_called()


async def test_startup_retries_connection_and_setup_without_losing_intentions(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = client_fixture()
    connect = AsyncMock(side_effect=[OSError("sensitive URL"), None, None])
    setup = AsyncMock(side_effect=[ServiceUnavailableError(), None])
    close = AsyncMock()
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(client, "setup", setup)
    monkeypatch.setattr(client, "close", close)
    await client.start()
    assert connect.await_count == 3 and setup.await_count == 2 and close.await_count == 2


async def test_startup_exhaustion_is_bounded_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = client_fixture()
    connect = AsyncMock(side_effect=OSError("sensitive URL"))
    monkeypatch.setattr(client, "connect", connect)
    with pytest.raises(RuntimeError, match="startup attempts exhausted") as error:
        await client.start()
    assert connect.await_count == 3
    assert error.value.__suppress_context__


async def test_bad_stream_request_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = client_fixture()
    connect = AsyncMock()
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(client, "setup", AsyncMock(side_effect=BadRequestError(code=400)))
    with pytest.raises(BadRequestError):
        await client.start()
    assert connect.await_count == 1


async def test_initial_connect_is_bounded_but_runtime_reconnect_is_unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = client_fixture(NATS_CONNECT_TIMEOUT_SECONDS=0.01)
    connection = MagicMock()

    async def stuck(**kwargs: object) -> None:
        assert kwargs["max_reconnect_attempts"] == -1
        await asyncio.Event().wait()

    connection.connect = AsyncMock(side_effect=stuck)
    connection.close = AsyncMock()
    monkeypatch.setattr("clients.nats.client.NATS", lambda: connection)
    with pytest.raises(TimeoutError):
        await client.connect()
    await client.close(drain=False)
    connection.close.assert_awaited_once()


@pytest.mark.parametrize("duplicate", [False, True])
async def test_publisher_enforces_persisted_msg_id_owner_and_puback(duplicate: bool) -> None:
    client, js = client_fixture()
    js.publish.return_value = PubAck(stream=LIFECYCLE_STREAM, seq=1, duplicate=duplicate)
    claim = make_claim()
    assert await CleanupPublisher(client).publish(claim=claim) is duplicate
    args, kwargs = js.publish.await_args
    assert args == (claim.subject, claim.payload.model_dump_json().encode())
    assert kwargs["headers"]["Nats-Msg-Id"] == str(claim.message_id)
    assert kwargs["stream"] == LIFECYCLE_STREAM and kwargs["timeout"] == 5


@pytest.mark.parametrize("ack", [None, PubAck(stream="wrong", seq=1), PubAck(stream=LIFECYCLE_STREAM, seq=0)])
async def test_missing_or_invalid_puback_never_reports_success(ack: PubAck | None) -> None:
    client, js = client_fixture()
    js.publish.return_value = ack
    with pytest.raises((ValueError, AttributeError)):
        await CleanupPublisher(client).publish(claim=make_claim())


async def test_reconnect_shutdown_falls_back_to_close_without_secrets(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = client_fixture()
    connection = MagicMock(is_closed=False)
    connection.drain = AsyncMock(side_effect=ConnectionReconnectingError("sensitive"))
    connection.close = AsyncMock()
    client._connection = connection
    await client.close()
    await client.close()
    connection.close.assert_awaited_once()
    assert client._jetstream is None and client._connection is None
    assert "sensitive" not in caplog.text


async def test_connection_failure_escalates_once_and_resets(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = client_fixture(NATS_ERROR_REPORT_AFTER_ATTEMPTS=2)
    for _ in range(5):
        await client._on_error(OSError("sensitive"))
    assert sum(record.levelname == "ERROR" for record in caplog.records) == 1
    assert "sensitive" not in caplog.text
    await client._on_reconnected()
    assert client._failures == 0


async def test_startup_uses_linear_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    instantiate = cast(Callable[..., NatsSettings], NatsSettings)
    client = NatsJetstreamClient(instantiate(_env_file=None, NATS_SETUP_MAX_ATTEMPTS=3))
    monkeypatch.setattr(client, "connect", AsyncMock(side_effect=[TimeoutError(), TimeoutError(), None]))
    monkeypatch.setattr(client, "setup", AsyncMock())
    sleep = AsyncMock()
    monkeypatch.setattr("clients.nats.client.asyncio.sleep", sleep)
    await client.start()
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4]


def test_runtime_di_uses_independent_sessions_and_lifespan_scoped_relay() -> None:
    from containers import container
    from utils.database import AsyncSessionLocal

    first = container.cleanup_outbox_relay()
    second = container.cleanup_outbox_relay()
    assert first is not second
    assert first._publisher is second._publisher
    assert first._repository is second._repository
    assert container.cleanup_outbox_repository()._sessions is AsyncSessionLocal
    assert container.nats_client() is container.nats_client()
