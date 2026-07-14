import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dashboard.backend.app import create_app
from dashboard.backend.refresh_jobs import RefreshAlreadyRunning, RefreshJobManager
from yt_sub_playlist.auth.oauth import YouTubeAuthenticationError


class PassiveJobs:
    def is_active(self):
        return False

    def latest(self):
        return None

    def get(self, _job_id):
        return None

    def start(self, _dry_run):
        return {"id": "b" * 32, "status": "queued"}


class DashboardChannelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.data_dir = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def app_for(self, client_factory):
        return create_app(
            data_dir=self.data_dir,
            youtube_client_factory=client_factory,
            refresh_manager=PassiveJobs(),
            testing=True,
        )

    def test_channel_list_and_search_return_normalized_records(self):
        class Client:
            def get_channels(self):
                return [
                    {"channel_id": "UC" + "b" * 22, "title": "Zed"},
                    {"channel_id": "UC" + "a" * 22, "title": "Alpha"},
                ]

            def search_channels(self, query):
                return [
                    channel
                    for channel in self.get_channels()
                    if query.casefold() in channel["title"].casefold()
                ]

        client = self.app_for(Client).test_client()
        payload = client.get("/api/channels").get_json()
        self.assertEqual([item["title"] for item in payload["channels"]], ["Alpha", "Zed"])
        search = client.get("/api/channels/search?q=zed").get_json()
        self.assertEqual(search["channels"], [{"channel_id": "UC" + "b" * 22, "title": "Zed"}])

    def test_authentication_error_becomes_service_unavailable(self):
        class Client:
            def get_channels(self):
                raise YouTubeAuthenticationError("token secret details")

        response = self.app_for(Client).test_client().get("/api/channels")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret details", response.get_data(as_text=True))

    def test_config_endpoint_rejects_unknown_fields_and_invalid_channel_ids(self):
        app = self.app_for(lambda: None)
        client = app.test_client()
        token = client.get("/api/csrf-token").get_json()["csrf_token"]
        headers = {"Origin": "http://localhost", "X-CSRF-Token": token}
        unknown = client.put("/api/config", json={"unknown": 1}, headers=headers)
        self.assertEqual(unknown.status_code, 400)
        invalid = client.put(
            "/api/channels/filter-config",
            json={"filter_mode": "allowlist", "allowlist": ["not-a-channel"], "blocklist": []},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 400)


class RefreshJobTests(unittest.TestCase):
    def make_manager(self, directory, runner, timeout=30):
        root = Path(directory)
        return RefreshJobManager(
            root / "jobs.json",
            root / "reports",
            root,
            runner=runner,
            python_executable="python",
            default_timeout=timeout,
        )

    def wait_final(self, manager, job_id):
        for _ in range(100):
            job = manager.get(job_id)
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.01)
        self.fail("refresh job did not finish")

    def test_single_flight_rejects_concurrent_refresh_and_reports_completion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            started = threading.Event()
            release = threading.Event()

            def runner(*_args, **_kwargs):
                started.set()
                release.wait(2)
                return subprocess.CompletedProcess([], 0, "full output", "")

            manager = self.make_manager(directory, runner)
            first = manager.start(False)
            self.assertTrue(started.wait(1))
            with self.assertRaises(RefreshAlreadyRunning):
                manager.start(True)
            release.set()
            final = self.wait_final(manager, first["id"])
            self.assertEqual(final["status"], "completed")
            self.assertNotIn("full output", json.dumps(final))

    def test_timeout_is_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:

            def runner(*_args, **kwargs):
                raise subprocess.TimeoutExpired("command", kwargs["timeout"], output="output")

            manager = self.make_manager(directory, runner)
            job = manager.start(False)
            final = self.wait_final(manager, job["id"])
            self.assertEqual(final["status"], "timed_out")
            self.assertIn("timeout", final["error"])

    def test_restart_reconciles_abandoned_active_job(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "jobs.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "jobs": {
                            "c" * 32: {
                                "id": "c" * 32,
                                "status": "running",
                                "created_at": "2026-01-01T00:00:00+00:00",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = self.make_manager(directory, lambda *_args, **_kwargs: None)
            self.assertEqual(manager.get("c" * 32)["status"], "abandoned")


if __name__ == "__main__":
    unittest.main()
