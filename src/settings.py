from functools import cached_property
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=True, alias="DEBUG")
    app_title: str = Field(default="FastAPI Template", alias="APP_TITLE")

    sentry_enabled: bool = Field(default=False, alias="SENTRY_ENABLED")
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_environment: str = Field(default="development", alias="SENTRY_ENVIRONMENT")
    sentry_traces_sample_rate: float = Field(default=0.0, alias="SENTRY_TRACES_SAMPLE_RATE", ge=0.0, le=1.0)
    sentry_release: str | None = Field(default=None, alias="SENTRY_RELEASE")

    postgres_user: str = Field(default="app", alias="POSTGRES_USER")
    postgres_password: str = Field(default="app", alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="app", alias="POSTGRES_DB")

    enctyption_service_key: str = Field(default="", alias="ENCRYPTION_SERVICE_KEY")

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        if self.sentry_enabled and not self.sentry_dsn:
            raise ValueError("SENTRY_DSN is required when SENTRY_ENABLED=true")
        if self.enctyption_service_key == "":
            raise ValueError("ENCRYPTION_SERVICE_KEY is required")
        return self

    @cached_property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class YandexAppSettings(BaseSettings):
    yandex_app_client_id: str = Field(default=..., alias="YANDEX_APP_CLIENT_ID")
    yandex_app_client_secret: str = Field(default=..., alias="YANDEX_APP_CLIENT_SECRET")
    yandex_app_redirect_uri: str = Field(default=..., alias="YANDEX_APP_REDIRECT_URI")

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")


class YandexMetricaServiceSettings(BaseSettings):
    ya_metrica_service_url: str = Field(default=..., alias="YA_METRTICA_SERVICE_URL")


settings = Settings()


class NatsSettings(BaseSettings):
    """Maintenance transport knobs; topology stays fixed by the approved contract."""

    nats_servers_raw: str = Field(default="nats://localhost:4222", alias="NATS_SERVERS")
    nats_setup_max_attempts: int = Field(default=10, alias="NATS_SETUP_MAX_ATTEMPTS", ge=1)
    nats_setup_backoff_seconds: float = Field(default=2, alias="NATS_SETUP_BACKOFF_SECONDS", ge=0)
    nats_connect_timeout_seconds: float = Field(default=5, alias="NATS_CONNECT_TIMEOUT_SECONDS", gt=0)
    nats_publish_timeout_seconds: float = Field(default=5, alias="NATS_PUBLISH_TIMEOUT_SECONDS", gt=0)
    nats_relay_poll_seconds: float = Field(default=1, alias="NATS_RELAY_POLL_SECONDS", gt=0)
    nats_relay_claim_seconds: float = Field(default=30, alias="NATS_RELAY_CLAIM_SECONDS", gt=0)
    nats_error_report_after_attempts: int = Field(default=5, alias="NATS_ERROR_REPORT_AFTER_ATTEMPTS", ge=1)

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @property
    def nats_servers(self) -> list[str]:
        return [server.strip() for server in self.nats_servers_raw.split(",") if server.strip()]

    @model_validator(mode="after")
    def validate_transport(self) -> NatsSettings:
        if not self.nats_servers:
            raise ValueError("NATS_SERVERS must not be empty")
        if self.nats_relay_claim_seconds <= self.nats_publish_timeout_seconds:
            raise ValueError("NATS_RELAY_CLAIM_SECONDS must exceed publish timeout")
        return self
