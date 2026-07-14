"""Normalized channel-management API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from yt_sub_playlist.auth.oauth import YouTubeAuthenticationError
from yt_sub_playlist.core.youtube_client import (
    YouTubeClient,
    YouTubeClientError,
    YouTubeQuotaError,
)

from .config_manager import ConfigManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_channels_blueprint(
    config_manager: ConfigManager,
    client_factory: Callable[[], YouTubeClient],
) -> Blueprint:
    blueprint = Blueprint("channels", __name__, url_prefix="/api/channels")

    def channel_error(exc: Exception):
        if isinstance(exc, YouTubeAuthenticationError):
            return jsonify(
                success=False,
                error="YouTube authorization is unavailable",
                channels=[],
                timestamp=_now(),
            ), 503
        if isinstance(exc, YouTubeQuotaError):
            return jsonify(
                success=False, error="YouTube quota is exhausted", channels=[], timestamp=_now()
            ), 503
        return jsonify(
            success=False,
            error="YouTube channel data is temporarily unavailable",
            channels=[],
            timestamp=_now(),
        ), 502

    @blueprint.get("")
    def get_channels():
        try:
            channels = sorted(
                client_factory().get_channels(), key=lambda item: item["title"].casefold()
            )
            return jsonify(success=True, channels=channels, count=len(channels), timestamp=_now())
        except (YouTubeAuthenticationError, YouTubeClientError) as exc:
            return channel_error(exc)

    @blueprint.get("/search")
    def search_channels():
        query = request.args.get("q", "")
        if not isinstance(query, str) or len(query) > 100:
            return jsonify(
                success=False, error="q must be at most 100 characters", channels=[]
            ), 400
        try:
            channels = sorted(
                client_factory().search_channels(query), key=lambda item: item["title"].casefold()
            )
            return jsonify(
                success=True, channels=channels, count=len(channels), query=query, timestamp=_now()
            )
        except (YouTubeAuthenticationError, YouTubeClientError) as exc:
            return channel_error(exc)

    @blueprint.get("/filter-config")
    def get_filter_config():
        try:
            config = config_manager.load_config()
            return jsonify(
                success=True,
                filter_mode=config["channel_filter_mode"],
                allowlist=config["channel_allowlist"] or [],
                blocklist=config["channel_blocklist"] or [],
                timestamp=_now(),
            )
        except (OSError, ValueError) as exc:
            return jsonify(success=False, error=str(exc), timestamp=_now()), 500

    @blueprint.put("/filter-config")
    def update_filter_config():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(success=False, errors=["Request body must be a JSON object"]), 400
        allowed = {"filter_mode", "allowlist", "blocklist"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            return jsonify(success=False, errors=[f"Unknown field(s): {', '.join(unknown)}"]), 400
        updates = {
            "channel_filter_mode": data.get("filter_mode", "none"),
            "channel_allowlist": data.get("allowlist") or None,
            "channel_blocklist": data.get("blocklist") or None,
        }
        result = config_manager.update_config(updates)
        return jsonify(**result, timestamp=_now()), 200 if result["success"] else 400

    @blueprint.get("/whitelisted")
    def get_whitelisted():
        config = config_manager.load_config()
        values = config["channel_allowlist"] or []
        return jsonify(
            success=True,
            enabled=config["channel_filter_mode"] == "allowlist",
            channel_ids=values,
            count=len(values),
            timestamp=_now(),
        )

    @blueprint.put("/whitelist")
    def update_whitelist():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
            return jsonify(
                success=False, errors=["enabled must be boolean and channel_ids must be an array"]
            ), 400
        channel_ids = data.get("channel_ids", [])
        if not isinstance(channel_ids, list):
            return jsonify(success=False, errors=["channel_ids must be an array"]), 400
        result = config_manager.update_config(
            {
                "channel_filter_mode": "allowlist" if data["enabled"] else "none",
                "channel_allowlist": channel_ids if data["enabled"] else None,
                "channel_blocklist": None,
            }
        )
        return jsonify(**result, timestamp=_now()), 200 if result["success"] else 400

    return blueprint
