from clients import YandexOAuthClient
from core.protocols.clients import YandexOAuthClientProtocol
from settings import yandex_app_settings


async def get_yandex_oauth_client() -> YandexOAuthClientProtocol:
    return YandexOAuthClient(
        client_id=yandex_app_settings.yandex_app_client_id,
        client_secret=yandex_app_settings.yandex_app_client_secret,
        redirect_url=yandex_app_settings.yandex_app_redirect_uri,
    )
