#!/usr/bin/env python3
"""
Convert CSV report to JSON format for dashboard.
Usage: python scripts/csv_to_json.py input.csv output.json
"""

import csv
import sys
from pathlib import Path

from yt_sub_playlist.core.atomic_io import atomic_write_json


def csv_to_playlist_json(csv_path: str, json_path: str | None = None) -> str:
    """Convert CSV report to playlist JSON format."""

    if json_path is None:
        json_path = csv_path.replace(".csv", ".json")

    playlist = []

    with open(csv_path, encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            video = {
                "title": row.get("title", ""),
                "video_id": row.get("video_id", ""),
                "channel_title": row.get("channel_title", ""),
                "channel_id": row.get("channel_id", ""),
                "published_at": row.get("published_at", ""),
                "duration_seconds": int(row.get("duration_seconds", 0))
                if row.get("duration_seconds")
                else 0,
                "live_broadcast": row.get("live_broadcast", "none"),
                "added": row.get("added", "").lower() in ("true", "1", "yes"),
            }
            playlist.append(video)

    atomic_write_json(json_path, playlist)
    print(f"✅ Converted {len(playlist)} videos from {csv_path} to {json_path}")
    return json_path


def main():
    """Main conversion function."""
    if len(sys.argv) < 2:
        print("Usage: python csv_to_json.py input.csv [output.json]")
        print(
            "Example: python csv_to_json.py yt_sub_playlist/reports/latest.csv dashboard/playlist.json"
        )
        sys.exit(1)

    csv_path = sys.argv[1]
    json_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(csv_path).exists():
        print(f"❌ CSV file not found: {csv_path}")
        sys.exit(1)

    try:
        result = csv_to_playlist_json(csv_path, json_path)
        print(f"🎉 Conversion complete: {result}")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"❌ Conversion failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
