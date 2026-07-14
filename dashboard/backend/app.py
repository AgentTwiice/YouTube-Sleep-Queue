"""Application factory for the loopback-only dashboard."""

from __future__ import annotations

import csv
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from yt_sub_playlist.core.paths import AppPaths
from yt_sub_playlist.core.youtube_client import YouTubeClient

from .channels_api import create_channels_blueprint
from .config_api import create_config_blueprint
from .config_manager import ConfigManager
from .refresh_jobs import RefreshAlreadyRunning, RefreshJobManager
from .stats_api import create_stats_blueprint

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
RESERVED_DEVICE = re.compile(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$")


class PlaylistDataSource:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    def get(self) -> dict[str, Any]:
        generated = self._generated()
        if generated is not None:
            return generated
        report = self._report()
        if report is not None:
            return report
        return {"source": "none", "stale": True, "last_updated": None, "videos": []}

    def _generated(self) -> dict[str, Any] | None:
        path = self.paths.dashboard_playlist
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("videos"), list)
        ):
            raise ValueError("Generated dashboard data has an invalid schema")
        updated_value = value.get("last_updated")
        if not isinstance(updated_value, str):
            raise ValueError("Generated dashboard data has no valid last_updated timestamp")
        try:
            updated = datetime.fromisoformat(updated_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Generated dashboard data has an invalid timestamp") from exc
        if updated.tzinfo is None:
            raise ValueError("Generated dashboard timestamp must include a timezone")
        age_seconds = (
            datetime.now(timezone.utc) - updated.astimezone(timezone.utc)
        ).total_seconds()
        return {
            "source": "generated",
            "stale": bool(value.get("stale", False)) or age_seconds > 86_400,
            "last_updated": updated_value,
            "videos": value["videos"],
        }

    def _report(self) -> dict[str, Any] | None:
        reports: list[Path] = []
        for directory in (self.paths.reports, self.paths.legacy_reports):
            if directory.exists():
                reports.extend(directory.glob("*.csv"))
        if not reports:
            return None
        path = max(reports, key=lambda candidate: candidate.stat().st_mtime)
        videos: list[dict[str, Any]] = []
        with path.open(newline="", encoding="utf-8") as report:
            for row in csv.DictReader(report):
                videos.append(dict(row))
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - modified).total_seconds()
        return {
            "source": "report",
            "stale": age_seconds > 86_400,
            "last_updated": modified.isoformat(),
            "videos": videos,
        }


def create_app(
    *,
    data_dir: Path | str | None = None,
    config_manager: ConfigManager | None = None,
    youtube_client_factory=None,
    refresh_manager: RefreshJobManager | None = None,
    testing: bool = False,
) -> Flask:
    paths = AppPaths.resolve(data_dir)
    manager = config_manager or ConfigManager(data_dir=paths.data_dir)
    client_factory = youtube_client_factory or (lambda: YouTubeClient(paths.data_dir))
    jobs = refresh_manager or RefreshJobManager(
        paths.refresh_jobs,
        paths.reports,
        Path.cwd().resolve(),
        default_timeout=_refresh_timeout(manager),
    )
    playlist_data = PlaylistDataSource(paths)

    app = Flask(__name__, static_folder=None)
    app.config.update(
        TESTING=testing,
        MAX_CONTENT_LENGTH=64 * 1024,
        CSRF_TOKEN=secrets.token_urlsafe(32),
        TRUSTED_HOSTS=["127.0.0.1:5001", "localhost:5001", "[::1]:5001"]
        + (["localhost"] if testing else []),
    )
    app.extensions["refresh_jobs"] = jobs
    app.register_blueprint(create_config_blueprint(manager))
    app.register_blueprint(create_channels_blueprint(manager, client_factory))
    app.register_blueprint(create_stats_blueprint(paths))

    @app.before_request
    def protect_local_mutations():
        if request.path.startswith("/api/") and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            if not request.is_json:
                return jsonify(success=False, error="Request must be JSON"), 415
            origin = request.headers.get("Origin")
            allowed_origins = {
                "http://127.0.0.1:5001",
                "http://localhost:5001",
                "http://[::1]:5001",
            }
            if testing:
                allowed_origins.add("http://localhost")
            if origin not in allowed_origins:
                return jsonify(
                    success=False, error="A valid loopback Origin header is required"
                ), 403
            fetch_site = request.headers.get("Sec-Fetch-Site")
            if fetch_site and fetch_site not in {"same-origin", "none"}:
                return jsonify(success=False, error="Cross-site browser request rejected"), 403
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or not secrets.compare_digest(supplied, app.config["CSRF_TOKEN"]):
                return jsonify(success=False, error="Invalid request-protection token"), 403
            if jobs.is_active() and request.path.startswith(("/api/config", "/api/channels")):
                return jsonify(success=False, error="Configuration is locked during refresh"), 409
        return None

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https://i.ytimg.com data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response

    @app.get("/")
    def index():
        return send_from_directory(DASHBOARD_DIR, "index.html")

    @app.get("/api/playlist")
    def get_playlist():
        try:
            result = playlist_data.get()
            return jsonify(
                success=True,
                data=result["videos"],
                count=len(result["videos"]),
                **{key: result[key] for key in ("source", "stale", "last_updated")},
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return jsonify(success=False, error=f"Playlist data is invalid: {exc}"), 500

    @app.get("/api/csrf-token")
    def csrf_token():
        response = jsonify(success=True, csrf_token=app.config["CSRF_TOKEN"])
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/refresh")
    def start_refresh():
        body = request.get_json(silent=True)
        if (
            not isinstance(body, dict)
            or set(body) - {"dry_run"}
            or not isinstance(body.get("dry_run", False), bool)
        ):
            return jsonify(success=False, error="Body may contain only boolean dry_run"), 400
        try:
            job = jobs.start(body.get("dry_run", False))
            return jsonify(success=True, job=job, job_id=job["id"]), 202
        except RefreshAlreadyRunning as exc:
            return jsonify(success=False, error=str(exc), job=jobs.latest()), 409

    @app.get("/api/refresh/<job_id>")
    def refresh_status(job_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            return jsonify(success=False, error="Invalid job ID"), 400
        job = jobs.get(job_id)
        if job is None:
            return jsonify(success=False, error="Refresh job not found"), 404
        return jsonify(success=True, job=job)

    @app.get("/api/status")
    def status():
        return jsonify(
            success=True,
            refresh=jobs.latest(),
            data_dir=str(paths.data_dir),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/<path:filename>")
    def static_files(filename: str):
        if any(RESERVED_DEVICE.fullmatch(part) for part in Path(filename).parts):
            return jsonify(success=False, error="Not Found"), 404
        return send_from_directory(DASHBOARD_DIR, filename)

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(success=False, error="Not Found"), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify(success=False, error="Internal Server Error"), 500

    return app


def _refresh_timeout(manager: ConfigManager) -> int:
    try:
        config = manager.load_config()
        explicit = config.get("refresh_timeout_seconds")
        if explicit:
            return int(explicit)
        return min(14_400, max(300, config["max_videos"] * config["ollama_timeout_seconds"] + 180))
    except (OSError, ValueError):
        return 1800
