import unittest
from unittest.mock import MagicMock

from yt_sub_playlist.core.playlist_manager import PlaylistManager


class SleepPlaylistManagerTests(unittest.TestCase):
    def _make_manager(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        manager.client = MagicMock()
        manager.filter = MagicMock()
        manager.store = MagicMock()
        manager.ranker = MagicMock()
        manager.config = {
            "max_videos": 2,
            "sleep_minimum_score": 70,
            "sleep_queue_size": 1,
        }
        manager.add_videos_to_playlist = MagicMock()
        manager.store.start_run.return_value = 42
        return manager

    def test_empty_discovery_completes_run(self):
        manager = self._make_manager()
        manager.client.get_recent_uploads_from_subscriptions.return_value = []

        result = manager.sync_subscription_videos_to_playlist(
            "PL1", "2026-01-01", dry_run=True
        )

        self.assertEqual(result, [])
        manager.store.complete_run.assert_called_once_with(42, 0, 0)
        manager.ranker.rank_all.assert_not_called()

    def test_ranks_recent_candidates_and_applies_threshold_and_queue_size(self):
        manager = self._make_manager()
        videos = [
            {"video_id": "old", "title": "Old", "published_at": "2026-01-01"},
            {"video_id": "new", "title": "New", "published_at": "2026-01-03"},
            {"video_id": "mid", "title": "Mid", "published_at": "2026-01-02"},
        ]
        manager.client.get_recent_uploads_from_subscriptions.return_value = videos
        manager.filter.filter_videos.return_value = videos
        ranked = [
            dict(
                videos[1],
                sleep_score=90,
                sleep_rationale="calm",
                sleep_signals=["calm"],
            ),
            dict(
                videos[2],
                sleep_score=80,
                sleep_rationale="steady",
                sleep_signals=["steady"],
            ),
        ]
        manager.ranker.rank_all.return_value = ranked
        manager.add_videos_to_playlist.return_value = [dict(ranked[0], added=True)]

        result = manager.sync_subscription_videos_to_playlist(
            "PL1", "2026-01-01", dry_run=True
        )

        manager.ranker.rank_all.assert_called_once_with([videos[1], videos[2]])
        manager.store.save_candidates.assert_called_once_with(42, [videos[1], videos[2]])
        manager.store.complete_run.assert_called_once_with(42, 2, 1)
        manager.add_videos_to_playlist.assert_called_once_with(
            playlist_id="PL1", videos=[ranked[0]], dry_run=True
        )
        manager.store.mark_added.assert_not_called()
        self.assertEqual(result, [dict(ranked[0], added=True)])


if __name__ == "__main__":
    unittest.main()
