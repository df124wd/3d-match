import os
import sys
import logging
import time
from contextlib import asynccontextmanager

from loguru import logger as loguru_logger
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from api.config import Settings
from api.db.session import create_engine_and_session
from api.services.faiss_manager import FaissManager
from api.routers import health, ingestion, query, matching

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

CONSOLE_FORMAT = (
    "<cyan>{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} - "
    "{message}"
)


class InterceptHandler(logging.Handler):
    """将标准 logging 桥接到 loguru，统一格式和输出。"""

    def emit(self, record):
        try:
            level = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)

    loguru_logger.remove()

    loguru_logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level="INFO",
        colorize=True,
    )

    loguru_logger.add(
        os.path.join(LOG_DIR, "app.log"),
        format=FILE_FORMAT,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="INFO",
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    for name in ["uvicorn.access", "sqlalchemy.engine"]:
        logging.getLogger(name).setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        method = request.method
        path = request.url.path

        response = await call_next(request)

        duration_ms = (time.time() - start) * 1000
        logger.info(
            "%s %s | Status: %d | Duration: %.2fms",
            method, path, response.status_code, duration_ms,
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings

    engine, session_factory = create_engine_and_session(settings)
    app.state.db_session_factory = session_factory

    faiss_manager = FaissManager(settings.faiss_index_dir, settings.feature_dim)
    faiss_manager.load()
    app.state.faiss_manager = faiss_manager

    logger.info(
        "Service started. MySQL=%s:%d DB=%s FAISS vectors=%d",
        settings.mysql_host, settings.mysql_port, settings.mysql_database,
        faiss_manager.vector_count(),
    )

    yield

    faiss_manager.save()
    engine.dispose()
    logger.info("Service stopped.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="3D Model Similarity Retrieval API",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLogMiddleware)

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(ingestion.router, prefix="/api/v1", tags=["ingestion"])
    app.include_router(query.router, prefix="/api/v1", tags=["query"])
    app.include_router(matching.router, prefix="/api/v1", tags=["matching"])

    return app


app = create_app()
