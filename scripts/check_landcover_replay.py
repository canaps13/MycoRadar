"""Replay the admitted frozen IGN sample in the geo image; no network or new source."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def check_replay(manifest: Path, require_container_user: bool) -> None:
    if require_container_user and (not hasattr(os, "getuid") or os.getuid() != 10001):
        raise RuntimeError("Unexpected geo image user")
    with TemporaryDirectory() as directory:
        output = Path(directory) / "landcover.geojson"
        command = [
            sys.executable,
            "-m",
            "mycoradar.landcover_job",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ]
        first = subprocess.run(command, capture_output=True, check=True, timeout=60)
        initial = output.read_bytes()
        second = subprocess.run(command, capture_output=True, check=True, timeout=60)
        a, b, artifact = json.loads(first.stdout), json.loads(second.stdout), json.loads(initial)
        if first.stderr or second.stderr or initial != output.read_bytes():
            raise RuntimeError("Landcover replay changed the artifact")
        if a.get("created") is not True or b.get("created") is not False:
            raise RuntimeError("Landcover replay was not idempotent")
        if a.get("job_id") != b.get("job_id") or a.get("job_id") != artifact.get("job_id"):
            raise RuntimeError("Landcover replay identity changed")
        quality = artifact["quality"]
        if (
            quality["received"] != 48
            or quality["output"] != 45
            or quality["unknown_source_year"] != 0
            or len(quality["vegetation_counts"]) != 8
            or artifact["coverage_status"] != "partial"
            or artifact["negative_inference_allowed"] is not False
            or artifact["grid_mask_status"] != "unavailable"
            or artifact["forest_fraction"] is not None
            or len(artifact["features"]) != 45
            or any(
                feature["properties"]["source_year"] != 2008
                or feature["properties"]["year_meaning"] != "acquisition"
                or feature["properties"]["current_ground_cover_verified"] is not False
                for feature in artifact["features"]
            )
        ):
            raise RuntimeError("Unexpected frozen landcover evidence or availability")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--require-container-user", action="store_true")
    args = parser.parse_args()
    try:
        check_replay(args.manifest, args.require_container_user)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
        print("Frozen landcover replay verification failed.")
        return 1
    print(
        "Frozen landcover replay verified: 45 features, acquisition 2008, "
        "unchanged replay, no mask or current-cover claim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
