"""Persistence for generated runtime identifiers that are not user configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_json, preserve_corrupt_file


class RuntimeState:
    VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": self.VERSION}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != self.VERSION:
                raise ValueError("expected a version 1 JSON object")
            playlist_id = value.get("playlist_id")
            if playlist_id is not None and (
                not isinstance(playlist_id, str) or not playlist_id.strip()
            ):
                raise ValueError("playlist_id must be a non-empty string")
            return value
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            backup = preserve_corrupt_file(self.path)
            raise ValueError(
                f"Runtime state {self.path} is invalid; preserved it as {backup}. "
                "Repair or remove the backup before retrying."
            ) from exc

    def playlist_id(self) -> str | None:
        value = self.load().get("playlist_id")
        return value if isinstance(value, str) else None

    def save_playlist_id(self, playlist_id: str) -> None:
        if not isinstance(playlist_id, str) or not playlist_id.strip():
            raise ValueError("playlist_id must be a non-empty string")
        atomic_write_json(
            self.path,
            {"version": self.VERSION, "playlist_id": playlist_id.strip()},
            mode=0o600,
        )
