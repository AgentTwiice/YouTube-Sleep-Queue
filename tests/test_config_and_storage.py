import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from dashboard.backend.config_manager import ConfigManager
from yt_sub_playlist.config.env_loader import VideoCache, load_config
from yt_sub_playlist.config.schema import ConfigSchema
from yt_sub_playlist.core.video_filtering import VideoFilter

CHANNEL_ID = "UC" + "a" * 22


class ConfigAndStorageTests(unittest.TestCase):
    def test_all_dashboard_filter_fields_reach_runtime_filter(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            saved = manager.save_config(
                {
                    **ConfigSchema.DEFAULTS,
                    "min_duration_seconds": 10,
                    "max_duration_seconds": 100,
                    "date_filter_mode": "date_range",
                    "date_filter_start": "2026-07-01",
                    "date_filter_end": "2026-07-31",
                    "keyword_filter_mode": "include",
                    "keyword_include": ["calm"],
                    "keyword_match_type": "all",
                    "keyword_case_sensitive": False,
                    "keyword_search_description": True,
                    "channel_filter_mode": "allowlist",
                    "channel_allowlist": [CHANNEL_ID],
                }
            )
            runtime = load_config(path)
            self.assertEqual({key: runtime[key] for key in saved}, saved)
            self.assertIsNone(runtime["playlist_id"])
            cache = MagicMock()
            cache.is_processed.return_value = False
            video_filter = VideoFilter(runtime, cache)
            good = {
                "video_id": "abcdefghijk",
                "title": "Night audio",
                "description": "Very calm sounds",
                "channel_id": CHANNEL_ID,
                "channel_title": "Sleep",
                "duration_seconds": 90,
                "published_at": "2026-07-14T00:00:00Z",
                "live_broadcast": "none",
            }
            too_long = dict(good, video_id="bbbbbbbbbbb", duration_seconds=101)
            wrong_channel = dict(good, video_id="ccccccccccc", channel_id="UC" + "b" * 22)
            no_keyword = dict(good, video_id="ddddddddddd", description="loud sports")
            self.assertEqual(
                video_filter.filter_videos([good, too_long, wrong_channel, no_keyword]), [good]
            )

    def test_unknown_fields_and_bool_in_integer_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown configuration"):
            ConfigSchema.validate_config({"surprise": True})
        with self.assertRaisesRegex(ValueError, "max_videos"):
            ConfigSchema.validate_config({"max_videos": True})
        with self.assertRaisesRegex(ValueError, "channel_allowlist"):
            ConfigSchema.validate_config(
                {"channel_filter_mode": "allowlist", "channel_allowlist": [{"id": CHANNEL_ID}]}
            )

    def test_strict_environment_boolean_parsing(self):
        with self.assertRaisesRegex(ValueError, "SKIP_LIVE_CONTENT"):
            ConfigSchema.parse_environment({"SKIP_LIVE_CONTENT": "truthy"})

    def test_corrupt_config_is_preserved_with_actionable_error(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "config.json"
            path.write_text("[]", encoding="utf-8")
            manager = ConfigManager(path)
            with self.assertRaisesRegex(ValueError, "preserved"):
                manager.load_config()
            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(directory).glob("config.json.corrupt.*"))), 1)

    def test_corrupt_cache_is_preserved_and_not_silently_reset(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "processed_videos.json"
            path.write_text(json.dumps([{"video_id": "abc"}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "preserved"):
                VideoCache(cache_file=path)
            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(directory).glob("processed_videos.json.corrupt.*"))), 1)


if __name__ == "__main__":
    unittest.main()
