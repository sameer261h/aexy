"""Shared helpers for matching remote integration projects/teams to workspace teams.

Used by the Jira and Linear integration services to auto-build default
mappings when an integration is first connected.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_remote_pairs(items: list, id_field: str) -> list[tuple[str, str]]:
    """Normalize remote items (objects or dicts) to (identifier, name) pairs.

    Args:
        items: Remote projects/teams as Pydantic objects or dicts.
        id_field: Attribute/key holding the identifier ("key" for Jira, "id" for Linear).

    Returns:
        List of (identifier, name) tuples; items without an identifier are skipped.
    """
    pairs: list[tuple[str, str]] = []
    for item in items:
        identifier = getattr(item, id_field, None) or (
            item.get(id_field) if isinstance(item, dict) else None
        )
        name = getattr(item, "name", None) or (
            item.get("name") if isinstance(item, dict) else None
        )
        if identifier:
            pairs.append((identifier, name or ""))
    return pairs


async def match_remote_items_to_teams(
    db: AsyncSession,
    workspace_id: str,
    pairs: list[tuple[str, str]],
) -> dict[str, str]:
    """Match remote (identifier, name) pairs to workspace teams by name.

    Matching is case-insensitive on the remote name (exact match or the
    "Name (KEY)" startswith form) or on the remote identifier. Teams with
    no name match produce no mapping — mappings are never guessed.

    Args:
        db: Database session.
        workspace_id: Workspace whose teams to match against.
        pairs: Remote (identifier, name) pairs from normalize_remote_pairs.

    Returns:
        {team_id: remote_identifier} for teams that matched by name; {} when
        there are no pairs, no teams, or nothing matches.
    """
    if not pairs:
        return {}

    from aexy.models.team import Team

    teams = list(
        (
            await db.execute(
                select(Team)
                .where(Team.workspace_id == workspace_id)
                .order_by(Team.created_at)
            )
        ).scalars().all()
    )
    if not teams:
        return {}

    matches: dict[str, str] = {}
    for team in teams:
        tname = (team.name or "").strip().lower()
        if not tname:
            continue
        for identifier, name in pairs:
            rname = name.strip().lower()
            if (
                rname == tname
                or rname.startswith(f"{tname} (")
                or identifier.lower() == tname
            ):
                matches[str(team.id)] = identifier
                break

    return matches
