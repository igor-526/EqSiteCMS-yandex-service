import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from clients import YaMetricaServiceClient, YandexOAuthClient
from containers.clients import ClientsContainer
from containers.repositories import RepositoriesContainer
from containers.services import ServicesContainer
from containers.settings import SettingsContainer
from core.services import (
    EncryptionService,
    YandexAccountsService,
    YandexMetricaService,
    YandexOauthService,
    YandexServiceAuthorizationService,
)
from depends import utils
from repositories import YandexUserRepository
from tests.conftest import TEST_ENV


def test_settings_singletons_and_real_provider_graph() -> None:
    settings = SettingsContainer()
    clients = ClientsContainer(settings_container=settings)
    repositories = RepositoriesContainer()
    services = ServicesContainer(
        settings_container=settings, clients_container=clients, repositories_container=repositories
    )
    for provider in (settings.app_settings, settings.yandex_app_settings, settings.ya_metrica_service_settings):
        assert provider() is provider()
    session = AsyncMock(spec=AsyncSession)
    with repositories.session.override(providers.Object(session)):
        repository = repositories.yandex_user_repository()
        assert isinstance(repository, YandexUserRepository) and repository.session is session
        oauth_client = clients.yandex_oauth_client()
        assert isinstance(oauth_client, YandexOAuthClient)
        assert oauth_client.client_id == TEST_ENV["YANDEX_APP_CLIENT_ID"]
        assert oauth_client.client_secret == TEST_ENV["YANDEX_APP_CLIENT_SECRET"]
        assert oauth_client.redirect_url == TEST_ENV["YANDEX_APP_REDIRECT_URI"]
        assert isinstance(clients.ya_metrica_service_client(), YaMetricaServiceClient)
        assert clients.ya_metrica_service_client().ya_metrica_service_url == TEST_ENV["YA_METRTICA_SERVICE_URL"]
        oauth = services.yandex_oauth_service()
        accounts = services.yandex_accounts_service()
        authorization = services.yandex_service_authorization_service()
        metrica = services.ya_metrica_service()
        assert isinstance(oauth, YandexOauthService)
        assert isinstance(accounts, YandexAccountsService)
        assert isinstance(authorization, YandexServiceAuthorizationService)
        assert isinstance(metrica, YandexMetricaService)
        assert isinstance(oauth._client, YandexOAuthClient)
        assert isinstance(metrica._yandex_metrica_client, YaMetricaServiceClient)
        for service in (oauth, accounts, authorization, metrica):
            assert isinstance(service._yandex_user_repository, YandexUserRepository)
            assert service._yandex_user_repository.session is session
        for service in (oauth, authorization, metrica):
            assert isinstance(service._encryption_service, EncryptionService)
            ciphertext = service._encryption_service.encrypt(data="provider graph token")
            assert services.encryption_service().decrypt(data=ciphertext) == "provider graph token"
        assert services.yandex_accounts_service() is not accounts
    assert not repositories.session.overridden


async def test_context_local_resource_isolates_concurrent_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[AsyncMock] = []

    def factory() -> AsyncMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__.return_value = session
        sessions.append(session)
        return session

    monkeypatch.setattr(utils, "AsyncSessionLocal", Mock(side_effect=factory))
    repositories = RepositoriesContainer()
    barrier = asyncio.Barrier(2)

    async def request() -> AsyncMock:
        session = await cast(Any, repositories.session)()
        try:
            await barrier.wait()
            repository = await cast(Any, repositories.yandex_user_repository)()
            assert repository.session is session
            assert await cast(Any, repositories.session)() is session
            return session
        finally:
            await cast(Any, repositories.session).shutdown()

    first, second = await asyncio.gather(request(), request())
    assert first is not second and len(sessions) == 2
    for session in sessions:
        session.__aenter__.assert_awaited_once()
        session.__aexit__.assert_awaited_once_with(None, None, None)
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()
