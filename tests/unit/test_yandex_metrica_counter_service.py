import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.entities import YandexMetricaCounter
from core.exceptions import ClientError, RepositoryError
from core.protocols.repositories import YandexMetricaCounterRepositoryProtocol, YandexUserRepositoryProtocol
from core.schemas.api import YandexAccountOutDto, YandexMetricaSetCounterInDto
from core.services.yandex_metrica_counter_service import YandexMetricaCounterService
from tests.unit.test_yandex_user_repository import account


def counter_input(counter: YandexMetricaCounter) -> YandexMetricaSetCounterInDto:
    return YandexMetricaSetCounterInDto(
        equestrian_id=counter.equestrian_id,
        yandex_account_id=counter.yandex_user_id,
        counter_id=counter.counter_id,
    )


@pytest.fixture
def counters():
    user = account()
    counter = YandexMetricaCounter(equestrian_id=user.equestrian_id, yandex_user_id=user.id, counter_id="42")
    repository = AsyncMock(spec=YandexMetricaCounterRepositoryProtocol)
    repository.get_by_equestrian.return_value = counter
    users = AsyncMock(spec=YandexUserRepositoryProtocol)
    users.get_by_id.return_value = user
    return YandexMetricaCounterService(repository, users), repository, users, counter, user


async def test_get_counter_includes_public_account(counters):
    service, repository, users, counter, user = counters
    response = await service.get_counter(equestrian_id=counter.equestrian_id)
    result = response.counter
    assert result is not None
    assert result.id == counter.id
    assert result.equestrian_id == counter.equestrian_id
    assert result.counter_id == counter.counter_id
    assert result.yandex_account == YandexAccountOutDto.model_validate(user)
    assert "enc_access_token" not in result.yandex_account.model_dump()
    repository.get_by_equestrian.assert_awaited_once_with(equestrian_id=counter.equestrian_id)
    users.get_by_id.assert_awaited_once_with(id=counter.yandex_user_id)


async def test_get_missing_counter(counters):
    service, repository, users, counter, _ = counters
    repository.get_by_equestrian.return_value = None
    result = await service.get_counter(equestrian_id=counter.equestrian_id)
    assert result.counter is None
    assert result.model_dump() == {"counter": None}
    users.get_by_id.assert_not_awaited()


@pytest.mark.parametrize("method", ["get", "set"])
async def test_missing_account(counters, method):
    service, repository, users, counter, _ = counters
    users.get_by_id.return_value = None
    with pytest.raises(ClientError, match="Аккаунт не найден"):
        if method == "get":
            await service.get_counter(equestrian_id=counter.equestrian_id)
        else:
            await service.set_counter(data=counter_input(counter))
    repository.create.assert_not_awaited()
    repository.update.assert_not_awaited()


@pytest.mark.parametrize("mode", ["create", "same", "counter", "account", "both"])
async def test_set_counter_is_idempotent(counters, mode, caplog):
    service, repository, users, counter, user = counters
    data = counter_input(counter)
    if mode == "create":
        repository.get_by_equestrian.return_value = None
    if mode in ("counter", "both"):
        data.counter_id = "43"
    if mode in ("account", "both"):
        user = user.model_copy(update={"id": uuid4()})
        users.get_by_id.return_value = user
        data.yandex_account_id = user.id
    with caplog.at_level(logging.INFO):
        result = await service.set_counter(data=data)
    assert result.counter_id == data.counter_id
    assert result.equestrian_id == data.equestrian_id
    assert result.yandex_account.id == user.id
    users.get_by_id.assert_awaited_once_with(id=data.yandex_account_id)
    assert "Set Yandex Metrica counter" in caplog.text
    if mode == "create":
        repository.create.assert_awaited_once()
        saved = repository.create.await_args.args[0]
        assert result.id == saved.id
        repository.update.assert_not_awaited()
    elif mode == "same":
        repository.create.assert_not_awaited()
        repository.update.assert_not_awaited()
        assert result.id == counter.id
    else:
        repository.create.assert_not_awaited()
        repository.update.assert_awaited_once()
        saved = repository.update.await_args.args[0]
        assert saved.id == counter.id
        assert saved.created_at == counter.created_at
        assert saved.counter_id == data.counter_id
        assert saved.yandex_user_id == data.yandex_account_id
        assert counter.counter_id == "42"


@pytest.mark.parametrize("exists", [False, True])
async def test_set_invalid_counter_converts_validation_error(counters, exists):
    service, repository, users, counter, _ = counters
    repository.get_by_equestrian.return_value = counter if exists else None
    data = counter_input(counter)
    data.counter_id = "1" * 32
    with pytest.raises(ClientError, match="Некорректные данные счётчика") as caught:
        await service.set_counter(data=data)
    assert isinstance(caught.value.__cause__, ValidationError)
    repository.create.assert_not_awaited()
    repository.update.assert_not_awaited()
    users.get_by_id.assert_not_awaited()


async def test_delete_counter_is_idempotent(counters, caplog):
    service, repository, _, counter, _ = counters
    repository.delete.return_value = None
    with caplog.at_level(logging.INFO):
        assert await service.delete_counter(counter_id=counter.id) is None
        assert await service.delete_counter(counter_id=counter.id) is None
    assert repository.delete.await_count == 2
    repository.delete.assert_awaited_with(id=counter.id)
    assert "Deleted Yandex Metrica counter" in caplog.text


@pytest.mark.parametrize("method", ["get", "set", "delete"])
async def test_repository_errors_propagate(counters, method):
    service, repository, _, counter, _ = counters
    error = RepositoryError("database unavailable")
    repository.get_by_equestrian.side_effect = error
    repository.delete.side_effect = error
    with pytest.raises(RepositoryError) as caught:
        if method == "get":
            await service.get_counter(equestrian_id=counter.equestrian_id)
        elif method == "set":
            await service.set_counter(data=counter_input(counter))
        else:
            await service.delete_counter(counter_id=counter.id)
    assert caught.value is error
