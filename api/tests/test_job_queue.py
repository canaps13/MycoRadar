"""Synthetic providers and real isolated SQLite files; no scheduled source enabled."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from mycoradar.job_queue import JobQueue, QueueError, RetryLater

A, B = "a" * 64, "b" * 64


@pytest.fixture
def setup(tmp_path):
    clock = [1000]
    path = tmp_path / "queue.sqlite"
    queue = JobQueue(path, clock=lambda: clock[0])
    queue.register("synthetic", "etl-v1")
    return queue, clock, path


def fail(delay=0):
    raise RetryLater(delay)


def test_hourly_poll_new_unchanged_and_restart_never_duplicate_job(setup):
    q, clock, path = setup
    assert q.poll("synthetic", lambda: A) == "queued"
    assert q.poll("synthetic", lambda: pytest.fail("not due")) == "not_due"
    clock[0] += 3600
    restarted = JobQueue(path, clock=lambda: clock[0])
    assert restarted.poll("synthetic", lambda: None) == "unchanged"
    assert restarted.counts() == {"queued": 1, "running": 0, "done": 0, "dead": 0}
    job = restarted.claim()
    assert restarted.finish(job)
    clock[0] += 3600
    assert q.poll("synthetic", lambda: A) == "unchanged"
    assert q.claim() is None and q.counts()["done"] == 1


def test_changed_source_and_changed_pipeline_have_distinct_keys(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    clock[0] += 3600
    q.poll("synthetic", lambda: B)
    q.register("synthetic", "etl-v2")
    assert q.poll("synthetic", lambda: None) == "not_due"
    clock[0] += 3600
    assert q.poll("synthetic", lambda: None) == "queued"
    assert q.counts()["queued"] == 3


def test_429_cooldown_applies_to_source_poll_and_existing_jobs(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    clock[0] += 3600
    assert q.poll("synthetic", lambda: fail(7200)) == "retry"
    q.register("synthetic", "etl-v2")
    assert q.claim() is None
    assert q.poll("synthetic", lambda: pytest.fail("cooldown")) == "not_due"
    q.register("independent-provider", "etl-v1")
    assert q.poll("independent-provider", lambda: A) == "queued"
    assert q.claim().source_id == "independent-provider"
    clock[0] += 7200
    assert q.poll("synthetic", lambda: B) == "queued"


def test_timeout_and_later_recovery(setup):
    q, clock, _ = setup

    def timeout():
        raise TimeoutError("PRIVATE URL")

    assert q.poll("synthetic", timeout) == "retry"
    clock[0] += 59
    assert q.poll("synthetic", lambda: A) == "not_due"
    clock[0] += 1
    assert q.poll("synthetic", lambda: A) == "queued"


def test_concurrent_poll_is_coalesced_without_holding_network_transaction(setup):
    q, _, path = setup
    entered, release = Event(), Event()

    def probe():
        entered.set()
        assert release.wait(3)
        return A

    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(q.poll, "synthetic", probe)
        assert entered.wait(3)
        try:
            other = JobQueue(path, clock=lambda: 1000)
            other.register("synthetic", "etl-v1")
            assert other.poll("synthetic", lambda: pytest.fail("duplicate probe")) == "not_due"
        finally:
            release.set()
        assert first.result() == "queued"


def test_expired_poll_cannot_override_newer_probe(setup):
    q, clock, path = setup

    def slow():
        clock[0] += 300
        other = JobQueue(path, clock=lambda: clock[0])
        assert other.poll("synthetic", lambda: B) == "queued"
        return A

    assert q.poll("synthetic", slow) == "stale"
    assert q.claim().source_version == B


def test_concurrent_claims_use_separate_connections_and_single_winner(setup):
    q, clock, path = setup
    q.poll("synthetic", lambda: A)

    def claim():
        return JobQueue(path, clock=lambda: clock[0]).claim()

    with ThreadPoolExecutor(2) as workers:
        jobs = list(workers.map(lambda _: claim(), range(2)))
    assert sum(job is not None for job in jobs) == 1


def test_lease_recovery_fences_old_worker_and_duplicate_ack(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    old = q.claim()
    clock[0] += 300
    assert not q.finish(old) and not q.renew(old)
    new = q.claim()
    assert new.id == old.id and new.token != old.token and new.attempt == 2
    assert not q.finish(old)
    assert not q.finish(replace(new, token="forged"))
    assert q.finish(new) and not q.finish(new)


def test_heartbeat_preserves_live_claim(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    job = q.claim()
    clock[0] += 299
    assert q.renew(job)
    clock[0] += 2
    assert q.claim() is None and q.finish(job)


def test_retry_budget_and_backoff_end_in_dead_letter(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    assert q.run_one(lambda _: fail()) == "retry"
    assert q.run_one(lambda _: pytest.fail("not due")) == "idle"
    clock[0] += 60
    assert q.run_one(lambda _: fail()) == "retry"
    clock[0] += 120
    assert q.run_one(lambda _: fail()) == "dead"
    assert q.claim() is None and q.counts()["dead"] == 1


def test_crashed_last_attempt_is_dead_lettered(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    for _ in range(3):
        assert q.claim() is not None
        clock[0] += 300
    assert q.claim() is None and q.counts()["dead"] == 1


def test_replayed_handler_uses_same_key_to_avoid_double_ingestion(setup, tmp_path):
    q, clock, _ = setup
    destination = tmp_path / "synthetic-destination.sqlite"
    with sqlite3.connect(destination) as db:
        db.execute("CREATE TABLE committed(job_id TEXT PRIMARY KEY)")
    seen = []

    def ingest(job):
        seen.append(job.id)
        with sqlite3.connect(destination) as db:
            db.execute("INSERT OR IGNORE INTO committed VALUES(?)", (job.id,))
        if len(seen) == 1:
            raise OSError("Simulated connection loss after commit")

    q.poll("synthetic", lambda: A)
    assert q.run_one(ingest) == "retry"
    clock[0] += 60
    assert q.run_one(ingest) == "done"
    assert len(seen) == 2 and seen[0] == seen[1]
    with sqlite3.connect(destination) as db:
        assert db.execute("SELECT COUNT(*) FROM committed").fetchone()[0] == 1


def test_capacity_preserves_old_key_and_unrecorded_version_can_be_retried(tmp_path):
    clock = [0]
    q = JobQueue(tmp_path / "bounded.sqlite", clock=lambda: clock[0], max_jobs=1)
    q.register("synthetic", "etl-v1")
    q.poll("synthetic", lambda: A)
    clock[0] += 3600
    with pytest.raises(QueueError, match="queue_capacity_reached"):
        q.poll("synthetic", lambda: B)
    assert q.counts()["queued"] == 1
    clock[0] += 300
    assert q.poll("synthetic", lambda: A) == "unchanged"


def test_clock_rollback_and_configuration_conflict_do_not_reset_queue(setup):
    q, clock, path = setup
    q.poll("synthetic", lambda: A)
    clock[0] -= 1
    with pytest.raises(QueueError, match="clock_regression"):
        q.claim()
    clock[0] += 1
    with pytest.raises(QueueError, match="queue_config_conflict"):
        JobQueue(path, clock=lambda: clock[0], max_attempts=1)
    assert q.counts()["queued"] == 1


@pytest.mark.parametrize("value", [-1, True, 604801, 1.5])
def test_invalid_retry_after_is_never_shortened(value):
    with pytest.raises(QueueError, match="invalid_retry_delay"):
        RetryLater(value)


def test_non_queue_database_is_not_modified(tmp_path):
    path = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
    before = path.read_bytes()
    with pytest.raises(QueueError, match="unrecognized_queue_database"):
        JobQueue(path)
    assert path.read_bytes() == before


def test_unverified_or_invalid_versions_cannot_enqueue(setup):
    q, clock, path = setup
    assert q.poll("synthetic", lambda: None) == "retry"
    clock[0] += 60
    assert q.poll("synthetic", lambda: "PRIVATE upstream response") == "retry"
    assert q.counts()["queued"] == 0
    assert b"PRIVATE" not in path.read_bytes()


def test_invalid_provider_delay_halts_instead_of_retrying_too_early(setup):
    q, clock, _ = setup
    assert q.poll("synthetic", lambda: fail(604801)) == "halted"
    clock[0] += 3600
    assert (
        q.poll("synthetic", lambda: pytest.fail("invalid cooldown must not be shortened"))
        == "halted"
    )
    q.resume("synthetic")
    assert q.poll("synthetic", lambda: A) == "queued"
    assert q.run_one(lambda _: fail(604801)) == "halted"
    assert q.counts()["dead"] == 1


def test_manual_resume_does_not_clear_a_valid_provider_cooldown(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: fail(7200))
    clock[0] += 3600
    q.resume("synthetic")
    assert q.poll("synthetic", lambda: pytest.fail("cooldown")) == "not_due"


def test_timeout_backoff_blocks_other_jobs_for_same_provider(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    clock[0] += 3600
    q.poll("synthetic", lambda: B)
    assert q.run_one(lambda _: fail()) == "retry"
    assert q.claim() is None
    clock[0] += 60
    assert q.claim() is not None


def test_expired_handler_cannot_acknowledge_completed_external_work(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    assert q.run_one(lambda _: clock.__setitem__(0, clock[0] + 300)) == "stale"
    assert q.claim().attempt == 2


def test_pipeline_change_during_live_poll_is_refused(setup):
    q, _, _ = setup

    def probe():
        with pytest.raises(QueueError, match="poll_in_progress"):
            q.register("synthetic", "etl-v2")
        return A

    assert q.poll("synthetic", probe) == "queued"
    assert q.claim().pipeline_version == "etl-v1"


@pytest.mark.parametrize("kwargs", [{"lease_s": 0}, {"max_attempts": 0}, {"max_jobs": 10001}])
def test_invalid_queue_limits_are_rejected(tmp_path, kwargs):
    with pytest.raises(QueueError, match="invalid_queue_config"):
        JobQueue(tmp_path / "queue.sqlite", **kwargs)


def test_unknown_schema_is_not_implicitly_migrated(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(QueueError, match="unsupported_queue_schema"):
        JobQueue(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_source_budget_is_explicit_and_unknown_source_not_polled(setup):
    q, _, _ = setup
    with pytest.raises(QueueError, match="unknown_source"):
        q.poll("missing", lambda: pytest.fail("not registered"))
    for i in range(99):
        q.register(f"synthetic-{i}", "etl-v1")
    with pytest.raises(QueueError, match="source_capacity_reached"):
        q.register("overflow", "etl-v1")


def test_stale_poll_still_applies_provider_cooldown_without_replacing_new_version(setup):
    q, clock, _ = setup

    def slow():
        clock[0] += 300
        assert q.poll("synthetic", lambda: B) == "queued"
        raise RetryLater(7200)

    assert q.poll("synthetic", slow) == "stale"
    assert q.claim() is None
    clock[0] += 7200
    assert q.claim().source_version == B


def test_stale_job_failure_does_not_erase_provider_cooldown(setup):
    q, clock, _ = setup
    q.poll("synthetic", lambda: A)
    old = q.claim()
    clock[0] += 300
    new = q.claim()
    assert not q.finish(old, retry_after_s=7200)
    assert q.finish(new)
    clock[0] += 3600
    assert q.poll("synthetic", lambda: pytest.fail("late 429 still applies")) == "not_due"
