"""Typed, quota-aware YouTube Data API client."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from googleapiclient.errors import HttpError

from ..auth.oauth import YouTubeAuthenticationError, get_authenticated_service
from ..config.quota_costs import get_quota_cost
from .atomic_io import atomic_write_json, preserve_corrupt_file
from .quota_log import read_quota_log, write_quota_log

logger = logging.getLogger(__name__)
_api_events: list[dict[str, Any]] = []
_persisted_event_counts: dict[Path, int] = {}


class YouTubeClientError(RuntimeError):
    """Base error for a YouTube API operation."""


class YouTubeQuotaError(YouTubeClientError):
    """The daily or per-user quota is exhausted."""


class YouTubeTransientError(YouTubeClientError):
    """A retryable server or network failure occurred."""


class YouTubeDiscoveryError(YouTubeClientError):
    """Discovery could not produce a trustworthy result."""


class ExistingPlaylistLookupError(YouTubeClientError):
    """Existing membership could not be determined safely."""


class PlaylistOperationError(YouTubeClientError):
    """Playlist creation or validation failed."""


class PlaylistAddOutcome(StrEnum):
    ADDED = "added"
    ALREADY_PRESENT = "already_present"
    FAILED = "failed"


@dataclass(frozen=True)
class DiscoveryIssue:
    channel_id: str | None
    channel_title: str
    category: str
    message: str


@dataclass
class DiscoveryResult:
    videos: list[dict[str, Any]] = field(default_factory=list)
    errors: list[DiscoveryIssue] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return bool(self.errors)


def track_api_call(method_name: str, result: str = "success") -> None:
    """Record every attempted quota-consuming request, including failures."""
    _api_events.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method_name,
            "quota_cost": get_quota_cost(method_name),
            "result": result,
        }
    )


def dump_api_call_log(path: Path) -> None:
    """Append this process's new events to the shared versioned daily log."""
    resolved = path.resolve()
    offset = min(_persisted_event_counts.get(resolved, 0), len(_api_events))
    new_events = _api_events[offset:]
    if not new_events:
        return
    existing = read_quota_log(path)
    today = datetime.now(timezone.utc).date().isoformat()
    current_events = [
        event
        for event in existing["events"]
        if event.get("timestamp") is None or str(event["timestamp"]).startswith(today)
    ]
    generated_at = datetime.now(timezone.utc).isoformat()
    write_quota_log(path, current_events + new_events, generated_at)
    _persisted_event_counts[resolved] = len(_api_events)


def parse_duration_to_seconds(duration: str) -> int:
    if not isinstance(duration, str) or not duration.startswith("PT"):
        return 0
    values = {
        unit: int(match.group(1)) if (match := re.search(rf"(\d+){unit}", duration)) else 0
        for unit in ("H", "M", "S")
    }
    return values["H"] * 3600 + values["M"] * 60 + values["S"]


