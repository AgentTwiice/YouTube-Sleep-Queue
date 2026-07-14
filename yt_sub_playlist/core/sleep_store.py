"""SQLite persistence for sleep queue candidates and ranking runs."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List


SCHEMA_VERSION = 1


class SleepQueueStore:
    """Store run summaries and latest candidate state without credentials."""

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {version} is newer than supported version {SCHEMA_VERSION}"
                )
            if version < 1:
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
                    PRAGMA user_version = 1;
                    """
                )

    def start_run(self, dry_run: bool) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO queue_runs(started_at, dry_run) VALUES (?, ?)",
                (_utc_now(), int(dry_run)),
            )
            return int(cursor.lastrowid)

    def save_candidates(self, run_id: int, videos: Iterable[Dict[str, Any]]) -> None:
        now = _utc_now()
        with self._connect() as connection:
            for video in videos:
                connection.execute(
                    """
                    INSERT INTO video_candidates(
                        video_id, title, channel_id, channel_title, published_at,
                        duration_seconds, first_seen_at, last_seen_at, last_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        title=excluded.title,
                        channel_id=excluded.channel_id,
                        channel_title=excluded.channel_title,
                        published_at=excluded.published_at,
                        duration_seconds=excluded.duration_seconds,
                        last_seen_at=excluded.last_seen_at,
                        last_run_id=excluded.last_run_id
                    """,
                    (
                        video["video_id"], video["title"], video.get("channel_id"),
                        video.get("channel_title"), video.get("published_at"),
                        video.get("duration_seconds"), now, now, run_id,
                    ),
                )

    def save_score(
        self,
        video_id: str,
        score: float,
        rationale: str,
        signals: List[str],
        selected: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE video_candidates
                SET sleep_score=?, rationale=?, signals_json=?, status=?
                WHERE video_id=?
                """,
                (
                    score,
                    rationale,
                    json.dumps(signals),
                    "selected" if selected else "rejected",
                    video_id,
                ),
            )

    def mark_added(self, video_ids: Iterable[str]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "UPDATE video_candidates SET status='added' WHERE video_id=?",
                ((video_id,) for video_id in video_ids),
            )

    def complete_run(self, run_id: int, candidate_count: int, selected_count: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_runs
                SET completed_at=?, candidate_count=?, selected_count=?
                WHERE id=?
                """,
                (_utc_now(), candidate_count, selected_count, run_id),
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
