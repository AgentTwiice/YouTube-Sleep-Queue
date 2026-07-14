import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard.backend.app import create_app
from dashboard.backend.config_manager import ConfigManager


class FakeJobs:
    def __init__(self):
        self.active = False
        self.job = None

    def is_active(self):
        return self.active

    def start(self, dry_run):
        self.active = True
        self.job = {
            "id": "a" * 32,
            "status": "queued",
            "progress": "queued",
            "dry_run": dry_run,
        }
        return self.job

    def latest(self):
        return self.job

    def get(self, job_id):
        return self.job if self.job and self.job["id"] == job_id else None


class DashboardSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        data_dir = Path(self.directory.name)
        self.data_dir = data_dir
        self.jobs = FakeJobs()
        self.app = create_app(data_dir=data_dir, refresh_manager=self.jobs, testing=True)
        self.client = self.app.test_client()
        token_response = self.client.get("/api/csrf-token")
        self.token = token_response.get_json()["csrf_token"]
        self.headers = {
            "Origin": "http://localhost",
            "X-CSRF-Token": self.token,
            "Sec-Fetch-Site": "same-origin",
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_refresh_requires_json_origin_and_csrf_token(self):
        self.assertEqual(self.client.post("/api/refresh").status_code, 415)
        self.assertEqual(self.client.post("/api/refresh", json={"dry_run": True}).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/refresh",
                json={"dry_run": True},
                headers={"Origin": "https://attacker.example", "X-CSRF-Token": self.token},
            ).status_code,
            403,
        )

    def test_same_origin_refresh_returns_accepted_job(self):
        response = self.client.post("/api/refresh", json={"dry_run": True}, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["job_id"], "a" * 32)

    def test_security_headers_and_csrf_no_store(self):
        response = self.client.get("/api/csrf-token")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn(
            "unsafe-inline", response.headers["Content-Security-Policy"].split("style-src")[0]
        )
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_rejects_non_loopback_host(self):
        response = self.client.get("/api/status", headers={"Host": "attacker.example"})
        self.assertEqual(response.status_code, 400)

    def test_windows_reserved_device_paths_are_not_served(self):
        for path in ("/CON", "/assets/NUL", "/nested/COM1.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_dom_code_does_not_interpolate_hostile_values(self):
        script = (Path(__file__).parents[1] / "dashboard" / "script.js").read_text(encoding="utf-8")
        channels = (Path(__file__).parents[1] / "dashboard" / "channels.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("innerHTML", channels)
        self.assertIn("title.textContent", script)
        self.assertIn("title.textContent", channels)

    def test_playlist_without_real_data_is_explicitly_empty_and_stale(self):
        payload = self.client.get("/api/playlist").get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["source"], "none")
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["data"], [])

    def test_generated_playlist_age_is_reported_as_stale(self):
        updated = datetime.now(timezone.utc) - timedelta(days=2)
        (self.data_dir / "dashboard_playlist.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "generated",
                    "stale": False,
                    "last_updated": updated.isoformat(),
                    "videos": [],
                }
            ),
            encoding="utf-8",
        )
        payload = self.client.get("/api/playlist").get_json()
        self.assertEqual(payload["source"], "generated")
        self.assertTrue(payload["stale"])

    def test_dashboard_defaults_and_validation_use_application_schema(self):
        manager = ConfigManager(Path(self.directory.name) / "config.json")
        defaults = manager.get_defaults()
        self.assertIn("date_filter_mode", defaults)
        self.assertIn("keyword_filter_mode", defaults)
        validation = manager.validate_config(
            {**defaults, "ollama_base_url": "http://user:pass@localhost:11434"}
        )
        self.assertFalse(validation["valid"])


if __name__ == "__main__":
    unittest.main()
