import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.entities.cleanup_outbox import CLEANUP_REQUESTED_SUBJECT, CleanupOutboxClaim, CleanupRequested
from core.services.cleanup_outbox_relay import CleanupOutboxRelay
from repositories.cleanup_outbox_repository import CleanupOutboxRepository
from settings import NatsSettings


def make_claim(*, attempts: int = 1) -> CleanupOutboxClaim:
    operation = uuid4()
    message_id = uuid5(NAMESPACE_URL, f"eqcms:maintenance:v1:{CLEANUP_REQUESTED_SUBJECT}:{operation}:requested")
    return CleanupOutboxClaim(
        message_id=message_id,
        claim_token=uuid4(),
        claim_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        attempts=attempts,
        subject=CLEANUP_REQUESTED_SUBJECT,
        payload=CleanupRequested(
            schema_version=1,
            message_id=message_id,
            operation_id=operation,
            equestrian_id=uuid4(),
            occurred_at=datetime.now(UTC),
            cleanup_seq=1,
            binding_generation=2,
            reason="counter_unlinked",
        ),
    )


def relay(repository: Any, publisher: Any) -> CleanupOutboxRelay:
    return CleanupOutboxRelay(repository, publisher, lease_seconds=30, poll_seconds=0.001)


async def test_puback_precedes_mark_and_duplicate_is_warning(caplog: pytest.LogCaptureFixture) -> None:
    claim = make_claim()
    repository = AsyncMock()
    repository.claim.return_value = claim
    publisher = AsyncMock()

    async def publish(**kwargs: Any) -> bool:
        repository.published.assert_not_awaited()
        assert kwargs["claim"] == claim
        return True

    publisher.publish.side_effect = publish
    assert await relay(repository, publisher).run_once()
    repository.published.assert_awaited_once_with(claim=claim)
    repository.retry.assert_not_awaited()
    assert "cleanup_puback_duplicate" in caplog.text


@pytest.mark.parametrize(("attempts", "delay"), [(1, 1), (2, 2), (5, 16), (7, 60), (100000, 60)])
async def test_timeout_retries_without_mark_or_payload_leak(
    attempts: int, delay: int, caplog: pytest.LogCaptureFixture
) -> None:
    claim = make_claim(attempts=attempts)
    repository = AsyncMock()
    repository.claim.return_value = claim
    publisher = AsyncMock()
    publisher.publish.side_effect = TimeoutError("sensitive connection diagnostic")
    assert await relay(repository, publisher).run_once()
    repository.published.assert_not_awaited()
    repository.retry.assert_awaited_once_with(claim=claim, delay_seconds=delay)
    assert "sensitive" not in caplog.text
    assert str(claim.payload.equestrian_id) not in caplog.text
    if attempts == 5:
        assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_lost_puback_and_restart_keep_the_exact_persisted_envelope() -> None:
    # Offline model of expired-claim recovery, not real PG/broker evidence.
    claim = make_claim()
    repository = AsyncMock()
    repository.claim.return_value = claim
    publisher = AsyncMock()
    publisher.publish.side_effect = [TimeoutError(), True]
    await relay(repository, publisher).run_once()
    restarted = relay(repository, publisher)
    await restarted.run_once()
    assert publisher.publish.await_args_list[0] == publisher.publish.await_args_list[1]
    repository.published.assert_awaited_once_with(claim=claim)


async def test_lost_mark_commit_leaves_message_for_retry() -> None:
    repository = AsyncMock()
    repository.claim.return_value = make_claim()
    repository.published.side_effect = RuntimeError("storage commit failed")
    publisher = AsyncMock()
    publisher.publish.return_value = False
    with pytest.raises(RuntimeError):
        await relay(repository, publisher).run_once()
    repository.retry.assert_not_awaited()


async def test_empty_queue_does_not_publish() -> None:
    repository = AsyncMock()
    repository.claim.return_value = None
    publisher = AsyncMock()
    assert not await relay(repository, publisher).run_once()
    publisher.publish.assert_not_awaited()


async def test_stop_during_publish_does_not_mark_or_release_live_claim() -> None:
    entered = asyncio.Event()
    repository = AsyncMock()
    repository.claim.return_value = make_claim()
    publisher = AsyncMock()

    async def wait(**kwargs: Any) -> bool:
        entered.set()
        await asyncio.Event().wait()
        return False

    publisher.publish.side_effect = wait
    task = asyncio.create_task(relay(repository, publisher).run())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    repository.published.assert_not_awaited()
    repository.retry.assert_not_awaited()


