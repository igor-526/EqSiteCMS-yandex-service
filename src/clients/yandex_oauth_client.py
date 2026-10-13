from collections.abc import Mapping
from typing import Any

import httpx

from core.exceptions import YandexClientException
from core.schemas.clients import YandexClientAuthResponse, YandexClientUserResponse


class YandexOAuthClient:
    base_oauth_url: str
    client_id: str
    client_secret: str
    redirect_url: str

    def __init__(self, *, client_id: str, client_secret: str, redirect_url: str) -> None:
        self.base_oauth_url = "https://oauth.yandex.ru"
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_url = redirect_url

    async def make_request(
        self,
        *,
        method: str = "GET",
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Any | None = None,
        auth: httpx.Auth | None = None,
        request_timeout: float | httpx.Timeout | None = 10.0,
    ) -> dict:
        async with httpx.AsyncClient(base_url=self.base_oauth_url) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                params=params,
                headers=headers,
                data=data,
                json=json,
                auth=auth,
                timeout=request_timeout,
            )
        response_data = response.json()
        if not isinstance(response_data, dict):
            raise YandexClientException(status=response.status_code, error="Empty response")
        if not 200 <= response.status_code < 300:
            raise YandexClientException(
                status=response.status_code,
                error=response_data.get("error", None),
                error_description=response_data.get("error_description", None),
            )
        return response_data

    def get_init_oauth_link(self, *, state: str | None = None) -> str:
        oauth_link = (
            f"{self.base_oauth_url}/authorize?response_type=code&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_url}"
        )
        if state:
            oauth_link += f"&state={state}"
        return oauth_link

    async def authenticate(self, *, code: str) -> YandexClientAuthResponse:
        response = await self.make_request(
            method="POST",
            url=f"{self.base_oauth_url}/token",
            data={"grant_type": "authorization_code", "code": code},
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
        )
        return YandexClientAuthResponse.model_validate(response)

    async def get_user_info(self, *, access_token: str) -> YandexClientUserResponse:
        response = await self.make_request(
            method="GET", url="https://login.yandex.ru/info", headers={"Authorization": f"OAuth {access_token}"}
        )
        return YandexClientUserResponse.model_validate(response)
