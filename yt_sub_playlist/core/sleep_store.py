"""SQLite persistence for sleep queue candidates and ranking runs."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator

SCHEMA_VERSION = 3
ACTIVE_RUN_STATUSES = {"running", "ranking", "adding"}
COMPLETED_RUN_STATUSES = {"completed", "completed_with_errors"}


class SleepQueueStore:
    """Store run summaries and latest candidate state without credentials."""

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()
        self.reconcile_abandoned_runs()

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
                self._run_migration(
                    connection,
                    1,
                    (
                        """
                        CREATE TABLE queue_runs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            started_at TEXT NOT NULL,
                            completed_at TEXT,
                            dry_run INTEGER NOT NULL,
                            candidate_count INTEGER NOT NULL DEFAULT 0,
                            selected_count INTEGER NOT NULL DEFAULT 0
                        )
                        """,
                        """
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
                        )
                        """,
                        """
                        CREATE INDEX idx_video_candidates_score
                        ON video_candidates(status, sleep_score DESC)
                        """,
                    ),
                )
                version = 1
            if version < 2:
                self._run_migration(
                    connection,
                    2,
                    (
                        "ALTER TABLE queue_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'running'",
                        "ALTER TABLE queue_runs ADD COLUMN error_message TEXT",
                        "ALTER TABLE queue_runs ADD COLUMN added_count INTEGER NOT NULL DEFAULT 0",
                        "ALTER TABLE queue_runs ADD COLUMN failed_count INTEGER NOT NULL DEFAULT 0",
                        "ALTER TABLE video_candidates ADD COLUMN model TEXT",
                        "ALTER TABLE video_candidates ADD COLUMN prompt_version TEXT",
                        "ALTER TABLE video_candidates ADD COLUMN metadata_hash TEXT",
                        "ALTER TABLE video_candidates ADD COLUMN scored_at TEXT",
                        "ALTER TABLE video_candidates ADD COLUMN ever_added_at TEXT",
                        """
                        UPDATE queue_runs
                        SET status = CASE
                            WHEN completed_at IS NULL THEN 'running'
                            ELSE 'completed'
                        END
                        """,
                        """
                        UPDATE video_candidates
                        SET ever_added_at = last_seen_at
                        WHERE status = 'added' AND ever_added_at IS NULL
                        """,
                        """
                        CREATE INDEX idx_video_candidates_cache
                        ON video_candidates(model, prompt_version, metadata_hash)
                        """,
                    ),
                )
                version = 2
            if version < 3:
                self._run_migration(
                    connection,
                    3,
                    (
                        "ALTER TABLE queue_runs ADD COLUMN existing_count INTEGER NOT NULL DEFAULT 0",
                        "ALTER TABLE queue_runs ADD COLUMN warning_count INTEGER NOT NULL DEFAULT 0",
                    ),
                )

    @staticmethod
    def _run_migration(
        connection: sqlite3.Connection, version: int, statements: Iterable[str]
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def start_run(self, dry_run: bool) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO queue_runs(started_at, dry_run, status) VALUES (?, ?, 'running')",
                (_utc_now(), int(dry_run)),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a run ID")
            return int(cursor.lastrowid)

    def reconcile_abandoned_runs(self) -> int:
        """Mark active rows left by a prior process as abandoned failures."""
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
            cursor = connection.execute(
                f"""
                UPDATE queue_runs
                SET completed_at=?, status='failed',
                    error_message='Run was abandoned by a crash or terminated refresh'
                WHERE completed_at IS NULL AND status IN ({placeholders})
                """,
                (_utc_now(), *sorted(ACTIVE_RUN_STATUSES)),
            )
            return int(cursor.rowcount)

    def set_run_status(self, run_id: int, status: str) -> None:
        if status not in ACTIVE_RUN_STATUSES:
            raise ValueError(f"Invalid active run status: {status}")
        with self._connect() as connection:
            connection.execute("UPDATE queue_runs SET status=? WHERE id=?", (status, run_id))

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
                        video["video_id"],
                        video["title"],
                        video.get("channel_id"),
                        video.get("channel_title"),
                        video.get("published_at"),
                        video.get("duration_seconds"),
                        now,
                        now,
                        run_id,
                    ),
                )

    def get_cached_scores(
        self,
        metadata_hashes: Dict[str, str],
        model: str,
        prompt_version: str,
    ) -> Dict[str, Dict[str, Any]]:
        if not metadata_hashes:
            return {}
        placeholders = ",".join("?" for _ in metadata_hashes)
        parameters = [*metadata_hashes.keys(), model, prompt_version]
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT video_id, sleep_score, rationale, signals_json, metadata_hash
                FROM video_candidates
                WHERE video_id IN ({placeholders})
                  AND model=? AND prompt_version=?
                  AND sleep_score IS NOT NULL AND rationale IS NOT NULL
                """,
                parameters,
            ).fetchall()

        cached: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if row["metadata_hash"] != metadata_hashes.get(row["video_id"]):
                continue
            try:
                signals = json.loads(row["signals_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            cached[row["video_id"]] = {
                "score": row["sleep_score"],
                "rationale": row["rationale"],
                "signals": signals,
            }
        return cached

    def save_rankings(
        self,
        ranked_videos: Iterable[Dict[str, Any]],
        model: str,
        prompt_version: str,
        selected_ids: set[str],
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            for ranked in ranked_videos:
                was_cached = bool(ranked.get("sleep_score_cached"))
                connection.execute(
                    """
                    UPDATE video_candidates
                    SET sleep_score=?, rationale=?, signals_json=?, status=?,
                        model=?, prompt_version=?, metadata_hash=?,
                        scored_at=CASE
                            WHEN ? AND scored_at IS NOT NULL THEN scored_at
                            ELSE ?
                        END
                    WHERE video_id=?
                    """,
                    (
                        ranked["sleep_score"],
                        ranked["sleep_rationale"],
                        json.dumps(ranked["sleep_signals"]),
                        "selected" if ranked["video_id"] in selected_ids else "rejected",
                        model,
                        prompt_version,
                        ranked["sleep_metadata_hash"],
                        was_cached,
                        now,
                        ranked["video_id"],
                    ),
                )

    def save_ranking(
        self,
        ranked: Dict[str, Any],
        model: str,
        prompt_version: str,
        selected: bool = False,
    ) -> None:
        """Persist one successful ranking immediately."""
        self.save_rankings(
            [ranked], model, prompt_version, {ranked["video_id"]} if selected else set()
        )

    def mark_added(self, video_ids: Iterable[str]) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.executemany(
                """
                UPDATE video_candidates
                SET status='added', ever_added_at=COALESCE(ever_added_at, ?)
                WHERE video_id=?
                """,
                ((now, video_id) for video_id in video_ids),
            )

    def mark_outcomes(
        self,
        added_ids: Iterable[str],
        existing_ids: Iterable[str],
        failed_ids: Iterable[str],
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.executemany(
                """
                UPDATE video_candidates
                SET status='added', ever_added_at=COALESCE(ever_added_at, ?)
                WHERE video_id=?
                """,
                ((now, video_id) for video_id in added_ids),
            )
            connection.executemany(
                "UPDATE video_candidates SET status='already_present' WHERE video_id=?",
                ((video_id,) for video_id in existing_ids),
            )
            connection.executemany(
                "UPDATE video_candidates SET status='add_failed' WHERE video_id=?",
                ((video_id,) for video_id in failed_ids),
            )

    def complete_run(
        self,
        run_id: int,
        candidate_count: int,
        selected_count: int,
        added_count: int = 0,
        failed_count: int = 0,
        existing_count: int = 0,
        warning_count: int = 0,
        status: str = "completed",
        warning_message: str | None = None,
    ) -> None:
        if status not in COMPLETED_RUN_STATUSES:
            raise ValueError(f"Invalid completed run status: {status}")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_runs
                SET completed_at=?, status=?, error_message=?,
                    candidate_count=?, selected_count=?, added_count=?, failed_count=?,
                    existing_count=?, warning_count=?
                WHERE id=?
                """,
                (
                    _utc_now(),
                    status,
                    warning_message[:2000] if warning_message else None,
                    candidate_count,
                    selected_count,
                    added_count,
                    failed_count,
                    existing_count,
                    warning_count,
                    run_id,
                ),
            )

    def fail_run(self, run_id: int, error: Exception | str) -> None:
        message = str(error).strip() or error.__class__.__name__
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_runs
                SET completed_at=?, status='failed', error_message=?
                WHERE id=?
                """,
                (_utc_now(), message[:2000], run_id),
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
