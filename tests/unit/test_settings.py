from collections.abc import Callable
from typing import Any, cast

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from settings import Settings, YandexAppSettings, YandexMetricaServiceSettings
from tests.conftest import TEST_ENV


def instantiate[T: BaseSettings](cls: type[T], **values: Any) -> T:
    # Pydantic mypy plugin omits the runtime BaseSettings _env_file argument.
    return cast(Callable[..., T], cls)(_env_file=None, **values)


@pytest.fixture
def clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in TEST_ENV:
        monkeypatch.delenv(key, raising=False)


def test_defaults_and_cached_database_url(clean_settings_env: None) -> None:
    settings = instantiate(Settings, ENCRYPTION_SERVICE_KEY="fake-key")
    assert settings.environment == "development"
    assert settings.debug is True
    assert settings.app_title == "FastAPI Template"
    assert settings.sentry_enabled is False
    assert settings.sentry_dsn == ""
    assert settings.sentry_environment == "development"
    assert settings.sentry_traces_sample_rate == 0.0
    assert settings.sentry_release is None
    assert settings.database_url == "postgresql+asyncpg://app:app@localhost:5432/app"
    settings.postgres_host = "changed.invalid"
    assert settings.database_url == "postgresql+asyncpg://app:app@localhost:5432/app"


@pytest.mark.parametrize("key", [None, ""])
def test_encryption_secret_required(clean_settings_env: None, key: str | None) -> None:
    values = {} if key is None else {"ENCRYPTION_SERVICE_KEY": key}
    with pytest.raises(ValidationError, match="ENCRYPTION_SERVICE_KEY is required"):
        instantiate(Settings, **values)


@pytest.mark.parametrize("rate", [-0.001, 0.0, 1.0, 1.001])
def test_sample_rate_bounds(clean_settings_env: None, rate: float) -> None:
    if rate < 0 or rate > 1:
        with pytest.raises(ValidationError):
            instantiate(Settings, ENCRYPTION_SERVICE_KEY="fake", SENTRY_TRACES_SAMPLE_RATE=rate)
    else:
        settings = instantiate(Settings, ENCRYPTION_SERVICE_KEY="fake", SENTRY_TRACES_SAMPLE_RATE=rate)
        assert settings.sentry_traces_sample_rate == rate


def test_sentry_requires_dsn(clean_settings_env: None) -> None:
    with pytest.raises(ValidationError, match="SENTRY_DSN is required"):
        instantiate(Settings, ENCRYPTION_SERVICE_KEY="fake", SENTRY_ENABLED=True)
    assert instantiate(
        Settings, ENCRYPTION_SERVICE_KEY="fake", SENTRY_ENABLED=True, SENTRY_DSN="https://fake.example.test"
    ).sentry_enabled


def test_environment_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "ENVIRONMENT": "staging",
        "DEBUG": "true",
        "APP_TITLE": "Alias title",
        "POSTGRES_USER": "alice",
        "POSTGRES_PASSWORD": "fake",
        "POSTGRES_HOST": "postgres.invalid",
        "POSTGRES_PORT": "5444",
        "POSTGRES_DB": "alias",
        "ENCRYPTION_SERVICE_KEY": "alias-key",
        "SENTRY_ENABLED": "true",
        "SENTRY_DSN": "https://fake.example.test",
        "SENTRY_ENVIRONMENT": "staging",
        "SENTRY_TRACES_SAMPLE_RATE": "0.5",
        "SENTRY_RELEASE": "release-test",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = instantiate(Settings)
    assert settings.environment == settings.sentry_environment == "staging"
    assert settings.debug and settings.sentry_enabled
    assert settings.app_title == "Alias title"
    assert settings.enctyption_service_key == "alias-key"
    assert settings.sentry_dsn == "https://fake.example.test"
    assert settings.sentry_release == "release-test"
    assert settings.sentry_traces_sample_rate == 0.5
    assert settings.database_url == "postgresql+asyncpg://alice:fake@postgres.invalid:5444/alias"


@pytest.mark.parametrize("missing", ["YANDEX_APP_CLIENT_ID", "YANDEX_APP_CLIENT_SECRET", "YANDEX_APP_REDIRECT_URI"])
def test_oauth_required_aliases(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError) as exc:
        instantiate(YandexAppSettings)
    assert exc.value.errors()[0]["loc"] == (missing,)


def test_oauth_and_metrica_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth = instantiate(YandexAppSettings)
    assert oauth.yandex_app_client_id == TEST_ENV["YANDEX_APP_CLIENT_ID"]
    assert oauth.yandex_app_client_secret == TEST_ENV["YANDEX_APP_CLIENT_SECRET"]
    assert oauth.yandex_app_redirect_uri == TEST_ENV["YANDEX_APP_REDIRECT_URI"]
    assert instantiate(YandexMetricaServiceSettings).ya_metrica_service_url == TEST_ENV["YA_METRTICA_SERVICE_URL"]
    monkeypatch.delenv("YA_METRTICA_SERVICE_URL")
    monkeypatch.setenv("YA_METRICA_SERVICE_URL", "https://correct-spelling.example.test")
    with pytest.raises(ValidationError) as exc:
        instantiate(YandexMetricaServiceSettings)
    assert exc.value.errors()[0]["loc"] == ("YA_METRTICA_SERVICE_URL",)
