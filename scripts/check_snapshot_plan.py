"""Exercise dependency planning and atomic staging with a synthetic calculator."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mycoradar.artifact_io import canonical
from mycoradar.snapshots import Store, Target


def main() -> None:
    with TemporaryDirectory(prefix="mycoradar-plan-smoke-") as folder:
        root = Path(folder)
        target = {
            "region_id": "synthetic-north",
            "taxon_id": "synthetic-taxon",
            "valid_at": "2000-01-01T00:00:00Z",
            "layer": "habitat",
            "model_version": "synthetic-model-v1",
            "input_versions": [{"source_id": "synthetic-source", "sha256": "a" * 64}],
        }
        plan = {
            "schema_version": "recompute-plan-v1",
            "targets": [target, {**target, "region_id": "synthetic-south"}],
        }
        path = root / "plan.json"
        path.write_bytes(canonical(plan))
        store = Store(root / "store")
        calls: list[str] = []

        def calculate(value: Target) -> bytes:
            calls.append(value.region_id)
            return canonical({"synthetic": True, "habitat_score": None, "fruiting_score": None})

        first = store.recompute(path, calculate, expected=None)
        assert first["calculated_targets"] == 2
        second = store.recompute(path, calculate, expected=str(first["run_id"]))
        assert second["calculated_targets"] == 0 and len(calls) == 2
        target["model_version"] = "synthetic-model-v2"
        path.write_bytes(canonical(plan))
        third = store.recompute(path, calculate, expected=str(second["run_id"]))
        assert third["calculated_targets"] == 1 and calls == [
            "synthetic-north",
            "synthetic-south",
            "synthetic-north",
        ]
        print(
            json.dumps(
                {
                    "scope": "synthetic_recompute_smoke",
                    "initial_calculations": 2,
                    "replay_calculations": 0,
                    "changed_calculations": 1,
                    "publication_allowed": False,
                    "scientific_validation": "not_performed",
                }
            )
        )


if __name__ == "__main__":
    main()
