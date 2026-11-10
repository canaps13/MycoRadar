"""Exercise the actual CLI twice on an explicitly synthetic offline manifest."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--require-container-user", action="store_true")
    args = parser.parse_args()
    if args.require_container_user:
        assert hasattr(os, "getuid") and os.getuid() == 10001
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "features.json"
        command = [
            sys.executable,
            "-m",
            "mycoradar.feature_job",
            "--manifest",
            str(args.manifest),
            "--output",
            str(output),
        ]
        first = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        content = output.read_bytes()
        modified = output.stat().st_mtime_ns
        second = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        assert json.loads(first.stdout)["created"] is True
        assert json.loads(second.stdout)["created"] is False
        assert output.read_bytes() == content and output.stat().st_mtime_ns == modified
        artifact = json.loads(content)
        rows = {row["feature_id"]: row for row in artifact["features"]}
        assert abs(rows["test:continuous"]["value"] - 5) < 1e-10
        assert rows["test:future"]["value"] is None
        assert rows["test:future"]["reason"] == "source_not_available_as_of"
        assert rows["test:missing"]["value"] is None
        assert rows["test:missing"]["reason"] == "incomplete_usable_coverage"
        assert artifact["input_kind"] == "synthetic"
        assert artifact["admitted_for_scientific_use"] is False
        # The same instants expressed as Unix numbers must fail before publication.
        for index, nested in enumerate((False, True)):
            invalid = json.loads(args.manifest.read_bytes())
            parent = invalid["layers"][-1]["source"] if nested else invalid
            key = "fetched_at" if nested else "as_of"
            parent[key] = int(datetime.fromisoformat(parent[key]).timestamp())
            invalid_path = Path(directory) / f"invalid-{index}.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
            invalid_output = Path(directory) / f"invalid-output-{index}.json"
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mycoradar.feature_job",
                    "--manifest",
                    str(invalid_path),
                    "--output",
                    str(invalid_output),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            assert rejected.returncode == 2 and rejected.stderr == ""
            assert json.loads(rejected.stdout) == {"error": "feature_job_failed"}
            assert not invalid_output.exists()
        print(
            json.dumps(
                {
                    "job_id": artifact["job_id"],
                    "rows": len(rows),
                    "replay_identical": True,
                    "invalid_timestamps_rejected": 2,
                    "status": artifact["status"],
                    "input_kind": artifact["input_kind"],
                }
            )
        )


if __name__ == "__main__":
    main()
