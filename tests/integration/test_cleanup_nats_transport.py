"""Real-broker producer gate: missing infrastructure is failure, never skip."""

import os
from collections.abc import Callable
from typing import cast
from uuid import uuid4

import pytest

from clients.nats import client as client_module
from clients.nats.client import NatsJetstreamClient
from settings import NatsSettings

pytestmark = pytest.mark.infrastructure


async def test_real_producer_setup_restart_and_duplicate_puback(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_NATS_URL")
    if not url:
        pytest.fail("TEST_NATS_URL must point to a dedicated JetStream test broker")
    suffix = uuid4().hex
    stream = f"Y2B2_{suffix}"
    subject = f"test.y2b2.{suffix}.cleanup.requested"
    monkeypatch.setattr(client_module, "LIFECYCLE_STREAM", stream)
    monkeypatch.setattr(client_module, "CLEANUP_REQUESTED_SUBJECT", subject)
    instantiate = cast(Callable[..., NatsSettings], NatsSettings)
    settings = instantiate(
        _env_file=None,
        NATS_SERVERS=url,
        NATS_SETUP_MAX_ATTEMPTS=2,
        NATS_SETUP_BACKOFF_SECONDS=0,
    )
    client = NatsJetstreamClient(settings)
    try:
        await client.start()
        headers = {"Nats-Msg-Id": str(uuid4())}
        assert not await client.publish(subject=subject, payload=b"{}", headers=headers)
        # Models PubAck received but published mark lost: same persisted ID after process restart.
        await client.close()
        await client.start()
        assert await client.publish(subject=subject, payload=b"{}", headers=headers)
        info = await client.jetstream.stream_info(stream)
        assert info.state.messages == 1
    finally:
        try:
            # Only this fixture's UUID-named stream, never production/shared resources.
            if client._jetstream is not None:
                await client.jetstream.delete_stream(stream)
        finally:
            await client.close()


async def test_real_completed_durable_ack_nak_term_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from clients.nats.consumer import CleanupCompletedConsumer
    from tests.unit.test_cleanup_completed import result_event

    url = os.environ.get("TEST_NATS_URL")
    if not url:
        pytest.fail("TEST_NATS_URL must point to a dedicated JetStream test broker")
    suffix = uuid4().hex
    stream = f"Y2C_{suffix}"
    subject = f"test.y2c.{suffix}.cleanup.completed"
    merge = f"test.y2c.{suffix}.merge.completed"
    durable = f"y2c-{suffix}"
    monkeypatch.setattr(client_module, "RESULTS_STREAM", stream)
    monkeypatch.setattr(client_module, "CLEANUP_COMPLETED_SUBJECT", subject)
    monkeypatch.setattr(client_module, "MERGE_COMPLETED_SUBJECT", merge)
    monkeypatch.setattr(client_module, "COMPLETED_DURABLE", durable)
    instantiate = cast(Callable[..., NatsSettings], NatsSettings)
    client = NatsJetstreamClient(
        instantiate(_env_file=None, NATS_SERVERS=url, NATS_SETUP_MAX_ATTEMPTS=2, NATS_SETUP_BACKOFF_SECONDS=0)
    )
    subscription = None
    try:
        async with asyncio.timeout(20):
            await client.connect()
            config = client_module.lifecycle_stream_config()
            config.name, config.subjects = stream, [subject, merge]
            config.duplicate_window = 0.1  # Test-only window: exercise replay beyond broker dedup.
            # Fixture acts as foreign owner only for its unique test stream.
            await client.jetstream.add_stream(config=config)
            subscription = await client.subscribe_completed()
            info = await client.jetstream.consumer_info(stream, durable)
            assert info.config.ack_wait == 30 and info.config.max_deliver == -1
            assert info.config.ack_policy == "explicit" and info.config.filter_subject == subject
            event = result_event()
            await client.jetstream.publish(
                subject, event.model_dump_json().encode(), headers={"Nats-Msg-Id": str(event.message_id)}
            )
            repo = AsyncMock()
            repo.apply.side_effect = OSError("transient storage failure")
            consumer = CleanupCompletedConsumer(client, repo)
            message = (await subscription.fetch(1, timeout=3))[0]
            await consumer.process(message)  # NAK 1 second, no ACK
            message = (await subscription.fetch(1, timeout=3))[0]
            assert message.metadata.num_delivered >= 2
            repo.apply.side_effect = None
            await consumer.process(message)
            await client.jetstream.publish(subject, b"{}")
            await consumer.process((await subscription.fetch(1, timeout=3))[0])  # TERM invalid
            await subscription.unsubscribe()
            subscription = None
            await client.close()
            await client.connect()
            subscription = await client.subscribe_completed()
            info = await client.jetstream.consumer_info(stream, durable)
            assert info.num_ack_pending == 0 and info.num_pending == 0
            # Replay the same valid identity beyond this fixture's broker dedup window.
            await asyncio.sleep(config.duplicate_window + 0.05)
            ack = await client.jetstream.publish(
                subject, event.model_dump_json().encode(), headers={"Nats-Msg-Id": str(event.message_id)}
            )
            assert not ack.duplicate
            await consumer.process((await subscription.fetch(1, timeout=3))[0])
            assert repo.apply.await_count == 3
    finally:
        try:
            if subscription is not None:
                await subscription.unsubscribe()
            if client._jetstream is not None:
                await client.jetstream.delete_stream(stream)
        finally:
            await client.close()
