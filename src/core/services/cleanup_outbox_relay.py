import asyncio
import logging

from core.protocols.cleanup_outbox import CleanupOutboxRepositoryProtocol, CleanupPublisherProtocol

logger = logging.getLogger(__name__)


class CleanupOutboxRelay:
    def __init__(
        self,
        repository: CleanupOutboxRepositoryProtocol,
        publisher: CleanupPublisherProtocol,
        *,
        lease_seconds: float,
        poll_seconds: float,
        error_report_after_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._lease_seconds = lease_seconds
        self._poll_seconds = poll_seconds
        self._report_after = error_report_after_attempts

    async def run_once(self) -> bool:
        claim = await self._repository.claim(lease_seconds=self._lease_seconds)
        if claim is None:
            return False
        try:
            duplicate = await self._publisher.publish(claim=claim)
        except Exception:
            # Do not log exception text, payload or connection credentials.
            log = logger.error if claim.attempts == self._report_after else logger.warning
            log("cleanup_publish_retry message_id=%s attempts=%s", claim.message_id, claim.attempts)
            delay = 2 ** (claim.attempts - 1) if claim.attempts < 7 else 60
            await self._repository.retry(claim=claim, delay_seconds=delay)
            return True
        if duplicate:
            logger.warning("cleanup_puback_duplicate message_id=%s", claim.message_id)
        # Lost mark/commit or expired lease => another delivery of the SAME ID.
        if not await self._repository.published(claim=claim):
            logger.warning("cleanup_puback_stale_claim message_id=%s", claim.message_id)
        return True

    async def run(self) -> None:
        failures = 0
        while True:
            try:
                worked = await self.run_once()
                failures = 0
            except Exception:
                # Claim/mark DB failure: retain the row, allow lease recovery.
                failures += 1
                log = logger.error if failures == self._report_after else logger.warning
                log("cleanup_relay_storage_retry attempts=%s", failures)
                worked = False
            if not worked:
                await asyncio.sleep(self._poll_seconds)
            else:
                # Bound event-loop starvation when draining a large backlog.
                await asyncio.sleep(0)
