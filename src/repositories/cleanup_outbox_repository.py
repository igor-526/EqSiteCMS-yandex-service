from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.entities.cleanup_outbox import CleanupOutboxClaim, CleanupRequested
from models.metrica_lifecycle import metrica_lifecycle_outbox as outbox


class CleanupOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def claim(self, *, lease_seconds: float) -> CleanupOutboxClaim | None:
        async with self._sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        select(outbox)
                        .where(
                            outbox.c.status == "pending",
                            outbox.c.next_attempt_at <= func.now(),
                            or_(outbox.c.claim_token.is_(None), outbox.c.claim_expires_at <= func.now()),
                        )
                        .order_by(outbox.c.next_attempt_at, outbox.c.message_id)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            payload = CleanupRequested.model_validate(row["payload"])
            if payload.operation_id != row["operation_id"] or payload.equestrian_id != row["equestrian_id"]:
                raise ValueError("Outbox correlation mismatch")
            token = uuid4()
            expires_at = (
                await session.execute(
                    update(outbox)
                    .where(outbox.c.message_id == row["message_id"])
                    .values(
                        claim_token=token,
                        claim_expires_at=func.now() + timedelta(seconds=lease_seconds),
                        attempts=outbox.c.attempts + 1,
                    )
                    .returning(outbox.c.claim_expires_at)
                )
            ).scalar_one()
            return CleanupOutboxClaim(
                message_id=row["message_id"],
                claim_token=token,
                claim_expires_at=expires_at,
                attempts=row["attempts"] + 1,
                subject=row["subject"],
                payload=payload,
            )

    async def _finish(self, *, claim: CleanupOutboxClaim, published: bool, delay_seconds: float = 0) -> bool:
        async with self._sessions() as session, session.begin():
            values: dict[str, Any] = {"claim_token": None, "claim_expires_at": None}
            if published:
                values.update(status="published", published_at=func.now())
            else:
                values.update(next_attempt_at=func.now() + timedelta(seconds=delay_seconds))
            result = await session.execute(
                update(outbox)
                .where(
                    outbox.c.message_id == claim.message_id,
                    outbox.c.status == "pending",
                    outbox.c.claim_token == claim.claim_token,
                    outbox.c.claim_expires_at > func.now(),
                )
                .values(**values)
                .returning(outbox.c.message_id)
            )
            return result.scalar_one_or_none() is not None

    async def published(self, *, claim: CleanupOutboxClaim) -> bool:
        return await self._finish(claim=claim, published=True)

    async def retry(self, *, claim: CleanupOutboxClaim, delay_seconds: float) -> bool:
        return await self._finish(claim=claim, published=False, delay_seconds=delay_seconds)
