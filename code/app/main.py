import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.minio_client import get_minio_client
from app.clients.orchestrator_client import get_orchestrator_client
from app.core.config import Environment, settings
from app.core.logging import setup_logging
from app.core.middleware import (
    ConcurrencyLimitMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)
from app.routers.api import router as api_router
from app.routers.dev import router as dev_router

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
setup_logging(log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting STR Assurance Engine API")

    if settings.ENVIRONMENT == Environment.prod:
        try:
            app.state.client = get_orchestrator_client()
        except Exception as e:
            logger.critical("Failed to initialize OrchestratorClient", exc_info=True)
            raise RuntimeError("Failed to initialize OrchestratorClient") from e
    else:
        minio = get_minio_client()
        for bucket in (settings.REPORTS_BUCKET, settings.AIMBOMS_BUCKET):
            try:
                minio.create_bucket(bucket)
            except Exception as e:
                logger.critical(
                    "MinIO startup failed for bucket %s", bucket, exc_info=True
                )
                raise RuntimeError(f"MinIO startup failed for bucket {bucket}") from e

        app.state.client = minio

    yield

    logger.info("Shutting down STR Assurance Engine API")

    if settings.ENVIRONMENT == Environment.prod:
        logger.info("Closing client connection")
        await app.state.client.close()


app = FastAPI(
    title="STR Assurance Engine API",
    version=settings.VERSION,
    description="Collects the security reports from the rest of the CoEvolution components and generate, based on those reports, the AIMBOM for a given assessed/secured/robust AI model.",
    lifespan=lifespan,
)

# Configure CORS (TODO: adjust origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Logging middleware
# app.add_middleware(LoggingMiddleware)

if settings.ENVIRONMENT == Environment.prod:
    # Rate limiting middleware
    app.add_middleware(
        RateLimitMiddleware,
        rate_limit=10,
        rate_limit_window=60,
        protected_routes=["/api/generate", "/api/status"],
    )

    # Concurrency limiting middleware
    app.add_middleware(
        ConcurrencyLimitMiddleware,
        max_concurrent_requests=20,
        timeout=5.0,
        protected_routes=["/api/generate", "/api/status"],
    )

    # Size limiting middleware
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_content_length=1024 * 1024 * 50,  # 50MB
    )

# Include api router
app.include_router(api_router)

# Include dev router
if settings.ENVIRONMENT == Environment.dev:
    app.include_router(dev_router)
