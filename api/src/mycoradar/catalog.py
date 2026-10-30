"""Load one bounded, precomputed public publication at startup; no ETL in requests."""

from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from mycoradar.catalog_models import Cell, Region, Snapshot, Source, Species

DEFAULT_CATALOG = Path(__file__).parent / "data" / "public-catalog.json"
MAX_BYTES = 32 * 1024 * 1024


class Catalog:
    def __init__(self, path: Path, expected_sha256: str) -> None:
        self.snapshot: Snapshot | None = None
        self.version = "unavailable"
        self.region_index: dict[str, Region] = {}
        self.collections: dict[str, tuple[Region | Species | Cell | Source, ...]] = {}
        try:
            if len(expected_sha256) != 64:
                return
            with path.open("rb") as stream:
                content = stream.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                return
            if sha256(content).hexdigest() != expected_sha256:
                return
            self.snapshot = Snapshot.model_validate_json(content)
            self.region_index = {region.id: region for region in self.snapshot.regions}
            self.collections = {
                name: tuple(sorted(getattr(self.snapshot, name), key=lambda record: record.id))
                for name in ("regions", "species", "cells", "metadata")
            }
            self.version = sha256(content).hexdigest()
        except (OSError, ValueError, ValidationError):
            # No file path, validation input, credentials or source coordinates in HTTP/logs.
            self.snapshot = None
