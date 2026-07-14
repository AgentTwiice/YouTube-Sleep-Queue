from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path

from yt_sub_playlist.core.sleep_store import SCHEMA_VERSION, SleepQueueStore


class SleepQueueStoreTests(unittest.TestCase):
    def test_migrates_and_persists_candidate_score(self):
        with temporary_database_path() as path:
            store = SleepQueueStore(str(path))
            run_id = store.start_run(True)
            store.save_candidates(
                run_id,
                [{"video_id": "abc", "title": "Rain", "duration_seconds": 3600}],
            )
            store.save_score("abc", 88, "steady rain", ["ambient"], True)
            store.complete_run(run_id, 1, 1)

            connection = sqlite3.connect(path)
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            row = connection.execute(
                "SELECT sleep_score, status FROM video_candidates"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (88.0, "selected"))

    def test_rejects_newer_schema(self):
        with temporary_database_path() as path:
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.close()
            with self.assertRaises(RuntimeError):
                SleepQueueStore(str(path))


@contextmanager
def temporary_database_path():
    file = tempfile.NamedTemporaryFile(
        suffix=".sqlite3", dir=Path(__file__).parent, delete=False
    )
    path = Path(file.name)
    file.close()
    path.unlink()
    try:
        yield path
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
