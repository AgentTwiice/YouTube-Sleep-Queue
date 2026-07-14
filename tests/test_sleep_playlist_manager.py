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
        manager.ranker.client.model = "model"
        manager.ranker.cache_fingerprint = "fingerprint"
        manager.config = {
            "max_videos": 2,
            "sleep_minimum_score": 70,
            "sleep_queue_size": 1,
        }
        manager.add_videos_to_playlist = MagicMock()
        manager.store.start_run.return_value = 42
        manager.store.get_cached_scores.return_value = {}
        return manager

    def test_empty_discovery_completes_run(self):
        manager = self._make_manager()
        manager.client.get_recent_uploads_from_subscriptions.return_value = []

        result = manager.sync_subscription_videos_to_playlist("PL1", "2026-01-01", dry_run=True)

        self.assertEqual(result, [])
        manager.store.complete_run.assert_called_once_with(
            42,
            0,
            0,
            warning_count=0,
            status="completed",
            warning_message=None,
        )
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
        manager.ranker.select.return_value = [ranked[0]]
        manager.add_videos_to_playlist.return_value = [dict(ranked[0], added=True)]
        manager.client.get_or_create_playlist.return_value = "PL1"

        result = manager.sync_subscription_videos_to_playlist("PL1", "2026-01-01", dry_run=True)

        self.assertEqual(manager.ranker.rank_all.call_args.args, ([videos[1], videos[2]], {}))
        self.assertIn("on_ranked", manager.ranker.rank_all.call_args.kwargs)
        manager.ranker.select.assert_called_once_with(ranked)
        manager.store.save_candidates.assert_called_once_with(42, [videos[1], videos[2]])
        manager.store.complete_run.assert_called_once_with(42, 2, 1, 0, 0, 0, 0, "completed", None)
        self.assertEqual(
            [call.args for call in manager.store.set_run_status.call_args_list],
            [(42, "ranking"), (42, "adding")],
        )
        manager.add_videos_to_playlist.assert_called_once_with(
            playlist_id="PL1", videos=[ranked[0]], dry_run=True
        )
        manager.store.mark_added.assert_not_called()
        self.assertEqual(result, [dict(ranked[0], added=True)])

    def test_failure_marks_run_failed(self):
        manager = self._make_manager()
        manager.client.get_recent_uploads_from_subscriptions.side_effect = RuntimeError(
            "youtube unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "youtube unavailable"):
            manager.sync_subscription_videos_to_playlist("PL1", "2026-01-01", dry_run=False)

        manager.store.fail_run.assert_called_once()
        self.assertEqual(manager.store.fail_run.call_args.args[0], 42)


if __name__ == "__main__":
    unittest.main()
