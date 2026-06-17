"""Sample Python code for AI analysis tests.

Used as input to CodeAnalyzer.analyze_code(). Intentionally exercises
several Python idioms a model should recognize: type hints, async/await,
dataclasses, FastAPI dependencies, SQLAlchemy queries.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from aexy.core.database import get_db
from aexy.models.developer import Developer


@dataclass
class DeveloperSummary:
    id: str
    name: str
    seniority: str
    last_active: Optional[datetime]


async def get_developer_summary(
    developer_id: str,
    db: AsyncSession = Depends(get_db),
) -> DeveloperSummary:
    """Fetch a compact summary of a developer for the sidebar widget.

    Raises 404 when the developer is not found. Last-active falls back
    to None when the developer has no recorded activity.
    """
    result = await db.execute(
        select(Developer).where(Developer.id == developer_id)
    )
    developer = result.scalar_one_or_none()
    if developer is None:
        raise HTTPException(status_code=404, detail="Developer not found")

    last_active = developer.last_active_at
    if last_active and last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=timezone.utc)

    return DeveloperSummary(
        id=str(developer.id),
        name=developer.name,
        seniority=developer.seniority_level or "unknown",
        last_active=last_active,
    )
