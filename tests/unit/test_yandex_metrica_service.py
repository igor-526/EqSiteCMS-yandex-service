from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.entities import YandexUser
from core.exceptions import ClientError, RepositoryError, YandexClientException
from core.protocols.clients import YaMetricaServiceClientProtocol
from core.protocols.repositories import YandexUserRepositoryProtocol
from core.schemas.api import YandexMetricaCounterOutDto, YandexMetricaCounterResponseOutDto
from core.services import EncryptionService
from core.services.yandex_metrica_service import YandexMetricaService


@pytest.fixture
def metrica() -> tuple[YandexMetricaService, AsyncMock, AsyncMock, YandexUser]:
    encryption = EncryptionService("test-secret")
    account = YandexUser(
        equestrian_id=uuid4(),
        yandex_id="user",
        yandex_login="login",
        display_name="Name",
        enc_access_token=encryption.encrypt(data="plaintext-token"),
        enc_refresh_token="encrypted",
        token_expires_at=datetime.now(UTC),
    )
    repository = AsyncMock(spec=YandexUserRepositoryProtocol)
    repository.get_by_id.return_value = account
    client = AsyncMock(spec=YaMetricaServiceClientProtocol)
    client.get_metrica_counters.return_value = YandexMetricaCounterResponseOutDto(total=0)
    return YandexMetricaService(encryption, repository, client), repository, client, account


@pytest.mark.parametrize("search", [None, "", "example.test"])
@pytest.mark.parametrize("items", [[], [YandexMetricaCounterOutDto(counter_id=42, site="example.test")]])
async def test_counters_preserve_filters_and_response(metrica, search: str | None, items: list) -> None:
    service, repository, client, account = metrica
    expected = YandexMetricaCounterResponseOutDto(total=7, items=items)
    client.get_metrica_counters.return_value = expected
    result = await service.get_counters(account_id=account.id, search=search)
    assert result == expected
    repository.get_by_id.assert_awaited_once_with(id=account.id)
    # GAP-MET-01 characterization; the strict desired-contract test below owns the finding.
    client.get_metrica_counters.assert_awaited_once_with(
        access_token=account.enc_access_token, search=search, limit=20, offset=0
    )


@pytest.mark.parametrize("limit,expected", [(-1, 1), (0, 1), (1, 1), (100, 100), (101, 100)])
@pytest.mark.parametrize("offset,expected_offset", [(-1, 0), (0, 0), (1000000, 1000000)])
async def test_counter_pagination_bounds(
    metrica, limit: int, expected: int, offset: int, expected_offset: int
) -> None:
    service, _, client, account = metrica
    await service.get_counters(account_id=account.id, limit=limit, offset=offset)
    client.get_metrica_counters.assert_awaited_once_with(
        access_token=account.enc_access_token, search=None, limit=expected, offset=expected_offset
    )


async def test_missing_account_never_calls_client(metrica) -> None:
    service, repository, client, _ = metrica
    repository.get_by_id.return_value = None
    with pytest.raises(ClientError, match="Аккаунт не найден"):
        await service.get_counters(account_id=uuid4())
    client.get_metrica_counters.assert_not_awaited()


async def test_repository_failure_propagates_before_client(metrica) -> None:
    service, repository, client, account = metrica
    error = RepositoryError("database unavailable")
    repository.get_by_id.side_effect = error
    with pytest.raises(RepositoryError) as caught:
        await service.get_counters(account_id=account.id)
    assert caught.value is error
    client.get_metrica_counters.assert_not_awaited()


async def test_provider_failure_propagates(metrica) -> None:
    service, _, client, account = metrica
    error = YandexClientException(status=503, error="unavailable")
    client.get_metrica_counters.side_effect = error
    with pytest.raises(YandexClientException) as caught:
        await service.get_counters(account_id=account.id)
    assert caught.value is error


async def test_invalid_counter_response_rejected(metrica) -> None:
    service, _, client, account = metrica
    client.get_metrica_counters.return_value = {"total": 1, "items": [{"counter_id": "bad", "site": "example"}]}
    with pytest.raises(ValidationError):
        await service.get_counters(account_id=account.id)


@pytest.mark.xfail(
    strict=True, reason="GAP-MET-01: Metrica client receives encrypted instead of decrypted access token"
)
async def test_metrica_client_receives_decrypted_token(metrica) -> None:
    service, _, client, account = metrica
    await service.get_counters(account_id=account.id)
    assert client.get_metrica_counters.await_args.kwargs["access_token"] == "plaintext-token"
