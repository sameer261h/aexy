#!/usr/bin/env python3
"""Compare SQLAlchemy model tables with the SQL migration table inventory.

This is intentionally a table-level audit. It does not claim that matching
table names prove matching columns, constraints, indexes, or data migrations;
those still require a live-schema diff. The report makes model-only tables
visible so a migration can be added before readiness is trusted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF(?:\s+NOT)?\s+EXISTS\s+)?(?:public\.)?"
    r'"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)
ALTER_RE = re.compile(
    r"\bALTER\s+TABLE\s+(?:IF(?:\s+NOT)?\s+EXISTS\s+)?(?:public\.)?"
    r'"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)


def migration_tables(directory: Path) -> set[str]:
    """Return tables created or altered by migration SQL in *directory*."""
    tables: set[str] = set()
    for path in sorted(directory.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        tables.update(match.group(1).lower() for match in TABLE_RE.finditer(sql))
        tables.update(match.group(1).lower() for match in ALTER_RE.finditer(sql))
    return tables


def load_model_tables(kind: str, root: Path) -> set[str]:
    """Import one service's model registry and return its table names."""
    if kind == "backend":
        sys.path.insert(0, str(root / "backend" / "src"))
        import aexy.models  # noqa: F401
        from aexy.core.database import Base
    else:
        sys.path.insert(0, str(root / "mailagent" / "src"))
        from mailagent.models import Base

    return {table.name.lower() for table in Base.metadata.tables.values()}


def audit_service(kind: str, root: Path) -> dict[str, object]:
    migration_dir = root / ("backend/scripts" if kind == "backend" else "mailagent/migrations")
    models = load_model_tables(kind, root)
    migrations = migration_tables(migration_dir)
    return {
        "service": kind,
        "model_tables": len(models),
        "migration_tables": len(migrations),
        "model_only": sorted(models - migrations),
        "migration_only": sorted(migrations - models),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true", help="exit 1 when model-only tables exist")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    reports = [audit_service(kind, root) for kind in ("backend", "mailagent")]

    if args.as_json:
        print(json.dumps(reports, indent=2))
    else:
        for report in reports:
            print(
                f"{report['service']}: {report['model_tables']} model tables, "
                f"{report['migration_tables']} migration tables"
            )
            print(f"  model-only ({len(report['model_only'])}): {', '.join(report['model_only']) or 'none'}")
            print(f"  migration-only ({len(report['migration_only'])}): {', '.join(report['migration_only']) or 'none'}")

    return 1 if args.strict and any(report["model_only"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
