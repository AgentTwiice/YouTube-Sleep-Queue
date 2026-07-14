import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_sub_playlist.auth import oauth


class OAuthStorageTests(unittest.TestCase):
    def test_saves_and_loads_authorized_user_json(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            token_path = Path(directory) / "token.json"
            credentials = MagicMock()
            credentials.to_json.return_value = '{"token":"secret"}'
            loaded = object()

            with patch.object(oauth, "TOKEN_FILE", str(token_path)):
                oauth._save_credentials(credentials)
                with patch.object(
                    oauth.Credentials,
                    "from_authorized_user_file",
                    return_value=loaded,
                ) as loader:
                    self.assertIs(oauth._load_stored_credentials(), loaded)

            self.assertEqual(token_path.read_text(encoding="utf-8"), '{"token":"secret"}')
            loader.assert_called_once_with(str(token_path), oauth.SCOPES)

    def test_rejects_legacy_binary_token_without_deserializing_it(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            token_path = Path(directory) / "token.json"
            token_path.write_bytes(b"\x80\x04legacy-pickle")
            with patch.object(oauth, "TOKEN_FILE", str(token_path)):
                with self.assertRaises(oauth.YouTubeAuthenticationError):
                    oauth._load_stored_credentials()


if __name__ == "__main__":
    unittest.main()
