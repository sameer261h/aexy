#!/usr/bin/env python3
"""Backfill: clone workspace-default task statuses into existing projects.

NOT a registered migration — the migration runner only picks up files matching
`migrate*.sql`, so this script will never run automatically. Operators run it
manually after applying `migrate_project_task_statuses.sql` to seed each
project's status set from the workspace defaults. Once cloned, the project's
statuses can diverge from the workspace without affecting other projects.

Usage:
    # Single project
    docker exec aexy-backend python scripts/backfill_project_task_statuses.py \\
        --workspace-id <ws-uuid> --project-id <proj-uuid>

    # Every project in a workspace
    docker exec aexy-backend python scripts/backfill_project_task_statuses.py \\
        --workspace-id <ws-uuid>

    # Every project in every workspace
    docker exec aexy-backend python scripts/backfill_project_task_statuses.py --all

    # Preview without writing
    docker exec aexy-backend python scripts/backfill_project_task_statuses.py --all --dry-run

The script is idempotent: a project that already has its own status rows is
skipped (count unchanged) so re-running is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
except NameError:
    for candidate in ("/app/src", os.path.join(os.getcwd(), "src")):
        if os.path.isdir(candidate):
            sys.path.insert(0, candidate)
            break

from sqlalchemy import select  # noqa: E402

from aexy.core.database import async_session_maker  # noqa: E402
from aexy.models.project import Project  # noqa: E402
from aexy.services.task_config_service import TaskConfigService  # noqa: E402


async def _projects_in_workspace(db, workspace_id: str) -> list[Project]:
    stmt = select(Project).where(Project.workspace_id == workspace_id)
    return list((await db.execute(stmt)).scalars().all())


async def _projects_in_all_workspaces(db) -> list[Project]:
    stmt = select(Project)
    return list((await db.execute(stmt)).scalars().all())


async def _backfill_one(db, workspace_id: str, project_id: str, dry_run: bool) -> str:
    """Returns one of: 'skipped', 'copied N', 'no_defaults'."""
    service = TaskConfigService(db)

    existing = await service.get_statuses(
        workspace_id, project_id=project_id, include_inactive=True
    )
    if existing:
        return "skipped (already has overrides)"

    defaults = await service.get_statuses(workspace_id, include_inactive=True)
    if not defaults:
        return "no_defaults (workspace has no task statuses to clone)"

    if dry_run:
        return f"would copy {len(defaults)}"

    cloned = await service.clone_workspace_statuses_to_project(workspace_id, project_id)
    return f"copied {len(cloned)}"


async def run(args: argparse.Namespace) -> int:
    async with async_session_maker() as db:
        # Resolve which projects to process.
        if args.all:
            projects = await _projects_in_all_workspaces(db)
        elif args.workspace_id and args.project_id:
            stmt = select(Project).where(
                Project.id == args.project_id,
                Project.workspace_id == args.workspace_id,
            )
            row = (await db.execute(stmt)).scalar_one_or_none()
            if not row:
                print(
                    f"ERROR: project {args.project_id} not found in workspace {args.workspace_id}",
                    file=sys.stderr,
                )
                return 2
            projects = [row]
        elif args.workspace_id:
            projects = await _projects_in_workspace(db, args.workspace_id)
        else:
            print(
                "ERROR: pass --all, --workspace-id, or both --workspace-id and --project-id",
                file=sys.stderr,
            )
            return 2

        if not projects:
            print("No matching projects.")
            return 0

        # One stable line per project so a long run is grep-friendly. Workspace
        # is included up-front because --all crosses workspaces.
        for project in projects:
            outcome = await _backfill_one(
                db,
                workspace_id=str(project.workspace_id),
                project_id=str(project.id),
                dry_run=args.dry_run,
            )
            print(
                f"ws={project.workspace_id} project={project.id} ({project.name!r}): {outcome}"
            )

        if args.dry_run:
            print("\nDRY RUN — no changes written.")
        else:
            await db.commit()
            print(f"\nDone. Processed {len(projects)} project(s).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clone workspace-default task statuses into projects.",
    )
    parser.add_argument(
        "--workspace-id",
        help="Workspace UUID. Without --project-id, processes every project in this workspace.",
    )
    parser.add_argument(
        "--project-id",
        help="Project UUID. Requires --workspace-id.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every project in every workspace.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing any rows.",
    )
    args = parser.parse_args()

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
