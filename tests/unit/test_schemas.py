from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.entities import PaginatedEntities, YandexUser
from core.schemas.api import (
    ServiceAuthorizationAccessTokenOutDto,
    YandexAccountOutDto,
    YandexAuthCodeInDto,
    YandexAuthLinkOutDto,
    YandexMetricaCounterOutDto,
    YandexMetricaCounterResponseOutDto,
)
from core.schemas.clients import YandexClientAuthResponse, YandexClientUserResponse


@pytest.fixture
def user_data() -> dict:
    return dict(
        equestrian_id=uuid4(),
        yandex_id="user",
        yandex_login="login",
        display_name="Name",
        enc_access_token="access",
        enc_refresh_token="refresh",
        token_expires_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "field,bound",
    [
        ("yandex_id", 63),
        ("yandex_login", 127),
        ("display_name", 127),
        ("email", 320),
        ("yandex_avatar_id", 63),
        ("yandex_phone", 31),
        ("enc_access_token", 511),
        ("enc_refresh_token", 511),
    ],
)
def test_entity_string_length_boundary(user_data: dict, field: str, bound: int) -> None:
    user_data[field] = "x" * bound
    assert getattr(YandexUser.model_validate(user_data), field) == "x" * bound
    user_data[field] = "x" * (bound + 1)
    with pytest.raises(ValidationError) as caught:
        YandexUser.model_validate(user_data)
    assert caught.value.errors()[0]["loc"] == (field,)


def test_entity_and_account_defaults_and_secret_projection(user_data: dict) -> None:
    first = YandexUser.model_validate(user_data)
    second = YandexUser.model_validate(user_data)
    assert isinstance(first.id, UUID)
    assert first.id != second.id
    assert first.created_at.tzinfo is UTC
    assert first.updated_at is None
    assert first.email is first.yandex_avatar_id is first.yandex_phone is None
    dto = YandexAccountOutDto.model_validate(first)
    assert dto.model_dump() == dict(
        id=first.id, yandex_id="user", yandex_login="login", display_name="Name", email=None, yandex_phone=None
    )
    assert "enc_access_token" not in dto.model_dump_json()
    assert "enc_refresh_token" not in dto.model_dump_json()
    assert "token_expires_at" not in dto.model_dump_json()


@pytest.mark.parametrize("bad_id", ["invalid-uuid", "", 123])
def test_auth_rejects_invalid_uuid(bad_id: object) -> None:
    with pytest.raises(ValidationError):
        YandexAuthCodeInDto.model_validate({"code": "code", "equestrian_id": bad_id})


def test_auth_uuid_parsing_and_unconstrained_empty_code() -> None:
    tenant = uuid4()
    dto = YandexAuthCodeInDto.model_validate({"code": "", "equestrian_id": str(tenant)})
    assert dto.equestrian_id == tenant
    assert dto.code == ""
    assert YandexAuthLinkOutDto(auth_link="https://example.test").model_dump() == {"auth_link": "https://example.test"}
    assert ServiceAuthorizationAccessTokenOutDto(access_token="token").model_dump() == {"access_token": "token"}


@pytest.mark.parametrize(
    "payload", [{}, {"code": "code"}, {"equestrian_id": str(uuid4())}, {"code": 123, "equestrian_id": str(uuid4())}]
)
def test_auth_required_fields_and_code_type(payload: dict) -> None:
    with pytest.raises(ValidationError):
        YandexAuthCodeInDto.model_validate(payload)


def test_counter_response_and_pagination_defaults_are_independent() -> None:
    first = YandexMetricaCounterResponseOutDto(total=7)
    second = YandexMetricaCounterResponseOutDto(total=0)
    first.items.append(YandexMetricaCounterOutDto(counter_id=1, site="example.test"))
    assert second.items == []
    assert first.total == 7
    assert first.model_dump() == {"total": 7, "items": [{"counter_id": 1, "site": "example.test"}]}
    page = PaginatedEntities[YandexAccountOutDto]()
    assert page.items == []
    assert page.total == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"total": "bad"},
        {"total": 1, "items": [{}]},
        {"total": 1, "items": [{"counter_id": "bad", "site": "example"}]},
    ],
)
def test_counter_invalid_payload(payload: dict) -> None:
    with pytest.raises(ValidationError):
        YandexMetricaCounterResponseOutDto.model_validate(payload)


def test_client_response_defaults_and_nullable_phone() -> None:
    auth = YandexClientAuthResponse(access_token="access", refresh_token="refresh", expires_in=0)
    assert auth.token_type == "bearer"
    data = dict(
        id="user",
        login="login",
        client_id="client",
        display_name="Name",
        real_name="Real Name",
        first_name="First",
        last_name="Last",
        default_email="email",
        default_avatar_id="avatar",
        psuid="id",
        default_phone=None,
    )
    first = YandexClientUserResponse.model_validate(data)
    second = YandexClientUserResponse.model_validate(data)
    assert first.default_phone is None
    assert first.sex is None
    assert first.is_avatar_empty is True
    first.emails.append("email")
    assert second.emails == []
    del data["default_phone"]
    with pytest.raises(ValidationError):
        YandexClientUserResponse.model_validate(data)
