from dependency_injector import containers, providers

from depends.utils import get_session
from repositories import YandexUserRepository


class RepositoriesContainer(containers.DeclarativeContainer):
    session = providers.ContextLocalResource(get_session)

    yandex_user_repository = providers.Factory(YandexUserRepository, session=session)
