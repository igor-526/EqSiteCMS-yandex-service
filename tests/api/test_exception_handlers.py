"""API-04: central handlers tested through actual registered endpoints."""

import pytest

from core.exceptions import AlreadyExistsError, AppError, ClientError
from tests.api.conftest import ACCOUNT_ID, RuntimeApi


@pytest.mark.parametrize("service", ["oauth", "accounts", "authorization", "metrica"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ClientError("invalid account"), 400),
        (AlreadyExistsError("duplicate"), 409),
        (AppError("unavailable"), 500),
        (RuntimeError("unexpected private data"), 500),
    ],
)
async def test_exception_mapping(runtime_api: RuntimeApi, service: str, error: Exception, status: int) -> None:
    method, url, mock = {
        "oauth": ("post", "/api/auth/code", runtime_api.oauth.authenticate),
        "accounts": ("delete", f"/api/accounts/{ACCOUNT_ID}", runtime_api.accounts.delete_account),
        "authorization": ("get", f"/api/servicing/access-token/{ACCOUNT_ID}", runtime_api.authorization.get_token),
        "metrica": ("get", f"/api/metrica/counters?account_id={ACCOUNT_ID}", runtime_api.metrica.get_counters),
    }[service]
    mock.side_effect = error
    async with runtime_api.client() as client:
        response = await client.request(method, url, json={"code": "abc", "equestrian_id": str(ACCOUNT_ID)})
    assert response.status_code == status
    if isinstance(error, AppError):
        assert response.json() == {"detail": error.message}
    else:
        assert "unexpected private data" not in response.text
    runtime_api.assert_transaction(status, "rollback")
