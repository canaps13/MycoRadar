"""Real local queue/runner I/O with invented JSON artifacts, never biological inputs."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest
from mycoradar.artifact_io import canonical, write_immutable
from mycoradar.queue_runner import Runner, serve


def publish(root, value):
    raw = canonical(value)
    digest = hashlib.sha256(raw).hexdigest()
    (root / "versions").mkdir(parents=True, exist_ok=True)
    (root / "versions" / f"{digest}.json").write_bytes(raw)
    (root / "current.json").write_bytes(canonical({"sha256": digest}))
    return digest


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    publish(root, {"synthetic": True, "value": 1})
    path = tmp_path / "runner.json"
    path.write_bytes(
        canonical(
            {
                "schema_version": "queue-runner-v1",
                "sources": [{"id": "synthetic", "root": "input", "pipeline_version": "test-v1"}],
            }
        )
    )
    return path, tmp_path / "state", root


def test_real_once_restart_hourly_and_changed_version(config, monkeypatch):
    path, state, root = config
    clock = [1000]
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Network forbidden"))
    runner = Runner(path, state, clock=lambda: clock[0])
    assert runner.tick()["jobs"]["done"] == 1
    receipt_path = next((state / "receipts").iterdir())
    before = receipt_path.read_bytes(), receipt_path.stat().st_mtime_ns
    runner = Runner(path, state, clock=lambda: clock[0])
    assert runner.tick()["polls"] == {"not_due": 1}
    clock[0] += 3600
    assert runner.tick()["polls"] == {"unchanged": 1}
    assert (receipt_path.read_bytes(), receipt_path.stat().st_mtime_ns) == before
    publish(root, {"synthetic": True, "value": 2})
    clock[0] += 3600
    assert runner.tick()["jobs"]["done"] == 2
    for receipt in (state / "receipts").iterdir():
        r = json.loads(receipt.read_bytes())
        assert r["publication_allowed"] is False and r["scientific_validation"] == "not_performed"
    assert "value" not in json.dumps(runner.tick())


def test_mutated_version_is_halted_instead_of_ingesting_current_pointer(config):
    path, state, root = config
    runner = Runner(path, state, clock=lambda: 1000)
    source, _ = runner.sources[0]
    runner.queue.poll(source.id, lambda: runner.probe(source))
    digest = runner.probe(source)
    (root / "versions" / f"{digest}.json").write_text('{"secret":"PRIVATE"}')
    result = runner.tick()
    assert result["runner_status"] == "degraded"
    assert result["jobs"]["dead"] == 1
    assert not (state / "receipts").exists()
    assert "PRIVATE" not in json.dumps(result)


def test_pending_jobs_keep_old_pipeline_configuration(config):
    path, state, root = config
    runner = Runner(path, state, clock=lambda: 1000)
    source, _ = runner.sources[0]
    runner.queue.poll(source.id, lambda: runner.probe(source))
    second = root.parent / "second"
    second.mkdir()
    publish(second, {"synthetic": True, "value": 2})
    cfg = json.loads(path.read_bytes())
    cfg["sources"][0]["root"] = "second"
    path.write_bytes(canonical(cfg))
    updated = Runner(path, state, clock=lambda: 4600)
    assert updated.tick()["jobs"]["done"] == 2
    assert len(list((state / "objects").iterdir())) == 2


def test_bounded_dispatch_drains_remaining_jobs(config):
    path, state, root = config
    clock = [1000]
    runner = Runner(path, state, clock=lambda: clock[0])
    source, _ = runner.sources[0]
    runner.queue.poll(source.id, lambda: runner.probe(source))
    publish(root, {"synthetic": True, "value": 2})
    clock[0] += 3600
    assert runner.tick(1)["jobs"] == {"done": 1, "queued": 1, "running": 0, "dead": 0}
    assert runner.tick(1)["jobs"]["done"] == 2


def test_transient_missing_pointer_does_not_claim_scientific_freshness(config):
    path, state, root = config
    (root / "current.json").unlink()
    result = Runner(path, state).tick()
    assert result["runner_status"] == "degraded" and result["polls"] == {"retry": 1}
    assert result["scientific_validation"] == "not_performed"


@pytest.mark.parametrize("raw", [b'{"sha256":"invalid"}', b'{"sha256":1,"sha256":2}', b"NaN"])
def test_bad_pointer_is_not_accepted(config, raw):
    path, state, root = config
    (root / "current.json").write_bytes(raw)
    result = Runner(path, state).tick()
    assert result["polls"] == {"halted": 1}
    assert not (state / "objects").exists()


def test_resolved_path_escape_is_refused(config, tmp_path, monkeypatch):
    path, state, root = config
    outside = tmp_path / "outside"
    outside.mkdir()
    digest = json.loads((root / "current.json").read_bytes())["sha256"]
    target = root / "versions" / f"{digest}.json"
    original = Path.resolve

    # Model a resolved directory link leaving the source tree on all supported OSes.
    def resolve(path, *args, **kwargs):
        return outside / "payload.json" if path == target else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    result = Runner(path, state).tick()
    assert result["jobs"]["dead"] == 1


def test_invalid_configuration_does_not_create_state(config):
    path, state, _ = config
    cfg = json.loads(path.read_bytes())
    cfg["sources"].append(cfg["sources"][0])
    path.write_bytes(canonical(cfg))
    with pytest.raises(ValueError):
        Runner(path, state)
    assert not state.exists()


def test_private_immutable_write_conflict_and_retry(tmp_path):
    path = tmp_path / "object.json"
    assert write_immutable(path, b"{}")
    mtime = path.stat().st_mtime_ns
    assert not write_immutable(path, b"{}") and path.stat().st_mtime_ns == mtime
    with pytest.raises(ValueError):
        write_immutable(path, b'{"different":1}')
    assert list(tmp_path.iterdir()) == [path]


def test_service_runs_only_until_explicit_stop(config, capsys):
    path, state, _ = config
    runner = Runner(path, state)
    stop = Event()
    tick = runner.tick

    def once(max_jobs):
        result = tick(max_jobs)
        stop.set()
        return result

    runner.tick = once
    serve(runner, stop, 5, 1)
    assert json.loads(capsys.readouterr().out)["jobs"]["done"] == 1


def test_real_cli_uses_production_entrypoint_and_sanitizes_invalid_args(config):
    path, state, _ = config
    command = [sys.executable, "-m", "mycoradar.queue_runner"]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    good = subprocess.run(
        command + ["--config", str(path), "--state", str(state), "--once"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert good.returncode == 0 and json.loads(good.stdout)["jobs"]["done"] == 1
    bad = subprocess.run(command + ["--PRIVATE-ARGUMENT"], capture_output=True, text=True, env=env)
    assert bad.returncode == 2 and bad.stderr == ""
    assert "PRIVATE-ARGUMENT" not in bad.stdout
