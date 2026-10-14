from dependency_injector import containers, providers

from clients import YaMetricaServiceClient, YandexOAuthClient


class ClientsContainer(containers.DeclarativeContainer):
    settings_container = providers.DependenciesContainer()

    yandex_oauth_client = providers.Factory(
        YandexOAuthClient,
        client_id=settings_container.yandex_app_settings.provided.yandex_app_client_id,
        client_secret=settings_container.yandex_app_settings.provided.yandex_app_client_secret,
        redirect_url=settings_container.yandex_app_settings.provided.yandex_app_redirect_uri,
    )
    ya_metrica_service_client = providers.Factory(
        YaMetricaServiceClient,
        ya_metrica_service_url=settings_container.ya_metrica_service_settings.provided.ya_metrica_service_url,
    )
