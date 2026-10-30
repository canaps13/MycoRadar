"""Offline, deterministic publication of the admitted display catalogue; no network."""

import argparse
import hashlib
import json
from pathlib import Path

from mycoradar.catalog import DEFAULT_CATALOG
from mycoradar.catalog_models import Snapshot

ROOT = Path(__file__).resolve().parents[1]


def build_catalog() -> bytes:
    manifest = json.loads((ROOT / "data/catalog/manifest.json").read_text(encoding="utf-8"))
    for path, checksum in (
        (manifest["original_path"], manifest["metadata"]["sha256"]),
        (manifest["geometry_path"], manifest["geometry_sha256"]),
    ):
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != checksum:
            raise ValueError("Input checksum mismatch")
    display = json.loads((ROOT / manifest["geometry_path"]).read_bytes())
    features = {feature["properties"]["id"]: feature for feature in display["features"]}
    if len(features) != len(display["features"]) or set(features) != {
        territory["id"] for territory in manifest["territories"]
    }:
        raise ValueError("Display geometry/territory identity mismatch")
    source_id = manifest["metadata"]["id"]
    regions = []
    for territory in manifest["territories"]:
        feature = features[territory["id"]]
        if territory["name"] != feature["properties"]["name"]:
            raise ValueError("Display name mismatch")
        regions.append(
            {
                **territory,
                "geometry": feature["geometry"],
                "visibility": "public",
                "source_ids": [source_id],
            }
        )
    snapshot = Snapshot.model_validate(
        {
            "schema_version": "public-catalog-v1",
            "published_at": manifest["published_at"],
            "availability": {
                "regions": {"status": "partial", "reason": "pilot_administrative_display_only"},
                "species": {"status": "unavailable", "reason": "no_admitted_taxonomy_published"},
                "cells": {"status": "unavailable", "reason": "no_grid_publication_admitted"},
                "metadata": {"status": "available", "reason": None},
            },
            "regions": regions,
            "species": [],
            "cells": [],
            "metadata": [manifest["metadata"]],
        }
    )
    return (snapshot.model_dump_json() + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = build_catalog()
    checksum = hashlib.sha256(content).hexdigest() + "\n"
    if args.check:
        if (
            DEFAULT_CATALOG.read_bytes() != content
            or DEFAULT_CATALOG.with_suffix(".sha256").read_text(encoding="ascii") != checksum
        ):
            raise ValueError("Regenerate the committed catalogue and checksum")
        print("Catalogue inputs, publication and SHA-256 verified.")
    else:
        DEFAULT_CATALOG.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_CATALOG.write_bytes(content)
        DEFAULT_CATALOG.with_suffix(".sha256").write_text(checksum, encoding="ascii")
        print(f"Published {DEFAULT_CATALOG.name}: {checksum.strip()}")


if __name__ == "__main__":
    main()
