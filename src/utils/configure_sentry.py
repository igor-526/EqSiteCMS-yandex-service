import logging

from settings import settings


def configure_sentry() -> None:
    """Configure Sentry error tracking."""
    if not settings.sentry_enabled:
        logging.info("Sentry is disabled")
        return

    if not settings.sentry_dsn:
        logging.warning("Sentry is enabled but SENTRY_DSN is not set")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            release=settings.sentry_release or None,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
        )
        logging.info("Sentry initialized successfully")
    except Exception as e:
        logging.error("Failed to initialize Sentry: %s", e, exc_info=True)
