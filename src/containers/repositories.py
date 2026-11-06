from dependency_injector import containers, providers

from depends.utils import get_session
from repositories import YandexMetricaCounterRepository, YandexUserRepository
from repositories.metrica_lifecycle_repository import MetricaLifecycleRepository


class RepositoriesContainer(containers.DeclarativeContainer):
    session = providers.ContextLocalResource(get_session)

    yandex_user_repository = providers.Factory(YandexUserRepository, session=session)
    yandex_metrica_counter_repository = providers.Factory(YandexMetricaCounterRepository, session=session)

    metrica_lifecycle_repository = providers.Factory(MetricaLifecycleRepository, session=session)
