import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from yt_sub_playlist.__main__ import create_argument_parser
from yt_sub_playlist.core.playlist_manager import PlaylistManager, _spreadsheet_safe


class CliAndReportTests(unittest.TestCase):
    def test_limit_must_be_between_one_and_two_hundred(self):
        parser = create_argument_parser()
        for value in ("0", "-1", "201"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    parser.parse_args(["--limit", value])
        self.assertEqual(parser.parse_args(["--limit", "25"]).limit, 25)

    def test_spreadsheet_formula_text_is_neutralized(self):
        for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", "\tformula"):
            with self.subTest(value=value):
                self.assertTrue(_spreadsheet_safe(value).startswith("'"))
        self.assertEqual(_spreadsheet_safe("Normal title"), "Normal title")

    def test_report_supports_a_bare_filename(self):
        manager = PlaylistManager.__new__(PlaylistManager)
        manager._write_dashboard_json = MagicMock()
        video = {
            "title": "=dangerous",
            "video_id": "abcdefghijk",
            "channel_title": "Channel",
            "added": True,
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            report_path = Path(directory) / "output.csv"
            manager.write_report([video], str(report_path))
            with report_path.open(newline="", encoding="utf-8") as report:
                row = next(csv.DictReader(report))
        self.assertEqual(row["title"], "'=dangerous")


if __name__ == "__main__":
    unittest.main()
