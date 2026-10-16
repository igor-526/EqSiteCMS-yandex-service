from typing import Protocol

from core.schemas.clients import YandexClientAuthResponse, YandexClientUserResponse


class YandexOAuthClientProtocol(Protocol):
    def get_init_oauth_link(self, *, state: str | None = None) -> str: ...

    async def authenticate(self, *, code: str) -> YandexClientAuthResponse:
        """Return validated tokens; raise local YandexClientException on any ordinary failure.

        Cancellation and other BaseException propagate unchanged; no automatic retry.
        """
        ...

    async def get_user_info(self, *, access_token: str) -> YandexClientUserResponse:
        """Return a validated profile; raise local YandexClientException on ordinary failure.

        Cancellation and other BaseException propagate unchanged.
        """
        ...
