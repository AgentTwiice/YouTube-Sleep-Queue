import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.backend.stats_api import read_quota_log
from scripts.check_repo_secrets import scan_content
from yt_sub_playlist.core import youtube_client
from yt_sub_playlist.core.playlist_manager import PlaylistManager
from yt_sub_playlist.core.sleep_ranker import (
    OllamaError,
    SleepRanker,
    SleepScore,
    ranking_fingerprint,
)
from yt_sub_playlist.core.sleep_store import SleepQueueStore


class SecurityQuotaRankingTests(unittest.TestCase):
    def test_secret_scanner_detects_temporary_case_variant_and_authorized_user_tokens(self):
        self.assertTrue(scan_content(".token.json.tmp", "{}"))
        self.assertTrue(scan_content("TOKEN.JSON", "{}"))
        self.assertTrue(
            scan_content(
                "state.json",
                '{"type":"authorized_user","client_id":"id","client_secret":"secret","refresh_token":"refresh"}',
            )
        )
        token = "github_" + "pat_abcdefghijklmnopqrstuvwxyz123456"
        self.assertTrue(scan_content("notes.txt", token))

    def test_gitignore_covers_temporary_and_case_variant_credentials(self):
        path_values = [".token.json.tmp", "token.json.tmp", "TOKEN.JSON", "client_secret.json.bak"]
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            input="\0".join(path_values) + "\0",
            text=True,
            capture_output=True,
            check=True,
        )
        ignored = {value for value in result.stdout.split("\0") if value}
        self.assertEqual(ignored, set(path_values))

    def test_dashboard_consumes_cli_quota_schema_and_legacy_schema(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "quota.json"
            youtube_client._api_events.clear()
            youtube_client.track_api_call("videos.list", "success")
            youtube_client.track_api_call("playlistItems.insert", "YouTubeQuotaError")
            youtube_client.dump_api_call_log(path)
            log = read_quota_log(path)
            self.assertEqual(len(log["events"]), 2)
            self.assertEqual(sum(event["quota_cost"] for event in log["events"]), 51)
            youtube_client.track_api_call("channels.list", "success")
            youtube_client.dump_api_call_log(path)
            self.assertEqual(len(read_quota_log(path)["events"]), 3)
            path.write_text('{"videos.list": 2}', encoding="utf-8")
            legacy = read_quota_log(path)
            self.assertEqual(len(legacy["events"]), 2)

    def test_ranking_fingerprint_changes_with_model(self):
        self.assertNotEqual(ranking_fingerprint("model-a"), ranking_fingerprint("model-b"))

    def test_successful_rankings_are_reported_incrementally_before_later_failure(self):
        class Client:
            model = "model"

            def __init__(self):
                self.calls = 0

            def score_video(self, _video):
                self.calls += 1
                if self.calls == 2:
                    raise OllamaError("candidate failed")
                return SleepScore(80, "calm", ["steady"])

        ranked = []
        ranker = SleepRanker(Client(), 70, 10)
        videos = [
            {"video_id": "abcdefghijk", "title": "One"},
            {"video_id": "bbbbbbbbbbb", "title": "Two"},
        ]
        with self.assertRaises(OllamaError):
            ranker.rank_all(videos, on_ranked=ranked.append)
        self.assertEqual([item["video_id"] for item in ranked], ["abcdefghijk"])

    def test_requested_report_write_failure_is_not_suppressed(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        with patch(
            "yt_sub_playlist.core.playlist_manager.atomic_write_text",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                manager.write_report([], "report.csv")

    def test_store_reconciles_stale_run(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "queue.sqlite3"
            store = SleepQueueStore(str(path))
            run_id = store.start_run(False)
            reopened = SleepQueueStore(str(path))
            import sqlite3

            connection = sqlite3.connect(path)
            status = connection.execute(
                "SELECT status FROM queue_runs WHERE id=?", (run_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(status, "failed")
            self.assertEqual(reopened.reconcile_abandoned_runs(), 0)


if __name__ == "__main__":
    unittest.main()
