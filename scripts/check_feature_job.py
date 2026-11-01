"""Exercise the actual CLI twice on an explicitly synthetic offline manifest."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
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
        first = subprocess.run(command, check=True, capture_output=True, text=True)
        content = output.read_bytes()
        modified = output.stat().st_mtime_ns
        second = subprocess.run(command, check=True, capture_output=True, text=True)
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
        print(
            json.dumps(
                {
                    "job_id": artifact["job_id"],
                    "rows": len(rows),
                    "replay_identical": True,
                    "status": artifact["status"],
                    "input_kind": artifact["input_kind"],
                }
            )
        )


if __name__ == "__main__":
    main()
