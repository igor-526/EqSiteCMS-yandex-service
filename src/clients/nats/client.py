import asyncio
import logging
from math import ceil

from nats import NATS
from nats.errors import Error as NatsError
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    DiscardPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.client import JetStreamContext
from nats.js.errors import APIError, NotFoundError

from core.entities.cleanup_outbox import CLEANUP_COMPLETED_SUBJECT, CLEANUP_REQUESTED_SUBJECT
from settings import NatsSettings

logger = logging.getLogger(__name__)
LIFECYCLE_STREAM = "YANDEX_LIFECYCLE"
RESULTS_STREAM = "METRICA_MAINTENANCE_RESULTS"
MERGE_COMPLETED_SUBJECT = "events.metrica.pages.merge.completed"
COMPLETED_DURABLE = "yandex-metrica-cleanup-completed"


def completed_consumer_config() -> ConsumerConfig:
    return ConsumerConfig(
        durable_name=COMPLETED_DURABLE,
        filter_subject=CLEANUP_COMPLETED_SUBJECT,
        deliver_policy=DeliverPolicy.ALL,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=30,
        max_deliver=-1,
    )


def lifecycle_stream_config() -> StreamConfig:
    return StreamConfig(
        name=LIFECYCLE_STREAM,
        subjects=[CLEANUP_REQUESTED_SUBJECT],
        storage=StorageType.FILE,
        retention=RetentionPolicy.LIMITS,
        discard=DiscardPolicy.NEW,
        max_age=0,
        max_msgs=-1,
        max_bytes=-1,
        duplicate_window=120,
    )


class NatsJetstreamClient:
    def __init__(self, settings: NatsSettings) -> None:
        self._settings = settings
        self._connection: NATS | None = None
        self._jetstream: JetStreamContext | None = None
        self._failures = 0

    @property
    def jetstream(self) -> JetStreamContext:
        if self._jetstream is None:
            raise RuntimeError("NATS JetStream is not initialized")
        return self._jetstream

    async def _on_error(self, error: Exception) -> None:
        # Never log exception text: server URLs may include credentials.
        self._failures += 1
        log = logger.error if self._failures == self._settings.nats_error_report_after_attempts else logger.warning
        log("nats_connection_retry attempts=%s", self._failures)

    async def _on_reconnected(self) -> None:
        self._failures = 0
        logger.info("nats_reconnected")

    async def connect(self) -> None:
        if self._connection is not None and self._connection.is_connected:
            return
        self._connection = NATS()
        async with asyncio.timeout(self._settings.nats_connect_timeout_seconds):
            await self._connection.connect(
                servers=self._settings.nats_servers,
                name="yandex-service",
                connect_timeout=ceil(self._settings.nats_connect_timeout_seconds),
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                drain_timeout=5,
                error_cb=self._on_error,
                reconnected_cb=self._on_reconnected,
            )
        self._jetstream = self._connection.jetstream()
        self._failures = 0

    async def setup(self) -> None:
        expected = lifecycle_stream_config()
        try:
            actual = (await self.jetstream.stream_info(LIFECYCLE_STREAM)).config
        except NotFoundError:
            actual = (await self.jetstream.add_stream(config=expected)).config
        # Do not silently rewrite an incompatible stream or touch foreign streams.
        fields = (
            "name",
            "subjects",
            "storage",
            "retention",
            "discard",
            "max_age",
            "max_msgs",
            "max_bytes",
            "duplicate_window",
            "max_msgs_per_subject",
            "max_msg_size",
            "no_ack",
            "sealed",
        )
        if any(getattr(actual, field) != getattr(expected, field) for field in fields):
            raise ValueError("Incompatible YANDEX_LIFECYCLE stream")

    async def start(self) -> None:
        for attempt in range(1, self._settings.nats_setup_max_attempts + 1):
            try:
                await self.connect()
                await self.setup()
                return
            except (NatsError, TimeoutError, OSError) as error:
                # Authentication/configuration errors must not be hidden by retry.
                if isinstance(error, APIError) and error.code is not None and error.code < 500:
                    raise
                logger.warning("nats_startup_retry attempts=%s", attempt)
                await self.close(drain=False)
                if attempt == self._settings.nats_setup_max_attempts:
                    raise RuntimeError("NATS startup attempts exhausted") from None
                await asyncio.sleep(self._settings.nats_setup_backoff_seconds * attempt)

    async def subscribe_completed(self) -> JetStreamContext.PullSubscription:
        for attempt in range(1, self._settings.nats_setup_max_attempts + 1):
            try:
                stream = (await self.jetstream.stream_info(RESULTS_STREAM)).config
                expected_stream = lifecycle_stream_config()
                expected_stream.name = RESULTS_STREAM
                expected_stream.subjects = [CLEANUP_COMPLETED_SUBJECT, MERGE_COMPLETED_SUBJECT]
                fields: tuple[str, ...] = (
                    "name",
                    "subjects",
                    "storage",
                    "retention",
                    "discard",
                    "max_age",
                    "max_msgs",
                    "max_bytes",
                )
                if any(getattr(stream, field) != getattr(expected_stream, field) for field in fields):
                    raise ValueError("Incompatible METRICA_MAINTENANCE_RESULTS stream")
                expected = completed_consumer_config()
                try:
                    actual = (await self.jetstream.consumer_info(RESULTS_STREAM, COMPLETED_DURABLE)).config
                except NotFoundError:
                    actual = (await self.jetstream.add_consumer(RESULTS_STREAM, config=expected)).config
                fields = (
                    "durable_name",
                    "filter_subject",
                    "deliver_policy",
                    "ack_policy",
                    "ack_wait",
                    "max_deliver",
                    "deliver_subject",
                )
                if any(getattr(actual, field) != getattr(expected, field) for field in fields):
                    raise ValueError("Incompatible cleanup completed durable")
                return await self.jetstream.pull_subscribe_bind(durable=COMPLETED_DURABLE, stream=RESULTS_STREAM)
            except NotFoundError:
                # Only the owner may create the foreign stream. BadRequest fails fast.
                if attempt == self._settings.nats_setup_max_attempts:
                    raise RuntimeError("Cleanup results stream lookup attempts exhausted") from None
                logger.warning("cleanup_results_lookup_retry attempts=%s", attempt)
                await asyncio.sleep(self._settings.nats_setup_backoff_seconds * attempt)
        raise RuntimeError("Cleanup results subscription unavailable")

    async def publish(self, *, subject: str, payload: bytes, headers: dict[str, str]) -> bool:
        ack = await self.jetstream.publish(
            subject,
            payload,
            headers=headers,
            stream=LIFECYCLE_STREAM,
            timeout=self._settings.nats_publish_timeout_seconds,
        )

        if ack.stream != LIFECYCLE_STREAM or not isinstance(ack.seq, int) or ack.seq <= 0:
            raise ValueError("Invalid cleanup PubAck")
        return bool(ack.duplicate)

    async def close(self, *, drain: bool = True) -> None:
        connection, self._connection = self._connection, None
        self._jetstream = None
        if connection is None:
            return
        try:
            if drain and not connection.is_closed:
                await connection.drain()
        except NatsError, TimeoutError, OSError:
            logger.warning("nats_shutdown_drain_failed")
        finally:
            try:
                await connection.close()
            except NatsError, TimeoutError, OSError:
                logger.warning("nats_shutdown_close_failed")
