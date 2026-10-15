"""API-07: exercise the actual FastAPI lifespan with database disposal mocked."""

from unittest.mock import AsyncMock

import pytest

import main


async def test_real_lifespan_closes_database_only_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    close = AsyncMock()
    monkeypatch.setattr(main, "close_database", close)
    async with main.app.router.lifespan_context(main.app):
        close.assert_not_awaited()
        assert main.app.state.container is main.services_container
    close.assert_awaited_once_with()
