import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from utils import configure_logger, configure_sentry


def test_logger_configuration_restores_state(monkeypatch: pytest.MonkeyPatch) -> None:
    httpx_logger = logging.getLogger("httpx")
    original_level = httpx_logger.level
    basic_config = Mock()
    logger = Mock()
    real_get_logger = logging.getLogger
    monkeypatch.setattr(configure_logger.logging, "basicConfig", basic_config)
    monkeypatch.setattr(
        configure_logger.logging, "getLogger", lambda name: httpx_logger if name == "httpx" else logger
    )
    try:
        configure_logger.configure_logger("test-service", "TEST")
        assert httpx_logger.level == logging.WARNING
        basic_config.assert_called_once_with(
            format="TEST:\n    %(name)s %(levelname)s %(asctime)s \n    MESSAGE: %(message)s", level=logging.INFO
        )
        logger.info.assert_called_once_with("Logger has configured.")
    finally:
        httpx_logger.setLevel(original_level)
        monkeypatch.setattr(configure_logger.logging, "getLogger", real_get_logger)


@pytest.mark.parametrize("enabled", [False, True])
def test_sentry_initialization_without_export(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    fake_settings = SimpleNamespace(
        sentry_enabled=enabled,
        sentry_dsn="https://fake.example.test",
        sentry_environment="test",
        sentry_release="test-release",
        sentry_traces_sample_rate=0.75,
    )
    init = Mock()
    monkeypatch.setattr(configure_sentry, "settings", fake_settings)
    monkeypatch.setattr(configure_sentry.sentry_sdk, "init", init)
    configure_sentry.configure_sentry()
    if not enabled:
        init.assert_not_called()
        return
    init.assert_called_once()
    kwargs = dict(init.call_args.kwargs)
    integrations = kwargs.pop("integrations")
    assert [type(integration) for integration in integrations] == [FastApiIntegration, SqlalchemyIntegration]
    assert kwargs == {
        "dsn": fake_settings.sentry_dsn,
        "environment": "test",
        "release": "test-release",
        "traces_sample_rate": 0.75,
        "send_default_pii": False,
    }
