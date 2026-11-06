"""Runtime producer lifecycle; no external network or database."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers

import main


async def test_real_lifespan_starts_relay_and_stops_before_client_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    relay = AsyncMock()
    consumer = AsyncMock()
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def run() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def client_close() -> None:
        assert stopped.is_set()
        consumer.stop.assert_awaited_once()

    async def database_close() -> None:
        client.close.assert_awaited_once()

    relay.run.side_effect = run
    client.close.side_effect = client_close
    close = AsyncMock(side_effect=database_close)
    monkeypatch.setattr(main, "close_database", close)
    with (
        main.container.nats_client.override(providers.Object(client)),
        main.container.cleanup_completed_consumer.override(providers.Object(consumer)),
        main.container.cleanup_outbox_relay.override(providers.Object(relay)),
    ):
        async with main.app.router.lifespan_context(main.app):
            await asyncio.wait_for(entered.wait(), timeout=1)
            client.start.assert_awaited_once()
            consumer.start.assert_awaited_once()
            close.assert_not_awaited()
            assert not hasattr(main.app.state, "container")
    close.assert_awaited_once_with()


async def test_startup_failure_cleans_client_and_database_without_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.start.side_effect = RuntimeError("startup failed")
    relay = AsyncMock()
    consumer = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(main, "close_database", close)
    with (
        main.container.nats_client.override(providers.Object(client)),
        main.container.cleanup_completed_consumer.override(providers.Object(consumer)),
        main.container.cleanup_outbox_relay.override(providers.Object(relay)),
        pytest.raises(RuntimeError, match="startup failed"),
    ):
        async with main.app.router.lifespan_context(main.app):
            pytest.fail("failed startup cannot serve requests")
    client.close.assert_awaited_once()
    close.assert_awaited_once()
    relay.run.assert_not_called()


async def test_consumer_setup_failure_prevents_serving_and_cleans_all(monkeypatch: pytest.MonkeyPatch) -> None:
    client, consumer, relay = AsyncMock(), AsyncMock(), AsyncMock()
    consumer.start.side_effect = RuntimeError("owner unavailable")
    close = AsyncMock()
    monkeypatch.setattr(main, "close_database", close)
    with (
        main.container.nats_client.override(providers.Object(client)),
        main.container.cleanup_completed_consumer.override(providers.Object(consumer)),
        main.container.cleanup_outbox_relay.override(providers.Object(relay)),
        pytest.raises(RuntimeError, match="owner unavailable"),
    ):
        async with main.app.router.lifespan_context(main.app):
            pytest.fail("consumer setup must gate startup")
    consumer.stop.assert_awaited_once()
    client.close.assert_awaited_once()
    close.assert_awaited_once()
    relay.run.assert_not_called()
