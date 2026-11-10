"""Offline replay of three admitted frozen extracts; preserve values and uncertainty."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SAMPLES = ("soilgrids-sample", "soilgrids-file-sample", "ign-terrain-sample")


def check_replay(root: Path, require_container_user: bool) -> None:
    if require_container_user and (not hasattr(os, "getuid") or os.getuid() != 10001):
        raise RuntimeError("Unexpected raster image user")
    with TemporaryDirectory() as directory:
        for name in SAMPLES:
            folder = root / name
            expected = json.loads((folder / "normalized.json").read_bytes())
            output = Path(directory) / (name + ".json")
            command = [
                sys.executable,
                "-m",
                "mycoradar.raster_job",
                "--manifest",
                str(folder / "manifest.json"),
                "--output",
                str(output),
            ]
            first = subprocess.run(command, capture_output=True, check=True, timeout=60)
            initial = output.read_bytes()
            second = subprocess.run(command, capture_output=True, check=True, timeout=60)
            a, b, artifact = (
                json.loads(first.stdout),
                json.loads(second.stdout),
                json.loads(initial),
            )
            if (
                first.stderr
                or second.stderr
                or initial != output.read_bytes()
                or a.get("created") is not True
                or b.get("created") is not False
                or a.get("job_id") != b.get("job_id")
                or a.get("job_id") != artifact.get("job_id")
            ):
                raise RuntimeError("Raster replay identity or bytes changed")
            if (
                artifact["values"] != expected["values"]
                or artifact["quality"] != expected["quality"]
                or artifact["conversion"]["output_unit"] != expected["conversion"]["output_unit"]
                or artifact["coverage_status"] != "partial"
                or artifact["effective_resolution_m"] is not None
                or artifact["source_year"] is not None
                or artifact["data_cutoff"] is not None
                or artifact["scores_added"] != 0
                or artifact["public_layers_added"] != 0
            ):
                raise RuntimeError("Frozen raster values or unknowns changed")
            if name == "ign-terrain-sample" and (
                artifact["delivery"]["requested_crs_matches_file"] is not False
                or artifact["delivery"]["server_resampling"] != "unknown"
                or artifact["vertical_reference"]["name"] is not None
            ):
                raise RuntimeError("Terrain delivery uncertainty lost")
    print(
        "Frozen raster replay verified: three stable artifacts, values and NoData "
        "preserved, terrain CRS mismatch and unknown vertical reference retained."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--require-container-user", action="store_true")
    args = parser.parse_args()
    try:
        check_replay(args.root, args.require_container_user)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
        print("Frozen raster replay verification failed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
