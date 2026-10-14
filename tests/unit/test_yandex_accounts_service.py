import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.entities import PaginatedEntities, YandexUser
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexAccountOutDto
from core.services.yandex_accounts_service import YandexAccountsService


@pytest.mark.parametrize("search", [None, "", "some.login"])
async def test_get_filtered_accounts_preserves_filters_and_excludes_tokens(search: str | None) -> None:
    equestrian_id = uuid4()
    account = YandexUser(
        equestrian_id=equestrian_id,
        yandex_id="yandex-id",
        yandex_login="some.login",
        display_name="Some Name",
        email="some@example.com",
        yandex_phone="+79990000000",
        enc_access_token="secret-access-token",
        enc_refresh_token="secret-refresh-token",
        token_expires_at=datetime.now(UTC),
    )
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_filtered.return_value = [account]
    repository.count_filtered.return_value = 17
    service = YandexAccountsService(yandex_user_repository=repository)

    result = await service.list_filtered(equestrian_id=equestrian_id, search=search, limit=5, offset=10)

    repository.get_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search=search, limit=5, offset=10)
    repository.count_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search=search)
    assert result.items == [YandexAccountOutDto.model_validate(account)]
    assert result.total == 17
    assert set(result.items[0].model_dump()) == {
        "id",
        "yandex_id",
        "yandex_login",
        "display_name",
        "email",
        "yandex_phone",
    }


async def test_get_filtered_accounts_defaults_and_empty_result() -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_filtered.return_value = []
    repository.count_filtered.return_value = 0
    service = YandexAccountsService(yandex_user_repository=repository)
    equestrian_id = uuid4()

    assert await service.list_filtered(equestrian_id=equestrian_id) == PaginatedEntities[YandexAccountOutDto](
        items=[], total=0
    )
    repository.count_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search=None)

    repository.get_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search=None, limit=20, offset=0)


async def test_delete_account_logs_success(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    service = YandexAccountsService(yandex_user_repository=repository)
    account_id = uuid4()

    with caplog.at_level(logging.INFO, logger="Yandex Accounts Service"):
        await service.delete_account(account_id=account_id)

    repository.delete.assert_awaited_once_with(id=account_id)
    assert caplog.messages == [f"Deleted Yandex account {account_id}"]


async def test_delete_account_does_not_log_success_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.delete.side_effect = RuntimeError("database unavailable")
    service = YandexAccountsService(yandex_user_repository=repository)

    with caplog.at_level(logging.INFO, logger="Yandex Accounts Service"):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await service.delete_account(account_id=uuid4())

    assert caplog.messages == []


async def test_get_filtered_accounts_offset_beyond_results_keeps_total() -> None:
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_filtered.return_value = []
    repository.count_filtered.return_value = 7
    service = YandexAccountsService(yandex_user_repository=repository)
    equestrian_id = uuid4()

    result = await service.list_filtered(equestrian_id=equestrian_id, search="login", limit=5, offset=100)

    assert result.items == []
    assert result.total == 7
    repository.count_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search="login")
    repository.get_filtered.assert_awaited_once_with(equestrian_id=equestrian_id, search="login", limit=5, offset=100)
