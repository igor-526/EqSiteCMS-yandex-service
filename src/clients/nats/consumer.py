import asyncio
import hashlib
import logging
from contextlib import suppress

from nats.errors import TimeoutError as NatsTimeoutError
from pydantic import ValidationError

from core.entities.cleanup_outbox import CleanupCompleted, InvalidCleanupResult
from core.protocols.cleanup_outbox import (
    CleanupConsumerTransportProtocol,
    CleanupMessageProtocol,
    CleanupResultRepositoryProtocol,
    CleanupSubscriptionProtocol,
)

logger = logging.getLogger(__name__)


class CleanupCompletedConsumer:
    def __init__(
        self,
        transport: CleanupConsumerTransportProtocol,
        repository: CleanupResultRepositoryProtocol,
        error_report_after_attempts: int = 5,
    ) -> None:
        self._transport = transport
        self._repository = repository
        self._report_after = error_report_after_attempts
        self._subscription: CleanupSubscriptionProtocol | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._subscription = await self._transport.subscribe_completed()
        self._task = asyncio.create_task(self._consume(), name="cleanup-completed-consumer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._subscription is not None:
            try:
                await self._subscription.unsubscribe()
            except Exception:
                logger.warning("cleanup_consumer_unsubscribe_failed")
            self._subscription = None

    async def process(self, message: CleanupMessageProtocol) -> None:
        try:
            if len(message.data) > 256 * 1024:
                raise InvalidCleanupResult("Cleanup envelope exceeds byte limit")
            event = CleanupCompleted.model_validate_json(message.data)
            if (message.headers or {}).get("Nats-Msg-Id") != str(event.message_id):
                raise InvalidCleanupResult("Cleanup header mismatch")
        except ValidationError, InvalidCleanupResult:
            logger.error("cleanup_result_rejected category=schema")
            await message.term()
            return
        try:
            # Canonical typed JSON hash: whitespace/key ordering is not a conflict.
            payload_hash = hashlib.sha256(event.model_dump_json().encode()).hexdigest()
            async with asyncio.timeout(25):  # below the durable ack_wait=30s
                await self._repository.apply(event=event, payload_hash=payload_hash)
        except InvalidCleanupResult:
            logger.error("cleanup_result_rejected category=correlation")
            await message.term()
            return
        except Exception:
            attempts = message.metadata.num_delivered
            log = logger.error if attempts >= self._report_after else logger.warning
            log("cleanup_result_retry attempts=%s", attempts)
            await message.nak(delay=min(60, 2 ** min(max(attempts - 1, 0), 6)))
            return
        # Repository returns only after transaction commit, including a duplicate.
        await message.ack()

    async def _consume(self) -> None:
        assert self._subscription is not None
        failures = 0
        while True:
            try:
                messages = await self._subscription.fetch(batch=1, timeout=1)
                for message in messages:
                    await self.process(message)
                failures = 0
            except NatsTimeoutError:
                continue
            except Exception:
                # Failed ACK/NAK/TERM is redelivered; do not lose the consumer task.
                failures += 1
                log = logger.error if failures >= self._report_after else logger.warning
                log("cleanup_consumer_retry attempts=%s", failures)
                await asyncio.sleep(min(60, 2 ** min(failures - 1, 6)))
