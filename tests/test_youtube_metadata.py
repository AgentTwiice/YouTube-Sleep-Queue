import unittest
from unittest.mock import MagicMock, patch

from yt_sub_playlist.core.youtube_client import YouTubeClient


class YouTubeMetadataTests(unittest.TestCase):
    def test_video_details_include_description_for_ranking(self):
        client = YouTubeClient.__new__(YouTubeClient)
        client.service = MagicMock()
        client.service.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "abc",
                    "contentDetails": {"duration": "PT1H"},
                    "snippet": {
                        "liveBroadcastContent": "none",
                        "description": "Soft rain throughout",
                    },
                }
            ]
        }

        with patch("yt_sub_playlist.core.youtube_client.track_api_call"):
            details = client._get_videos_details_batch(["abc"])

        self.assertEqual(details["abc"]["description"], "Soft rain throughout")


if __name__ == "__main__":
    unittest.main()
