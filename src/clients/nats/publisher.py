from core.entities.cleanup_outbox import CleanupOutboxClaim
from core.protocols.cleanup_outbox import CleanupTransportProtocol


class CleanupPublisher:
    def __init__(self, transport: CleanupTransportProtocol) -> None:
        self._transport = transport

    async def publish(self, *, claim: CleanupOutboxClaim) -> bool:
        return await self._transport.publish(
            subject=claim.subject,
            payload=claim.payload.model_dump_json().encode(),
            headers={"Nats-Msg-Id": str(claim.message_id), "Content-Type": "application/json"},
        )
