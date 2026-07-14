import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_sub_playlist.config.schema import ConfigSchema
from yt_sub_playlist.core.atomic_io import atomic_write_json, atomic_write_text
from yt_sub_playlist.core.playlist_manager import PlaylistManager
from yt_sub_playlist.core.runtime_state import RuntimeState
from yt_sub_playlist.core.youtube_client import (
    DiscoveryIssue,
    DiscoveryResult,
    ExistingPlaylistLookupError,
    PlaylistAddOutcome,
    YouTubeClient,
    YouTubeDiscoveryError,
)


class CriticalRegressionTests(unittest.TestCase):
    def test_generated_playlist_id_is_reused_and_explicit_id_wins(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manager = PlaylistManager.__new__(PlaylistManager)
            manager.data_dir = directory
            manager.runtime_state = RuntimeState(Path(directory) / "runtime_state.json")
            manager.client = MagicMock()
            manager.client.get_or_create_playlist.side_effect = (
                lambda **kwargs: kwargs["playlist_id"] or "PLgenerated"
            )

            first = manager.get_or_create_playlist(None, "Sleep", "unlisted")
            second = manager.get_or_create_playlist(None, "Sleep", "unlisted")
            explicit = manager.get_or_create_playlist("PLexplicit", "Sleep", "unlisted")

            self.assertEqual(
                (first, second, explicit), ("PLgenerated", "PLgenerated", "PLexplicit")
            )
            calls = manager.client.get_or_create_playlist.call_args_list
            self.assertIsNone(calls[0].kwargs["playlist_id"])
            self.assertEqual(calls[1].kwargs["playlist_id"], "PLgenerated")
            self.assertEqual(calls[2].kwargs["playlist_id"], "PLexplicit")
            self.assertEqual(
                json.loads((Path(directory) / "runtime_state.json").read_text())["playlist_id"],
                "PLgenerated",
            )

    def test_partial_discovery_records_explicit_partial_state(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        manager.config = ConfigSchema.validate_config({})
        manager.client = MagicMock()
        manager.filter = MagicMock()
        manager.store = MagicMock()
        manager.store.start_run.return_value = 9
        manager.client.get_recent_uploads_from_subscriptions.return_value = DiscoveryResult(
            [], [DiscoveryIssue("UC" + "a" * 22, "Channel", "transient", "temporary failure")]
        )

        result = manager.sync_subscription_videos_to_playlist(None, "2026-01-01", dry_run=True)

        self.assertEqual(result, [])
        manager.store.complete_run.assert_called_once_with(
            9,
            0,
            0,
            warning_count=1,
            status="completed_with_errors",
            warning_message="temporary failure",
        )

    def test_fatal_discovery_error_marks_run_failed(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        manager.config = ConfigSchema.validate_config({})
        manager.client = MagicMock()
        manager.store = MagicMock()
        manager.store.start_run.return_value = 12
        manager.client.get_recent_uploads_from_subscriptions.side_effect = YouTubeDiscoveryError(
            "subscriptions unavailable"
        )
        with self.assertRaises(YouTubeDiscoveryError):
            manager.sync_subscription_videos_to_playlist(None, "2026-01-01")
        manager.store.fail_run.assert_called_once()

    def test_existing_video_is_not_counted_as_new_addition(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        manager.client = MagicMock()
        manager.cache = MagicMock()
        manager.client.add_videos_to_playlist.return_value = {
            "abcdefghijk": PlaylistAddOutcome.ALREADY_PRESENT
        }
        result = manager.add_videos_to_playlist(
            "PL1",
            [{"video_id": "abcdefghijk", "title": "Rain", "channel_title": "Calm"}],
        )
        self.assertFalse(result[0]["added"])
        self.assertEqual(result[0]["playlist_status"], "already_present")
        manager.cache.mark_processed_many.assert_called_once()

    def test_existing_item_lookup_failure_aborts_insertion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            client = YouTubeClient.__new__(YouTubeClient)
            client.service = MagicMock()
            client.service.playlistItems.return_value.list.return_value.execute.side_effect = (
                RuntimeError("network down")
            )
            client.quota_exceeded = False
            client.data_dir = Path(directory)
            client.playlist_cache_dir = Path(directory)
            with self.assertRaises(ExistingPlaylistLookupError):
                client.add_videos_to_playlist("PL1", ["abcdefghijk"])
            client.service.playlistItems.return_value.insert.assert_not_called()

    def test_date_modes_change_discovery_boundary(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        lookback = ConfigSchema.validate_config({"lookback_hours": 6})
        days = ConfigSchema.validate_config({"date_filter_mode": "days", "date_filter_days": 2})
        range_config = ConfigSchema.validate_config(
            {
                "date_filter_mode": "date_range",
                "date_filter_start": "2026-06-01",
                "date_filter_end": "2026-06-30",
            }
        )
        self.assertEqual(ConfigSchema.discovery_start(lookback, now), "2026-07-14T06:00:00Z")
        self.assertEqual(ConfigSchema.discovery_start(days, now), "2026-07-12T00:00:00Z")
        self.assertEqual(ConfigSchema.discovery_start(range_config, now), "2026-06-01T00:00:00Z")

    def test_atomic_write_replaces_content_and_cleans_temp_after_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            destination = Path(directory) / "state.json"
            atomic_write_json(destination, {"value": 1})
            self.assertEqual(json.loads(destination.read_text()), {"value": 1})
            with patch(
                "yt_sub_playlist.core.atomic_io.os.replace", side_effect=OSError("disk error")
            ):
                with self.assertRaises(OSError):
                    atomic_write_text(destination, "replacement")
            self.assertEqual(json.loads(destination.read_text()), {"value": 1})
            self.assertEqual(list(Path(directory).glob(".state.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
