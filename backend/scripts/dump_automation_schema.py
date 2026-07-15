"""Dump the automation trigger/action registry to a JSON file.

The frontend Playwright suite (e2e/ai-automation-*.spec.ts) parametrises
its per-subtype tests from this fixture so that adding a new trigger or
action on the backend forces a matching test entry — no hand-maintained
mirror to drift out of sync.

When run via `docker exec`, the frontend tree isn't mounted in the
container — pipe stdout to the host path:

    docker exec aexy-backend python scripts/dump_automation_schema.py \\
        --out - > frontend/e2e/fixtures/automation-schema.generated.json

When run on the host with the backend venv active, the default --out
points at the right path and no redirection is needed.

Use `--check` in CI to verify the on-disk fixture is up to date.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aexy.schemas.automation import (
    ENABLED_MODULES,
    get_all_actions,
    get_all_triggers,
)


DEFAULT_OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "e2e"
    / "fixtures"
    / "automation-schema.generated.json"
)


def build_payload() -> dict:
    # Enabled (CRM-only) scope — mirrors exactly what the registry API serves
    # the palette. Non-CRM modules and hidden capabilities are excluded.
    modules = list(ENABLED_MODULES)
    return {
        "_meta": {
            "source": "backend/src/aexy/schemas/automation.py",
            "generator": "backend/scripts/dump_automation_schema.py",
        },
        "modules": modules,
        "triggers": get_all_triggers(),
        "actions": get_all_actions(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Output JSON path, or '-' for stdout (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the on-disk file differs from what would be written.",
    )
    args = parser.parse_args()

    payload = build_payload()
    encoded = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    summary = (
        f"{len(payload['modules'])} modules, "
        f"{sum(len(v) for v in payload['triggers'].values())} triggers, "
        f"{sum(len(v) for v in payload['actions'].values())} actions"
    )

    if args.check:
        out_path = Path(args.out)
        if not out_path.exists():
            print(f"check: {out_path} does not exist", file=sys.stderr)
            return 1
        existing = out_path.read_text()
        if existing != encoded:
            print(
                f"check: {out_path} is stale — re-run "
                f"`python scripts/dump_automation_schema.py` and commit.",
                file=sys.stderr,
            )
            return 1
        print(f"check: {out_path} up to date ({summary}).", file=sys.stderr)
        return 0

    if args.out == "-":
        # Progress to stderr so stdout is pure JSON — keeps pipe usage
        # `docker exec ... --out - > foo.json` clean.
        sys.stdout.write(encoded)
        print(f"wrote {summary} → stdout", file=sys.stderr)
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(encoded)
    print(f"wrote {summary} → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
