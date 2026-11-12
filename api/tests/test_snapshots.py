"""Invented precomputed target artifacts; tests do not admit any scientific model."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from mycoradar.artifact_io import canonical
from mycoradar.snapshots import Conflict, Store


@pytest.fixture
def setup(tmp_path):
    data = canonical({"synthetic": True, "score": None})
    (tmp_path / "payload.json").write_bytes(data)
    entry = {
        "region_id": "synthetic-north",
        "taxon_id": "synthetic-taxon",
        "valid_at": "2000-01-01T00:00:00Z",
        "layer": "habitat",
        "model_version": "synthetic-model-v1",
        "input_versions": [{"source_id": "synthetic-source", "sha256": "a" * 64}],
        "sha256": hashlib.sha256(data).hexdigest(),
        "path": "payload.json",
    }
    batch = {"schema_version": "snapshot-batch-v1", "updates": [entry]}
    path = tmp_path / "batch.json"

    def write():
        path.write_bytes(canonical(batch))
        return path

    return Store(tmp_path / "store"), batch, write


def test_replay_is_identical_and_unchanged_snapshot_keeps_mtime(setup):
    store, _, write = setup
    path = write()
    first = store.publish(path, expected=None)
    pointer = store.root / "current.json"
    before = pointer.read_bytes(), pointer.stat().st_mtime_ns
    second = store.publish(path, expected=first["run_id"])
    assert second == {"run_id": first["run_id"], "changed_targets": 0, "created": False}
    assert (pointer.read_bytes(), pointer.stat().st_mtime_ns) == before
    snapshot = store.read()
    assert snapshot.publication_allowed is False and snapshot.computed_at is None
    assert snapshot.data_cutoff is None and snapshot.effective_resolution_m is None


def test_incremental_update_retains_unaffected_region_and_horizon(setup):
    store, batch, write = setup
    batch["updates"].append({**batch["updates"][0], "region_id": "synthetic-south"})
    old = store.publish(write(), expected=None)
    old_entries = store.read().entries
    batch["updates"] = [batch["updates"][0]]
    batch["updates"][0]["input_versions"][0]["sha256"] = "b" * 64
    new = store.publish(write(), expected=old["run_id"])
    assert new["changed_targets"] == 1 and len(store.read().entries) == 2
    for key, entry in old_entries.items():
        if entry.region_id == "synthetic-south":
            assert store.read().entries[key] == entry
    store.rollback(old["run_id"], expected=new["run_id"])
    assert store.head() == old["run_id"] and store.read().entries == old_entries


def test_stale_writer_cannot_overwrite_a_newer_head(setup):
    store, _, write = setup
    path = write()
    first = store.publish(path, expected=None)
    with pytest.raises(Conflict):
        store.publish(path, expected=None)
    assert store.head() == first["run_id"]


def test_two_independent_connections_have_only_one_initial_winner(setup):
    store, _, write = setup
    path = write()

    def publish():
        try:
            return Store(store.root).publish(path, expected=None)["run_id"]
        except Conflict:
            return None

    with ThreadPoolExecutor(2) as workers:
        runs = list(workers.map(lambda _: publish(), range(2)))
    assert sum(value is not None for value in runs) == 1
    assert store.head() in runs and store.read() is not None


def test_failure_before_head_swap_keeps_last_healthy_then_retries(setup, monkeypatch):
    store, batch, write = setup
    old = store.publish(write(), expected=None)
    batch["updates"][0]["model_version"] = "synthetic-model-v2"
    pointer = store.root / "current.json"
    before = pointer.read_bytes()
    original = store._point

    def fail(_run):
        raise OSError("Synthetic crash before atomic swap")

    monkeypatch.setattr(store, "_point", fail)
    with pytest.raises(OSError):
        store.publish(write(), expected=old["run_id"])
    assert pointer.read_bytes() == before and store.read() is not None
    monkeypatch.setattr(store, "_point", original)
    new = store.publish(write(), expected=old["run_id"])
    assert new["run_id"] != old["run_id"] and store.read() is not None


def test_changed_output_without_changed_model_or_inputs_is_refused(setup):
    store, batch, write = setup
    old = store.publish(write(), expected=None)
    raw = canonical({"synthetic": True, "different": True})
    (store.root.parent / "payload.json").write_bytes(raw)
    batch["updates"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="changed_payload_without_new_dependencies"):
        store.publish(write(), expected=old["run_id"])
    assert store.head() == old["run_id"] and store.read() is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid_at", 1000000000),
        ("valid_at", "2000-01-01"),
        ("valid_at", "2000-01-01T00:00:00"),
        ("valid_at", "2000-02-30T00:00:00Z"),
        ("path", "../outside.json"),
        ("sha256", "0" * 64),
    ],
)
def test_invalid_batch_never_creates_a_head(setup, field, value):
    store, batch, write = setup
    batch["updates"][0][field] = value
    with pytest.raises((ValueError, OSError)):
        store.publish(write(), expected=None)
    assert store.head() is None


def test_equivalent_timestamp_identity_and_duplicate_targets_are_checked(setup):
    store, batch, write = setup
    batch["updates"].append({**batch["updates"][0], "valid_at": "2000-01-01T01:00:00+01:00"})
    with pytest.raises(ValueError, match="duplicate_target"):
        store.publish(write(), expected=None)


def test_corrupt_rollback_target_is_never_made_current(setup):
    store, batch, write = setup
    old = store.publish(write(), expected=None)
    batch["updates"][0]["model_version"] = "synthetic-model-v2"
    new = store.publish(write(), expected=old["run_id"])
    (store.root / "runs" / f"{old['run_id']}.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot_checksum_mismatch"):
        store.rollback(old["run_id"], expected=new["run_id"])
    assert store.head() == new["run_id"] and store.read() is not None


def test_last_invalid_member_aborts_whole_batch(setup):
    store, batch, write = setup
    batch["updates"].append(
        {**batch["updates"][0], "region_id": "synthetic-south", "sha256": "0" * 64}
    )
    with pytest.raises(ValueError):
        store.publish(write(), expected=None)
    assert not store.root.exists()


def test_payload_and_manifest_budgets_are_enforced(setup):
    store, batch, write = setup
    (store.root.parent / "payload.json").write_bytes(b" " * 1048577)
    with pytest.raises(ValueError, match="input_budget_exceeded"):
        store.publish(write(), expected=None)
    path = write()
    path.write_bytes(b" " * 262145)
    with pytest.raises(ValueError, match="input_budget_exceeded"):
        store.publish(path, expected=None)


def test_rollback_fails_if_expected_head_is_stale(setup):
    store, _, write = setup
    old = store.publish(write(), expected=None)
    with pytest.raises(Conflict):
        store.rollback(old["run_id"], expected="0" * 64)


def plan_file(store, batch):
    path = store.root.parent / "plan.json"
    targets = [
        {k: v for k, v in row.items() if k not in {"path", "sha256"}} for row in batch["updates"]
    ]
    path.write_bytes(canonical({"schema_version": "recompute-plan-v1", "targets": targets}))
    return path


def test_recompute_calls_only_affected_target_then_no_callback_on_replay(setup):
    store, batch, write = setup
    batch["updates"].append({**batch["updates"][0], "region_id": "synthetic-south"})
    old = store.publish(write(), expected=None)
    original = store.read().entries
    batch["updates"][0] = {**batch["updates"][0], "model_version": "synthetic-v2"}
    calls = []

    def calculate(target):
        calls.append(target.region_id)
        return canonical({"synthetic": True, "score": None})

    plan = plan_file(store, batch)
    new = store.recompute(plan, calculate, expected=old["run_id"])
    assert calls == ["synthetic-north"] and new["calculated_targets"] == 1
    for key, entry in original.items():
        if entry.region_id == "synthetic-south":
            assert store.read().entries[key] == entry
    again = store.recompute(plan, lambda _: pytest.fail("unchanged target"), expected=new["run_id"])
    assert again["created"] is False and again["calculated_targets"] == 0


def test_calculation_runs_outside_lock_and_concurrent_commit_is_not_overwritten(setup):
    store, batch, write = setup
    old = store.publish(write(), expected=None)
    batch["updates"][0]["model_version"] = "planned-v2"
    plan = plan_file(store, batch)
    concurrent = []

    def calculate(_target):
        batch["updates"][0]["model_version"] = "concurrent-v3"
        concurrent.append(store.publish(write(), expected=old["run_id"])["run_id"])
        return canonical({"synthetic": True})

    with pytest.raises(Conflict):
        store.recompute(plan, calculate, expected=old["run_id"])
    assert store.head() == concurrent[0]


def test_late_calculation_failure_keeps_snapshot_and_earlier_outputs_private(setup):
    store, batch, write = setup
    old = store.publish(write(), expected=None)
    before = set((store.root / "objects").iterdir())
    batch["updates"] = [{**batch["updates"][0], "region_id": f"synthetic-{i}"} for i in range(2)]

    def calculate(target):
        if target.region_id.endswith("1"):
            raise RuntimeError("Synthetic model failure")
        return canonical({"synthetic": True, "changed": 1})

    with pytest.raises(RuntimeError):
        store.recompute(plan_file(store, batch), calculate, expected=old["run_id"])
    assert store.head() == old["run_id"] and set((store.root / "objects").iterdir()) == before


@pytest.mark.parametrize("output", [b"NaN", b"[]", b"{", "not bytes", b" " * 1048577])
def test_invalid_calculator_output_is_never_staged(setup, output):
    store, batch, _ = setup
    with pytest.raises(ValueError):
        store.recompute(plan_file(store, batch), lambda _: output, expected=None)
    assert store.head() is None


def test_callback_metadata_mutation_does_not_change_declared_versions(setup):
    store, batch, _ = setup

    def calculate(target):
        target.model_version = "mutated"
        target.input_versions[0].sha256 = "f" * 64
        return canonical({"synthetic": True})

    store.recompute(plan_file(store, batch), calculate, expected=None)
    entry = next(iter(store.read().entries.values()))
    assert entry.model_version == "synthetic-model-v1"
    assert entry.input_versions[0].sha256 == "a" * 64
