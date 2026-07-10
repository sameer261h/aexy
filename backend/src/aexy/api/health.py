"""Health check endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from aexy.core.database import get_async_session

router = APIRouter()

REQUIRED_TABLES = ("workspaces", "developers")


async def _check_schema(session) -> tuple[bool, list[str]]:
    """Check the minimum PostgreSQL schema required to serve application traffic."""
    if session.get_bind().dialect.name != "postgresql":
        # SQLite is used for the unit-test suite and has no pg_extension catalog.
        return True, []

    result = await session.execute(
        text(
            """
            SELECT
                to_regclass('public.workspaces') AS workspaces,
                to_regclass('public.developers') AS developers,
                EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'vector'
                ) AS vector_extension
            """
        )
    )
    row = result.mappings().one()
    missing = [table for table in REQUIRED_TABLES if row[table] is None]
    if not row["vector_extension"]:
        missing.append("extension:vector")
    return not missing, missing


@router.get("/health")
async def health_check():
    """Liveness check — confirms the process is running."""
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check():
    """Readiness check — confirms DB connectivity and the minimum schema exist."""
    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
            schema_ready, missing = await _check_schema(session)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": False, "schema": False},
        )
    if not schema_ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": True,
                "schema": False,
                "missing": missing,
            },
        )
    return {"status": "ready"}
