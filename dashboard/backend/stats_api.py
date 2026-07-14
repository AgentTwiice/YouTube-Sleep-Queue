"""Dashboard statistics backed by the same files as the CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from yt_sub_playlist.config.env_loader import VideoCache
from yt_sub_playlist.core.paths import AppPaths
from yt_sub_playlist.core.quota_log import QUOTA_LOG_VERSION, read_quota_log


def create_stats_blueprint(paths: AppPaths) -> Blueprint:
    blueprint = Blueprint("stats", __name__, url_prefix="/api/stats")

    @blueprint.get("/quota")
    def quota_stats():
        try:
            log = read_quota_log(paths.quota_log)
            today = datetime.now(timezone.utc).date().isoformat()
            events = [
                event
                for event in log["events"]
                if event.get("timestamp") is None or str(event["timestamp"]).startswith(today)
            ]
            used = sum(event["quota_cost"] for event in events)
            limit = 10_000
            return jsonify(
                success=True,
                quota={
                    "schema_version": QUOTA_LOG_VERSION,
                    "daily_used": used,
                    "remaining": max(0, limit - used),
                    "percentage_used": min(100.0, used / limit * 100),
                    "attempted_calls": len(events),
                },
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return jsonify(success=False, error=f"Quota log is invalid: {exc}"), 500

    @blueprint.get("/cache")
    def cache_stats():
        try:
            stats = VideoCache(cache_file=paths.cache).get_stats()
            return jsonify(
                success=True,
                cache={
                    "total_videos": stats["total_processed"],
                    "oldest_entry_age_days": stats["oldest_entry_days"],
                },
            )
        except (OSError, ValueError) as exc:
            return jsonify(success=False, error=str(exc)), 500

    @blueprint.get("/health")
    def health():
        return jsonify(
            success=True,
            status="healthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    return blueprint
