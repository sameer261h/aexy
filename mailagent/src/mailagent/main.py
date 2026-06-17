"""Main application entry point for mailagent service."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mailagent import __version__
from mailagent.api import (
    admin_router,
    domains_router,
    health_router,
    onboarding_router,
    agents_router,
    send_router,
    webhooks_router,
    process_router,
    invocations_router,
)
from mailagent.config import get_settings
from mailagent.database import engine
from mailagent.middleware import InternalAuthMiddleware
from mailagent.models import Base
from mailagent.redis_client import close_redis


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    settings = get_settings()

    # Create tables (in production, use migrations)
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Mailagent",
        description="Email administration, onboarding, and domain setup microservice",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — by default mailagent talks only to the Aexy backend (server →
    # server). Override via MAILAGENT_CORS_ALLOWED_ORIGINS only if a browser
    # tool needs direct access. `allow_credentials` is intentionally False;
    # the prior `allow_origins=["*"]` with credentials was a CORS spec
    # violation that also let non-browser callers through.
    allowed_origins = [
        o.strip() for o in (settings.cors_allowed_origins or "").split(",") if o.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Mailagent-Signature", "X-Mailagent-Timestamp"],
        )

    # HMAC auth on every non-public route. See middleware.py for the wire
    # format. When `internal_secret` is empty (dev) the middleware passes
    # through; in that mode the port MUST be bound to the internal network.
    app.add_middleware(InternalAuthMiddleware)
    if not settings.internal_secret:
        # WS-086: refuse to boot in prod/staging when the shared secret is
        # missing — silent fail-open here meant any pod-network neighbor
        # could call non-public mailagent routes without HMAC.
        if settings.environment.lower() in {"production", "staging"}:
            raise RuntimeError(
                "Mailagent internal_secret is empty but environment is "
                f"{settings.environment!r}. Configure MAILAGENT_INTERNAL_SECRET "
                "(matching the backend's mailagent_signing_secret) before deploy."
            )
        logger.warning(
            "Mailagent internal_secret is empty — running without backend HMAC auth. "
            "DO NOT deploy to production with this configuration."
        )

    # Register routers
    app.include_router(health_router)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(domains_router, prefix=settings.api_prefix)
    app.include_router(onboarding_router, prefix=settings.api_prefix)
    app.include_router(agents_router, prefix=settings.api_prefix)
    app.include_router(send_router, prefix=settings.api_prefix)
    app.include_router(webhooks_router, prefix=settings.api_prefix)
    app.include_router(process_router, prefix=settings.api_prefix)
    app.include_router(invocations_router, prefix=settings.api_prefix)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mailagent.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
