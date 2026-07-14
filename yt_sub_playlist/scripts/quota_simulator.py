"""Summarize the shared versioned quota event log."""

from collections import Counter

from yt_sub_playlist.core.paths import AppPaths
from yt_sub_playlist.core.quota_log import read_quota_log

DAILY_QUOTA_LIMIT = 10_000


def main() -> None:
    path = AppPaths.resolve().quota_log
    log = read_quota_log(path)
    calls = Counter(event["method"] for event in log["events"])
    costs: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    for event in log["events"]:
        costs[event["method"]] += event["quota_cost"]
        if event["result"] not in {"success", "legacy_success"}:
            failures[event["method"]] += 1
    total = sum(costs.values())
    print(f"Quota log: {path}")
    for method in sorted(calls):
        print(
            f"  {method:<25} {calls[method]:>4} attempts, "
            f"{failures[method]:>3} failed, {costs[method]:>5} units"
        )
    print(f"Total: {total} / {DAILY_QUOTA_LIMIT} units")


if __name__ == "__main__":
    main()
