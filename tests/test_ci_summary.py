"""A missing, skipped or tolerated failure must never be reported as success."""

from scripts.ci_summary import render_summary


def test_summary_preserves_actual_outcomes() -> None:
    result = render_summary(
        {
            "lint": {"outcome": "success"},
            "types": {"outcome": "failure", "conclusion": "success"},
            "build": {"outcome": "skipped"},
            "browser": {"outcome": "cancelled"},
            "unknown": {"outcome": "unexpected"},
        },
        ["lint", "types", "build", "browser", "missing", "unknown"],
    )
    assert "| `lint` | Réussi |" in result
    assert "| `types` | Échoué |" in result
    assert "| `build` | Non exécuté (skipped) |" in result
    assert "| `browser` | Annulé |" in result
    assert "| `missing` | Non exécuté (résultat absent ou inconnu) |" in result
    assert "| `unknown` | Non exécuté (résultat absent ou inconnu) |" in result
    assert result.count("Réussi") == 1
