from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from depends import utils


@pytest.mark.parametrize("fail", [False, True])
async def test_get_session_context_cleanup(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.__aenter__.return_value = session
    factory = Mock(return_value=session)
    monkeypatch.setattr(utils, "AsyncSessionLocal", factory)
    iterator = utils.get_session()
    assert await anext(iterator) is session
    if fail:
        error = RuntimeError("caller failed")
        with pytest.raises(RuntimeError) as exc:
            await iterator.athrow(error)
        assert exc.value is error
        assert session.__aexit__.await_args.args[:2] == (RuntimeError, error)
    else:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        session.__aexit__.assert_awaited_once_with(None, None, None)
    factory.assert_called_once_with()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
