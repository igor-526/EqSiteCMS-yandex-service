"""UT-D-03/04: strict completed wire, commit-before-ACK, safe retry/TERM."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from nats.js.errors import BadRequestError, NotFoundError
from pydantic import ValidationError

from clients.nats.client import COMPLETED_DURABLE, RESULTS_STREAM, completed_consumer_config, lifecycle_stream_config
from clients.nats.consumer import CleanupCompletedConsumer
from core.entities.cleanup_outbox import CLEANUP_COMPLETED_SUBJECT, CleanupCompleted, InvalidCleanupResult
from repositories.metrica_lifecycle_repository import CleanupResultRepository
from tests.unit.test_nats_cleanup_runtime import client_fixture


def result_event(*, seq: int = 1, tenant: UUID | None = None, operation: UUID | None = None) -> CleanupCompleted:
    operation = operation or uuid4()
    return CleanupCompleted(
        schema_version=1,
        message_id=uuid5(NAMESPACE_URL, f"eqcms:maintenance:v1:{CLEANUP_COMPLETED_SUBJECT}:{operation}:completed"),
        operation_id=operation,
        equestrian_id=tenant or uuid4(),
        occurred_at=datetime.now(UTC),
        cleanup_seq=seq,
        status="completed",
    )


def delivery(event: CleanupCompleted | None = None, attempts: int = 1) -> MagicMock:
    event = event or result_event()
    return MagicMock(
        data=event.model_dump_json().encode(),
        headers={"Nats-Msg-Id": str(event.message_id)},
        metadata=MagicMock(num_delivered=attempts),
        ack=AsyncMock(),
        nak=AsyncMock(),
        term=AsyncMock(),
    )


async def test_ack_only_after_repository_commit_and_duplicate_replay() -> None:
    repo = AsyncMock()
    message = delivery()

    async def commit(**kwargs: object) -> None:
        message.ack.assert_not_awaited()
        assert len(str(kwargs["payload_hash"])) == 64

    repo.apply.side_effect = commit
    consumer = CleanupCompletedConsumer(AsyncMock(), repo)
    await consumer.process(message)
    message.ack.assert_awaited_once()
    repo.apply.side_effect = None
    await consumer.process(message)
    assert message.ack.await_count == 2 and repo.apply.await_count == 2
    message.nak.assert_not_awaited()
    message.term.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("message_id", str(uuid4())),
        ("cleanup_seq", 0),
        ("cleanup_seq", "1"),
        ("cleanup_seq", True),
        ("cleanup_seq", 9223372036854775808),
        ("status", "failed"),
        ("token", "never-log-me"),
        ("occurred_at", "2025-01-01T00:00:00+03:00"),
        ("occurred_at", "2025-01-01T00:00:00"),
        ("occurred_at", 1735689600),
        ("occurred_at", "2025-01-01 00:00:00Z"),
    ],
)
async def test_invalid_envelope_terms_without_storage(
    field: str, value: object, caplog: pytest.LogCaptureFixture
) -> None:
    repo = AsyncMock()
    payload = result_event().model_dump(mode="json")
    payload[field] = value
    message = delivery()
    message.data = json.dumps(payload).encode()
    await CleanupCompletedConsumer(AsyncMock(), repo).process(message)
    message.term.assert_awaited_once()
    message.ack.assert_not_awaited()
    repo.apply.assert_not_awaited()
    assert "never-log-me" not in caplog.text


async def test_missing_header_and_invalid_json_are_permanent() -> None:
    consumer = CleanupCompletedConsumer(AsyncMock(), AsyncMock())
    for message in (delivery(), delivery()):
        message.headers = None
        await consumer.process(message)
        message.term.assert_awaited_once()
    message = delivery()
    message.data = b"not-json"
    await consumer.process(message)
    message.term.assert_awaited_once()


async def test_unknown_foreign_seq_or_hash_conflict_term_without_ack(caplog: pytest.LogCaptureFixture) -> None:
    repo = AsyncMock()
    repo.apply.side_effect = InvalidCleanupResult("never-log-me")
    message = delivery()
    await CleanupCompletedConsumer(AsyncMock(), repo).process(message)
    message.term.assert_awaited_once()
    message.ack.assert_not_awaited()
    message.nak.assert_not_awaited()
    assert "never-log-me" not in caplog.text


@pytest.mark.parametrize("attempt,delay", [(1, 1), (2, 2), (5, 16), (7, 60), (9999, 60)])
async def test_commit_failure_naks_forever_with_bounded_backoff(
    attempt: int, delay: int, caplog: pytest.LogCaptureFixture
) -> None:
    repo = AsyncMock()
    repo.apply.side_effect = OSError("never-log-me")
    message = delivery(attempts=attempt)
    await CleanupCompletedConsumer(AsyncMock(), repo).process(message)
    message.nak.assert_awaited_once_with(delay=delay)
    message.ack.assert_not_awaited()
    message.term.assert_not_awaited()
    assert "never-log-me" not in caplog.text
    assert any(record.levelname == "ERROR" for record in caplog.records) is (attempt >= 5)


async def test_cancel_during_transaction_leaves_unacked_for_redelivery() -> None:
    repo = AsyncMock()
    repo.apply.side_effect = asyncio.CancelledError()
    message = delivery()
    with pytest.raises(asyncio.CancelledError):
        await CleanupCompletedConsumer(AsyncMock(), repo).process(message)
    message.ack.assert_not_awaited()
    message.nak.assert_not_awaited()


def setup_result_stream(js: AsyncMock) -> None:
    config = lifecycle_stream_config()
    config.name = RESULTS_STREAM
    config.subjects = [CLEANUP_COMPLETED_SUBJECT, "events.metrica.pages.merge.completed"]
    js.stream_info.return_value = MagicMock(config=config)
    js.consumer_info.return_value = MagicMock(config=completed_consumer_config())


async def test_foreign_stream_lookup_retries_only_not_found_then_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    client, js = client_fixture()
    setup_result_stream(js)
    info = js.stream_info.return_value
    js.stream_info.side_effect = [NotFoundError(), NotFoundError(), info]
    js.consumer_info.side_effect = NotFoundError()
    js.add_consumer.return_value = MagicMock(config=completed_consumer_config())
    await client.subscribe_completed()
    assert js.stream_info.await_count == 3
    js.add_stream.assert_not_awaited()
    js.update_stream.assert_not_awaited()
    js.add_consumer.assert_awaited_once_with(RESULTS_STREAM, config=completed_consumer_config())
    js.pull_subscribe_bind.assert_awaited_once_with(durable=COMPLETED_DURABLE, stream=RESULTS_STREAM)


async def test_foreign_stream_missing_is_bounded() -> None:
    client, js = client_fixture()
    js.stream_info.side_effect = NotFoundError()
    with pytest.raises(RuntimeError, match="lookup attempts exhausted"):
        await client.subscribe_completed()
    assert js.stream_info.await_count == 3
    js.add_stream.assert_not_awaited()


async def test_incompatible_durable_and_bad_request_fail_fast() -> None:
    client, js = client_fixture()
    setup_result_stream(js)
    js.consumer_info.return_value.config.max_deliver = 5
    with pytest.raises(ValueError, match="durable"):
        await client.subscribe_completed()
    assert js.stream_info.await_count == 1
    js.consumer_info.side_effect = BadRequestError(code=400)
    with pytest.raises(BadRequestError):
        await client.subscribe_completed()
    assert js.stream_info.await_count == 2


async def test_consumer_start_stop_and_ack_transport_failure_survives() -> None:
    transport = AsyncMock()
    subscription = transport.subscribe_completed.return_value
    entered = asyncio.Event()
    message = delivery()
    message.ack.side_effect = OSError("no ack")

    async def fetch(**kwargs: object) -> list[MagicMock]:
        entered.set()
        if message.ack.await_count == 0:
            return [message]
        await asyncio.Event().wait()
        return []

    subscription.fetch.side_effect = fetch
    consumer = CleanupCompletedConsumer(transport, AsyncMock())
    await consumer.start()
    await consumer.start()
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.sleep(0)
    assert consumer._task is not None and not consumer._task.done()
    await consumer.stop()
    await consumer.stop()
    transport.subscribe_completed.assert_awaited_once()
    subscription.unsubscribe.assert_awaited_once()


async def test_repository_unknown_tenant_rolls_back_without_inbox() -> None:
    session = AsyncMock()
    session.begin = MagicMock(return_value=AsyncMock())
    session.execute.return_value = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    with pytest.raises(InvalidCleanupResult):
        await CleanupResultRepository(factory).apply(event=result_event(), payload_hash="a" * 64)
    assert session.execute.await_count == 1
    assert session.begin.return_value.__aexit__.await_args.args[0] is InvalidCleanupResult


def test_result_contract_matches_asyncapi() -> None:
    from pathlib import Path

    import yaml  # type: ignore[import-untyped]

    document = yaml.safe_load((Path(__file__).parents[2] / "docs/asyncapi.yaml").read_text())
    schema = document["components"]["schemas"]["CleanupCompleted"]
    assert set(schema["required"]) == set(CleanupCompleted.model_fields)
    assert schema["additionalProperties"] is False
    assert document["channels"][CLEANUP_COMPLETED_SUBJECT]["x-consumers"][0]["durable"] == COMPLETED_DURABLE
    with pytest.raises(ValidationError):
        CleanupCompleted.model_validate({})


@pytest.mark.parametrize("prefix", [None, 1, 2])
async def test_repository_updates_only_own_ledger_prefix_in_one_transaction(prefix: int | None) -> None:
    from sqlalchemy.dialects import postgresql

    event = result_event()
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    state, operation, inserted, saved_hash, marked, contiguous, updated = [MagicMock() for _ in range(7)]
    state.mappings.return_value.first.return_value = {"cleanup_requested_seq": 3, "cleanup_completed_seq": 0}
    operation.mappings.return_value.first.return_value = {"id": event.operation_id}
    saved_hash.scalar_one.return_value = "a" * 64
    contiguous.scalar_one_or_none.return_value = prefix
    session.execute.side_effect = [state, operation, inserted, saved_hash, marked, contiguous, updated]
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    await CleanupResultRepository(factory).apply(event=event, payload_hash="a" * 64)
    calls = session.execute.await_args_list
    assert len(calls) == (6 if prefix is None else 7)
    statements = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in calls]
    assert "FOR UPDATE" in statements[0]
    assert "ON CONFLICT (consumer, message_id) DO NOTHING" in statements[2]
    assert "row_number() OVER" in statements[5] and "ordinal" in statements[5]
    if prefix is not None:
        params = calls[-1].args[0].compile().params
        assert params["cleanup_completed_seq"] == prefix
        assert event.equestrian_id in params.values()
    transaction.__aexit__.assert_awaited_once_with(None, None, None)


async def test_hash_conflict_rolls_back_before_marking_operation() -> None:
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    state, operation, inserted, saved_hash = [MagicMock() for _ in range(4)]
    state.mappings.return_value.first.return_value = {"cleanup_requested_seq": 2, "cleanup_completed_seq": 0}
    operation.mappings.return_value.first.return_value = {"id": uuid4()}
    saved_hash.scalar_one.return_value = "b" * 64
    session.execute.side_effect = [state, operation, inserted, saved_hash]
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    with pytest.raises(InvalidCleanupResult, match="hash conflict"):
        await CleanupResultRepository(factory).apply(event=result_event(), payload_hash="a" * 64)
    assert session.execute.await_count == 4
    assert transaction.__aexit__.await_args.args[0] is InvalidCleanupResult
