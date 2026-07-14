"""Validated and atomic dashboard configuration persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yt_sub_playlist.config.env_loader import load_config_json
from yt_sub_playlist.config.schema import ConfigSchema
from yt_sub_playlist.core.atomic_io import atomic_write_json, preserve_corrupt_file
from yt_sub_playlist.core.paths import AppPaths


class ConfigManager:
    DEFAULT_CONFIG = dict(ConfigSchema.DEFAULTS)

    def __init__(self, config_file: Path | None = None, data_dir: Path | None = None):
        self.paths = AppPaths.resolve(data_dir)
        self.config_file = Path(config_file) if config_file else self.paths.config

    def load_config(self) -> dict[str, Any]:
        if self.config_file.exists():
            try:
                value = json.loads(self.config_file.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("the JSON root must be an object")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                backup = preserve_corrupt_file(self.config_file)
                raise ValueError(
                    f"Configuration is invalid; preserved it as {backup}. Repair it before retrying."
                ) from exc
        elif self.paths.legacy_config.exists() and self.config_file == self.paths.config:
            value = load_config_json(self.paths.legacy_config)
        else:
            value = {}
        return ConfigSchema.validate_config(value, allow_runtime_keys=False)

    def save_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        validated = ConfigSchema.validate_config(config, allow_runtime_keys=False)
        atomic_write_json(self.config_file, validated, mode=0o600)
        return validated

    def validate_config(self, config: Any) -> dict[str, Any]:
        try:
            ConfigSchema.validate_config(config, allow_runtime_keys=False)
        except (TypeError, ValueError) as exc:
            return {"valid": False, "errors": [str(exc)]}
        return {"valid": True, "errors": []}

    def get_defaults(self) -> dict[str, Any]:
        return dict(self.DEFAULT_CONFIG)

    def reset_to_defaults(self) -> dict[str, Any]:
        return self.save_config(self.DEFAULT_CONFIG)

    def update_config(self, updates: Any) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return {"success": False, "errors": ["Configuration update must be a JSON object"]}
        unknown = sorted(set(updates) - ConfigSchema.USER_KEYS)
        if unknown:
            return {
                "success": False,
                "errors": [f"Unknown configuration field(s): {', '.join(unknown)}"],
            }
        try:
            current = self.load_config()
            current.update(updates)
            validated = self.save_config(current)
            return {"success": True, "config": validated}
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "errors": [str(exc)]}

    def get_config_summary(self) -> dict[str, Any]:
        config = self.load_config()
        return {
            "playlist": {
                "name": config["playlist_name"],
                "visibility": config["playlist_visibility"],
            },
            "filters": {
                key: config[key]
                for key in (
                    "min_duration_seconds",
                    "max_duration_seconds",
                    "date_filter_mode",
                    "lookback_hours",
                    "date_filter_days",
                    "date_filter_start",
                    "date_filter_end",
                    "max_videos",
                    "skip_live_content",
                    "keyword_filter_mode",
                )
            },
            "channel_filter": {
                "mode": config["channel_filter_mode"],
                "allowlist": config["channel_allowlist"],
                "blocklist": config["channel_blocklist"],
            },
            "sleep_ranking": {
                "ollama_base_url": config["ollama_base_url"],
                "ollama_model": config["ollama_model"],
                "minimum_score": config["sleep_minimum_score"],
                "queue_size": config["sleep_queue_size"],
            },
        }
