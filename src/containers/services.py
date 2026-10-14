from dependency_injector import containers, providers

from core.services import (
    EncryptionService,
    YandexAccountsService,
    YandexMetricaService,
    YandexOauthService,
    YandexServiceAuthorizationService,
)


class ServicesContainer(containers.DeclarativeContainer):
    settings_container = providers.DependenciesContainer()
    repositories_container = providers.DependenciesContainer()
    clients_container = providers.DependenciesContainer()

    encryption_service = providers.Factory(
        EncryptionService, secret_key=settings_container.app_settings.provided.enctyption_service_key
    )
    yandex_oauth_service = providers.Factory(
        YandexOauthService,
        client=clients_container.yandex_oauth_client,
        encryption_service=encryption_service,
        yandex_user_repository=repositories_container.yandex_user_repository,
    )
    yandex_accounts_service = providers.Factory(
        YandexAccountsService, yandex_user_repository=repositories_container.yandex_user_repository
    )
    yandex_service_authorization_service = providers.Factory(
        YandexServiceAuthorizationService,
        encryption_service=encryption_service,
        yandex_user_repository=repositories_container.yandex_user_repository,
    )
    ya_metrica_service = providers.Factory(
        YandexMetricaService,
        encryption_service=encryption_service,
        yandex_user_repository=repositories_container.yandex_user_repository,
        yandex_metrica_client=clients_container.ya_metrica_service_client,
    )
