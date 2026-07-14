"""Authoritative configuration defaults, parsing, and validation."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


class ConfigSchema:
    """Single contract used by files, environment variables, and the dashboard."""

    DEFAULTS: dict[str, Any] = {
        "playlist_name": "YouTube Sleep Queue",
        "playlist_visibility": "unlisted",
        "min_duration_seconds": 60,
        "max_duration_seconds": None,
        "lookback_hours": 24,
        "date_filter_mode": "lookback",
        "date_filter_days": None,
        "date_filter_start": None,
        "date_filter_end": None,
        "max_videos": 50,
        "skip_live_content": True,
        "channel_filter_mode": "none",
        "channel_allowlist": None,
        "channel_blocklist": None,
        "keyword_filter_mode": "none",
        "keyword_include": None,
        "keyword_exclude": None,
        "keyword_match_type": "any",
        "keyword_case_sensitive": False,
        "keyword_search_description": False,
        "ollama_base_url": "http://localhost:11434",
        "ollama_model": "llama3.2:3b",
        "ollama_timeout_seconds": 30,
        "ollama_concurrency": 1,
        "sleep_minimum_score": 70.0,
        "sleep_queue_size": 10,
        "refresh_timeout_seconds": None,
    }
    LEGACY_KEYS = {"channel_whitelist"}
    RUNTIME_KEYS = {"playlist_id"}
    USER_KEYS = frozenset(DEFAULTS) | LEGACY_KEYS
    ALL_KEYS = USER_KEYS | RUNTIME_KEYS

    ENVIRONMENT: dict[str, tuple[str, str]] = {
        "playlist_id": ("PLAYLIST_ID", "optional_string"),
        "playlist_name": ("PLAYLIST_NAME", "string"),
        "playlist_visibility": ("PLAYLIST_VISIBILITY", "string"),
        "min_duration_seconds": ("VIDEO_MIN_DURATION_SECONDS", "integer"),
        "max_duration_seconds": ("VIDEO_MAX_DURATION_SECONDS", "optional_integer"),
        "lookback_hours": ("LOOKBACK_HOURS", "integer"),
        "date_filter_mode": ("DATE_FILTER_MODE", "string"),
        "date_filter_days": ("DATE_FILTER_DAYS", "optional_integer"),
        "date_filter_start": ("DATE_FILTER_START", "optional_string"),
        "date_filter_end": ("DATE_FILTER_END", "optional_string"),
        "max_videos": ("MAX_VIDEOS_TO_FETCH", "integer"),
        "skip_live_content": ("SKIP_LIVE_CONTENT", "boolean"),
        "channel_filter_mode": ("CHANNEL_FILTER_MODE", "string"),
        "channel_allowlist": ("CHANNEL_ALLOWLIST", "array"),
        "channel_blocklist": ("CHANNEL_BLOCKLIST", "array"),
        "channel_whitelist": ("CHANNEL_ID_WHITELIST", "array"),
        "keyword_filter_mode": ("KEYWORD_FILTER_MODE", "string"),
        "keyword_include": ("KEYWORD_INCLUDE", "array"),
        "keyword_exclude": ("KEYWORD_EXCLUDE", "array"),
        "keyword_match_type": ("KEYWORD_MATCH_TYPE", "string"),
        "keyword_case_sensitive": ("KEYWORD_CASE_SENSITIVE", "boolean"),
        "keyword_search_description": ("KEYWORD_SEARCH_DESCRIPTION", "boolean"),
        "ollama_base_url": ("OLLAMA_BASE_URL", "string"),
        "ollama_model": ("OLLAMA_MODEL", "string"),
        "ollama_timeout_seconds": ("OLLAMA_TIMEOUT_SECONDS", "integer"),
        "ollama_concurrency": ("OLLAMA_CONCURRENCY", "integer"),
        "sleep_minimum_score": ("SLEEP_MINIMUM_SCORE", "number"),
        "sleep_queue_size": ("SLEEP_QUEUE_SIZE", "integer"),
        "refresh_timeout_seconds": ("REFRESH_TIMEOUT_SECONDS", "optional_integer"),
    }

    @classmethod
    def parse_environment(cls, environment: Mapping[str, str]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for field, (name, value_type) in cls.ENVIRONMENT.items():
            if name not in environment:
                continue
            raw = environment[name]
            try:
                parsed[field] = cls._parse_environment_value(raw, value_type)
            except ValueError as exc:
                raise ValueError(f"Invalid environment variable {name}: {exc}") from exc
        return parsed

    @staticmethod
    def _parse_environment_value(raw: str, value_type: str) -> Any:
        stripped = raw.strip()
        if value_type.startswith("optional_") and not stripped:
            return None
        if value_type in {"string", "optional_string"}:
            return stripped
        if value_type in {"integer", "optional_integer"}:
            if not re.fullmatch(r"[+-]?\d+", stripped):
                raise ValueError("must be an integer")
            return int(stripped)
        if value_type == "number":
            try:
                return float(stripped)
            except ValueError as exc:
                raise ValueError("must be a number") from exc
        if value_type == "boolean":
            normalized = stripped.lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise ValueError("must be true/false, yes/no, on/off, or 1/0")
        if value_type == "array":
            return [item.strip() for item in raw.split(",") if item.strip()] or None
        raise AssertionError(f"Unsupported configuration parser: {value_type}")

    @classmethod
    def validate_config(
        cls,
        config: Mapping[str, Any],
        *,
        allow_runtime_keys: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise ValueError("Configuration must be a JSON object")
        allowed = cls.ALL_KEYS if allow_runtime_keys else cls.USER_KEYS
        unknown = sorted(set(config) - allowed)
        if unknown:
            raise ValueError(f"Unknown configuration field(s): {', '.join(unknown)}")

        result = dict(cls.DEFAULTS)
        result.update(config)
        if allow_runtime_keys:
            result.setdefault("playlist_id", None)
        result = cls._migrate_legacy(result)

        cls._string(result, "playlist_name", 1, 150)
        cls._choice(result, "playlist_visibility", {"private", "unlisted", "public"})
        cls._choice(result, "date_filter_mode", {"lookback", "days", "date_range"})
        cls._choice(result, "channel_filter_mode", {"none", "allowlist", "blocklist"})
        cls._choice(result, "keyword_filter_mode", {"none", "include", "exclude", "both"})
        cls._choice(result, "keyword_match_type", {"any", "all"})
        cls._integer(result, "min_duration_seconds", 0, 86_400)
        cls._optional_integer(result, "max_duration_seconds", 1, 86_400)
        cls._integer(result, "lookback_hours", 1, 168)
        cls._optional_integer(result, "date_filter_days", 1, 365)
        cls._integer(result, "max_videos", 1, 200)
        cls._integer(result, "ollama_timeout_seconds", 1, 300)
        cls._integer(result, "ollama_concurrency", 1, 3)
        cls._integer(result, "sleep_queue_size", 1, 200)
        cls._optional_integer(result, "refresh_timeout_seconds", 30, 14_400)
        cls._number(result, "sleep_minimum_score", 0, 100)
        for field in (
            "skip_live_content",
            "keyword_case_sensitive",
            "keyword_search_description",
        ):
            if not isinstance(result[field], bool):
                raise ValueError(f"{field} must be a boolean")

        if result["max_duration_seconds"] is not None and (
            result["max_duration_seconds"] < result["min_duration_seconds"]
        ):
            raise ValueError("max_duration_seconds cannot be less than min_duration_seconds")

        cls._validate_dates(result)
        result["channel_allowlist"] = cls._string_array(
            result.get("channel_allowlist"), "channel_allowlist", 200, 24, CHANNEL_ID_PATTERN
        )
        result["channel_blocklist"] = cls._string_array(
            result.get("channel_blocklist"), "channel_blocklist", 200, 24, CHANNEL_ID_PATTERN
        )
        overlap = set(result["channel_allowlist"] or ()) & set(result["channel_blocklist"] or ())
        if overlap:
            raise ValueError("A channel cannot appear in both allowlist and blocklist")
        if result["channel_filter_mode"] == "allowlist" and not result["channel_allowlist"]:
            raise ValueError("channel_allowlist is required in allowlist mode")
        if result["channel_filter_mode"] == "blocklist" and not result["channel_blocklist"]:
            raise ValueError("channel_blocklist is required in blocklist mode")

        result["keyword_include"] = cls._string_array(
            result.get("keyword_include"), "keyword_include", 50, 100
        )
        result["keyword_exclude"] = cls._string_array(
            result.get("keyword_exclude"), "keyword_exclude", 50, 100
        )
        mode = result["keyword_filter_mode"]
        if mode in {"include", "both"} and not result["keyword_include"]:
            raise ValueError("keyword_include is required in include/both mode")
        if mode in {"exclude", "both"} and not result["keyword_exclude"]:
            raise ValueError("keyword_exclude is required in exclude/both mode")

        cls._url(result, "ollama_base_url")
        cls._string(result, "ollama_model", 1, 200)
        playlist_id = result.get("playlist_id")
        if playlist_id is not None:
            if not isinstance(playlist_id, str) or not 1 <= len(playlist_id.strip()) <= 200:
                raise ValueError("playlist_id must be a non-empty string of at most 200 characters")
            result["playlist_id"] = playlist_id.strip()
        if not allow_runtime_keys:
            result.pop("playlist_id", None)
        result.pop("channel_whitelist", None)
        return result

    @staticmethod
    def _migrate_legacy(config: dict[str, Any]) -> dict[str, Any]:
        legacy = config.get("channel_whitelist")
        if (
            legacy
            and config.get("channel_filter_mode") == "none"
            and not config.get("channel_allowlist")
        ):
            config["channel_filter_mode"] = "allowlist"
            config["channel_allowlist"] = legacy
        return config

    @staticmethod
    def _string(config: dict[str, Any], field: str, minimum: int, maximum: int) -> None:
        value = config[field]
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f"{field} must be a string between {minimum} and {maximum} characters")
        config[field] = value.strip()

    @staticmethod
    def _choice(config: dict[str, Any], field: str, choices: set[str]) -> None:
        if config[field] not in choices:
            raise ValueError(f"{field} must be one of: {', '.join(sorted(choices))}")

    @staticmethod
    def _integer(config: dict[str, Any], field: str, minimum: int, maximum: int) -> None:
        value = config[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")

    @classmethod
    def _optional_integer(
        cls, config: dict[str, Any], field: str, minimum: int, maximum: int
    ) -> None:
        if config[field] is not None:
            cls._integer(config, field, minimum, maximum)

    @staticmethod
    def _number(config: dict[str, Any], field: str, minimum: float, maximum: float) -> None:
        value = config[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not minimum <= value <= maximum
        ):
            raise ValueError(f"{field} must be a number between {minimum} and {maximum}")

    @staticmethod
    def _string_array(
        value: Any,
        field: str,
        maximum_items: int,
        maximum_length: int,
        pattern: re.Pattern[str] | None = None,
    ) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
            raise ValueError(f"{field} must be an array of strings")
        if len(value) > maximum_items:
            raise ValueError(f"{field} cannot contain more than {maximum_items} entries")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > maximum_length:
                raise ValueError(
                    f"Every {field} entry must be a non-empty string up to {maximum_length} characters"
                )
            item = item.strip()
            if pattern is not None and not pattern.fullmatch(item):
                raise ValueError(f"Invalid YouTube channel ID in {field}: {item}")
            if item not in normalized:
                normalized.append(item)
        return normalized or None

    @staticmethod
    def _validate_dates(config: dict[str, Any]) -> None:
        parsed: dict[str, date | None] = {}
        for field in ("date_filter_start", "date_filter_end"):
            value = config[field]
            if value is None:
                parsed[field] = None
                continue
            if not isinstance(value, str):
                raise ValueError(f"{field} must be YYYY-MM-DD or null")
            try:
                parsed[field] = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from exc
        if (
            parsed["date_filter_start"]
            and parsed["date_filter_end"]
            and parsed["date_filter_end"] < parsed["date_filter_start"]
        ):
            raise ValueError("date_filter_end cannot be before date_filter_start")
        mode = config["date_filter_mode"]
        if mode == "days" and config["date_filter_days"] is None:
            raise ValueError("date_filter_days is required in days mode")
        if mode == "date_range" and (
            parsed["date_filter_start"] is None or parsed["date_filter_end"] is None
        ):
            raise ValueError(
                "date_filter_start and date_filter_end are required in date_range mode"
            )

    @staticmethod
    def _url(config: dict[str, Any], field: str) -> None:
        value = config[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty URL")
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"{field} must be an HTTP(S) URL without credentials, query, or fragment"
            )
        config[field] = value.rstrip("/")

    @classmethod
    def discovery_start(cls, config: Mapping[str, Any], now: datetime | None = None) -> str:
        """Return the earliest RFC3339 boundary implied by the selected mode."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        mode = config["date_filter_mode"]
        if mode == "lookback":
            boundary = current - timedelta(hours=config["lookback_hours"])
        elif mode == "days":
            target = current.date() - timedelta(days=config["date_filter_days"])
            boundary = datetime.combine(target, time.min, tzinfo=timezone.utc)
        else:
            boundary = datetime.combine(
                date.fromisoformat(config["date_filter_start"]), time.min, tzinfo=timezone.utc
            )
        return boundary.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def get_config_summary(cls, config: Mapping[str, Any]) -> str:
        return (
            f"Playlist={config['playlist_name']}; date_mode={config['date_filter_mode']}; "
            f"max_videos={config['max_videos']}; model={config['ollama_model']}"
        )
