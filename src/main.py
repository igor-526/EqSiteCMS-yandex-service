from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api import yandex_accounts_router, yandex_auth_router
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


app = FastAPI(title=settings.app_title, debug=settings.debug, lifespan=lifespan)

router = APIRouter(prefix="/api")
router.include_router(yandex_auth_router, prefix="/auth", tags=["Yandex Auth"])
router.include_router(yandex_accounts_router, prefix="/accounts", tags=["Yandex Accounts"])
app.include_router(router)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.errors()})
