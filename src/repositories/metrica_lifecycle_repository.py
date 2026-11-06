from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.entities import YandexMetricaCounter
from core.entities.cleanup_outbox import CleanupCompleted, InvalidCleanupResult
from core.entities.metrica_lifecycle import MetricaBindingSnapshot, MetricaTenantLifecycle
from core.exceptions import ClientError
from models import yandex_metrica_counters, yandex_user
from models.metrica_lifecycle import (
    metrica_cleanup_operations,
    metrica_lifecycle_inbox,
    metrica_lifecycle_outbox,
    metrica_tenant_lifecycle,
)


class MetricaLifecycleRepository:
    """Transactional lifecycle mutations; commit belongs to the request boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, equestrian_id: UUID) -> MetricaTenantLifecycle:
        row = (
            (
                await self.session.execute(
                    select(metrica_tenant_lifecycle).where(metrica_tenant_lifecycle.c.equestrian_id == equestrian_id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return MetricaTenantLifecycle(equestrian_id=equestrian_id)
        return MetricaTenantLifecycle.model_validate(dict(row))

    async def get_binding_snapshot(self, *, equestrian_id: UUID) -> MetricaBindingSnapshot:
        # One statement / MVCC snapshot: never pair an old counter with a new
        # generation during DELETE -> rebind. The anchor covers pristine tenants.
        tenant = select(literal(equestrian_id).label("equestrian_id")).subquery()
        lifecycle = metrica_tenant_lifecycle
        binding = yandex_metrica_counters
        row = (
            (
                await self.session.execute(
                    select(
                        lifecycle.c.binding_generation,
                        lifecycle.c.cleanup_requested_seq,
                        lifecycle.c.cleanup_completed_seq,
                        *binding.c,
                    ).select_from(
                        tenant.outerjoin(lifecycle, lifecycle.c.equestrian_id == tenant.c.equestrian_id).outerjoin(
                            binding, binding.c.equestrian_id == tenant.c.equestrian_id
                        )
                    )
                )
            )
            .mappings()
            .one()
        )
        counter = None
        if row["id"] is not None:
            if row["binding_generation"] is None:
                raise ClientError("Состояние привязки недоступно")
            counter = YandexMetricaCounter.model_validate({column.name: row[column.name] for column in binding.c})
        return MetricaBindingSnapshot(
            lifecycle=MetricaTenantLifecycle(
                equestrian_id=equestrian_id,
                binding_generation=row["binding_generation"] or 0,
                cleanup_requested_seq=row["cleanup_requested_seq"] or 0,
                cleanup_completed_seq=row["cleanup_completed_seq"] or 0,
            ),
            counter=counter,
        )

    async def lock_tenants(self, *, equestrian_ids: Sequence[UUID]) -> None:
        # Insert one at a time in the same sorted order too: concurrent INSERT
        # ON CONFLICT can wait on another transaction before SELECT FOR UPDATE.
        for equestrian_id in sorted(set(equestrian_ids)):
            await self.session.execute(
                insert(metrica_tenant_lifecycle)
                .values(equestrian_id=equestrian_id)
                .on_conflict_do_nothing(index_elements=[metrica_tenant_lifecycle.c.equestrian_id])
            )
            await self.session.execute(
                select(metrica_tenant_lifecycle.c.equestrian_id)
                .where(metrica_tenant_lifecycle.c.equestrian_id == equestrian_id)
                .with_for_update()
            )

    async def advance_generation(self, *, equestrian_id: UUID) -> MetricaTenantLifecycle:
        await self.lock_tenants(equestrian_ids=[equestrian_id])
        row = (
            (
                await self.session.execute(
                    update(metrica_tenant_lifecycle)
                    .where(metrica_tenant_lifecycle.c.equestrian_id == equestrian_id)
                    .values(binding_generation=metrica_tenant_lifecycle.c.binding_generation + 1)
                    .returning(metrica_tenant_lifecycle)
                )
            )
            .mappings()
            .one()
        )
        return MetricaTenantLifecycle.model_validate(dict(row))

    async def set_binding(self, *, counter: YandexMetricaCounter) -> YandexMetricaCounter:
        await self.lock_tenants(equestrian_ids=[counter.equestrian_id])
        # Same lock order as cascade: tenant(s), account, then binding.
        account = (
            await self.session.execute(
                select(yandex_user.c.id).where(yandex_user.c.id == counter.yandex_user_id).with_for_update()
            )
        ).first()
        if account is None:
            raise ClientError("Аккаунт не найден")
        existing = (
            (
                await self.session.execute(
                    select(yandex_metrica_counters)
                    .where(yandex_metrica_counters.c.equestrian_id == counter.equestrian_id)
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            current = YandexMetricaCounter.model_validate(dict(existing))
            if (current.counter_id, current.yandex_user_id) == (counter.counter_id, counter.yandex_user_id):
                return current
            counter = current.model_copy(
                update={
                    "counter_id": counter.counter_id,
                    "yandex_user_id": counter.yandex_user_id,
                    "updated_at": datetime.now(UTC),
                }
            )
            await self.session.execute(
                update(yandex_metrica_counters)
                .where(yandex_metrica_counters.c.id == counter.id)
                .values(**counter.model_dump())
            )
        else:
            await self.session.execute(insert(yandex_metrica_counters).values(**counter.model_dump()))
        await self.advance_generation(equestrian_id=counter.equestrian_id)
        return counter

    async def _request_cleanup(self, *, counter: YandexMetricaCounter, reason: str) -> None:
        # Caller holds the tenant lock and has re-read the actual binding.
        state = await self.get(equestrian_id=counter.equestrian_id)
        operation_id = uuid4()
        seq = state.cleanup_requested_seq + 1
        await self.session.execute(
            update(metrica_tenant_lifecycle)
            .where(metrica_tenant_lifecycle.c.equestrian_id == counter.equestrian_id)
            .values(cleanup_requested_seq=seq)
        )
        await self.session.execute(
            insert(metrica_cleanup_operations).values(
                id=operation_id,
                equestrian_id=counter.equestrian_id,
                binding_id=counter.id,
                binding_generation=state.binding_generation,
                cleanup_seq=seq,
                reason=reason,
            )
        )
        subject = "events.yandex.metrica.cleanup.requested"
        message_id = uuid5(NAMESPACE_URL, f"eqcms:maintenance:v1:{subject}:{operation_id}:requested")
        await self.session.execute(
            insert(metrica_lifecycle_outbox).values(
                message_id=message_id,
                equestrian_id=counter.equestrian_id,
                operation_id=operation_id,
                subject=subject,
                payload={
                    "schema_version": 1,
                    "message_id": str(message_id),
                    "operation_id": str(operation_id),
                    "equestrian_id": str(counter.equestrian_id),
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "cleanup_seq": seq,
                    "binding_generation": state.binding_generation,
                    "reason": reason,
                },
            )
        )

    async def delete_binding(self, *, counter_id: UUID) -> None:
        tenant = (
            await self.session.execute(
                select(yandex_metrica_counters.c.equestrian_id).where(yandex_metrica_counters.c.id == counter_id)
            )
        ).scalar_one_or_none()
        if tenant is None:
            return
        await self.lock_tenants(equestrian_ids=[tenant])
        row = (
            (
                await self.session.execute(
                    select(yandex_metrica_counters).where(yandex_metrica_counters.c.id == counter_id).with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return
        await self._request_cleanup(counter=YandexMetricaCounter.model_validate(dict(row)), reason="counter_unlinked")
        await self.session.execute(delete(yandex_metrica_counters).where(yandex_metrica_counters.c.id == counter_id))

    async def _account_bindings(self, account_id: UUID) -> list[YandexMetricaCounter]:
        rows = (
            (
                await self.session.execute(
                    select(yandex_metrica_counters).where(yandex_metrica_counters.c.yandex_user_id == account_id)
                )
            )
            .mappings()
            .all()
        )
        return [YandexMetricaCounter.model_validate(dict(row)) for row in rows]

    async def delete_account(self, *, account_id: UUID) -> None:
        # Discovery is not authoritative: a rebind may commit before account lock.
        # On an expanded tenant set, release savepoint locks and retry in UUID order.
        # This also handles legacy cross-tenant FK bindings without changing access policy.
        while True:
            async with self.session.begin_nested() as attempt:
                bindings = await self._account_bindings(account_id)
                tenants = {counter.equestrian_id for counter in bindings}
                await self.lock_tenants(equestrian_ids=list(tenants))
                account = (
                    await self.session.execute(
                        select(yandex_user.c.id).where(yandex_user.c.id == account_id).with_for_update()
                    )
                ).first()
                if account is None:
                    return
                bindings = await self._account_bindings(account_id)
                if not {counter.equestrian_id for counter in bindings}.issubset(tenants):
                    await attempt.rollback()
                    continue
                for counter in bindings:
                    await self._request_cleanup(counter=counter, reason="account_deleted")
                # Account row lock prevents new FK references; tenant locks prevent
                # concurrent binding deletion/rebind until ledger + cascade commit.
                await self.session.execute(delete(yandex_user).where(yandex_user.c.id == account_id))
                return


class CleanupResultRepository:
    CONSUMER = "yandex-metrica-cleanup-completed"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def apply(self, *, event: CleanupCompleted, payload_hash: str) -> None:
        async with self._sessions() as session, session.begin():
            lifecycle = metrica_tenant_lifecycle
            operations = metrica_cleanup_operations
            inbox = metrica_lifecycle_inbox
            # Same tenant lock as DELETE/rebind; never create state for an unknown result.
            state = (
                (
                    await session.execute(
                        select(lifecycle).where(lifecycle.c.equestrian_id == event.equestrian_id).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if state is None:
                raise InvalidCleanupResult("Unknown cleanup tenant")
            operation = (
                (
                    await session.execute(
                        select(operations).where(
                            operations.c.id == event.operation_id,
                            operations.c.equestrian_id == event.equestrian_id,
                            operations.c.cleanup_seq == event.cleanup_seq,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if operation is None or event.cleanup_seq > state["cleanup_requested_seq"]:
                raise InvalidCleanupResult("Cleanup correlation mismatch")
            await session.execute(
                insert(inbox)
                .values(
                    consumer=self.CONSUMER,
                    message_id=event.message_id,
                    equestrian_id=event.equestrian_id,
                    operation_id=event.operation_id,
                    payload_hash=payload_hash,
                )
                .on_conflict_do_nothing(index_elements=[inbox.c.consumer, inbox.c.message_id])
            )
            saved_hash = (
                await session.execute(
                    select(inbox.c.payload_hash).where(
                        inbox.c.consumer == self.CONSUMER,
                        inbox.c.message_id == event.message_id,
                    )
                )
            ).scalar_one()
            if saved_hash != payload_hash:
                raise InvalidCleanupResult("Cleanup inbox hash conflict")
            await session.execute(
                update(operations)
                .where(
                    operations.c.id == event.operation_id,
                    operations.c.status == "pending",
                )
                .values(status="completed", completed_at=func.now())
            )
            # Number only completed rows after the watermark. Once a missing/pending
            # seq is encountered, seq != watermark + ordinal for all later rows.
            completed = (
                select(
                    operations.c.cleanup_seq,
                    func.row_number().over(order_by=operations.c.cleanup_seq).label("ordinal"),
                )
                .where(
                    operations.c.equestrian_id == event.equestrian_id,
                    operations.c.status == "completed",
                    operations.c.cleanup_seq > state["cleanup_completed_seq"],
                    operations.c.cleanup_seq <= state["cleanup_requested_seq"],
                )
                .subquery()
            )
            prefix = (
                await session.execute(
                    select(func.max(completed.c.cleanup_seq)).where(
                        completed.c.cleanup_seq == state["cleanup_completed_seq"] + completed.c.ordinal,
                    )
                )
            ).scalar_one_or_none()
            if prefix is not None:
                await session.execute(
                    update(lifecycle)
                    .where(
                        lifecycle.c.equestrian_id == event.equestrian_id,
                    )
                    .values(cleanup_completed_seq=prefix)
                )
