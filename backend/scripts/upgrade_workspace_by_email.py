#!/usr/bin/env python3
"""Upgrade a workspace to a premium plan, selected interactively by user email.

Given a user's email, this lists every workspace that user owns or is a member
of, lets you pick one interactively (or via --index / --workspace), pick a plan
tier (or via --plan), and upgrades it.

Usage:
    python scripts/upgrade_workspace_by_email.py <email> [--plan <tier>] [--index N] [--workspace <slug_or_id>] [--yes]

Examples:
    # Interactive: list the user's workspaces, then prompt for the one to upgrade
    python scripts/upgrade_workspace_by_email.py user@example.com

    # Non-interactive: upgrade the 2nd listed workspace to pro
    python scripts/upgrade_workspace_by_email.py user@example.com --plan pro --index 2 --yes

    # Non-interactive: upgrade a specific workspace of that user to enterprise
    python scripts/upgrade_workspace_by_email.py user@example.com --workspace my-workspace --plan enterprise --yes
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aexy.models.developer import Developer
from aexy.models.plan import Plan, PlanTier
from aexy.models.workspace import Workspace, WorkspaceMember


async def get_db_url():
    """Get database URL from environment."""
    import os

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")

    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return db_url


async def _plan_name_for(session: AsyncSession, workspace: Workspace) -> str:
    """Human-readable current plan name for a workspace."""
    if not workspace.plan_id:
        return "Free (no plan)"
    plan_result = await session.execute(select(Plan).where(Plan.id == workspace.plan_id))
    plan = plan_result.scalar_one_or_none()
    return plan.name if plan else "Unknown"


async def find_user_workspaces(session: AsyncSession, developer: Developer):
    """Return workspaces the developer owns or is an active member of.

    Result is a list of (workspace, membership_role) tuples, deduplicated by
    workspace id, sorted by workspace name.
    """
    # Workspaces the user owns.
    owned_result = await session.execute(
        select(Workspace).where(
            Workspace.owner_id == developer.id,
            Workspace.is_active == True,  # noqa: E712
        )
    )
    owned = {ws.id: ws for ws in owned_result.scalars().all()}

    # Workspaces the user is a member of (any non-removed status).
    member_result = await session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.developer_id == developer.id,
            WorkspaceMember.status != "removed",
            Workspace.is_active == True,  # noqa: E712
        )
    )
    member_roles: dict[str, str] = {}
    member_ws: dict[str, Workspace] = {}
    for ws, role in member_result.all():
        member_ws[ws.id] = ws
        member_roles[ws.id] = role

    combined: dict[str, tuple[Workspace, str]] = {}
    for ws_id, ws in owned.items():
        combined[ws_id] = (ws, "owner")
    for ws_id, ws in member_ws.items():
        if ws_id not in combined:
            combined[ws_id] = (ws, member_roles.get(ws_id, "member"))

    return sorted(combined.values(), key=lambda pair: (pair[0].name or "").lower())


async def apply_upgrade(session: AsyncSession, workspace: Workspace, plan: Plan) -> None:
    """Set the workspace's plan and commit."""
    workspace.plan_id = plan.id
    await session.commit()

    print(f"\nSuccessfully upgraded workspace '{workspace.name}' to {plan.name} plan!")
    print("\nPlan features:")
    print(f"  - Team features: {plan.enable_team_features}")
    print(f"  - Advanced analytics: {plan.enable_advanced_analytics}")
    print(f"  - Exports: {plan.enable_exports}")
    print(f"  - Webhooks: {plan.enable_webhooks}")
    print(f"  - Real-time sync: {plan.enable_real_time_sync}")
    print(f"  - Max repos: {plan.max_repos}")
    print(f"  - LLM requests/day: {plan.llm_requests_per_day}")


async def resolve_plan(session: AsyncSession, plan_tier: str) -> Plan | None:
    """Look up an active plan by tier, printing available options if missing."""
    result = await session.execute(
        select(Plan).where(Plan.tier == plan_tier, Plan.is_active == True)  # noqa: E712
    )
    plan = result.scalar_one_or_none()
    if plan:
        return plan

    print(f"Plan not found: {plan_tier}")
    print("\nAvailable plans:")
    result = await session.execute(select(Plan).where(Plan.is_active == True))  # noqa: E712
    for p in result.scalars().all():
        print(f"  - {p.tier}: {p.name} (team_features={p.enable_team_features})")
    return None


