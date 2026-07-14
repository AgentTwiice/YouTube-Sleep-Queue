"""Versioned YouTube quota event schema shared by CLI, dashboard, and tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config.quota_costs import get_quota_cost
from .atomic_io import atomic_write_json

QUOTA_LOG_VERSION = 1


def write_quota_log(path: Path, events: list[dict[str, Any]], generated_at: str) -> None:
    validated = _validate_events(events)
    atomic_write_json(
        path,
        {
            "schema_version": QUOTA_LOG_VERSION,
            "generated_at": generated_at,
            "events": validated,
        },
        mode=0o600,
    )


def read_quota_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": QUOTA_LOG_VERSION, "events": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Quota log root must be an object")
    if "schema_version" not in value:
        events: list[dict[str, Any]] = []
        for method, count in value.items():
            if (
                not isinstance(method, str)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError("Legacy quota log has an invalid entry")
            events.extend(
                {
                    "timestamp": None,
                    "method": method,
                    "quota_cost": get_quota_cost(method),
                    "result": "legacy_success",
                }
                for _ in range(count)
            )
        return {
            "schema_version": QUOTA_LOG_VERSION,
            "events": events,
            "migrated_from": 0,
        }
    if value.get("schema_version") != QUOTA_LOG_VERSION:
        raise ValueError("Unsupported quota log schema")
    raw_events = value.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("Quota log events must be an array")
    result = dict(value)
    result["events"] = _validate_events(raw_events)
    return result


def _validate_events(events: list[Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Quota events must be objects")
        method = event.get("method")
        result = event.get("result")
        cost = event.get("quota_cost")
        timestamp = event.get("timestamp")
        if not isinstance(method, str) or not method:
            raise ValueError("Quota event method must be a non-empty string")
        if not isinstance(result, str) or not result:
            raise ValueError("Quota event result must be a non-empty string")
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise ValueError("Quota event cost must be a non-negative integer")
        if timestamp is not None and not isinstance(timestamp, str):
            raise ValueError("Quota event timestamp must be a string or null")
        validated.append(
            {
                "timestamp": timestamp,
                "method": method,
                "quota_cost": cost,
                "result": result,
            }
        )
    return validated
