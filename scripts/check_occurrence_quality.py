"""Run the invented quality fixture twice through the real CLI; never use private inputs here."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/quality/synthetic/batch.json"))
    path = parser.parse_args().input
    command = [sys.executable, "-m", "mycoradar.occurrence_quality", "--input", str(path)]
    first = subprocess.run(command, capture_output=True, timeout=30, check=False)
    second = subprocess.run(command, capture_output=True, timeout=30, check=False)
    if (
        first.returncode
        or second.returncode
        or first.stderr
        or second.stderr
        or first.stdout != second.stdout
    ):
        raise RuntimeError("Synthetic quality replay failed")
    report = json.loads(first.stdout)
    expected = {
        "capture_kind": "synthetic",
        "report_visibility": "private",
        "input_rows": 7,
        "representative_rows_for_audit_only": 3,
        "identical_duplicate_rows": 1,
        "conflicting_identity_groups": 1,
        "invalid_rows": 1,
        "rejected_identity_rows": 3,
        "coincident_event_candidate_groups": 1,
        "coincident_event_candidate_rows": 2,
        "coincident_events_automatically_merged": False,
        "records_emitted": 0,
        "publication_allowed": False,
        "scientific_admission": "not_performed",
        "sampling_effort": "unknown",
        "absence_evidence": "unavailable",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Synthetic quality audit changed unexpectedly")
    print(
        json.dumps(
            {
                "event": "synthetic_occurrence_quality_smoke",
                "status": "ok",
                "deterministic_cli": True,
                "input_rows": report["input_rows"],
                "conflicts_quarantined": True,
                "records_emitted": 0,
                "publication_allowed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
