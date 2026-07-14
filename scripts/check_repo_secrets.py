"""Fail when tracked or pending files contain common credential material."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SENSITIVE_PATHS = (
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(
        r"(^|/)(?:\.?token\.json(?:[.~].*)?|client_secrets?[^/]*\.json(?:[.~].*)?|credentials\.json(?:[.~].*)?|[^/]*_credentials\.json(?:[.~].*)?)$",
        re.IGNORECASE,
    ),
    re.compile(r"\.(sqlite|sqlite3|db)(-(wal|shm|journal))?$", re.IGNORECASE),
)
TOKEN_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
)


def repository_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines()]


def scan_content(relative_path: str, contents: str) -> list[str]:
    normalized_path = relative_path.replace("\\", "/")
    failures: list[str] = []
    if normalized_path.casefold() == ".env.example":
        return failures
    if any(pattern.search(normalized_path) for pattern in SENSITIVE_PATHS):
        failures.append(f"sensitive path: {normalized_path}")
    if any(pattern.search(contents) for pattern in TOKEN_PATTERNS):
        failures.append(f"credential pattern: {normalized_path}")
    try:
        value = json.loads(contents)
    except (json.JSONDecodeError, UnicodeDecodeError):
        value = None
    if _contains_authorized_user(value):
        failures.append(f"authorized-user OAuth JSON: {normalized_path}")
    return failures


def _contains_authorized_user(value: object) -> bool:
    if isinstance(value, dict):
        keys = {str(key).casefold() for key in value}
        if (
            value.get("type") == "authorized_user"
            and {"client_id", "client_secret", "refresh_token"} <= keys
        ):
            return True
        if {"client_id", "client_secret", "refresh_token", "token_uri"} <= keys:
            return True
        return any(_contains_authorized_user(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_authorized_user(item) for item in value)
    return False


def main() -> int:
    failures: list[str] = []
    for relative_path in repository_files():
        path = Path(relative_path)
        if not path.exists():
            # A tracked path can be absent while its deletion is still unstaged.
            continue
        try:
            contents = path.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            failures.append(f"could not inspect {relative_path}: {exc}")
            continue
        failures.extend(scan_content(relative_path, contents))
    if failures:
        print("Repository secret scan failed:", file=sys.stderr)
        for failure in sorted(set(failures)):
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Repository secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