def _published_at(item: dict[str, Any]) -> datetime | None:
    value = item.get("snippet", {}).get("publishedAt")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class YouTubeClient:
    """Small high-level client with normalized results and explicit failures."""

    def __init__(self, data_dir: str | Path = "data", service: Any | None = None):
        self.service = service if service is not None else get_authenticated_service()
        self.quota_exceeded = False
        self.data_dir = Path(data_dir)
        self.playlist_cache_dir = self.data_dir / "playlist_cache"
        self.playlist_cache_dir.mkdir(parents=True, exist_ok=True)

    def _execute(self, request: Any, method: str) -> dict[str, Any]:
        try:
            response = request.execute()
            if not isinstance(response, dict):
                raise YouTubeClientError(f"{method} returned a non-object response")
            track_api_call(method, "success")
            return response
        except HttpError as exc:
            error = self._classify_http_error(method, exc)
            track_api_call(method, error.__class__.__name__)
            raise error from exc
        except YouTubeClientError:
            track_api_call(method, "invalid_response")
            raise
        except Exception as exc:
            track_api_call(method, "transient_failure")
            raise YouTubeTransientError(f"{method} failed: {exc}") from exc

    def _classify_http_error(
        self, method: str, exc: HttpError
    ) -> YouTubeClientError | YouTubeAuthenticationError:
        status = int(getattr(exc.resp, "status", 0) or 0)
        text = str(exc)
        lowered = text.lower()
        if status in {403, 429} and any(
            reason in lowered for reason in ("quota", "ratelimit", "dailylimit")
        ):
            self.quota_exceeded = True
            return YouTubeQuotaError(f"YouTube quota exhausted during {method}")
        if status in {401} or (
            status == 403
            and any(
                reason in lowered
                for reason in ("autherror", "insufficientpermissions", "forbidden")
            )
        ):
            return YouTubeAuthenticationError(f"YouTube authorization failed during {method}")
        if status in {408, 429, 500, 502, 503, 504}:
            return YouTubeTransientError(
                f"Temporary YouTube failure during {method} (HTTP {status})"
            )
        return YouTubeClientError(f"YouTube request {method} failed (HTTP {status or 'unknown'})")

    def get_channels(self) -> list[dict[str, str]]:
        """Return normalized subscribed channel records for public consumers."""
        normalized: list[dict[str, str]] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            response = self._execute(
                self.service.subscriptions().list(
                    part="snippet", mine=True, maxResults=50, pageToken=token
                ),
                "subscriptions.list",
            )
            items = response.get("items", [])
            if not isinstance(items, list):
                raise YouTubeDiscoveryError("subscriptions.list returned invalid items")
            for item in items:
                try:
                    snippet = item["snippet"]
                    channel_id = snippet["resourceId"]["channelId"]
                    title = snippet["title"]
                except (KeyError, TypeError) as exc:
                    raise YouTubeDiscoveryError("A subscription was missing channel data") from exc
                if channel_id not in seen:
                    normalized.append({"channel_id": str(channel_id), "title": str(title)})
                    seen.add(channel_id)
            token = response.get("nextPageToken")
            if not token:
                break
            if len(normalized) >= 2_000:
                raise YouTubeDiscoveryError("Subscription pagination exceeded the safety limit")
        return normalized

    def search_channels(self, query: str) -> list[dict[str, str]]:
        needle = query.strip().casefold()
        channels = self.get_channels()
        if not needle:
            return channels
        return [
            channel
            for channel in channels
            if needle in channel["title"].casefold() or needle in channel["channel_id"].casefold()
        ]

    def get_recent_uploads_from_subscriptions(
        self,
        published_after: str,
        max_per_channel: int = 5,
        max_total: int | None = None,
    ) -> DiscoveryResult:
        channels = self.get_channels()
        if not channels:
            return DiscoveryResult()
        uploads, issues = self._get_upload_playlists(channels)
        item_records: list[tuple[dict[str, str], dict[str, Any]]] = []
        for channel in channels:
            if self.quota_exceeded:
                raise YouTubeQuotaError("YouTube quota exhausted during discovery")
            playlist_id = uploads.get(channel["channel_id"])
            if not playlist_id:
                continue
            try:
                response = self._execute(
                    self.service.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=playlist_id,
                        maxResults=min(max_per_channel, 50),
                    ),
                    "playlistItems.list",
                )
                items = response.get("items", [])
                if not isinstance(items, list):
                    raise YouTubeClientError("playlistItems.list returned invalid items")
                item_records.extend((channel, item) for item in items)
            except YouTubeQuotaError:
                raise
            except YouTubeAuthenticationError:
                raise
            except YouTubeClientError as exc:
                issues.append(self._issue(channel, exc))

        boundary = datetime.fromisoformat(published_after.replace("Z", "+00:00"))
        item_records = [
            record
            for record in item_records
            if (published := _published_at(record[1])) is not None and published > boundary
        ]
        item_records.sort(key=lambda record: _published_at(record[1]) or boundary, reverse=True)
        if max_total is not None:
            item_records = item_records[:max_total]

        video_ids: list[str] = []
        for _, item in item_records:
            video_id = item.get("contentDetails", {}).get("videoId")
            if isinstance(video_id, str):
                video_ids.append(video_id)
        try:
            details = self._get_videos_details(video_ids)
        except YouTubeQuotaError:
            raise
        except YouTubeAuthenticationError:
            raise
        except YouTubeClientError as exc:
            if not issues:
                raise YouTubeDiscoveryError(str(exc)) from exc
            issues.append(DiscoveryIssue(None, "video details", exc.__class__.__name__, str(exc)))
            details = {}

        videos: list[dict[str, Any]] = []
        for channel, item in item_records:
            try:
                snippet = item["snippet"]
                video_id = item["contentDetails"]["videoId"]
                published_at = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                detail = details[video_id]
            except (KeyError, TypeError, ValueError):
                continue
            if published_at <= boundary:
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "title": str(snippet.get("title", "")),
                    "channel_id": channel["channel_id"],
                    "channel_title": channel["title"],
                    "published_at": snippet["publishedAt"],
                    "duration_seconds": parse_duration_to_seconds(detail["duration"]),
                    "live_broadcast": detail["liveBroadcastContent"],
                    "description": detail.get("description", ""),
                }
            )
        if not videos and issues and len(issues) >= len(channels):
            raise YouTubeDiscoveryError("Discovery failed for every subscribed channel")
        return DiscoveryResult(videos, issues)

    def _get_upload_playlists(
        self, channels: list[dict[str, str]]
    ) -> tuple[dict[str, str], list[DiscoveryIssue]]:
        uploads: dict[str, str] = {}
        issues: list[DiscoveryIssue] = []
        by_id = {channel["channel_id"]: channel for channel in channels}
        ids = list(by_id)
        for offset in range(0, len(ids), 50):
            batch = ids[offset : offset + 50]
            try:
                response = self._execute(
                    self.service.channels().list(part="contentDetails", id=",".join(batch)),
                    "channels.list",
                )
            except (YouTubeQuotaError, YouTubeAuthenticationError):
                raise
            except YouTubeClientError as exc:
                issues.extend(self._issue(by_id[channel_id], exc) for channel_id in batch)
                continue
            returned: set[str] = set()
            for item in response.get("items", []):
                try:
                    channel_id = item["id"]
                    playlist_id = item["contentDetails"]["relatedPlaylists"]["uploads"]
                except (KeyError, TypeError):
                    continue
                uploads[channel_id] = playlist_id
                returned.add(channel_id)
            for channel_id in set(batch) - returned:
                issues.append(
                    DiscoveryIssue(
                        channel_id,
                        by_id[channel_id]["title"],
                        "missing_channel",
                        "No uploads playlist was returned",
                    )
                )
        return uploads, issues

    @staticmethod
    def _issue(channel: dict[str, str], error: Exception) -> DiscoveryIssue:
        return DiscoveryIssue(
            channel["channel_id"], channel["title"], error.__class__.__name__, str(error)[:500]
        )

    def _get_videos_details(self, video_ids: Iterable[str]) -> dict[str, dict[str, str]]:
        unique = list(dict.fromkeys(video_ids))
        details: dict[str, dict[str, str]] = {}
        for offset in range(0, len(unique), 50):
            if self.quota_exceeded:
                raise YouTubeQuotaError("YouTube quota exhausted while fetching video details")
            batch = unique[offset : offset + 50]
            if not batch:
                continue
            response = self._execute(
                self.service.videos().list(part="contentDetails,snippet", id=",".join(batch)),
                "videos.list",
            )
            for item in response.get("items", []):
                try:
                    details[item["id"]] = {
                        "duration": item["contentDetails"]["duration"],
                        "liveBroadcastContent": item["snippet"].get("liveBroadcastContent", "none"),
                        "description": item["snippet"].get("description", ""),
                    }
                except (KeyError, TypeError):
                    continue
        return details

    def _get_videos_details_batch(self, video_ids: list[str]) -> dict[str, dict[str, str]]:
        """Compatibility wrapper for callers that already provide one valid batch."""
        if not 1 <= len(video_ids) <= 50:
            raise ValueError("video_ids batch must contain between 1 and 50 IDs")
        response = self._execute(
            self.service.videos().list(part="contentDetails,snippet", id=",".join(video_ids)),
            "videos.list",
        )
        details: dict[str, dict[str, str]] = {}
        for item in response.get("items", []):
            try:
                details[item["id"]] = {
                    "duration": item["contentDetails"]["duration"],
                    "liveBroadcastContent": item["snippet"].get("liveBroadcastContent", "none"),
                    "description": item["snippet"].get("description", ""),
                }
            except (KeyError, TypeError):
                continue
        return details

    def fetch_existing_playlist_items(self, playlist_id: str) -> set[str]:
        cache_file = self.playlist_cache_dir / f"existing_playlist_items_{playlist_id}.json"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 12 * 3600:
            try:
                import json

                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if not isinstance(cached, dict) or not isinstance(cached.get("video_ids"), list):
                    raise ValueError("invalid playlist cache shape")
                if not all(isinstance(value, str) for value in cached["video_ids"]):
                    raise ValueError("playlist cache IDs must be strings")
                return set(cached["video_ids"])
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                backup = preserve_corrupt_file(cache_file)
                raise ExistingPlaylistLookupError(
                    f"Existing-item cache is corrupt; preserved it as {backup}"
                ) from exc
        video_ids: set[str] = set()
        token: str | None = None
        try:
            for _ in range(100):
                response = self._execute(
                    self.service.playlistItems().list(
                        part="contentDetails",
                        playlistId=playlist_id,
                        maxResults=50,
                        pageToken=token,
                    ),
                    "playlistItems.list",
                )
                for item in response.get("items", []):
                    video_id = item.get("contentDetails", {}).get("videoId")
                    if isinstance(video_id, str):
                        video_ids.add(video_id)
                token = response.get("nextPageToken")
                if not token:
                    break
            else:
                raise ExistingPlaylistLookupError("Playlist pagination exceeded 5,000 items")
        except (YouTubeClientError, YouTubeAuthenticationError) as exc:
            raise ExistingPlaylistLookupError(
                "Could not safely determine existing playlist items"
            ) from exc
        atomic_write_json(
            cache_file,
            {
                "playlist_id": playlist_id,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "video_ids": sorted(video_ids),
            },
            mode=0o600,
        )
        return video_ids

    def get_or_create_playlist(
        self, playlist_id: str | None, playlist_name: str, privacy_status: str = "unlisted"
    ) -> str:
        if playlist_id:
            response = self._execute(
                self.service.playlists().list(part="snippet", id=playlist_id), "playlists.list"
            )
            if not response.get("items"):
                raise PlaylistOperationError(
                    f"Playlist {playlist_id} was not found or is inaccessible"
                )
            return playlist_id
        response = self._execute(
            self.service.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": playlist_name,
                        "description": "Automatically curated playlist created by YouTube Sleep Queue",
                    },
                    "status": {"privacyStatus": privacy_status},
                },
            ),
            "playlists.insert",
        )
        new_id = response.get("id")
        if not isinstance(new_id, str) or not new_id:
            raise PlaylistOperationError("Playlist creation returned no ID")
        return new_id

    def add_video_to_playlist(self, playlist_id: str, video_id: str) -> PlaylistAddOutcome:
        try:
            self._execute(
                self.service.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                ),
                "playlistItems.insert",
            )
            return PlaylistAddOutcome.ADDED
        except YouTubeQuotaError:
            raise
        except YouTubeAuthenticationError:
            raise
        except YouTubeClientError:
            return PlaylistAddOutcome.FAILED

    def add_videos_to_playlist(
        self, playlist_id: str, video_ids: list[str]
    ) -> dict[str, PlaylistAddOutcome]:
        if not video_ids:
            return {}
        existing = self.fetch_existing_playlist_items(playlist_id)
        outcomes: dict[str, PlaylistAddOutcome] = {
            video_id: PlaylistAddOutcome.ALREADY_PRESENT
            for video_id in video_ids
            if video_id in existing
        }
        for video_id in video_ids:
            if video_id in outcomes:
                continue
            if self.quota_exceeded:
                outcomes[video_id] = PlaylistAddOutcome.FAILED
                continue
            outcomes[video_id] = self.add_video_to_playlist(playlist_id, video_id)
        return outcomes
