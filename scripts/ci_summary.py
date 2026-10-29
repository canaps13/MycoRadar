"""Report actual Actions step outcomes, including checks that did not run."""

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

LABELS = {
    "success": "Réussi",
    "failure": "Échoué",
    "skipped": "Non exécuté (skipped)",
    "cancelled": "Annulé",
}


def render_summary(steps: Mapping[str, object], checks: Sequence[str]) -> str:
    rows = ["## Validation", "", "| Contrôle | Résultat |", "|---|---|"]
    for check in checks:
        step = steps.get(check)
        outcome = step.get("outcome") if isinstance(step, dict) else None
        # Never infer success from a missing result or a continue-on-error conclusion.
        label = LABELS.get(str(outcome), "Non exécuté (résultat absent ou inconnu)")
        rows.append(f"| `{check}` | {label} |")
    return "\n".join(rows) + "\n"


def main() -> None:
    steps = json.loads(os.environ["CI_STEPS_JSON"])
    if not isinstance(steps, dict):
        raise ValueError("CI_STEPS_JSON must be an object")
    summary = render_summary(steps, sys.argv[1:])
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
        output.write(summary)


if __name__ == "__main__":
    main()
