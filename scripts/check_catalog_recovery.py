"""Offline CLI recovery drill followed by real HTTP on a temporary Uvicorn server."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import uvicorn
from mycoradar.catalog import DEFAULT_CATALOG


def command(
    operation: str, source: Path, digest: str, *extra: str, code: int = 0
) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mycoradar.catalog_recovery",
            operation,
            "--input",
            str(source),
            "--sha256",
            digest,
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != code or result.stderr:
        raise RuntimeError("Recovery CLI failed; inspect the isolated exercise")
    report: dict[str, Any] = json.loads(result.stdout)
    return report


def check_restored_http(restored: Path, digest: str) -> None:
    os.environ["MYCORADAR_CATALOG_PATH"] = str(restored)
    os.environ["MYCORADAR_CATALOG_SHA256"] = digest
    from mycoradar.main import app
    from mycoradar.settings import get_settings

    get_settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not server.started:
                raise RuntimeError("Restored API did not start")
            base = f"http://127.0.0.1:{listener.getsockname()[1]}"
            with urlopen(f"{base}/v1/regions?limit=1&country=FR", timeout=5) as response:
                page = json.load(response)
            if (
                page["catalog_version"] != digest
                or page["pagination"]["total"] != 3
                or page["items"][0]["id"] != "FR-13"
            ):
                raise RuntimeError("Restored catalogue is not served correctly")
            with urlopen(f"{base}/v1/species", timeout=5) as response:
                page = json.load(response)
            if page["status"] != "unavailable" or page["items"]:
                raise RuntimeError("Restoration fabricated scientific availability")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Temporary API did not stop")


def main() -> None:
    digest = DEFAULT_CATALOG.with_suffix(".sha256").read_text(encoding="ascii").strip()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        backup, broken, restored = (
            root / name for name in ("backup.json", "broken.json", "new.json")
        )
        command("backup", DEFAULT_CATALOG, digest, "--output", str(backup))
        command("verify", backup, digest)
        broken.write_bytes(backup.read_bytes() + b"INJECTED_CORRUPTION")
        detected = command("restore", broken, digest, "--output", str(restored), code=1)
        if detected["error"] != "checksum_mismatch" or restored.exists():
            raise RuntimeError("Corruption was not safely rejected")
        command("restore", backup, digest, "--output", str(restored))
        if restored.read_bytes() != DEFAULT_CATALOG.read_bytes():
            raise RuntimeError("Restored bytes changed")
        collision = command("restore", broken, digest, "--output", str(restored), code=1)
        if collision["error"] != "checksum_mismatch":
            raise RuntimeError("Bad backup was not rejected after recovery")
        audit = command("audit", restored, digest, "--max-source-age-seconds", "86400", code=2)
        if "source_date_unknown" not in audit["metrics"]["alerts"]:
            raise RuntimeError("Unknown source date was hidden")
        check_restored_http(restored, digest)
    print(
        json.dumps(
            {
                "event": "catalogue_recovery_smoke",
                "status": "ok",
                "injected_corruption_detected": True,
                "exact_bytes_restored": True,
                "restored_http_verified": True,
                "unknown_source_date_alerted": True,
                "database_backup_tested": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
