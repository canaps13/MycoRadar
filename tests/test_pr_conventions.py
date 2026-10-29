import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.check_pr import PullRequest, read_pull_request, validate_pull_request

ROADMAP = "| MR-002 | IN_PROGRESS | Conventions | Preuves |"
BODY = """## Objectif
Conventions MR-002.
## Validation
Tests exécutés.
## Risques et retour arrière
Revert de la PR.
"""
VALID_PR = PullRequest("MR-002 : conventions", "feat/MR-002-project-conventions", "main", BODY)


@pytest.mark.parametrize("status", ["IN_PROGRESS", "DONE"])
def test_valid_pull_request(status: str) -> None:
    assert validate_pull_request(VALID_PR, ROADMAP.replace("IN_PROGRESS", status)) == []


def test_windows_line_endings_are_supported() -> None:
    assert validate_pull_request(replace(VALID_PR, body=BODY.replace("\n", "\r\n")), ROADMAP) == []


@pytest.mark.parametrize(
    "change",
    [
        {"branch": "main"},
        {"branch": "feat/MR-002-Invalid_Name"},
        {"title": "Missing task"},
        {"title": "MR-002 :\nmultiline title"},
        {"title": "MR-003 : other task"},
        {"base": "other"},
        {"body": ""},
        {"body": BODY.replace("Tests exécutés.", "<!-- à compléter -->")},
        {"body": BODY.replace("## Objectif", "## Autre")},
    ],
)
def test_invalid_metadata_is_rejected(change: dict[str, str]) -> None:
    assert validate_pull_request(replace(VALID_PR, **change), ROADMAP)


@pytest.mark.parametrize(
    "roadmap", ["MR-002 only mentioned in text", "| MR-002 | TODO |", "| MR-002 | BLOCKED |"]
)
def test_task_must_be_registered_and_started(roadmap: str) -> None:
    assert validate_pull_request(VALID_PR, roadmap)


def test_an_unfilled_template_is_rejected() -> None:
    template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
    assert len(validate_pull_request(replace(VALID_PR, body=template), ROADMAP)) == 3


def test_shell_syntax_is_only_text(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    title = f'MR-002 : $(touch {marker}) "; exit 0; #'
    event = {
        "pull_request": {
            "title": title,
            "head": {"ref": VALID_PR.branch},
            "base": {"ref": "main"},
            "body": BODY,
        }
    }
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event), encoding="utf-8")
    pr = read_pull_request(event_file)
    assert pr.title == title
    assert validate_pull_request(pr, ROADMAP) == []
    assert not marker.exists()


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"pull_request": None},
        {"pull_request": {"title": 42, "head": {"ref": "x"}, "base": {"ref": "main"}}},
    ],
)
def test_incomplete_events_fail_explicitly(tmp_path: Path, event: object) -> None:
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(ValueError):
        read_pull_request(event_file)