async def test_periodic_loop_recovers_after_storage_error(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock()
    recovered = asyncio.Event()

    async def claim(**kwargs: Any) -> None:
        if repository.claim.await_count == 1:
            raise RuntimeError("private database diagnostic")
        recovered.set()
        return None

    repository.claim.side_effect = claim
    task = asyncio.create_task(relay(repository, AsyncMock()).run())
    await asyncio.wait_for(recovered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "cleanup_relay_storage_retry" in caplog.text
    assert "private database" not in caplog.text


def repository_fixture() -> tuple[CleanupOutboxRepository, AsyncMock]:
    session = AsyncMock()
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return CleanupOutboxRepository(cast(async_sessionmaker[AsyncSession], factory)), session


async def test_repository_claim_skip_locked_expiry_and_committed_token() -> None:
    repository, session = repository_fixture()
    claim = make_claim()
    row = {
        "message_id": claim.message_id,
        "operation_id": claim.payload.operation_id,
        "equestrian_id": claim.payload.equestrian_id,
        "subject": claim.subject,
        "payload": claim.payload.model_dump(mode="json"),
        "attempts": 0,
    }
    selected = MagicMock()
    selected.mappings.return_value.first.return_value = row
    updated = MagicMock()
    updated.scalar_one.return_value = claim.claim_expires_at
    session.execute.side_effect = [selected, updated]
    result = await repository.claim(lease_seconds=30)
    assert result is not None and result.attempts == 1
    assert result.payload == claim.payload
    sql = str(session.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "claim_expires_at <= now()" in sql
    assert "next_attempt_at <= now()" in sql
    assert "LIMIT" in sql
    sql = str(session.execute.await_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "attempts=(metrica_lifecycle_outbox.attempts +" in sql
    session.begin.return_value.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.parametrize("published", [True, False])
async def test_repository_marks_are_fenced_by_token_status_and_unexpired_lease(published: bool) -> None:
    repository, session = repository_fixture()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    claim = make_claim()
    if published:
        assert not await repository.published(claim=claim)
    else:
        assert not await repository.retry(claim=claim, delay_seconds=4)
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "claim_token =" in sql and "claim_expires_at > now()" in sql and "status =" in sql
    assert "RETURNING" in sql
    assert statement.compile().params["message_id_1"] == claim.message_id


@pytest.mark.parametrize("patch", [{"schema_version": 2}, {"message_id": str(uuid4())}, {"token": "forbidden"}])
def test_envelope_rejects_incompatible_identity_and_extra_fields(patch: dict[str, Any]) -> None:
    data = make_claim().payload.model_dump(mode="json")
    data.update(patch)
    with pytest.raises(ValidationError):
        CleanupRequested.model_validate(data)


def test_settings_defaults_and_lease_constraint() -> None:
    # Match existing settings tests: plugin hides BaseSettings runtime kwargs.
    instantiate = cast(Callable[..., NatsSettings], NatsSettings)
    settings = instantiate(_env_file=None)
    assert settings.nats_setup_max_attempts == 10
    assert settings.nats_setup_backoff_seconds == 2
    with pytest.raises(ValidationError):
        instantiate(_env_file=None, NATS_RELAY_CLAIM_SECONDS=2, NATS_PUBLISH_TIMEOUT_SECONDS=5)
    with pytest.raises(ValidationError):
        instantiate(_env_file=None, NATS_SERVERS=" , ")


async def test_repository_empty_claim_is_noop() -> None:
    repository, session = repository_fixture()
    selected = MagicMock()
    selected.mappings.return_value.first.return_value = None
    session.execute.return_value = selected
    assert await repository.claim(lease_seconds=30) is None
    assert session.execute.await_count == 1


async def test_repository_rejects_foreign_tenant_without_updating_claim() -> None:
    repository, session = repository_fixture()
    claim = make_claim()
    selected = MagicMock()
    selected.mappings.return_value.first.return_value = {
        "payload": claim.payload.model_dump(mode="json"),
        "operation_id": claim.payload.operation_id,
        "equestrian_id": uuid4(),
    }
    session.execute.return_value = selected
    with pytest.raises(ValueError, match="Outbox correlation mismatch"):
        await repository.claim(lease_seconds=30)
    assert session.execute.await_count == 1
    assert session.begin.return_value.__aexit__.await_args.args[0] is ValueError


async def test_expired_mark_does_not_schedule_a_new_envelope(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock()
    repository.claim.return_value = make_claim()
    repository.published.return_value = False
    publisher = AsyncMock()
    publisher.publish.return_value = False
    assert await relay(repository, publisher).run_once()
    assert "cleanup_puback_stale_claim" in caplog.text
    repository.retry.assert_not_awaited()
