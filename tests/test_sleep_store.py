import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
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
            store.save_rankings(
                [
                    {
                        "video_id": "abc",
                        "sleep_score": 88,
                        "sleep_rationale": "steady rain",
                        "sleep_signals": ["ambient"],
                        "sleep_score_cached": False,
                        "sleep_metadata_hash": "hash",
                    }
                ],
                "model",
                "1",
                {"abc"},
            )
            store.complete_run(run_id, 1, 1, 1, 0)

            connection = sqlite3.connect(path)
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            row = connection.execute("SELECT sleep_score, status FROM video_candidates").fetchone()
            run = connection.execute(
                "SELECT status, added_count, failed_count FROM queue_runs"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (88.0, "selected"))
            self.assertEqual(run, ("completed", 1, 0))

    def test_reuses_score_only_for_matching_model_prompt_and_metadata(self):
        with temporary_database_path() as path:
            store = SleepQueueStore(str(path))
            run_id = store.start_run(True)
            store.save_candidates(run_id, [{"video_id": "abc", "title": "Rain"}])
            ranking = {
                "video_id": "abc",
                "sleep_score": 88,
                "sleep_rationale": "steady rain",
                "sleep_signals": ["ambient"],
                "sleep_score_cached": False,
                "sleep_metadata_hash": "hash",
            }
            store.save_rankings([ranking], "model", "1", {"abc"})

            self.assertIn("abc", store.get_cached_scores({"abc": "hash"}, "model", "1"))
            self.assertEqual(store.get_cached_scores({"abc": "changed"}, "model", "1"), {})
            self.assertEqual(store.get_cached_scores({"abc": "hash"}, "other", "1"), {})

    def test_records_failed_run(self):
        with temporary_database_path() as path:
            store = SleepQueueStore(str(path))
            run_id = store.start_run(False)
            store.fail_run(run_id, RuntimeError("ollama unavailable"))
            connection = sqlite3.connect(path)
            row = connection.execute(
                "SELECT status, completed_at, error_message FROM queue_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            connection.close()
            self.assertEqual(row[0], "failed")
            self.assertIsNotNone(row[1])
            self.assertEqual(row[2], "ollama unavailable")

    def test_migrates_existing_version_one_database(self):
        with temporary_database_path() as path:
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE queue_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    dry_run INTEGER NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    selected_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE video_candidates (
                    video_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    channel_id TEXT,
                    channel_title TEXT,
                    published_at TEXT,
                    duration_seconds INTEGER,
                    sleep_score REAL,
                    rationale TEXT,
                    signals_json TEXT,
                    status TEXT NOT NULL DEFAULT 'discovered',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_run_id INTEGER,
                    FOREIGN KEY(last_run_id) REFERENCES queue_runs(id)
                );
                CREATE INDEX idx_video_candidates_score
                    ON video_candidates(status, sleep_score DESC);
                INSERT INTO queue_runs(started_at, completed_at, dry_run)
                    VALUES ('start', 'end', 0);
                INSERT INTO video_candidates(
                    video_id, title, status, first_seen_at, last_seen_at, last_run_id
                ) VALUES ('abc', 'Rain', 'added', 'first', 'last', 1);
                PRAGMA user_version = 1;
                """
            )
            connection.close()

            SleepQueueStore(str(path))
            connection = sqlite3.connect(path)
            run = connection.execute(
                "SELECT status, added_count, failed_count FROM queue_runs"
            ).fetchone()
            candidate = connection.execute(
                "SELECT ever_added_at, model, prompt_version FROM video_candidates"
            ).fetchone()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            connection.close()

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(run, ("completed", 0, 0))
            self.assertEqual(candidate, ("last", None, None))

    def test_rejects_newer_schema(self):
        with temporary_database_path() as path:
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.close()
            with self.assertRaises(RuntimeError):
                SleepQueueStore(str(path))


@contextmanager
def temporary_database_path():
    file = tempfile.NamedTemporaryFile(suffix=".sqlite3", dir=Path(__file__).parent, delete=False)
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
