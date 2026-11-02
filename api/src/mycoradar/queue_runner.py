"""Explicit local runner for immutable JSON artifacts; no remote provider or public output."""

import argparse
import hashlib
import json
import signal
import sqlite3
from collections import Counter
from collections.abc import Callable
from functools import partial
from pathlib import Path
from threading import Event
from typing import Annotated, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field

from mycoradar.artifact_io import canonical, parse_object, read_bytes, write_immutable
from mycoradar.job_queue import DIGEST, HaltSource, Job, JobQueue, QueueError

MAX_PAYLOAD = 8 * 1024 * 1024
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,79}$")]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: Id
    root: Annotated[str, Field(min_length=1, max_length=2048)]
    pipeline_version: Id
    adapter: Literal["verified-json-v1"] = "verified-json-v1"
    interval_s: Annotated[int, Field(strict=True, ge=3600, le=604800)] = 3600


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["queue-runner-v1"]
    sources: Annotated[tuple[Source, ...], Field(min_length=1, max_length=16)]


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise QueueError("runner_input_invalid")


def contained(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HaltSource("source_path_invalid")
    return path


class Runner:
    def __init__(self, config_path: Path, state: Path, *, clock: Callable[[], int] | None = None):
        config = Config.model_validate(parse_object(read_bytes(config_path, 65536)))
        if len({source.id for source in config.sources}) != len(config.sources):
            raise QueueError("duplicate_source")
        normalized = []
        for source in config.sources:
            root = (config_path.parent / source.root).resolve()
            if not root.is_dir():
                raise QueueError("source_directory_missing")
            normalized.append(Source.model_validate({**source.model_dump(), "root": str(root)}))
        self.state = state.resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.queue = (
            JobQueue(self.state / "queue.sqlite", clock=clock)
            if clock is not None
            else JobQueue(self.state / "queue.sqlite")
        )
        self.sources: list[tuple[Source, str]] = []
        for source in normalized:
            data = canonical(source.model_dump())
            pipeline = hashlib.sha256(data).hexdigest()
            write_immutable(contained(self.state, f"configs/{pipeline}.json"), data)
            self.queue.register(source.id, pipeline, interval_s=source.interval_s)
            self.sources.append((source, pipeline))

    def probe(self, source: Source) -> str:
        try:
            pointer = parse_object(read_bytes(contained(Path(source.root), "current.json"), 256))
            version = pointer.get("sha256")
            if (
                set(pointer) != {"sha256"}
                or not isinstance(version, str)
                or not DIGEST.fullmatch(version)
            ):
                raise ValueError("invalid_pointer")
            return version
        except (ValueError, RecursionError) as error:
            raise HaltSource("source_pointer_invalid") from error

    def ingest(self, job: Job) -> None:
        try:
            config = read_bytes(
                contained(self.state, f"configs/{job.pipeline_version}.json"), 65536
            )
            if hashlib.sha256(config).hexdigest() != job.pipeline_version:
                raise ValueError("config_checksum_mismatch")
            source = Source.model_validate(parse_object(config))
            if source.id != job.source_id:
                raise ValueError("job_source_mismatch")
            root = Path(source.root)
            data = read_bytes(contained(root, f"versions/{job.source_version}.json"), MAX_PAYLOAD)
            if hashlib.sha256(data).hexdigest() != job.source_version:
                raise ValueError("payload_checksum_mismatch")
            parse_object(data)  # Structural JSON check, no scientific interpretation or admission.
            write_immutable(contained(self.state, f"objects/{job.source_version}.json"), data)
            receipt = {
                "schema_version": "queued-artifact-receipt-v1",
                "job_id": job.id,
                "source_id": job.source_id,
                "pipeline_version": job.pipeline_version,
                "payload_sha256": job.source_version,
                "adapter": source.adapter,
                "publication_allowed": False,
                "scientific_validation": "not_performed",
            }
            write_immutable(contained(self.state, f"receipts/{job.id}.json"), canonical(receipt))
        except (ValueError, RecursionError) as error:
            raise HaltSource("artifact_rejected") from error

    def tick(self, max_jobs: int = 16) -> dict[str, object]:
        if type(max_jobs) is not int or not 1 <= max_jobs <= 100:
            raise QueueError("invalid_job_budget")
        polls = Counter(
            self.queue.poll(source.id, partial(self.probe, source)) for source, _ in self.sources
        )
        executions: Counter[str] = Counter()
        for _ in range(max_jobs):
            result = self.queue.run_one(self.ingest)
            executions[result] += 1
            if result == "idle":
                break
        counts = self.queue.counts()
        degraded = (
            bool(counts["dead"])
            or any(polls[k] for k in ("retry", "halted", "stale"))
            or any(executions[k] for k in ("retry", "dead", "halted", "stale"))
        )
        return {
            "runner_status": "degraded" if degraded else "ok",
            "polls": dict(polls),
            "executions": dict(executions),
            "jobs": counts,
            "publication_allowed": False,
            "scientific_validation": "not_performed",
        }


def serve(runner: Runner, stop: Event, interval: int, max_jobs: int) -> None:
    while not stop.is_set():
        print(json.dumps(runner.tick(max_jobs), sort_keys=True), flush=True)
        if stop.wait(interval):
            break


def main() -> int:
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--config", type=Path, required=True)
        parser.add_argument("--state", type=Path, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--once", action="store_true")
        mode.add_argument("--serve", action="store_true")
        parser.add_argument("--tick-seconds", type=int, default=30)
        parser.add_argument("--max-jobs", type=int, default=16)
        args = parser.parse_args()
        if not 5 <= args.tick_seconds <= 60 or not 1 <= args.max_jobs <= 100:
            raise QueueError("runner_input_invalid")
        runner = Runner(args.config, args.state)
        if args.once:
            result = runner.tick(args.max_jobs)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["runner_status"] == "ok" else 2
        stop = Event()
        previous = {
            s: signal.signal(s, lambda _s, _f: stop.set()) for s in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            serve(runner, stop, args.tick_seconds, args.max_jobs)
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
        return 0
    except (ValueError, OSError, sqlite3.Error, RecursionError):
        print(
            json.dumps({"runner_status": "unavailable", "error": "runner_input_or_state_invalid"})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
