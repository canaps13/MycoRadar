"""Local durable polling/queue primitives, called only by an explicit job runner."""

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,79}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class QueueError(ValueError):
    """No provider body, query, credential or exception is persisted."""


class InvalidRetryDelay(QueueError):
    pass


class RetryLater(Exception):
    def __init__(self, retry_after_s: int = 0):
        if type(retry_after_s) is not int or not 0 <= retry_after_s <= 604800:
            raise InvalidRetryDelay("invalid_retry_delay")
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class Job:
    id: str
    source_id: str
    pipeline_version: str
    source_version: str
    attempt: int
    token: str


class JobQueue:
    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], int] = lambda: int(time.time()),
        lease_s: int = 300,
        max_attempts: int = 3,
        max_jobs: int = 10000,
    ):
        if (
            type(lease_s) is not int
            or not 1 <= lease_s <= 3600
            or type(max_attempts) is not int
            or not 1 <= max_attempts <= 10
            or type(max_jobs) is not int
            or not 1 <= max_jobs <= 10000
        ):
            raise QueueError("invalid_queue_config")
        self.database, self.clock = database, clock
        self.lease_s, self.max_attempts, self.max_jobs = lease_s, max_attempts, max_jobs
        with self._transaction() as db:
            revision = db.execute("PRAGMA user_version").fetchone()[0]
            if revision == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise QueueError("unrecognized_queue_database")
                db.execute("""CREATE TABLE sources (
                    id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, interval_s INTEGER NOT NULL,
                    next_poll INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0,
                    last_checked INTEGER, version TEXT, failures INTEGER NOT NULL DEFAULT 0,
                    token TEXT, lease_until INTEGER, halted INTEGER NOT NULL DEFAULT 0)""")
                db.execute("""CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(id),
                    pipeline TEXT NOT NULL, version TEXT NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, available INTEGER NOT NULL,
                    token TEXT, lease_until INTEGER)""")
                db.execute("CREATE INDEX jobs_ready ON jobs(state, available, lease_until)")
                db.execute(
                    "CREATE TABLE settings(configuration TEXT NOT NULL,last_clock INTEGER NOT NULL)"
                )
                db.execute(
                    "INSERT INTO settings VALUES(?,0)",
                    (json.dumps([lease_s, max_attempts, max_jobs]),),
                )
                db.execute("PRAGMA user_version=1")
            elif revision != 1:
                raise QueueError("unsupported_queue_schema")
            if db.execute("SELECT configuration FROM settings").fetchone()[0] != json.dumps(
                [lease_s, max_attempts, max_jobs]
            ):
                raise QueueError("queue_config_conflict")
            self._tick(db)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _now(self) -> int:
        value = self.clock()
        if type(value) is not int or not 0 <= value <= 2**53:
            raise QueueError("invalid_clock")
        return value

    def _tick(self, db: sqlite3.Connection) -> int:
        now = self._now()
        if now < db.execute("SELECT last_clock FROM settings").fetchone()[0]:
            raise QueueError("clock_regression")
        db.execute("UPDATE settings SET last_clock=?", (now,))
        return now

    def register(self, source: str, pipeline: str, *, interval_s: int = 3600) -> None:
        if (
            not IDENTIFIER.fullmatch(source)
            or not IDENTIFIER.fullmatch(pipeline)
            or type(interval_s) is not int
            or not 3600 <= interval_s <= 604800
        ):
            raise QueueError("invalid_source_config")
        with self._transaction() as db:
            now = self._tick(db)
            old = db.execute("SELECT * FROM sources WHERE id=?", (source,)).fetchone()
            if old is None:
                if db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] >= 100:
                    raise QueueError("source_capacity_reached")
                db.execute(
                    "INSERT INTO sources(id,pipeline,interval_s,next_poll) VALUES(?,?,?,?)",
                    (source, pipeline, interval_s, now),
                )
            elif old["pipeline"] == pipeline and old["interval_s"] == interval_s:
                return
            elif old["token"] is not None and old["lease_until"] > now:
                raise QueueError("poll_in_progress")
            else:
                # Changing a pipeline does not bypass an existing provider cooldown.
                db.execute(
                    "UPDATE sources SET pipeline=?,interval_s=? WHERE id=?",
                    (pipeline, interval_s, source),
                )

    def poll(self, source: str, probe: Callable[[], str | None]) -> str:
        token = uuid4().hex
        with self._transaction() as db:
            now = self._tick(db)
            row = db.execute("SELECT * FROM sources WHERE id=?", (source,)).fetchone()
            if row is None:
                raise QueueError("unknown_source")
            if row["halted"]:
                return "halted"
            if max(row["next_poll"], row["blocked_until"]) > now or (
                row["token"] is not None and row["lease_until"] > now
            ):
                return "not_due"
            db.execute(
                "UPDATE sources SET token=?,lease_until=? WHERE id=?",
                (token, now + self.lease_s, source),
            )
        try:
            version = probe()
            if version is not None and (
                not isinstance(version, str) or not DIGEST.fullmatch(version)
            ):
                raise QueueError("invalid_source_version")
            if version is None:
                version = row["version"]
            if version is None:
                raise QueueError("unchanged_without_version")
        except InvalidRetryDelay:
            return self._finish_poll(source, token, None, -1)
        except (RetryLater, TimeoutError, OSError, QueueError) as error:
            delay = error.retry_after_s if isinstance(error, RetryLater) else 0
            return self._finish_poll(source, token, None, delay)
        return self._finish_poll(source, token, version, None)

    def _finish_poll(self, source: str, token: str, version: str | None, delay: int | None) -> str:
        with self._transaction() as db:
            now = self._tick(db)
            row = db.execute("SELECT * FROM sources WHERE id=?", (source,)).fetchone()
            assert row is not None
            if row["token"] != token or row["lease_until"] <= now:
                # An old result cannot publish a version, but a provider cooldown still applies.
                if delay == -1:
                    db.execute("UPDATE sources SET halted=1 WHERE id=?", (source,))
                elif delay:
                    db.execute(
                        "UPDATE sources SET blocked_until=MAX(blocked_until,?) WHERE id=?",
                        (now + delay, source),
                    )
                return "stale"
            if delay == -1:
                db.execute(
                    "UPDATE sources SET halted=1,token=NULL,lease_until=NULL WHERE id=?", (source,)
                )
                return "halted"
            if delay is not None:
                failures = min(row["failures"] + 1, 10)
                wait = max(delay, min(60 * 2 ** (failures - 1), 3600))
                db.execute(
                    """UPDATE sources SET token=NULL,lease_until=NULL,failures=?,
                           next_poll=?,blocked_until=MAX(blocked_until,?) WHERE id=?""",
                    (failures, now + wait, now + wait, source),
                )
                return "retry"
            key = hashlib.sha256(
                json.dumps([source, row["pipeline"], version]).encode()
            ).hexdigest()
            exists = db.execute("SELECT 1 FROM jobs WHERE id=?", (key,)).fetchone() is not None
            if not exists:
                if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= self.max_jobs:
                    raise QueueError("queue_capacity_reached")
                db.execute(
                    "INSERT INTO jobs(id,source,pipeline,version,state,available) "
                    "VALUES(?,?,?,?,?,?)",
                    (key, source, row["pipeline"], version, "queued", now),
                )
            db.execute(
                """UPDATE sources SET token=NULL,lease_until=NULL,failures=0,
                       last_checked=?,version=?,next_poll=? WHERE id=?""",
                (now, version, now + row["interval_s"], source),
            )
            return "unchanged" if exists else "queued"

    def claim(self) -> Job | None:
        with self._transaction() as db:
            now = self._tick(db)
            db.execute(
                """UPDATE jobs SET state='dead',token=NULL,lease_until=NULL
                       WHERE state='running' AND lease_until<=? AND attempts>=?""",
                (now, self.max_attempts),
            )
            row = db.execute(
                """SELECT j.* FROM jobs j JOIN sources s ON j.source=s.id
                WHERE s.halted=0 AND s.blocked_until<=? AND j.attempts<? AND
                ((j.state='queued' AND j.available<=?) OR
                 (j.state='running' AND j.lease_until<=?)) ORDER BY j.available,j.id LIMIT 1""",
                (now, self.max_attempts, now, now),
            ).fetchone()
            if row is None:
                return None
            token = uuid4().hex
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1,token=?,lease_until=? "
                "WHERE id=?",
                (token, now + self.lease_s, row["id"]),
            )
            return Job(
                row["id"],
                row["source"],
                row["pipeline"],
                row["version"],
                row["attempts"] + 1,
                token,
            )

    def finish(self, job: Job, *, retry_after_s: int | None = None, halt: bool = False) -> bool:
        if retry_after_s is not None:
            RetryLater(retry_after_s)  # Validate before writing any state.
        with self._transaction() as db:
            now = self._tick(db)
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job.id,)).fetchone()
            if row is not None:
                if halt:
                    db.execute("UPDATE sources SET halted=1 WHERE id=?", (row["source"],))
                elif retry_after_s:
                    db.execute(
                        "UPDATE sources SET blocked_until=MAX(blocked_until,?) WHERE id=?",
                        (now + retry_after_s, row["source"]),
                    )
            if (
                row is None
                or row["state"] != "running"
                or row["token"] != job.token
                or row["lease_until"] <= now
            ):
                return False
            if halt:
                state, available = "dead", now
                db.execute("UPDATE sources SET halted=1 WHERE id=?", (row["source"],))
            elif retry_after_s is None:
                state, available = "done", now
            else:
                state = "dead" if row["attempts"] >= self.max_attempts else "queued"
                available = now + max(retry_after_s, min(60 * 2 ** (row["attempts"] - 1), 3600))
                db.execute(
                    "UPDATE sources SET blocked_until=MAX(blocked_until,?) WHERE id=?",
                    (available, row["source"]),
                )
            db.execute(
                "UPDATE jobs SET state=?,available=?,token=NULL,lease_until=NULL WHERE id=?",
                (state, available, job.id),
            )
            return True

    def renew(self, job: Job) -> bool:
        with self._transaction() as db:
            now = self._tick(db)
            changed = db.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND token=? "
                "AND state='running' AND lease_until>?",
                (now + self.lease_s, job.id, job.token, now),
            )
            return changed.rowcount == 1

    def run_one(self, ingest: Callable[[Job], None]) -> str:
        job = self.claim()
        if job is None:
            return "idle"
        try:
            ingest(job)  # The adapter must commit idempotently using job.id.
        except InvalidRetryDelay:
            return "halted" if self.finish(job, halt=True) else "stale"
        except (RetryLater, TimeoutError, OSError) as error:
            delay = error.retry_after_s if isinstance(error, RetryLater) else 0
            if not self.finish(job, retry_after_s=delay):
                return "stale"
            return "dead" if job.attempt >= self.max_attempts else "retry"
        return "done" if self.finish(job) else "stale"

    def resume(self, source: str) -> None:
        """Explicit operator action after reviewing a halted source; preserve its cooldown."""
        with self._transaction() as db:
            self._tick(db)
            if db.execute("UPDATE sources SET halted=0 WHERE id=?", (source,)).rowcount != 1:
                raise QueueError("unknown_source")

    def counts(self) -> dict[str, int]:
        with self._transaction() as db:
            values = {
                row["state"]: row["n"]
                for row in db.execute("SELECT state,COUNT(*) n FROM jobs GROUP BY state")
            }
        return {state: values.get(state, 0) for state in ("queued", "running", "done", "dead")}
