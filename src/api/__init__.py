from .yandex_accounts import router as yandex_accounts_router
from .yandex_auth import router as yandex_auth_router

__all__ = ["yandex_auth_router", "yandex_accounts_router"]