def prompt_choice(count: int) -> int | None:
    """Prompt for a 1-based selection in [1, count]. Returns 0-based index."""
    while True:
        raw = input(f"\nSelect a workspace to upgrade [1-{count}], or 'q' to quit: ").strip()
        if raw.lower() in ("q", "quit", "exit", ""):
            return None
        if raw.isdigit() and 1 <= int(raw) <= count:
            return int(raw) - 1
        print(f"  Invalid choice: {raw!r}")


def prompt_plan(valid_tiers: list[str], default: str) -> str | None:
    """Prompt for a plan tier."""
    while True:
        raw = input(
            f"\nPlan tier {valid_tiers} [default: {default}], or 'q' to quit: "
        ).strip()
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw == "":
            return default
        if raw in valid_tiers:
            return raw
        print(f"  Invalid tier: {raw!r}")


async def run(args) -> bool:
    db_url = await get_db_url()
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    valid_tiers = [t.value for t in PlanTier]

    try:
        async with async_session() as session:
            # Find the developer by email (case-insensitive).
            dev_result = await session.execute(
                select(Developer).where(Developer.email.ilike(args.email))
            )
            developer = dev_result.scalar_one_or_none()
            if not developer:
                print(f"No user found with email: {args.email}")
                return False

            print(f"User: {developer.name or '(no name)'} <{developer.email}> (ID: {developer.id})")

            # Gather the user's workspaces.
            workspaces = await find_user_workspaces(session, developer)
            if not workspaces:
                print("\nThis user is not the owner or a member of any active workspace.")
                return False

            print(f"\nWorkspaces for this user ({len(workspaces)}):")
            for i, (ws, role) in enumerate(workspaces, start=1):
                plan_name = await _plan_name_for(session, ws)
                print(f"  {i}. {ws.name}  (slug: {ws.slug}, ID: {ws.id})")
                print(f"       role: {role} | current plan: {plan_name}")

            # Determine which workspace to upgrade.
            selected: Workspace | None = None
            if args.workspace:
                for ws, _role in workspaces:
                    if args.workspace in (ws.slug, ws.id):
                        selected = ws
                        break
                if not selected:
                    print(f"\nWorkspace {args.workspace!r} is not among this user's workspaces.")
                    return False
            elif args.index is not None:
                if not (1 <= args.index <= len(workspaces)):
                    print(f"\n--index must be between 1 and {len(workspaces)}")
                    return False
                selected = workspaces[args.index - 1][0]
            else:
                idx = prompt_choice(len(workspaces))
                if idx is None:
                    print("Aborted.")
                    return False
                selected = workspaces[idx][0]

            # Determine the plan tier.
            plan_tier = args.plan
            if plan_tier is None:
                plan_tier = prompt_plan(valid_tiers, default="enterprise")
                if plan_tier is None:
                    print("Aborted.")
                    return False
            if plan_tier not in valid_tiers:
                print(f"Invalid plan tier: {plan_tier}")
                print(f"Valid options: {', '.join(valid_tiers)}")
                return False

            plan = await resolve_plan(session, plan_tier)
            if not plan:
                return False

            # Confirm unless --yes.
            current_plan_name = await _plan_name_for(session, selected)
            print(
                f"\nAbout to upgrade '{selected.name}' (slug: {selected.slug})"
                f" from [{current_plan_name}] to [{plan.name}]."
            )
            if not args.yes:
                confirm = input("Proceed? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("Aborted.")
                    return False

            await apply_upgrade(session, selected, plan)
            return True
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Upgrade a workspace (selected by user email) to a premium plan.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("email", help="Email of the user whose workspaces to list/upgrade")
    parser.add_argument(
        "--plan",
        help="Plan tier to upgrade to (e.g. pro, enterprise). Prompted if omitted.",
    )
    parser.add_argument(
        "--index",
        type=int,
        help="1-based index of the workspace to upgrade (from the printed list). "
        "Skips the interactive prompt.",
    )
    parser.add_argument(
        "--workspace",
        help="Slug or ID of the workspace to upgrade (must belong to the user). "
        "Skips the interactive prompt.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    ok = asyncio.run(run(args))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
