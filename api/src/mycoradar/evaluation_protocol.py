"""Offline audit of declared evaluation partitions; no labels, fitting or predictions."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_BYTES = 4 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=1)]
Fraction = Annotated[float, Field(strict=True, gt=0, le=1, allow_inf_nan=False)]
Baselines = Literal["seasonality", "simple_habitat", "simple_weather"]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class SpatialDesign(Contract):
    autocorrelation_range_m: Positive | None
    minimum_separation_m: Positive | None
    justification_sha256: Digest | None


class DecisionRule(Contract):
    primary_metric: Literal["presence_capture_at_area_fraction"]
    area_fraction: Fraction | None
    minimum_capture_gain: Fraction | None
    minimum_development_blocks: Count | None
    minimum_test_blocks: Count | None
    minimum_test_time_blocks: Count | None
    uncertainty: Literal["blocked_bootstrap"]
    require_gain_lower_bound: Literal[True]
    require_equal_coverage: Literal[True]
    justification_sha256: Digest | None


class Assignment(Contract):
    record_sha256: Digest
    split: Literal["development", "test"]
    inner_fold: Annotated[int, Field(strict=True, ge=0, le=99)] | None
    spatial_block_sha256: Digest | None
    time_block_sha256: Digest | None
    site_group_sha256: Digest | None
    visit_group_sha256: Digest | None
    cell_group_sha256: Digest | None
    duplicate_group_sha256: Digest | None
    event_start: AwareDatetime
    event_end: AwareDatetime
    prediction_at: AwareDatetime
    feature_data_cutoff: AwareDatetime | None
    feature_available_at: AwareDatetime | None
    label_available_at: AwareDatetime | None
    nearest_development_distance_m: Annotated[float, Field(strict=True, ge=0)] | None

    @model_validator(mode="after")
    def time_interval(self) -> Self:
        if self.event_start >= self.event_end:
            raise ValueError("Explicit nonempty observation interval required")
        return self


class Plan(Contract):
    schema_version: Literal["evaluation-plan-v1"]
    input_kind: Literal["synthetic", "private_operator_manifest"]
    observation_basis: Literal["presence_only"]
    state: Literal["draft", "frozen"]
    frozen_at: AwareDatetime | None
    model_selection_started_at: AwareDatetime | None
    test_labels_accessed_at: AwareDatetime | None
    pilot_admission_sha256: Digest | None
    source_manifest_sha256: Digest | None
    taxon_scope_sha256: Digest | None
    territory_scope_sha256: Digest | None
    sampling_bias_review_sha256: Digest | None
    background_scope_sha256: Digest | None
    baseline_configs_sha256: Digest | None
    metric_definition_sha256: Digest | None
    split_construction_sha256: Digest | None
    baselines: Annotated[tuple[Baselines, ...], Field(max_length=3)]
    spatial_design: SpatialDesign
    decision_rule: DecisionRule
    assignments: Annotated[tuple[Assignment, ...], Field(max_length=10_000)]


GROUPS = (
    "spatial_block_sha256",
    "site_group_sha256",
    "visit_group_sha256",
    "cell_group_sha256",
    "duplicate_group_sha256",
)
EVIDENCE = (
    "pilot_admission_sha256",
    "source_manifest_sha256",
    "taxon_scope_sha256",
    "territory_scope_sha256",
    "sampling_bias_review_sha256",
    "background_scope_sha256",
    "baseline_configs_sha256",
    "metric_definition_sha256",
    "split_construction_sha256",
)


def audit(plan: Plan, input_sha256: str) -> dict[str, object]:
    blockers: set[str] = set()
    development = [row for row in plan.assignments if row.split == "development"]
    test = [row for row in plan.assignments if row.split == "test"]
    if plan.state != "frozen" or plan.frozen_at is None:
        blockers.add("protocol_not_frozen")
    elif (
        plan.model_selection_started_at is not None
        and plan.frozen_at > plan.model_selection_started_at
    ):
        blockers.add("freeze_after_model_selection")
    if plan.test_labels_accessed_at is not None:
        blockers.add("test_labels_already_accessed")
    if any(getattr(plan, name) is None for name in EVIDENCE):
        blockers.add("admission_or_design_evidence_missing")
    if len(plan.baselines) != 3 or set(plan.baselines) != {
        "seasonality",
        "simple_habitat",
        "simple_weather",
    }:
        blockers.add("baselines_incomplete")
    spatial = plan.spatial_design
    if (
        spatial.autocorrelation_range_m is None
        or spatial.minimum_separation_m is None
        or spatial.justification_sha256 is None
    ):
        blockers.add("spatial_design_unjustified")
    elif spatial.minimum_separation_m < spatial.autocorrelation_range_m:
        blockers.add("spatial_separation_below_declared_range")
    rule = plan.decision_rule
    if any(
        getattr(rule, name) is None
        for name in (
            "area_fraction",
            "minimum_capture_gain",
            "minimum_development_blocks",
            "minimum_test_blocks",
            "minimum_test_time_blocks",
            "justification_sha256",
        )
    ):
        blockers.add("decision_thresholds_unjustified")
    if not development or not test:
        blockers.add("partition_missing")
    if len({row.record_sha256 for row in plan.assignments}) != len(plan.assignments):
        blockers.add("duplicate_record")
    if (
        development
        and test
        and max(row.event_end for row in development) > min(row.event_start for row in test)
    ):
        blockers.add("chronological_holdout_overlap")

    groups: dict[tuple[str, str], tuple[str, int | None]] = {}
    time_blocks: dict[str, str] = {}
    for row in plan.assignments:
        if row.prediction_at > row.event_start:
            blockers.add("prediction_after_event_start")
        if row.feature_data_cutoff is None or row.feature_available_at is None:
            blockers.add("feature_availability_unknown")
        elif not row.feature_data_cutoff <= row.feature_available_at <= row.prediction_at:
            blockers.add("feature_information_leakage")
        if row.label_available_at is None:
            blockers.add("label_availability_unknown")
        elif row.label_available_at < row.event_end:
            blockers.add("label_before_observation_end")
        elif (
            row.split == "development"
            and plan.model_selection_started_at is not None
            and row.label_available_at > plan.model_selection_started_at
        ):
            blockers.add("development_label_unavailable_at_fit")
        if row.split == "test":
            if row.inner_fold is not None:
                blockers.add("test_in_inner_cv")
            distance = row.nearest_development_distance_m
            if distance is None:
                blockers.add("test_separation_unknown")
            elif (
                spatial.minimum_separation_m is not None and distance < spatial.minimum_separation_m
            ):
                blockers.add("test_within_spatial_buffer")
        elif row.inner_fold is None:
            blockers.add("development_fold_missing")
        for name in GROUPS:
            identity = getattr(row, name)
            if identity is None:
                blockers.add("dependency_group_unknown")
                continue
            key = (name, identity)
            partition = (row.split, row.inner_fold)
            if key in groups and groups[key] != partition:
                blockers.add("dependency_group_crosses_partitions")
            groups[key] = partition
        if row.time_block_sha256 is None:
            blockers.add("time_block_unknown")
        elif (
            row.time_block_sha256 in time_blocks and time_blocks[row.time_block_sha256] != row.split
        ):
            blockers.add("time_block_crosses_holdout")
        else:
            time_blocks[row.time_block_sha256] = row.split

    fold_count = len({row.inner_fold for row in development if row.inner_fold is not None})
    if fold_count < 2:
        blockers.add("inner_cv_needs_multiple_folds")
    counts = {
        "development": len(development),
        "test": len(test),
        "inner_folds": fold_count,
        "development_blocks": len(
            {
                row.spatial_block_sha256
                for row in development
                if row.spatial_block_sha256 is not None
            }
        ),
        "test_blocks": len(
            {row.spatial_block_sha256 for row in test if row.spatial_block_sha256 is not None}
        ),
        "test_time_blocks": len(
            {row.time_block_sha256 for row in test if row.time_block_sha256 is not None}
        ),
    }
    for threshold, count in (
        (rule.minimum_development_blocks, counts["development_blocks"]),
        (rule.minimum_test_blocks, counts["test_blocks"]),
        (rule.minimum_test_time_blocks, counts["test_time_blocks"]),
    ):
        if threshold is not None and count < threshold:
            blockers.add("declared_sample_threshold_not_met")
    return {
        "schema_version": "evaluation-audit-v1",
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_sha256": input_sha256,
        "input_kind": plan.input_kind,
        "structural_status": "blocked" if blockers else "passed",
        "blockers": sorted(blockers),
        "counts": counts,
        "observation_basis": "presence_only",
        "probability_evaluation_supported": False,
        "scientific_validation": "not_performed",
        "model_training_authorized": False,
        "publication_allowed": False,
    }


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON key")
        result[key] = value
    return result


def audit_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError("Input file required")
    with path.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Manifest budget exceeded")
    plan = Plan.model_validate(json.loads(content, object_pairs_hook=_unique_keys))
    return audit(plan, hashlib.sha256(content).hexdigest())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_file(args.manifest)
    except (OSError, ValueError, TypeError, RecursionError):
        print('{"error":"evaluation_manifest_invalid"}')
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if report["structural_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
