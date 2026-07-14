"""High-level orchestration for sleep queue discovery, ranking, and insertion."""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from ..config.env_loader import VideoCache
from .atomic_io import atomic_write_json, atomic_write_text
from .paths import DEFAULT_DATA_DIR, AppPaths
from .runtime_state import RuntimeState
from .sleep_ranker import OllamaClient, SleepRanker, video_metadata_hash
from .sleep_store import SleepQueueStore
from .video_filtering import VideoFilter
from .youtube_client import DiscoveryResult, PlaylistAddOutcome, YouTubeClient

logger = logging.getLogger(__name__)


def resolve_data_dir(explicit: str | None = None) -> str:
    """Backward-compatible string wrapper around the shared path resolver."""
    if explicit:
        return explicit
    import os

    return os.getenv("YT_SUB_PLAYLIST_DATA_DIR") or DEFAULT_DATA_DIR


class PlaylistManager:
    DRY_RUN_PLAYLIST_ID = "(dry-run)"

    def __init__(
        self,
        config: dict[str, Any],
        data_dir: str | None = None,
        *,
        client: YouTubeClient | None = None,
        cache: VideoCache | None = None,
        store: SleepQueueStore | None = None,
        ranker: SleepRanker | None = None,
    ):
        self.config = config
        self.paths = AppPaths.resolve(data_dir)
        self.data_dir = str(self.paths.data_dir)
        self.client = client or YouTubeClient(self.paths.data_dir)
        self.cache = cache or VideoCache(cache_file=self.paths.cache)
        self.filter = VideoFilter(config, self.cache)
        self.store = store or SleepQueueStore(str(self.paths.database))
        self.runtime_state = RuntimeState(self.paths.runtime_state)
        self.ranker = ranker or SleepRanker(
            OllamaClient(
                config["ollama_base_url"],
                config["ollama_model"],
                config["ollama_timeout_seconds"],
            ),
            config["sleep_minimum_score"],
            config["sleep_queue_size"],
            config.get("ollama_concurrency", 1),
        )

    def sync_subscription_videos_to_playlist(
        self,
        playlist_id: str | None,
        published_after: str,
        channel_whitelist: set[str] | None = None,
        dry_run: bool = False,
        playlist_name: str | None = None,
        privacy_status: str | None = None,
    ) -> list[dict[str, Any]]:
        run_id = self.store.start_run(dry_run)
        try:
            discovered = self.client.get_recent_uploads_from_subscriptions(
                published_after=published_after,
                max_per_channel=5,
                max_total=self.config["max_videos"],
            )
            # Compatibility for injected legacy test doubles; production always returns DiscoveryResult.
            discovery = (
                discovered
                if isinstance(discovered, DiscoveryResult)
                else DiscoveryResult(list(discovered))
            )
            completion = "completed_with_errors" if discovery.partial else "completed"
            warning = "; ".join(issue.message for issue in discovery.errors)[:2000] or None
            warning_count = len(discovery.errors)
            if not discovery.videos:
                self.store.complete_run(
                    run_id,
                    0,
                    0,
                    warning_count=warning_count,
                    status=completion,
                    warning_message=warning,
                )
                return []

            filtered = self.filter.filter_videos(discovery.videos, channel_whitelist)
            filtered = sorted(
                filtered,
                key=lambda video: video.get("published_at") or "",
                reverse=True,
            )[: self.config["max_videos"]]
            if not filtered:
                self.store.complete_run(
                    run_id,
                    0,
                    0,
                    warning_count=warning_count,
                    status=completion,
                    warning_message=warning,
                )
                return []

            self.store.save_candidates(run_id, filtered)
            self.store.set_run_status(run_id, "ranking")
            metadata_hashes = {video["video_id"]: video_metadata_hash(video) for video in filtered}
            model = self.ranker.client.model
            fingerprint = self.ranker.cache_fingerprint
            cached = self.store.get_cached_scores(metadata_hashes, model, fingerprint)
            ranked_all = self.ranker.rank_all(
                filtered,
                cached,
                on_ranked=lambda ranked: self.store.save_ranking(ranked, model, fingerprint),
            )
            selected = self.ranker.select(ranked_all)
            selected_ids = {video["video_id"] for video in selected}
            self.store.save_rankings(ranked_all, model, fingerprint, selected_ids)
            if not selected:
                self.store.complete_run(
                    run_id,
                    len(filtered),
                    0,
                    warning_count=warning_count,
                    status=completion,
                    warning_message=warning,
                )
                return []

            # Playlist creation is deliberately deferred until there is something to insert.
            resolved_playlist_id = self.get_or_create_playlist(
                playlist_id=playlist_id,
                playlist_name=playlist_name
                or self.config.get("playlist_name", "YouTube Sleep Queue"),
                privacy_status=privacy_status or self.config.get("playlist_visibility", "unlisted"),
                dry_run=dry_run,
            )
            self.store.set_run_status(run_id, "adding")
            results = self.add_videos_to_playlist(
                playlist_id=resolved_playlist_id, videos=selected, dry_run=dry_run
            )
            if dry_run:
                added_ids: list[str] = []
                existing_ids: list[str] = []
                failed_ids: list[str] = []
            else:
                added_ids = [
                    v["video_id"]
                    for v in results
                    if v["playlist_status"] == PlaylistAddOutcome.ADDED
                ]
                existing_ids = [
                    v["video_id"]
                    for v in results
                    if v["playlist_status"] == PlaylistAddOutcome.ALREADY_PRESENT
                ]
                failed_ids = [
                    v["video_id"]
                    for v in results
                    if v["playlist_status"] == PlaylistAddOutcome.FAILED
                ]
                self.store.mark_outcomes(added_ids, existing_ids, failed_ids)
            final_status = (
                "completed_with_errors" if discovery.partial or failed_ids else "completed"
            )
            final_warning_count = warning_count + len(failed_ids)
            self.store.complete_run(
                run_id,
                len(filtered),
                len(selected),
                len(added_ids),
                len(failed_ids),
                len(existing_ids),
                final_warning_count,
                final_status,
                warning,
            )
            return results
        except Exception as exc:
            try:
                self.store.fail_run(run_id, exc)
            except Exception:
                logger.exception("Failed to persist the run failure state")
            raise

    def add_videos_to_playlist(
        self,
        playlist_id: str,
        videos: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        if dry_run:
            return [dict(video, added=False, playlist_status="would_add") for video in videos]
        outcomes = self.client.add_videos_to_playlist(
            playlist_id, [video["video_id"] for video in videos]
        )
        processed: list[tuple[str, str, str]] = []
        detailed: list[dict[str, Any]] = []
        for video in videos:
            outcome = outcomes.get(video["video_id"], PlaylistAddOutcome.FAILED)
            if outcome in {PlaylistAddOutcome.ADDED, PlaylistAddOutcome.ALREADY_PRESENT}:
                processed.append(
                    (video["video_id"], video["title"], video.get("channel_title", ""))
                )
            detailed.append(
                dict(
                    video,
                    added=outcome == PlaylistAddOutcome.ADDED,
                    playlist_status=str(outcome),
                )
            )
        self.cache.mark_processed_many(processed)
        return detailed

    def get_or_create_playlist(
        self,
        playlist_id: str | None = None,
        playlist_name: str | None = None,
        privacy_status: str = "unlisted",
        dry_run: bool = False,
    ) -> str:
        """Resolve explicit ID first, then persisted generated ID, then create once."""
        if dry_run and not playlist_id:
            return self.DRY_RUN_PLAYLIST_ID
        state = getattr(
            self,
            "runtime_state",
            RuntimeState(AppPaths.resolve(getattr(self, "data_dir", None)).runtime_state),
        )
        persisted = None if playlist_id else state.playlist_id()
        resolved = self.client.get_or_create_playlist(
            playlist_id=playlist_id or persisted,
            playlist_name=playlist_name or "YouTube Sleep Queue",
            privacy_status=privacy_status,
        )
        if not playlist_id and not persisted:
            state.save_playlist_id(resolved)
        return resolved

    def write_report(self, video_results: list[dict[str, Any]], report_path: str) -> None:
        """Atomically write an explicitly requested CSV report and dashboard snapshot."""
        fields = [
            "title",
            "video_id",
            "channel_title",
            "channel_id",
            "published_at",
            "duration_seconds",
            "live_broadcast",
            "sleep_score",
            "sleep_rationale",
            "playlist_status",
            "added",
        ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for video in video_results:
            writer.writerow({field: _spreadsheet_safe(video.get(field, "")) for field in fields})
        atomic_write_text(report_path, output.getvalue())
        self._write_dashboard_json(video_results)

    def _write_dashboard_json(self, video_results: list[dict[str, Any]]) -> None:
        from datetime import datetime, timezone

        atomic_write_json(
            self.paths.dashboard_playlist,
            {
                "schema_version": 1,
                "source": "generated",
                "stale": False,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "videos": [
                    {
                        key: video.get(key, default)
                        for key, default in {
                            "title": "",
                            "video_id": "",
                            "channel_title": "",
                            "channel_id": "",
                            "published_at": "",
                            "duration_seconds": 0,
                            "live_broadcast": "none",
                            "sleep_score": None,
                            "sleep_rationale": "",
                            "playlist_status": "unknown",
                            "added": False,
                        }.items()
                    }
                    for video in video_results
                ],
            },
            mode=0o600,
        )

    def get_cache_stats(self) -> dict[str, int]:
        return self.cache.get_stats()

    def get_filtering_stats(self) -> dict[str, int]:
        return self.filter.get_filtering_stats()


def _spreadsheet_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value
