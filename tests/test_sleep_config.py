import os
import unittest
from unittest.mock import patch

from yt_sub_playlist.config.env_loader import load_config
from yt_sub_playlist.config.schema import ConfigSchema


class SleepConfigTests(unittest.TestCase):
    def test_accepts_default_sleep_configuration(self):
        config = ConfigSchema.validate_config({})
        self.assertEqual(config["ollama_base_url"], "http://localhost:11434")
        self.assertEqual(config["sleep_minimum_score"], 70.0)
        self.assertEqual(config["sleep_queue_size"], 10)
        self.assertIsNone(config["playlist_id"])

    def test_rejects_invalid_sleep_configuration(self):
        invalid_values = [
            {"sleep_minimum_score": 101},
            {"ollama_timeout_seconds": 0},
            {"sleep_queue_size": 0},
            {"ollama_base_url": "file:///tmp/ollama"},
            {"ollama_base_url": "http://user:password@localhost:11434"},
            {"ollama_model": ""},
        ]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ConfigSchema.validate_config(value)

    def test_environment_values_are_validated(self):
        environment = {key: value for key, value in os.environ.items() if key != "SLEEP_QUEUE_SIZE"}
        environment["SLEEP_QUEUE_SIZE"] = "0"
        with patch.dict(os.environ, environment, clear=True), self.assertRaises(ValueError):
            load_config()


if __name__ == "__main__":
    unittest.main()
