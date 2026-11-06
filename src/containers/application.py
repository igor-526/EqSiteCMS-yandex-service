from dependency_injector import containers, providers

from clients.nats.client import NatsJetstreamClient
from clients.nats.consumer import CleanupCompletedConsumer
from clients.nats.publisher import CleanupPublisher
from containers.clients import ClientsContainer
from containers.repositories import RepositoriesContainer
from containers.services import ServicesContainer
from containers.settings import SettingsContainer
from core.services.cleanup_outbox_relay import CleanupOutboxRelay
from repositories.cleanup_outbox_repository import CleanupOutboxRepository
from repositories.metrica_lifecycle_repository import CleanupResultRepository
from utils.database import AsyncSessionLocal

settings_container = SettingsContainer()
clients_container = ClientsContainer(settings_container=settings_container)
repositories_container = RepositoriesContainer()
services_container = ServicesContainer(
    settings_container=settings_container,
    repositories_container=repositories_container,
    clients_container=clients_container,
)


class ApplicationContainer(containers.DeclarativeContainer):
    nats_settings = providers.Object(settings_container.nats_settings())
    session_factory = providers.Object(AsyncSessionLocal)
    nats_client = providers.Singleton(NatsJetstreamClient, settings=nats_settings)
    cleanup_publisher = providers.Singleton(CleanupPublisher, transport=nats_client)
    cleanup_outbox_repository = providers.Singleton(CleanupOutboxRepository, session_factory=session_factory)
    cleanup_result_repository = providers.Singleton(CleanupResultRepository, session_factory=session_factory)
    cleanup_completed_consumer = providers.Factory(
        CleanupCompletedConsumer,
        transport=nats_client,
        repository=cleanup_result_repository,
        error_report_after_attempts=nats_settings.provided.nats_error_report_after_attempts,
    )
    cleanup_outbox_relay = providers.Factory(
        CleanupOutboxRelay,
        repository=cleanup_outbox_repository,
        publisher=cleanup_publisher,
        lease_seconds=nats_settings.provided.nats_relay_claim_seconds,
        poll_seconds=nats_settings.provided.nats_relay_poll_seconds,
        error_report_after_attempts=nats_settings.provided.nats_error_report_after_attempts,
    )


container = ApplicationContainer()
