"""Fail when tracked or pending files contain common credential material."""

import re
import subprocess
import sys
from pathlib import Path


SENSITIVE_PATHS = (
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"(^|/)(client_secret[^/]*\.json|client_secrets[^/]*\.json|token\.json)$"),
    re.compile(r"\.(sqlite|sqlite3|db)(-(wal|shm|journal))?$"),
)
TOKEN_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
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


def main() -> int:
    failures: list[str] = []
    for relative_path in repository_files():
        if relative_path == ".env.example":
            continue
        if any(pattern.search(relative_path) for pattern in SENSITIVE_PATHS):
            failures.append(f"sensitive path: {relative_path}")
            continue

        path = Path(relative_path)
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(pattern.search(contents) for pattern in TOKEN_PATTERNS):
            failures.append(f"credential pattern: {relative_path}")

    if failures:
        print("Repository secret scan failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Repository secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
