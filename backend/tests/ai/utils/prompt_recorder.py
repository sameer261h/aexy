"""Per-test prompt/completion recorder for the AI test suite.

Mirrors what the production `LLMGateway._log_prompt` writes to the
`llm_prompt_log` table, but lands in `tests/ai/.logs/<nodeid>.jsonl` so
debugging a failing AI test is a matter of `cat`-ing one file.

Wired in `tests/ai/conftest.py` as the `recorder` fixture, which
monkeypatches `LLMGateway._log_prompt` to append to the file in addition
to (or instead of) the DB log.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent / ".logs"


def _safe_nodeid(nodeid: str) -> str:
    # Replace path separators and brackets so the result is one filename.
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", nodeid)


class PromptRecorder:
    """Append-only JSONL recorder, one file per pytest node."""

    def __init__(self, nodeid: str, enabled: bool = True):
        self.nodeid = nodeid
        self.enabled = enabled
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOGS_DIR / f"{_safe_nodeid(nodeid)}.jsonl"
        if enabled:
            # Truncate so a re-run doesn't accumulate stale entries.
            self.path.write_text("")
        self._token_total = 0
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        *,
        operation: str,
        provider: str,
        model: str,
        system_prompt: str | None,
        user_prompt: str,
        completion: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "nodeid": self.nodeid,
            "operation": operation,
            "provider": provider,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "completion": completion,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if extra:
            entry["extra"] = extra
        self._token_total += input_tokens + output_tokens
        self._records.append(entry)
        if self.enabled:
            with self.path.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    @property
    def total_tokens(self) -> int:
        return self._token_total

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def summary(self) -> str:
        if not self._records:
            return f"[recorder] {self.nodeid}: no LLM calls"
        ops = ", ".join(sorted({r["operation"] for r in self._records}))
        return (
            f"[recorder] {self.nodeid}: {len(self._records)} calls, "
            f"{self._token_total} tokens — ops: {ops}"
        )


def write_golden(name: str, data: Any) -> Path:
    """Write/refresh a golden JSON file under tests/ai/goldens/."""
    goldens = Path(__file__).resolve().parent.parent / "goldens"
    goldens.mkdir(parents=True, exist_ok=True)
    path = goldens / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str, sort_keys=True))
    return path


def read_golden(name: str) -> Any | None:
    path = Path(__file__).resolve().parent.parent / "goldens" / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def should_update_goldens() -> bool:
    """True when the user passed --update-goldens or set UPDATE_GOLDENS=1."""
    return os.environ.get("UPDATE_GOLDENS") == "1"
