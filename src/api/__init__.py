from .servicing import router as servicing_router
from .yandex_accounts import router as yandex_accounts_router
from .yandex_auth import router as yandex_auth_router
from .yandex_connections import router as yandex_connections_router
from .yandex_metrica import router as yandex_metrica_router

__all__ = [
    "yandex_auth_router",
    "yandex_accounts_router",
    "servicing_router",
    "yandex_metrica_router",
    "yandex_connections_router",
]
