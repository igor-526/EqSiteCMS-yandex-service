"""IT-D-01: isolated PostgreSQL schema, atomicity, cascade and lifecycle races."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.entities.cleanup_outbox import CleanupOutboxClaim, CleanupRequested
from core.services.cleanup_outbox_relay import CleanupOutboxRelay
from models import yandex_metrica_counters, yandex_user
from models.metrica_lifecycle import metrica_cleanup_operations, metrica_lifecycle_outbox, metrica_tenant_lifecycle
from repositories.cleanup_outbox_repository import CleanupOutboxRepository
from repositories.metrica_lifecycle_repository import MetricaLifecycleRepository
from tests.unit.test_metrica_lifecycle import TABLES, load_migration
from utils.basemodel import metadata

pytestmark = pytest.mark.infrastructure


@pytest.fixture
def require_lifecycle_database() -> None:
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("Dedicated TEST_DATABASE_URL is required for lifecycle PostgreSQL verification")


@pytest.fixture
async def lifecycle_engine(require_lifecycle_database: None, pg_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    async with pg_engine.begin() as connection:

        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                load_migration().upgrade()

        await connection.run_sync(upgrade)
    yield pg_engine


async def test_lifecycle_postgres_schema_matches_metadata(lifecycle_engine: AsyncEngine) -> None:
    async with lifecycle_engine.begin() as connection:

        def compare(conn):
            names = {table.name for table in TABLES}
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_object": lambda obj, name, type_, reflected, compare_to: (
                        type_ != "table" or name in names
                    ),
                    "compare_server_default": True,
                },
            )
            return compare_metadata(context, metadata)

        assert await connection.run_sync(compare) == []


async def test_lifecycle_postgres_backfill_and_empty_downgrade(
    require_lifecycle_database: None, pg_engine: AsyncEngine
) -> None:
    tenant, account_id = uuid4(), uuid4()
    async with pg_engine.begin() as connection:
        await connection.execute(
            insert(yandex_user).values(
                id=account_id,
                equestrian_id=tenant,
                yandex_id="test",
                yandex_login="test",
                display_name="Test",
                enc_access_token="fixture",
                enc_refresh_token="fixture",
            )
        )
        await connection.execute(
            insert(yandex_metrica_counters).values(
                equestrian_id=tenant,
                yandex_user_id=account_id,
                counter_id="42",
            )
        )

        def migrate(conn, direction):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(load_migration(), direction)()

        await connection.run_sync(migrate, "upgrade")
        row = (await connection.execute(select(metrica_tenant_lifecycle))).mappings().one()
        assert (row["binding_generation"], row["cleanup_requested_seq"], row["cleanup_completed_seq"]) == (1, 0, 0)
        # This fixture has not activated cleanup and is safe to downgrade/re-upgrade.
        await connection.run_sync(migrate, "downgrade")
        await connection.run_sync(migrate, "upgrade")


async def test_lifecycle_postgres_rollback_and_tenant_qualified_constraints(lifecycle_engine: AsyncEngine) -> None:
    tenant, other = uuid4(), uuid4()
    async with AsyncSession(lifecycle_engine) as session:
        repo = MetricaLifecycleRepository(session)
        await repo.lock_tenants(equestrian_ids=[tenant, other])
        await session.commit()
        operation = uuid4()
        await session.execute(
            update(metrica_tenant_lifecycle)
            .where(metrica_tenant_lifecycle.c.equestrian_id == tenant)
            .values(cleanup_requested_seq=1)
        )
        await session.execute(
            insert(metrica_cleanup_operations).values(
                id=operation,
                equestrian_id=tenant,
                binding_id=uuid4(),
                binding_generation=1,
                cleanup_seq=1,
                reason="counter_unlinked",
            )
        )
        await session.execute(
            insert(metrica_lifecycle_outbox).values(
                message_id=uuid4(),
                equestrian_id=tenant,
                operation_id=operation,
                subject="events.yandex.metrica.cleanup.requested",
                payload={"fixture": True},
            )
        )
        await session.rollback()
        assert (await repo.get(equestrian_id=tenant)).cleanup_requested_seq == 0
        assert not (await session.execute(select(metrica_cleanup_operations))).all()
        assert not (await session.execute(select(metrica_lifecycle_outbox))).all()
        await session.execute(
            insert(metrica_cleanup_operations).values(
                id=operation,
                equestrian_id=tenant,
                binding_id=uuid4(),
                binding_generation=1,
                cleanup_seq=1,
                reason="account_deleted",
            )
        )
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    insert(metrica_cleanup_operations).values(
                        id=uuid4(),
                        equestrian_id=tenant,
                        binding_id=uuid4(),
                        binding_generation=1,
                        cleanup_seq=1,
                        reason="counter_unlinked",
                    )
                )
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    insert(metrica_lifecycle_outbox).values(
                        message_id=uuid4(),
                        equestrian_id=other,
                        operation_id=operation,
                        subject="fixture",
                        payload={},
                    )
                )
        await session.commit()
    async with lifecycle_engine.connect() as connection:

        def downgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                load_migration().downgrade()

        with pytest.raises(DBAPIError, match="lifecycle history exists"):
            await connection.run_sync(downgrade)


async def test_lifecycle_postgres_concurrent_generation_and_watermark(lifecycle_engine: AsyncEngine) -> None:
    tenant = uuid4()
    async with AsyncSession(lifecycle_engine) as session:
        await MetricaLifecycleRepository(session).lock_tenants(equestrian_ids=[tenant])
        await session.execute(
            update(metrica_tenant_lifecycle)
            .where(metrica_tenant_lifecycle.c.equestrian_id == tenant)
            .values(cleanup_requested_seq=2, cleanup_completed_seq=1)
        )
        await session.commit()

    async def increment() -> int:
        async with AsyncSession(lifecycle_engine) as session:
            state = await MetricaLifecycleRepository(session).advance_generation(equestrian_id=tenant)
            await session.commit()
            return state.binding_generation

    assert sorted(await asyncio.wait_for(asyncio.gather(increment(), increment()), timeout=10)) == [1, 2]
    async with AsyncSession(lifecycle_engine) as session:
        state = await MetricaLifecycleRepository(session).get(equestrian_id=tenant)
        assert (state.binding_generation, state.cleanup_requested_seq, state.cleanup_completed_seq) == (2, 2, 1)


async def seed_lifecycle_binding(engine: AsyncEngine):
    from core.entities import YandexMetricaCounter

    tenant, account_id, unrelated = uuid4(), uuid4(), uuid4()
    async with AsyncSession(engine) as session:
        for ident in (account_id, unrelated):
            await session.execute(
                insert(yandex_user).values(
                    id=ident,
                    equestrian_id=tenant,
                    yandex_id=str(ident),
                    yandex_login="fixture",
                    display_name="Fixture",
                    enc_access_token="fixture",
                    enc_refresh_token="fixture",
                )
            )
        binding = YandexMetricaCounter(equestrian_id=tenant, yandex_user_id=account_id, counter_id="42")
        await MetricaLifecycleRepository(session).set_binding(counter=binding)
        await session.commit()
    return binding, unrelated


async def test_lifecycle_postgres_account_cascade_and_unrelated_account(lifecycle_engine: AsyncEngine) -> None:
    binding, unrelated = await seed_lifecycle_binding(lifecycle_engine)
    async with AsyncSession(lifecycle_engine) as session:
        repo = MetricaLifecycleRepository(session)
        await repo.delete_account(account_id=unrelated)
        await session.commit()
        assert (await session.execute(select(yandex_metrica_counters))).scalar_one() == binding.id
        assert not (await session.execute(select(metrica_cleanup_operations))).all()
        await repo.delete_account(account_id=binding.yandex_user_id)
        await session.commit()
        await repo.delete_account(account_id=binding.yandex_user_id)
        await session.commit()
        assert not (await session.execute(select(yandex_metrica_counters))).all()
        operation = (await session.execute(select(metrica_cleanup_operations))).mappings().one()
        assert operation["binding_id"] == binding.id and operation["reason"] == "account_deleted"
        assert (await session.execute(select(metrica_lifecycle_outbox))).mappings().one()["operation_id"] == operation[
            "id"
        ]
        assert (await repo.get(equestrian_id=binding.equestrian_id)).cleanup_requested_seq == 1


@pytest.mark.parametrize("delete_account", [False, True])
async def test_lifecycle_postgres_outbox_failure_rolls_back_delete_and_seq(
    lifecycle_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, delete_account: bool
) -> None:
    binding, _ = await seed_lifecycle_binding(lifecycle_engine)
    async with AsyncSession(lifecycle_engine) as session:
        execute = session.execute

        async def fail_outbox(statement, *args, **kwargs):
            if getattr(statement, "is_insert", False) and statement.table is metrica_lifecycle_outbox:
                raise RuntimeError("injected outbox failure")
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", fail_outbox)
        repo = MetricaLifecycleRepository(session)
        with pytest.raises(RuntimeError, match="injected outbox failure"):
            if delete_account:
                await repo.delete_account(account_id=binding.yandex_user_id)
            else:
                await repo.delete_binding(counter_id=binding.id)
        await session.rollback()
        assert (await session.execute(select(yandex_metrica_counters.c.id))).scalar_one() == binding.id
        assert (
            await session.execute(select(yandex_user.c.id).where(yandex_user.c.id == binding.yandex_user_id))
        ).scalar_one()
        assert (await repo.get(equestrian_id=binding.equestrian_id)).cleanup_requested_seq == 0
        assert not (await session.execute(select(metrica_cleanup_operations))).all()
        assert not (await session.execute(select(metrica_lifecycle_outbox))).all()


@pytest.mark.parametrize("cascade", [False, True])
async def test_lifecycle_postgres_concurrent_deletes_then_rebind_keeps_watermark(
    lifecycle_engine: AsyncEngine, cascade: bool
) -> None:
    binding, unrelated = await seed_lifecycle_binding(lifecycle_engine)

    async def delete_counter():
        async with AsyncSession(lifecycle_engine) as session:
            await MetricaLifecycleRepository(session).delete_binding(counter_id=binding.id)
            await session.commit()

    async def second_delete():
        if not cascade:
            await delete_counter()
            return
        async with AsyncSession(lifecycle_engine) as session:
            await MetricaLifecycleRepository(session).delete_account(account_id=binding.yandex_user_id)
            await session.commit()

    await asyncio.wait_for(asyncio.gather(delete_counter(), second_delete()), timeout=10)
    async with AsyncSession(lifecycle_engine) as session:
        repo = MetricaLifecycleRepository(session)
        assert len((await session.execute(select(metrica_cleanup_operations))).all()) == 1
        rebound = binding.model_copy(update={"id": uuid4(), "yandex_user_id": unrelated})
        await repo.set_binding(counter=rebound)
        await repo.set_binding(counter=rebound)  # identical POST does not advance generation
        await session.commit()
        state = await repo.get(equestrian_id=binding.equestrian_id)
        assert (state.binding_generation, state.cleanup_requested_seq, state.cleanup_completed_seq) == (2, 1, 0)
        await repo.delete_binding(counter_id=binding.id)  # stale UUID does not delete rebound
        await repo.delete_binding(counter_id=rebound.id)
        await session.commit()
        operations = (
            (
                await session.execute(
                    select(metrica_cleanup_operations).order_by(metrica_cleanup_operations.c.cleanup_seq)
                )
            )
            .mappings()
            .all()
        )
        assert [(op["cleanup_seq"], op["binding_generation"]) for op in operations] == [(1, 1), (2, 2)]
        assert len((await session.execute(select(metrica_lifecycle_outbox))).all()) == 2


async def test_lifecycle_postgres_rebind_waits_for_uncommitted_delete(lifecycle_engine: AsyncEngine) -> None:
    binding, _ = await seed_lifecycle_binding(lifecycle_engine)
    entered_lock = asyncio.Event()
    rebound = binding.model_copy(update={"id": uuid4(), "counter_id": "43"})

    async def rebind():
        async with AsyncSession(lifecycle_engine) as session:
            repo = MetricaLifecycleRepository(session)
            lock = repo.lock_tenants

            async def observed_lock(*, equestrian_ids):
                entered_lock.set()
                await lock(equestrian_ids=equestrian_ids)

            repo.lock_tenants = observed_lock
            await repo.set_binding(counter=rebound)
            await session.commit()

    async with AsyncSession(lifecycle_engine) as deleting:
        await MetricaLifecycleRepository(deleting).delete_binding(counter_id=binding.id)
        task = asyncio.create_task(rebind())
        try:
            await asyncio.wait_for(entered_lock.wait(), timeout=5)
            assert not task.done()
            await deleting.commit()
            await asyncio.wait_for(task, timeout=10)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with AsyncSession(lifecycle_engine) as session:
        state = await MetricaLifecycleRepository(session).get(equestrian_id=binding.equestrian_id)
        assert (state.binding_generation, state.cleanup_requested_seq, state.cleanup_completed_seq) == (2, 1, 0)
        assert (await session.execute(select(yandex_metrica_counters.c.id))).scalar_one() == rebound.id


async def test_lifecycle_postgres_binding_snapshot_survives_delete_and_rebind(lifecycle_engine: AsyncEngine) -> None:
    binding, _ = await seed_lifecycle_binding(lifecycle_engine)
    async with AsyncSession(lifecycle_engine) as session:
        repository = MetricaLifecycleRepository(session)
        pristine = await repository.get_binding_snapshot(equestrian_id=uuid4())
        assert pristine.counter is None and pristine.lifecycle.binding_generation == 0
        current = await repository.get_binding_snapshot(equestrian_id=binding.equestrian_id)
        assert current.counter == binding and current.lifecycle.binding_generation == 1
        await repository.delete_binding(counter_id=binding.id)
        await session.commit()
        deleted = await repository.get_binding_snapshot(equestrian_id=binding.equestrian_id)
        assert deleted.counter is None
        assert (deleted.lifecycle.binding_generation, deleted.lifecycle.cleanup_requested_seq) == (1, 1)
        rebound = binding.model_copy(update={"id": uuid4()})
        await repository.set_binding(counter=rebound)
        await session.commit()
        current = await repository.get_binding_snapshot(equestrian_id=binding.equestrian_id)
        assert current.counter == rebound
        assert (current.lifecycle.binding_generation, current.lifecycle.cleanup_requested_seq) == (2, 1)
        assert current.lifecycle.cleanup_completed_seq == 0


async def test_completed_out_of_order_duplicate_and_foreign_preserve_barrier(lifecycle_engine: AsyncEngine) -> None:
    from hashlib import sha256

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.entities.cleanup_outbox import InvalidCleanupResult
    from models.metrica_lifecycle import metrica_lifecycle_inbox
    from repositories.metrica_lifecycle_repository import CleanupResultRepository
    from tests.unit.test_cleanup_completed import result_event

    tenant, other = uuid4(), uuid4()
    operations = [uuid4(), uuid4(), uuid4()]
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await session.execute(
            insert(metrica_tenant_lifecycle).values(
                equestrian_id=tenant,
                binding_generation=4,
                cleanup_requested_seq=3,
            )
        )
        await session.execute(insert(metrica_tenant_lifecycle).values(equestrian_id=other))
        for seq, operation in enumerate(operations, 1):
            await session.execute(
                insert(metrica_cleanup_operations).values(
                    id=operation,
                    equestrian_id=tenant,
                    binding_id=uuid4(),
                    binding_generation=seq,
                    cleanup_seq=seq,
                    reason="counter_unlinked",
                )
            )
    repository = CleanupResultRepository(async_sessionmaker(lifecycle_engine))

    async def apply(event):
        await repository.apply(event=event, payload_hash=sha256(event.model_dump_json().encode()).hexdigest())

    async def watermark() -> int:
        async with AsyncSession(lifecycle_engine) as session:
            state = await MetricaLifecycleRepository(session).get(equestrian_id=tenant)
            assert state.binding_generation == 4 and state.cleanup_requested_seq == 3
            return state.cleanup_completed_seq

    second = result_event(seq=2, tenant=tenant, operation=operations[1])
    first = result_event(seq=1, tenant=tenant, operation=operations[0])
    await apply(second)
    assert await watermark() == 0
    await apply(first)
    assert await watermark() == 2  # seq=3 still gates a new generation
    await asyncio.gather(apply(first), apply(second))
    assert await watermark() == 2
    for invalid in (
        result_event(seq=3, tenant=tenant),
        result_event(seq=3, tenant=other, operation=operations[2]),
        result_event(seq=99, tenant=tenant, operation=operations[2]),
    ):
        with pytest.raises(InvalidCleanupResult):
            await apply(invalid)
    with pytest.raises(InvalidCleanupResult):
        await repository.apply(event=first, payload_hash="f" * 64)
    assert await watermark() == 2
    await apply(result_event(seq=3, tenant=tenant, operation=operations[2]))
    assert await watermark() == 3
    async with AsyncSession(lifecycle_engine) as session:
        assert len((await session.execute(select(metrica_lifecycle_inbox))).all()) == 3


async def test_completed_commit_failure_rolls_back_inbox_ledger_and_watermark(
    lifecycle_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import event as sqlalchemy_event
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from models.metrica_lifecycle import metrica_lifecycle_inbox
    from repositories.metrica_lifecycle_repository import CleanupResultRepository
    from tests.unit.test_cleanup_completed import result_event

    tenant, operation = uuid4(), uuid4()
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await session.execute(insert(metrica_tenant_lifecycle).values(equestrian_id=tenant, cleanup_requested_seq=1))
        await session.execute(
            insert(metrica_cleanup_operations).values(
                id=operation,
                equestrian_id=tenant,
                binding_id=uuid4(),
                binding_generation=1,
                cleanup_seq=1,
                reason="account_deleted",
            )
        )
    factory = async_sessionmaker(lifecycle_engine)

    def fail_commit(session):
        raise RuntimeError("injected commit failure")

    # Private test session class, not runtime/global Session events.
    from sqlalchemy.orm import Session

    class FailingSession(Session):
        pass

    sqlalchemy_event.listen(FailingSession, "before_commit", fail_commit)
    failing_factory = async_sessionmaker(lifecycle_engine, sync_session_class=FailingSession)
    event = result_event(tenant=tenant, operation=operation)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await CleanupResultRepository(failing_factory).apply(event=event, payload_hash="a" * 64)
    async with factory() as session:
        assert not (await session.execute(select(metrica_lifecycle_inbox))).all()
        assert (await session.execute(select(metrica_cleanup_operations.c.status))).scalar_one() == "pending"
        assert (await MetricaLifecycleRepository(session).get(equestrian_id=tenant)).cleanup_completed_seq == 0
    await CleanupResultRepository(factory).apply(event=event, payload_hash="a" * 64)


async def test_outbox_postgres_concurrent_claim_expiry_reclaim_and_fencing(lifecycle_engine: AsyncEngine) -> None:
    binding, _ = await seed_lifecycle_binding(lifecycle_engine)
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await MetricaLifecycleRepository(session).delete_binding(counter_id=binding.id)
    repo = CleanupOutboxRepository(async_sessionmaker(lifecycle_engine))
    claims = await asyncio.wait_for(asyncio.gather(repo.claim(lease_seconds=30), repo.claim(lease_seconds=30)), 5)
    assert sum(claim is not None for claim in claims) == 1
    first = next(claim for claim in claims if claim is not None)
    assert first.attempts == 1
    assert await repo.claim(lease_seconds=30) is None
    outbox = metrica_lifecycle_outbox
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await session.execute(
            update(outbox)
            .where(outbox.c.message_id == first.message_id)
            .values(claim_expires_at=func.now() - timedelta(seconds=1))
        )
    # Even the current token cannot finish after expiry, before another owner reclaims.
    assert not await repo.published(claim=first)
    assert not await repo.retry(claim=first, delay_seconds=0)
    second = await repo.claim(lease_seconds=30)
    assert second is not None
    assert (second.message_id, second.subject, second.payload) == (first.message_id, first.subject, first.payload)
    assert second.claim_token != first.claim_token and second.attempts == 2
    assert not await repo.published(claim=first)
    assert not await repo.retry(claim=first, delay_seconds=0)
    assert await repo.retry(claim=second, delay_seconds=60)
    assert await repo.claim(lease_seconds=30) is None
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await session.execute(
            update(outbox)
            .where(outbox.c.message_id == first.message_id)
            .values(next_attempt_at=func.now() - timedelta(seconds=1))
        )
    third = await repo.claim(lease_seconds=30)
    assert third is not None
    assert third.attempts == 3 and third.payload == first.payload and third.message_id == first.message_id
    assert await repo.published(claim=third)
    assert not await repo.published(claim=third)
    assert not await repo.retry(claim=third, delay_seconds=0)
    assert await repo.claim(lease_seconds=30) is None
    async with AsyncSession(lifecycle_engine) as session:
        row = (await session.execute(select(outbox))).mappings().one()
        assert row["status"] == "published" and row["published_at"] is not None
        assert row["claim_token"] is None and row["claim_expires_at"] is None


@pytest.mark.parametrize("duplicate", [False, True])
async def test_outbox_postgres_relay_marks_only_after_puback(lifecycle_engine: AsyncEngine, duplicate: bool) -> None:
    binding, _ = await seed_lifecycle_binding(lifecycle_engine)
    async with AsyncSession(lifecycle_engine) as session, session.begin():
        await MetricaLifecycleRepository(session).delete_binding(counter_id=binding.id)
    repo = CleanupOutboxRepository(async_sessionmaker(lifecycle_engine))
    outbox = metrica_lifecycle_outbox

    class Publisher:
        async def publish(self, *, claim: CleanupOutboxClaim) -> bool:
            # Real independent PG session: claim committed, no lock held during publish;
            # fake transport returns the PubAck result only after checking pending state.
            async with AsyncSession(lifecycle_engine) as session, session.begin():
                row = (await session.execute(select(outbox).with_for_update(nowait=True))).mappings().one()
                assert row["status"] == "pending" and row["published_at"] is None
                assert row["claim_token"] == claim.claim_token
                assert CleanupRequested.model_validate(row["payload"]) == claim.payload
            return duplicate

    relay = CleanupOutboxRelay(repo, Publisher(), lease_seconds=30, poll_seconds=0.01)
    assert await relay.run_once()
    assert not await relay.run_once()
    async with AsyncSession(lifecycle_engine) as session:
        row = (await session.execute(select(outbox))).mappings().one()
        assert row["status"] == "published" and row["published_at"] is not None
        assert row["claim_token"] is None and row["claim_expires_at"] is None
