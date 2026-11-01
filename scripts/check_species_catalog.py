"""Run the real bibliographic catalogue twice, offline, without activating a pilot."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    command = [sys.executable, "-m", "mycoradar.species_ecology", "--manifest", str(args.manifest)]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout and first.stderr == second.stderr == ""
    report = json.loads(first.stdout)
    assert report["content_kind"] == "real_bibliographic_catalog"
    assert report["status"] == "partial" and report["publication_allowed"] is False
    assert report["taxonomic_reference"] == "gbif_backbone_legacy"
    assert report["source_count"] == 4
    assert len(report["candidates"]) == 4
    assert sum(c["association_count"] for c in report["candidates"]) == 5
    for candidate in report["candidates"]:
        assert candidate["configured_thresholds"] == 0
        assert candidate["pilot_admission"] == "not_admitted"
        assert candidate["habitat_score"] is candidate["fruiting_score"] is None
        assert candidate["effective_resolution_m"] is None
    print(
        json.dumps(
            {
                "catalog_sha256": report["catalog_sha256"],
                "candidates": 4,
                "bibliographic_associations": 5,
                "repeat_identical": True,
                "publication_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
