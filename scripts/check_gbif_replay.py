"""Exercise the packaged GBIF CLI against the frozen synthetic fixture only."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from mycoradar.catalog import DEFAULT_CATALOG
from mycoradar.exploration import CONTEXT_PATH, check_bundle

# Canonical JSON of result in docs/evidence/MR-010-offline-sample.json.
# Pin the entire receipt: exit 0 and accepted=0 alone do not rule out disclosure.
EXPECTED_SHA256 = "5a5380ba3ab2983b052ea77fca2572504800cc77b5d2174d1fa9807e2369cf23"


def publication_bytes() -> tuple[bytes, ...]:
    return tuple(
        path.read_bytes()
        for path in (
            DEFAULT_CATALOG,
            DEFAULT_CATALOG.with_suffix(".sha256"),
            CONTEXT_PATH,
            CONTEXT_PATH.with_suffix(".sha256"),
        )
    )


def check_replay(snapshot: Path) -> None:
    before = publication_bytes()
    check_bundle()
    command = [sys.executable, "-m", "mycoradar.gbif_job", "--snapshot", str(snapshot)]
    runs = [subprocess.run(command, capture_output=True, timeout=20, check=False) for _ in range(2)]
    if any(run.returncode != 0 or run.stderr for run in runs):
        raise RuntimeError("GBIF replay process failed")
    if runs[0].stdout != runs[1].stdout:
        raise RuntimeError("GBIF replay was not deterministic")
    payload = json.loads(runs[0].stdout)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if hashlib.sha256(canonical.encode("ascii")).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("GBIF synthetic receipt changed")
    if publication_bytes() != before:
        raise RuntimeError("GBIF replay modified the public catalogue")
    check_bundle()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        check_replay(args.snapshot)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        # Never echo child stdout/stderr, input paths or provider details on failure.
        print("GBIF synthetic replay verification failed.")
        return 1
    print(
        "GBIF synthetic replay verified: two identical receipts, zero releases, "
        "catalogue unchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
