"""Run the production CLI twice on a labelled synthetic, read-only input tree."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="mycoradar-runner-smoke-") as folder:
        command = [
            sys.executable,
            "-m",
            "mycoradar.queue_runner",
            "--config",
            str(args.config),
            "--state",
            folder,
            "--once",
        ]
        results = []
        for _ in range(2):
            process = subprocess.run(
                command, check=True, capture_output=True, text=True, timeout=30
            )
            assert process.stderr == ""
            results.append(json.loads(process.stdout))
        assert results[0]["jobs"]["done"] == results[1]["jobs"]["done"] == 1
        assert results[1]["polls"] == {"not_due": 1}
        receipts = list((Path(folder) / "receipts").iterdir())
        assert len(receipts) == 1
        receipt = json.loads(receipts[0].read_bytes())
        assert receipt["publication_allowed"] is False
        print(
            json.dumps(
                {
                    "scope": "synthetic_runner_smoke",
                    "jobs_done": 1,
                    "restart_deduplicated": True,
                    "publication_allowed": False,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
