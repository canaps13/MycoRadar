"""Image smoke must reject successful but changed or disclosing CLI responses."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mycoradar.main import app

from scripts import check_gbif_replay as smoke

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/gbif/offline-synthetic/snapshot.json"


def test_real_cli_does_not_admit_synthetic_data_to_the_explorer(monkeypatch, capsys):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "api/src"))
    with TestClient(app) as client:
        before = client.get("/v1/exploration?valid_at=2026-01-04").json()
        smoke.check_replay(SNAPSHOT)
        response = client.get("/v1/exploration?valid_at=2026-01-04")
        assert response.status_code == 200
        assert response.json() == before
        assert before["species"] == []
        assert before["habitat"]["score"] is before["fruiting"]["score"] is None
    assert "PRIVATE_" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure",
    ["release", "extra_coordinate", "fake_freshness", "stderr", "exit_code", "repeat", "catalogue"],
)
def test_smoke_rejects_changed_success_or_failed_child(monkeypatch, failure):
    payload = json.loads((ROOT / "docs/evidence/MR-010-offline-sample.json").read_bytes())["result"]
    changed = copy.deepcopy(payload)
    if failure == "release":
        changed["admission"]["accepted"] = 1
    elif failure == "extra_coordinate":
        changed["coordinates"] = "PRIVATE_SENTINEL"
    elif failure == "fake_freshness":
        changed["receipt"]["fetched_at"] = "2026-11-10T00:00:00Z"
    stdout = json.dumps(changed).encode()
    runs = iter(
        [
            subprocess.CompletedProcess(
                [],
                2 if failure == "exit_code" else 0,
                stdout,
                b"PRIVATE_SENTINEL" if failure == "stderr" else b"",
            ),
            subprocess.CompletedProcess(
                [], 0, stdout + (b" " if failure == "repeat" else b""), b""
            ),
        ]
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *a, **kw: next(runs))
    monkeypatch.setattr(smoke, "check_bundle", lambda: None)
    if failure == "catalogue":
        publications = iter([(b"original",), (b"changed",)])
        monkeypatch.setattr(smoke, "publication_bytes", lambda: next(publications))
    with pytest.raises(RuntimeError):
        smoke.check_replay(SNAPSHOT)


def test_smoke_failure_does_not_print_child_payload_or_input_path(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["smoke", "--snapshot", "PRIVATE_PATH"])

    def fail(path):
        raise RuntimeError("PRIVATE_PAYLOAD")

    monkeypatch.setattr(smoke, "check_replay", fail)
    assert smoke.main() == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == "GBIF synthetic replay verification failed.\n"
