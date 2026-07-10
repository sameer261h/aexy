"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from mailagent import __version__
from mailagent.config import get_settings
from mailagent.database import async_session_factory, check_db_connection
from mailagent.redis_client import check_redis_connection
from mailagent.schemas import HealthResponse

router = APIRouter(tags=["Health"])

REQUIRED_TABLES = ("mailagent_providers", "mailagent_domains", "mailagent_inboxes")


async def check_schema_connection() -> bool:
    """Confirm the core mailagent tables exist, not just the database socket."""
    try:
        async with async_session_factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                return True
            result = await session.execute(
                text(
                    "SELECT "
                    + ", ".join(
                        f"to_regclass('public.{table}') AS {table}"
                        for table in REQUIRED_TABLES
                    )
                )
            )
            row = result.mappings().one()
            return all(row[table] is not None for table in REQUIRED_TABLES)
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health."""
    settings = get_settings()

    db_healthy = await check_db_connection()
    redis_healthy = await check_redis_connection()

    status = "healthy" if (db_healthy and redis_healthy) else "degraded"

    return HealthResponse(
        status=status,
        service=settings.service_name,
        version=__version__,
        database=db_healthy,
        redis=redis_healthy,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready")
async def readiness_check() -> dict:
    """Kubernetes readiness probe."""
    db_healthy = await check_db_connection()
    redis_healthy = await check_redis_connection()
    schema_healthy = await check_schema_connection()

    if not db_healthy or not redis_healthy or not schema_healthy:
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "database": db_healthy,
                "redis": redis_healthy,
                "schema": schema_healthy,
            },
        )

    return {"ready": True, "schema": True}


@router.get("/live")
async def liveness_check() -> dict:
    """Kubernetes liveness probe."""
    return {"alive": True}
