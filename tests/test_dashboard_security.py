import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / "dashboard" / "backend"
sys.path.insert(0, str(BACKEND_DIR))
import app as dashboard_app  # noqa: E402
from config_manager import ConfigManager  # noqa: E402


class DashboardSecurityTests(unittest.TestCase):
    def setUp(self):
        dashboard_app.app.config.update(TESTING=True)
        self.client = dashboard_app.app.test_client()
        self.token = self.client.get("/api/csrf-token").get_json()["csrf_token"]

    def test_refresh_requires_json_and_csrf_token(self):
        self.assertEqual(self.client.post("/api/refresh").status_code, 415)
        self.assertEqual(
            self.client.post("/api/refresh", json={"dry_run": True}).status_code,
            403,
        )

    def test_refresh_rejects_hostile_origin(self):
        response = self.client.post(
            "/api/refresh",
            json={"dry_run": True},
            headers={
                "Origin": "https://attacker.example",
                "X-CSRF-Token": self.token,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_same_origin_refresh_with_token_is_allowed(self):
        with patch.object(
            dashboard_app.api,
            "refresh_playlist",
            return_value={"success": True, "dry_run": True},
        ):
            response = self.client.post(
                "/api/refresh",
                json={"dry_run": True},
                headers={
                    "Origin": "http://localhost",
                    "X-CSRF-Token": self.token,
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_video_card_does_not_interpolate_untrusted_attributes(self):
        source = (BACKEND_DIR.parent / "script.js").read_text(encoding="utf-8")
        self.assertNotIn('alt="${video.title}"', source)
        self.assertNotIn('href="${youtubeUrl}"', source)
        self.assertIn("image.alt = String(video.title", source)

    def test_dashboard_defaults_and_validation_use_application_schema(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manager = ConfigManager(Path(directory) / "config.json")
            defaults = manager.get_defaults()
            self.assertEqual(defaults["playlist_name"], "YouTube Sleep Queue")
            self.assertIn("date_filter_mode", defaults)
            self.assertIn("keyword_filter_mode", defaults)
            self.assertIn("ollama_model", defaults)

            validation = manager.validate_config(
                {**defaults, "ollama_base_url": "http://user:pass@localhost:11434"}
            )
            self.assertFalse(validation["valid"])


if __name__ == "__main__":
    unittest.main()
