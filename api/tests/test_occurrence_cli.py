"""CLI boundary checks use only invented records and ephemeral test files."""

import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mycoradar.occurrence_privacy import PrivacyPolicy, SourceRule, TaxonRule

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "PRIVATE-SYNTHETIC-CLI-LOCATION-12.3456789"


def setup_input(tmp_path: Path) -> tuple[Path, Path]:
    instant = datetime.now(UTC)
    policy = PrivacyPolicy(
        version="synthetic-cli-v1",
        review_reference="https://example.invalid/review",
        reviewed_at=instant - timedelta(days=1),
        expires_at=instant + timedelta(days=1),
        sources=(
            SourceRule(
                id="synthetic",
                version="v1",
                license="CC0-1.0",
                attribution="Synthetic fixture only",
                citation_url="https://example.invalid/source",
                fetched_at=instant - timedelta(days=2),
                source_published_at=None,
                public_distribution_authorized=True,
            ),
        ),
        taxa=(TaxonRule(taxon_id="synthetic-taxon", country_code="FR", sensitivity="public"),),
    )
    row = {
        "record_id": "public-fixture",
        "source_id": "synthetic",
        "source_version": "v1",
        "record_license": "CC0-1.0",
        "taxon_id": "synthetic-taxon",
        "country_code": "FR",
        "location_visibility": "public",
        "sensitivity": "public",
        "reviewed_for_release": True,
        "coordinate_crs": "EPSG:4326",
        "longitude": 6.2,
        "latitude": 43.4,
        "location_uncertainty_m": 1000,
        "generalized": True,
    }
    policy_file = tmp_path / "policy.json"
    input_file = tmp_path / "input.ndjson"
    policy_file.write_text(policy.model_dump_json(), encoding="utf-8")
    input_file.write_text(
        json.dumps(row)
        + "\n"
        + json.dumps(
            {
                **row,
                "record_id": SENTINEL,
                "location_visibility": "private",
                "longitude": 12.3456789,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return policy_file, input_file


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "scripts/filter_occurrences.py", *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "api/src")},
        capture_output=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize("surface", ["api", "tiles", "export", "urls", "audit"])
def test_cli_outputs_only_filtered_artifacts_without_saving_private_data(
    tmp_path: Path, surface: str
) -> None:
    policy_file, input_file = setup_input(tmp_path)
    before = set(tmp_path.iterdir())
    result = invoke("--policy", str(policy_file), "--input", str(input_file), "--format", surface)
    assert result.returncode == 0 and result.stderr == b""
    assert set(tmp_path.iterdir()) == before
    output = result.stdout
    if surface == "export":
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            output = b"\n".join(archive.read(name) for name in archive.namelist())
    else:
        data = json.loads(output)
        if surface == "api":
            assert len(data["items"]) == 1
        if surface == "tiles":
            assert len(data["features"]) == 1
        if surface == "urls":
            assert len(data) == 1 and "?" not in data[0]
        if surface == "audit":
            assert data["accepted"] == data["excluded"] == 1
    assert SENTINEL.encode() not in output and b"12.3456789" not in output
    assert str(input_file).encode() not in output


@pytest.mark.parametrize(
    "failure", ["json", "late_json", "non_object", "policy", "missing", "oversized", "args"]
)
def test_cli_errors_never_echo_inputs_file_paths_or_private_arguments(
    tmp_path: Path, failure: str
) -> None:
    policy_file, input_file = setup_input(tmp_path)
    extra: list[str] = []
    if failure == "json":
        input_file.write_text(SENTINEL, encoding="utf-8")
    if failure == "late_json":
        with input_file.open("a", encoding="utf-8") as stream:
            stream.write(SENTINEL)
    if failure == "non_object":
        input_file.write_text(json.dumps([SENTINEL]), encoding="utf-8")
    if failure == "policy":
        policy_file.write_text(json.dumps({"secret": SENTINEL}), encoding="utf-8")
    if failure == "missing":
        input_file = tmp_path / SENTINEL
    if failure == "oversized":
        input_file.write_bytes((SENTINEL * 5000).encode())
    if failure == "args":
        extra = ["--private-location", SENTINEL]
    result = invoke("--policy", str(policy_file), "--input", str(input_file), *extra)
    assert result.returncode == 2 and result.stderr == b""
    assert json.loads(result.stdout)["status"] == "unavailable"
    assert SENTINEL.encode() not in result.stdout and str(tmp_path).encode() not in result.stdout
