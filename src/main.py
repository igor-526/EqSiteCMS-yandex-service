import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api import (
    servicing,
    servicing_router,
    yandex_accounts,
    yandex_accounts_router,
    yandex_auth,
    yandex_auth_router,
    yandex_connections,
    yandex_connections_router,
    yandex_metrica,
    yandex_metrica_router,
)
from containers import services_container
from core.exceptions import AppError
from settings import settings
from utils.configure_logger import configure_logger
from utils.configure_sentry import configure_sentry
from utils.database import close_database

configure_logger(logger_root_name=__name__, logger_prefix_output="eqcms_yandex")
configure_sentry()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_database()


services_container.wire(
    modules=[yandex_auth, yandex_accounts, servicing, yandex_metrica, yandex_connections],
)


class SafeHttpErrorBoundary:
    """Handle failures after dependency cleanup, before ServerErrorMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception as exc:
            # Never replace an already-started response or swallow BaseException.
            if response_started:
                raise
            response = await unexpected_error_handler(Request(scope), exc)
            await response(scope, receive, send)


# Starlette's debug middleware bypasses the unexpected-error handler and exposes
# tracebacks. Never enable it on this peer, even when development settings do.
app = FastAPI(title=settings.app_title, debug=False, lifespan=lifespan, redirect_slashes=False)
app.add_middleware(SafeHttpErrorBoundary)
logger = logging.getLogger(__name__)
app.state.container = services_container

router = APIRouter(prefix="/api")
router.include_router(yandex_auth_router, prefix="/auth", tags=["Yandex Auth"])
router.include_router(yandex_accounts_router, prefix="/accounts", tags=["Yandex Accounts"])
router.include_router(servicing_router, prefix="/servicing", tags=["Servicing"])
router.include_router(yandex_metrica_router, prefix="/metrica", tags=["Yandex Metrica"])
router.include_router(yandex_connections_router, prefix="/connections", tags=["Connections"])
app.include_router(router)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    # Even domain messages may embed Pydantic input or repository diagnostics.
    logger.warning("request_failure category=application")
    return JSONResponse(status_code=400, content={"detail": "Не удалось выполнить запрос"})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo input, ctx, msg or arbitrary loc keys from a malformed body.
    detail = [{"type": "request_validation", "msg": "Некорректные параметры запроса"} for _ in exc.errors()]
    return JSONResponse(status_code=400, content={"detail": detail})


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # Do not forward exception detail/headers (they can contain secrets).
    logger.warning("request_failure category=http")
    return JSONResponse(status_code=400, content={"detail": "Запрос отклонён"})


@app.exception_handler(ResponseValidationError)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    category = "response_validation" if isinstance(exc, ResponseValidationError) else "unexpected"
    # Chained causes are retained internally, never printed with traceback.
    logger.error("request_failure category=%s", category)
    return JSONResponse(status_code=400, content={"detail": "Не удалось выполнить запрос"})
