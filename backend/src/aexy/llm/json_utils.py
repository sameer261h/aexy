"""Shared helpers for parsing JSON out of noisy LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from an LLM response.

    Tolerates the markdown code fences (```json ... ```) that models routinely
    add, and prose surrounding the object. Returns None when no JSON *object*
    can be recovered (arrays and other top-level values are rejected), so
    callers can fall back to their default output.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # The model may have wrapped the object in prose; try the outermost
    # {...} span.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
