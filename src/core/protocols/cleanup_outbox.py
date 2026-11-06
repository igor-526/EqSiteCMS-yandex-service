from collections.abc import Sequence
from typing import Protocol

from core.entities.cleanup_outbox import CleanupCompleted, CleanupOutboxClaim


class CleanupOutboxRepositoryProtocol(Protocol):
    """Each call owns a short transaction; publishing never holds DB locks."""

    async def claim(self, *, lease_seconds: float) -> CleanupOutboxClaim | None: ...

    async def published(self, *, claim: CleanupOutboxClaim) -> bool: ...

    async def retry(self, *, claim: CleanupOutboxClaim, delay_seconds: float) -> bool: ...


class CleanupPublisherProtocol(Protocol):
    async def publish(self, *, claim: CleanupOutboxClaim) -> bool:
        """Await PubAck; return its duplicate flag, never an optimistic success.

        Must set Nats-Msg-Id to claim.message_id and enforce the owner stream.
        Raise on missing/invalid PubAck or any integration error.
        """
        ...


class CleanupTransportProtocol(Protocol):
    async def publish(self, *, subject: str, payload: bytes, headers: dict[str, str]) -> bool:
        """Await a validated owner-stream PubAck and return duplicate flag."""
        ...


class CleanupResultRepositoryProtocol(Protocol):
    async def apply(self, *, event: CleanupCompleted, payload_hash: str) -> None:
        """Commit inbox, own ledger completion and contiguous watermark atomically."""
        ...


class CleanupDeliveryMetadataProtocol(Protocol):
    @property
    def num_delivered(self) -> int: ...


class CleanupMessageProtocol(Protocol):
    @property
    def data(self) -> bytes: ...

    @property
    def headers(self) -> dict[str, str] | None: ...

    @property
    def metadata(self) -> CleanupDeliveryMetadataProtocol: ...

    async def ack(self) -> None: ...

    async def nak(self, delay: float | None = None) -> None: ...

    async def term(self) -> None: ...


class CleanupSubscriptionProtocol(Protocol):
    async def fetch(self, batch: int, timeout: float) -> Sequence[CleanupMessageProtocol]: ...  # noqa: ASYNC109

    async def unsubscribe(self) -> None: ...


class CleanupConsumerTransportProtocol(Protocol):
    async def subscribe_completed(self) -> CleanupSubscriptionProtocol: ...
