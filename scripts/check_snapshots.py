"""Verify atomic private snapshot CLI across processes using invented unavailable results."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="mycoradar-snapshot-smoke-") as folder:
        store = Path(folder) / "store"
        base = [sys.executable, "-m", "mycoradar.snapshots", "--store", str(store)]
        initial = base + ["--batch", str(args.input / "batch.json")]
        processes = [
            subprocess.Popen(initial, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        outputs = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                assert stderr == ""
                outputs.append((process.returncode, json.loads(stdout)))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        assert sorted(code for code, _ in outputs) == [0, 2]
        first = next(data for code, data in outputs if code == 0)
        assert (
            next(data for code, data in outputs if code == 2)["error"] == "snapshot_head_conflict"
        )
        run = first["run_id"]
        before = (store / "current.json").stat().st_mtime_ns

        def call(options: list[str]) -> dict[str, Any]:
            result = subprocess.run(
                base + options, capture_output=True, check=True, text=True, timeout=30
            )
            assert result.stderr == ""
            data = json.loads(result.stdout)
            assert isinstance(data, dict)
            return data

        replay = call(["--batch", str(args.input / "batch.json"), "--expected-run", run])
        assert replay["created"] is False and replay["changed_targets"] == 0
        assert (store / "current.json").stat().st_mtime_ns == before
        delta = call(["--batch", str(args.input / "delta.json"), "--expected-run", run])
        assert delta["changed_targets"] == 1
        descriptor = json.loads((store / "runs" / f"{delta['run_id']}.json").read_bytes())
        assert len(descriptor["entries"]) == 2 and descriptor["publication_allowed"] is False
        call(["--rollback", run, "--expected-run", delta["run_id"]])
        assert json.loads((store / "current.json").read_bytes())["run_id"] == run
        print(
            json.dumps(
                {
                    "scope": "synthetic_snapshot_smoke",
                    "concurrent_winners": 1,
                    "changed_targets": 1,
                    "unaffected_target_retained": True,
                    "replay_preserved": True,
                    "rollback_verified": True,
                    "publication_allowed": False,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
