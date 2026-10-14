from dependency_injector import containers, providers

from clients import YandexOAuthClient


class ClientsContainer(containers.DeclarativeContainer):
    settings_container = providers.DependenciesContainer()

    yandex_oauth_client = providers.Factory(
        YandexOAuthClient,
        client_id=settings_container.yandex_app_settings.provided.yandex_app_client_id,
        client_secret=settings_container.yandex_app_settings.provided.yandex_app_client_secret,
        redirect_url=settings_container.yandex_app_settings.provided.yandex_app_redirect_uri,
    )
