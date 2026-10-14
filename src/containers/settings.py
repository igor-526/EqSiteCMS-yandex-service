from dependency_injector import containers, providers

from settings import Settings, YandexAppSettings


class SettingsContainer(containers.DeclarativeContainer):
    app_settings = providers.Singleton(Settings)
    yandex_app_settings = providers.Singleton(YandexAppSettings)
