"""Single-flight in-process refresh jobs for the loopback dashboard."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yt_sub_playlist.core.atomic_io import atomic_write_json, preserve_corrupt_file

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {"queued", "running"}
FINAL_STATUSES = {"completed", "failed", "timed_out", "abandoned"}


class RefreshAlreadyRunning(RuntimeError):
    pass


class RefreshJobManager:
    def __init__(
        self,
        state_path: Path,
        reports_dir: Path,
        project_root: Path,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        python_executable: str = sys.executable,
        default_timeout: int = 1800,
    ):
        self.state_path = state_path
        self.reports_dir = reports_dir
        self.project_root = project_root
        self.runner = runner
        self.python_executable = python_executable
        self.default_timeout = default_timeout
        self._lock = threading.RLock()
        self._jobs = self._load_jobs()
        self.reconcile_abandoned_jobs()

    def _load_jobs(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.exists():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != 1
                or not isinstance(value.get("jobs"), dict)
            ):
                raise ValueError("expected version 1 refresh-job state")
            return value["jobs"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            backup = preserve_corrupt_file(self.state_path)
            raise ValueError(f"Refresh job state is corrupt; preserved it as {backup}") from exc

    def _save(self) -> None:
        # Retain a bounded history without dropping an active job.
        ordered = sorted(self._jobs.values(), key=lambda job: job["created_at"], reverse=True)
        keep = {job["id"]: job for job in ordered[:20]}
        self._jobs = keep
        atomic_write_json(self.state_path, {"schema_version": 1, "jobs": keep}, mode=0o600)

    def reconcile_abandoned_jobs(self) -> int:
        with self._lock:
            changed = 0
            for job in self._jobs.values():
                if job.get("status") in ACTIVE_STATUSES:
                    job.update(
                        status="abandoned",
                        finished_at=_now(),
                        error="Refresh was abandoned when the dashboard process stopped",
                    )
                    changed += 1
            if changed:
                self._save()
            return changed

    def is_active(self) -> bool:
        with self._lock:
            return any(job.get("status") in ACTIVE_STATUSES for job in self._jobs.values())

    def start(self, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self.is_active():
                raise RefreshAlreadyRunning("A refresh is already in progress")
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "status": "queued",
                "dry_run": dry_run,
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "progress": "queued",
                "error": None,
                "return_code": None,
                "timeout_seconds": timeout or self.default_timeout,
            }
            self._jobs[job_id] = job
            self._save()
            thread = threading.Thread(
                target=self._run, args=(job_id,), name=f"refresh-{job_id[:8]}", daemon=True
            )
            thread.start()
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._jobs:
                return None
            return dict(max(self._jobs.values(), key=lambda job: job["created_at"]))

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(
                status="running", started_at=_now(), progress="discovering and ranking videos"
            )
            self._save()
            timeout = int(job["timeout_seconds"])
            dry_run = bool(job["dry_run"])
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report = self.reports_dir / f"dashboard_refresh_{job_id}.csv"
        command = [self.python_executable, "-m", "yt_sub_playlist", "--report", str(report)]
        if dry_run:
            command.append("--dry-run")
        try:
            completed = self.runner(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            logger.info("Refresh %s stdout:\n%s", job_id, completed.stdout)
            if completed.stderr:
                logger.warning("Refresh %s stderr:\n%s", job_id, completed.stderr)
            with self._lock:
                job = self._jobs[job_id]
                job["return_code"] = completed.returncode
                job["finished_at"] = _now()
                if completed.returncode == 0:
                    job.update(status="completed", progress="completed", error=None)
                else:
                    job.update(
                        status="failed",
                        progress="failed",
                        error=_sanitize_error(
                            completed.stderr or completed.stdout, self.project_root
                        ),
                    )
                self._save()
        except subprocess.TimeoutExpired as exc:
            logger.error(
                "Refresh %s timed out; stdout=%r stderr=%r", job_id, exc.stdout, exc.stderr
            )
            with self._lock:
                self._jobs[job_id].update(
                    status="timed_out",
                    progress="timed out",
                    finished_at=_now(),
                    error=f"Refresh exceeded its {timeout}-second timeout",
                )
                self._save()
        except Exception as exc:
            logger.exception("Refresh %s failed", job_id)
            with self._lock:
                self._jobs[job_id].update(
                    status="failed",
                    progress="failed",
                    finished_at=_now(),
                    error=_sanitize_error(str(exc), self.project_root),
                )
                self._save()


def _sanitize_error(value: str | bytes | None, project_root: Path) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = (value or "Refresh failed without an error message").replace(
        str(project_root), "<project>"
    )
    text = re.sub(
        r"(?i)(token|secret|api[_-]?key|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", text
    )
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    return text.strip()[-2000:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
