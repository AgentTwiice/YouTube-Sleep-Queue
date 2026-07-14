"""Configuration loading, logging setup, and processed-video cache."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..core.atomic_io import atomic_write_json, preserve_corrupt_file
from ..core.paths import AppPaths
from .schema import ConfigSchema

logger = logging.getLogger(__name__)
CACHE_TTL_DAYS = 30


def load_config_json(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load a validated JSON object, preserving malformed user data for diagnosis."""
    paths = AppPaths.resolve()
    path = Path(config_path) if config_path else paths.config
    if not path.exists() and config_path is None and paths.legacy_config.exists():
        path = paths.legacy_config
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("the JSON root must be an object")
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        backup = preserve_corrupt_file(path)
        raise ValueError(
            f"Configuration file {path} is invalid ({exc}); it was preserved as {backup}. "
            "Repair the backup or create a valid configuration object."
        ) from exc


def load_config(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load defaults < JSON file < environment variables (CLI overrides later)."""
    load_dotenv()
    merged = load_config_json(config_path)
    merged.update(ConfigSchema.parse_environment(os.environ))
    return ConfigSchema.validate_config(merged)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in ("googleapiclient.discovery", "google.auth", "urllib3.connectionpool"):
        logging.getLogger(name).setLevel(logging.WARNING)


class VideoCache:
    """Validated, atomic JSON cache for processed video IDs."""

    def __init__(
        self,
        cache_file: str | os.PathLike[str] | None = None,
        ttl_days: int = CACHE_TTL_DAYS,
        data_dir: str | os.PathLike[str] | None = None,
    ):
        self.cache_file = Path(cache_file) if cache_file else AppPaths.resolve(data_dir).cache
        self.ttl_days = ttl_days
        self._cache: dict[str, dict[str, Any]] = {}
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            value = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("cache root must be an object")
            for video_id, entry in value.items():
                if not isinstance(video_id, str) or not isinstance(entry, dict):
                    raise ValueError("cache entries must map string IDs to objects")
                if not isinstance(entry.get("added_at"), str):
                    raise ValueError(f"cache entry {video_id!r} has no valid added_at")
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
            self._cache = {
                video_id: entry
                for video_id, entry in value.items()
                if _parse_timestamp(entry["added_at"]) > cutoff
            }
            if len(self._cache) != len(value):
                self._save_cache()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            backup = preserve_corrupt_file(self.cache_file)
            raise ValueError(
                f"Video cache {self.cache_file} is invalid; preserved it as {backup}. "
                "Inspect the backup and retry."
            ) from exc

    def _save_cache(self) -> None:
        atomic_write_json(self.cache_file, self._cache, mode=0o600)

    def is_processed(self, video_id: str) -> bool:
        return video_id in self._cache

    def mark_processed(self, video_id: str, title: str = "", channel: str = "") -> None:
        self.mark_processed_many([(video_id, title, channel)])

    def mark_processed_many(self, videos: list[tuple[str, str, str]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for video_id, title, channel in videos:
            self._cache[video_id] = {"added_at": now, "title": title, "channel": channel}
        if videos:
            self._save_cache()

    def get_stats(self) -> dict[str, int]:
        return {"total_processed": len(self._cache), "oldest_entry_days": self._oldest_age()}

    def _oldest_age(self) -> int:
        if not self._cache:
            return 0
        oldest = min(_parse_timestamp(entry["added_at"]) for entry in self._cache.values())
        return max(0, (datetime.now(timezone.utc) - oldest).days)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
