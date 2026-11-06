from dependency_injector import containers, providers

from settings import NatsSettings, Settings, YandexAppSettings, YandexMetricaServiceSettings


class SettingsContainer(containers.DeclarativeContainer):
    nats_settings = providers.Singleton(NatsSettings)
    app_settings = providers.Singleton(Settings)
    yandex_app_settings = providers.Singleton(YandexAppSettings)
    ya_metrica_service_settings = providers.Singleton(YandexMetricaServiceSettings)
