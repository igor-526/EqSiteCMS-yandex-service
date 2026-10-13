from typing import Annotated

from fastapi import Depends

from core.protocols.clients import YandexOAuthClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.services import EnctryptionService, YandexOauthService
from depends.clients import get_yandex_oauth_client
from depends.repositories import get_yandex_user_repository
from settings import settings


def get_encryption_service() -> EnctryptionService:
    return EnctryptionService(secret_key=settings.enctyption_service_key)


async def get_yandex_oauth_service(
    client: Annotated[YandexOAuthClientProtocol, Depends(get_yandex_oauth_client)],
    yandex_user_repository: Annotated[YandexUserRepositoryProtocol, Depends(get_yandex_user_repository)],
) -> YandexOauthService:
    return YandexOauthService(
        client=client, encryption_service=get_encryption_service(), yandex_user_repository=yandex_user_repository
    )
