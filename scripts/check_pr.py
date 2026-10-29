"""Validate PR metadata as data; never execute a title, branch name, or body."""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_SECTIONS = ("Objectif", "Validation", "Risques et retour arrière")


@dataclass(frozen=True)
class PullRequest:
    title: str
    branch: str
    base: str
    body: str


def validate_pull_request(pr: PullRequest, roadmap: str) -> list[str]:
    errors = []
    branch = re.fullmatch(r"feat/(MR-\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*", pr.branch)
    title = re.fullmatch(r"(MR-\d{3})[ \t]*:[ \t]*\S[^\r\n]*", pr.title)
    if branch is None:
        errors.append("Branche attendue : feat/MR-XXX-description (minuscules et tirets).")
    if title is None:
        errors.append("Titre attendu : MR-XXX : description.")
    if pr.base != "main":
        errors.append("La PR doit cibler main.")
    if branch and title and branch[1] != title[1]:
        errors.append("Le titre et la branche doivent désigner la même tâche.")
    if branch:
        task = re.search(rf"^\|\s*{re.escape(branch[1])}\s*\|\s*(\w+)\s*\|", roadmap, re.MULTILINE)
        if task is None:
            errors.append("La tâche de la branche doit figurer dans la table de la roadmap.")
        elif task[1] not in {"IN_PROGRESS", "DONE"}:
            errors.append("La tâche doit être IN_PROGRESS ou DONE selon les preuves disponibles.")

    body = re.sub(r"<!--.*?-->", "", pr.body.replace("\r\n", "\n"), flags=re.DOTALL)
    headings = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", body, re.MULTILINE))
    sections = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        sections[heading[1]] = body[heading.end() : end].strip()
    for name in REQUIRED_SECTIONS:
        if not sections.get(name):
            errors.append(f"Rubrique obligatoire à renseigner : {name}.")
    return errors


def read_pull_request(event_file: Path) -> PullRequest:
    event = json.loads(event_file.read_text(encoding="utf-8-sig"))
    try:
        pr = event["pull_request"]
        values = [pr["title"], pr["head"]["ref"], pr["base"]["ref"], pr.get("body") or ""]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Événement GitHub pull_request incomplet.") from exc
    if not all(isinstance(value, str) for value in values):
        raise ValueError("Les métadonnées de la PR doivent être des chaînes de caractères.")
    return PullRequest(*values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-file", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    args = parser.parse_args()
    if args.event_file is None:
        parser.error("Indiquer --event-file ou GITHUB_EVENT_PATH.")
    try:
        pr = read_pull_request(args.event_file)
        roadmap = (Path(__file__).resolve().parents[1] / "ROADMAP.md").read_text(encoding="utf-8")
        errors = validate_pull_request(pr, roadmap)
    except (OSError, ValueError) as exc:
        print(f"Contrôle impossible : {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Conventions PR valides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
