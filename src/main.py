import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from core.exceptions import AppError
from settings import settings
from utils.configure_sentry import configure_sentry
from utils.database import close_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

configure_sentry()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    # Startup
    logging.info("Yandex Service starting up...")

    try:
        yield
    finally:
        # Shutdown
        logging.info("Yandex Service shutting down...")
        await close_database()


app = FastAPI(title=settings.app_title, debug=settings.debug, lifespan=lifespan)

Instrumentator().instrument(app)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Health check endpoint - anonymous access allowed."""
    return {"status": "ok"}


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.errors()})
