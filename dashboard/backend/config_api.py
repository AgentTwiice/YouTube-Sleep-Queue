"""Configuration API blueprint factory."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from .config_manager import ConfigManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_config_blueprint(manager: ConfigManager) -> Blueprint:
    blueprint = Blueprint("config", __name__, url_prefix="/api/config")

    @blueprint.get("")
    def get_config():
        try:
            return jsonify(success=True, config=manager.load_config(), timestamp=_now())
        except (OSError, ValueError) as exc:
            return jsonify(success=False, error=str(exc), timestamp=_now()), 500

    @blueprint.put("")
    def update_config():
        updates = request.get_json(silent=True)
        if not isinstance(updates, dict):
            return jsonify(success=False, errors=["Request body must be a JSON object"]), 400
        result = manager.update_config(updates)
        return jsonify(**result, timestamp=_now()), 200 if result["success"] else 400

    @blueprint.post("/validate")
    def validate_config():
        value = request.get_json(silent=True)
        result = manager.validate_config(value)
        return jsonify(**result, timestamp=_now()), 200 if result["valid"] else 400

    @blueprint.get("/defaults")
    def get_defaults():
        return jsonify(success=True, defaults=manager.get_defaults(), timestamp=_now())

    @blueprint.post("/reset")
    def reset_config():
        try:
            config = manager.reset_to_defaults()
            return jsonify(success=True, config=config, timestamp=_now())
        except (OSError, ValueError) as exc:
            return jsonify(success=False, error=str(exc), timestamp=_now()), 500

    @blueprint.get("/summary")
    def get_summary():
        try:
            return jsonify(success=True, summary=manager.get_config_summary(), timestamp=_now())
        except (OSError, ValueError) as exc:
            return jsonify(success=False, error=str(exc), timestamp=_now()), 500

    return blueprint
