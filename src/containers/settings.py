from dependency_injector import containers, providers

from settings import Settings, YandexAppSettings, YandexMetricaServiceSettings


class SettingsContainer(containers.DeclarativeContainer):
    app_settings = providers.Singleton(Settings)
    yandex_app_settings = providers.Singleton(YandexAppSettings)
    ya_metrica_service_settings = providers.Singleton(YandexMetricaServiceSettings)
