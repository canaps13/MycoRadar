"""Exercise aggregate-only protocol audits in separate processes, offline."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    def run(name: str, expected: int) -> str:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mycoradar.evaluation_protocol",
                "--manifest",
                str(args.input / name),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected and result.stderr == ""
        return result.stdout

    positive = run("synthetic.json", 0)
    assert positive == run("synthetic.json", 0)
    valid = json.loads(positive)
    assert valid["structural_status"] == "passed" and valid["input_kind"] == "synthetic"
    assert not valid["publication_allowed"] and not valid["model_training_authorized"]
    invalid = json.loads(run("synthetic-leakage.json", 2))
    assert {"dependency_group_crosses_partitions", "feature_information_leakage"} <= set(
        invalid["blockers"]
    )
    draft = json.loads(run("pilot-plan.json", 2))
    assert draft["structural_status"] == "blocked"
    assert {
        "protocol_not_frozen",
        "decision_thresholds_unjustified",
        "spatial_design_unjustified",
        "admission_or_design_evidence_missing",
    } <= set(draft["blockers"])
    print(
        json.dumps(
            {
                "synthetic_structure": "passed",
                "leakage_case": "blocked",
                "pilot_plan": "blocked",
                "repeat_identical": True,
                "publication_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
