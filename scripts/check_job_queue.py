"""Exercise the real queue across processes using synthetic source versions only."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from mycoradar.job_queue import JobQueue, RetryLater


def check(database: Path) -> dict[str, object]:
    clock = [1000]
    queue = JobQueue(database, clock=lambda: clock[0])
    queue.register("synthetic-source", "smoke-v1")
    assert queue.poll("synthetic-source", lambda: "a" * 64) == "queued"
    processes = [
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--claim", "--database", str(database)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0 and not stderr
            results.append(json.loads(stdout)["claimed"])
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert sum(results) == 1
    clock[0] += 300
    recovered = queue.claim()
    assert recovered is not None and recovered.attempt == 2 and queue.finish(recovered)
    clock[0] = 4600
    assert queue.poll("synthetic-source", lambda: None) == "unchanged"
    clock[0] += 3600
    assert queue.poll("synthetic-source", lambda: "b" * 64) == "queued"
    clock[0] += 3600

    def limited() -> str:
        raise RetryLater(600)

    assert queue.poll("synthetic-source", limited) == "retry"
    assert queue.claim() is None
    clock[0] += 600
    assert queue.poll("synthetic-source", lambda: None) == "unchanged"

    def timeout(_job: object) -> None:
        raise TimeoutError("Synthetic transient error")

    assert queue.run_one(timeout) == "retry"
    clock[0] += 60
    assert queue.run_one(lambda _job: None) == "done"
    assert queue.counts() == {"queued": 0, "running": 0, "done": 2, "dead": 0}
    return {
        "scope": "synthetic_queue_smoke",
        "concurrent_claim_winners": sum(results),
        "lease_recovered": True,
        "unchanged_deduplicated": True,
        "provider_cooldown_respected": True,
        "timeout_recovered": True,
        "counts": queue.counts(),
        "real_sources_polled": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--database", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.claim:
            if args.database is None:
                raise ValueError
            result: dict[str, object] = {
                "claimed": JobQueue(args.database, clock=lambda: 1000).claim() is not None
            }
        else:
            with TemporaryDirectory(prefix="mycoradar-queue-smoke-") as folder:
                result = check(Path(folder) / "queue.sqlite")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, AssertionError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "unavailable", "error": "queue_smoke_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
