from uuid import UUID

from core.exceptions import ClientError
from core.protocols.repositories import YandexUserRepositoryProtocol


class YandexServiceAuthorizationService:
    def __init__(
        self,
        yandex_user_repository: YandexUserRepositoryProtocol,
    ) -> None:
        self._yandex_user_repository = yandex_user_repository

    async def get_token(self, *, account_id: UUID) -> str:
        yandex_account = await self._yandex_user_repository.get_by_id(id=account_id)
        if yandex_account is None:
            raise ClientError("Аккаунт не найден")
        return yandex_account.enc_access_token
