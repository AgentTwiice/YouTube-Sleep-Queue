"""Shared resolution of all mutable application paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = "yt_sub_playlist/data"


def resolve_data_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve data location: explicit argument, environment, then local default."""
    configured = explicit or os.getenv("YT_SUB_PLAYLIST_DATA_DIR")
    return Path(configured) if configured else Path(DEFAULT_DATA_DIR)


@dataclass(frozen=True)
class AppPaths:
    """Canonical mutable paths shared by the CLI and dashboard."""

    data_dir: Path

    @classmethod
    def resolve(cls, explicit: str | os.PathLike[str] | None = None) -> "AppPaths":
        return cls(resolve_data_dir(explicit))

    @property
    def config(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def legacy_config(self) -> Path:
        return Path("config.json")

    @property
    def runtime_state(self) -> Path:
        return self.data_dir / "runtime_state.json"

    @property
    def cache(self) -> Path:
        return self.data_dir / "processed_videos.json"

    @property
    def database(self) -> Path:
        return self.data_dir / "sleep_queue.sqlite3"

    @property
    def quota_log(self) -> Path:
        return self.data_dir / "api_call_log.json"

    @property
    def dashboard_playlist(self) -> Path:
        return self.data_dir / "dashboard_playlist.json"

    @property
    def refresh_jobs(self) -> Path:
        return self.data_dir / "refresh_jobs.json"

    @property
    def reports(self) -> Path:
        return self.data_dir / "reports"

    @property
    def legacy_reports(self) -> Path:
        return Path("yt_sub_playlist/reports")
