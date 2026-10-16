"""Independent, deterministic validation of provisional RESILIANT-Z candidates.

This module consumes a Session 11 candidate-discovery report and explicitly split,
context-rich observations. It does not run experiments or promote knowledge records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Literal["1.0.0"]
Split = Literal["discovery", "selection", "validation", "replay"]
Quality = Literal["measured", "missing", "stale", "unmeasured", "not_applicable"]
BackendId = Literal["discrete_event", "surrogate"]
CandidateKind = Literal["main_effect", "interaction"]
ValidationOutcome = Literal["validated", "rejected", "inconclusive", "invalidated"]
NonBlank = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


class FactorRange(StrictModel):
    minimum_observed: float = Field(allow_inf_nan=False)
    maximum_observed: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=256)
    calibration_status: Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]


class CandidateRecord(BaseModel):
    """Compatibility projection of the Session 11 candidate record."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    candidate_id: str = Field(pattern=r"^cand-[0-9a-f]{24}$")
    spec_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    candidate_kind: CandidateKind
    variable_ids: list[str] = Field(min_length=1, max_length=2)
    target_metric: str = Field(min_length=1, max_length=128)
    target_unit: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: BackendId
    evidence_label: str = Field(min_length=1, max_length=256)
    model_version: str = Field(min_length=1, max_length=128)
    estimated_effect: float | None = Field(default=None, allow_inf_nan=False)
    effect_direction: Literal[
        "increase", "decrease", "positive_interaction", "negative_interaction", "unclear"
    ]
    factor_ranges: dict[str, FactorRange]
    evidence_ids: list[str] = Field(max_length=500)
    selection_outcome: Literal["shortlisted", "not_shortlisted", "insufficient_evidence"]
    lifecycle_status: Literal["provisional"] = "provisional"
    method_id: str = "coded-ols-normal-approx-v1"


class CandidateDiscoveryReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: SchemaVersion = "1.0.0"
    batch_id: str = Field(pattern=r"^candbatch-[0-9a-f]{24}$")
    status: Literal["provisional_candidates_only"]
    config_id: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    backend_id: BackendId
    evidence_label: str
    target_metric: str
    target_unit: str
    training_splits: list[Literal["discovery", "selection"]]
    total_observations_received: int = Field(ge=0)
    eligible_observations: int = Field(ge=0)
    excluded_observation_count: int = Field(ge=0)
    excluded_reasons: dict[str, int]
    candidates: list[CandidateRecord] = Field(max_length=25)
    selection_procedure: str
    model_version: str
    limitations: list[str]


class FactorLevels(StrictModel):
    low: float = Field(allow_inf_nan=False)
    high: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> FactorLevels:
        if self.low >= self.high:
            raise ValueError("factor level low must be strictly less than high")
        return self


class ValidationRule(StrictModel):
    spec_id: str = Field(min_length=1, max_length=128)
    expected_effect_sign: Literal["positive", "negative"]
    factor_levels: dict[str, FactorLevels] = Field(min_length=1, max_length=2)
    minimum_replicates: int = Field(default=6, ge=3, le=100)
    minimum_absolute_effect: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    minimum_concordant_fraction: float = Field(default=0.8, gt=0.0, le=1.0, allow_inf_nan=False)
    minimum_effect_retention_fraction: float = Field(
        default=0.25, ge=0.0, le=2.0, allow_inf_nan=False
    )
    minimum_distinct_scenarios: int = Field(default=2, ge=1, le=20)
    minimum_distinct_initial_states: int = Field(default=2, ge=1, le=100)
    minimum_distinct_task_patterns: int = Field(default=2, ge=1, le=100)
    minimum_distinct_workload_patterns: int = Field(default=2, ge=1, le=100)


class Session12Config(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    config_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    primary_split: Literal["validation"] = "validation"
    allowed_validation_scenarios: list[str] = Field(min_length=2, max_length=20)
    rules: list[ValidationRule] = Field(min_length=1, max_length=25)
    minimum_training_evidence_links: int = Field(default=1, ge=1, le=100)
    metric_min_value: float = Field(default=-1_000_000.0, allow_inf_nan=False)
    metric_max_value: float = Field(default=1_000_000.0, allow_inf_nan=False)
    max_config_bytes: int = Field(default=1_048_576, ge=1024, le=8_388_608)
    max_candidate_report_bytes: int = Field(default=8_388_608, ge=1024, le=32_000_000)
    max_observation_bytes: int = Field(default=16_777_216, ge=1024, le=64_000_000)
    max_observations: int = Field(default=100_000, ge=10, le=200_000)
    max_candidates: int = Field(default=25, ge=1, le=25)
    max_report_bytes: int = Field(default=16_777_216, ge=1024, le=64_000_000)

    @model_validator(mode="after")
    def validate_config(self) -> Session12Config:
        if len(set(self.allowed_validation_scenarios)) != len(self.allowed_validation_scenarios):
            raise ValueError("allowed_validation_scenarios must be unique")
        if any(not item.strip() for item in self.allowed_validation_scenarios):
            raise ValueError("scenario identifiers must not be blank")
        if self.metric_min_value >= self.metric_max_value:
            raise ValueError("metric_min_value must be strictly less than metric_max_value")
        specs = [item.spec_id for item in self.rules]
        if len(set(specs)) != len(specs):
            raise ValueError("rules must have unique spec_id values")
        if len(self.rules) > self.max_candidates:
            raise ValueError("rule count exceeds max_candidates")
        return self


class ValidationObservation(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    observation_id: str = Field(min_length=1, max_length=160)
    evidence_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(pattern=r"^cand-[0-9a-f]{24}$")
    spec_id: str = Field(min_length=1, max_length=128)
    seed: int = Field(ge=0, le=2_147_483_647)
    replicate_index: int = Field(ge=0, le=999)
    split: Split
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: BackendId
    evidence_label: str = Field(min_length=1, max_length=256)
    metric_id: str = Field(min_length=1, max_length=128)
    metric_unit: str = Field(min_length=1, max_length=128)
    value: float | None = Field(default=None, allow_inf_nan=False)
    quality: Quality
    reason: str | None = Field(default=None, max_length=512)
    factor_values: dict[str, float] = Field(min_length=1, max_length=50)
    initial_state_id: str = Field(min_length=1, max_length=160)
    task_pattern_id: str = Field(min_length=1, max_length=160)
    workload_pattern_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_quality(self) -> ValidationObservation:
        if self.quality == "measured":
            if self.value is None:
                raise ValueError(
                    "measured observation requires a numeric value; measured zero is valid"
                )
        elif self.value is not None:
            raise ValueError("non-measured observation value must be null")
        elif not self.reason or not self.reason.strip():
            raise ValueError("non-measured observation requires a reason")
        if any(not math.isfinite(v) for v in self.factor_values.values()):
            raise ValueError("factor values must be finite")
        return self


class ObservationAudit(StrictModel):
    observation_id: str
    spec_id: str
    split: Split
    disposition: Literal["training_reference", "included_validation", "excluded"]
    reason: str


class ValidationResult(StrictModel):
    candidate_id: str | None
    spec_id: str
    status: ValidationOutcome
    reason: str
    candidate_kind: CandidateKind | None = None
    target_metric: str | None = None
    target_unit: str | None = None
    pair_count: int = Field(ge=0)
    mean_effect: float | None = Field(default=None, allow_inf_nan=False)
    sample_sd_effect: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    confidence_interval_95_low: float | None = Field(default=None, allow_inf_nan=False)
    confidence_interval_95_high: float | None = Field(default=None, allow_inf_nan=False)
    concordant_fraction: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    effect_retention_fraction: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    validated_scenarios: list[str]
    distinct_initial_states: int = Field(ge=0)
    distinct_task_patterns: int = Field(ge=0)
    distinct_workload_patterns: int = Field(ge=0)
    replicate_effects: list[float]
    criteria_snapshot: dict[str, object]
    evidence_ids: list[str]


class IndependentValidationReport(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    report_id: str = Field(pattern=r"^valreport-[0-9a-f]{24}$")
    status: Literal["independent_validation_report"] = "independent_validation_report"
    validation_config_id: str
    validation_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_splits_excluded_from_estimation: list[Literal["discovery", "selection"]] = [
        "discovery",
        "selection",
    ]
    replay_excluded_from_estimation: bool = True
    results: list[ValidationResult] = Field(max_length=25)
    audit: list[ObservationAudit] = Field(max_length=100_000)
    overall_limitations: list[str]


class IndependentValidationError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _read_limited(path: str | Path, limit: int, label: str) -> bytes:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise IndependentValidationError(
            f"{label}_read_error", f"could not read {label}: {type(exc).__name__}"
        ) from None
    if len(data) > limit:
        raise IndependentValidationError(
            f"{label}_too_large", f"{label} exceeds configured byte limit"
        )
    return data


def load_config(path: str | Path) -> tuple[Session12Config, bytes]:
    raw = _read_limited(path, 8_388_608, "config")
    try:
        config = Session12Config.model_validate_json(raw)
    except Exception as exc:
        raise IndependentValidationError(
            "config_invalid", f"config does not satisfy Session 12 contract: {type(exc).__name__}"
        ) from None
    if len(raw) > config.max_config_bytes:
        raise IndependentValidationError(
            "config_too_large", "config exceeds its own max_config_bytes"
        )
    return config, raw


def load_candidate_report(
    path: str | Path, config: Session12Config
) -> tuple[CandidateDiscoveryReport, bytes]:
    raw = _read_limited(path, config.max_candidate_report_bytes, "candidate_report")
    try:
        report = CandidateDiscoveryReport.model_validate_json(raw)
    except Exception as exc:
        raise IndependentValidationError(
            "candidate_report_invalid", f"candidate report is invalid: {type(exc).__name__}"
        ) from None
    if report.status != "provisional_candidates_only":
        raise IndependentValidationError(
            "candidate_report_not_provisional",
            "Session 12 accepts Session 11 provisional candidate reports only",
        )
    if report.training_splits != ["discovery", "selection"]:
        raise IndependentValidationError(
            "training_split_contract",
            "candidate report must declare discovery and selection as training splits",
        )
    if len(report.candidates) > config.max_candidates:
        raise IndependentValidationError(
            "candidate_limit_exceeded", "candidate report exceeds configured max_candidates"
        )
    return report, raw


def read_observations(
    path: str | Path, config: Session12Config
) -> tuple[list[ValidationObservation], bytes]:
    raw = _read_limited(path, config.max_observation_bytes, "observations")
    rows: list[ValidationObservation] = []
    try:
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(ValidationObservation.model_validate_json(line))
            except Exception as exc:
                raise IndependentValidationError(
                    "observation_invalid",
                    f"invalid observation on line {line_number}: {type(exc).__name__}",
                ) from None
            if len(rows) > config.max_observations:
                raise IndependentValidationError(
                    "observation_limit_exceeded",
                    "observation count exceeds configured max_observations",
                )
    except UnicodeDecodeError:
        raise IndependentValidationError(
            "observations_encoding", "observations file must be UTF-8 JSONL"
        ) from None
    if not rows:
        raise IndependentValidationError(
            "observations_empty", "at least one observation is required"
        )
    ids = [row.observation_id for row in rows]
    if len(ids) != len(set(ids)):
        raise IndependentValidationError(
            "duplicate_observation_id", "observation_id values must be globally unique"
        )
    return rows, raw


def _t_critical_975(df: int) -> float:
    # Two-sided 95% Student-t values through df=30. Above 30 use a deterministic
    # Cornish-Fisher expansion around the normal quantile.
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
        30: 2.042,
    }
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    if df in table:
        return table[df]
    z = 1.959963984540054
    nu = float(df)
    return z + (z**3 + z) / (4.0 * nu) + (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * nu**2)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _sample_sd(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _effect_for_cells(values: Mapping[str, float], kind: CandidateKind) -> float:
    if kind == "main_effect":
        return values["high"] - values["low"]
    # Difference-in-differences: (high,high - high,low) - (low,high - low,low).
    return values["high_high"] - values["high_low"] - values["low_high"] + values["low_low"]


def _expected_cells(kind: CandidateKind) -> set[str]:
    if kind == "main_effect":
        return {"low", "high"}
    return {"low_low", "high_low", "low_high", "high_high"}


def _cell_for(row: ValidationObservation, candidate: CandidateRecord, rule: ValidationRule) -> str:
    factor_ids = candidate.variable_ids
    if len(factor_ids) != len(rule.factor_levels) or set(factor_ids) != set(rule.factor_levels):
        raise ValueError("factor level keys must exactly match candidate variable_ids")
    states: dict[str, str] = {}
    for factor_id in factor_ids:
        if factor_id not in row.factor_values:
            raise ValueError(f"missing candidate factor value: {factor_id}")
        observed = row.factor_values[factor_id]
        levels = rule.factor_levels[factor_id]
        if math.isclose(observed, levels.low, abs_tol=1e-9, rel_tol=0.0):
            states[factor_id] = "low"
        elif math.isclose(observed, levels.high, abs_tol=1e-9, rel_tol=0.0):
            states[factor_id] = "high"
        else:
            raise ValueError(f"factor {factor_id!r} must equal a predeclared low/high level")
    if candidate.candidate_kind == "main_effect":
        return states[factor_ids[0]]
    # Preserve the variable ordering used by the candidate's registered spec.
    a, b = factor_ids
    return f"{states[a]}_{states[b]}"


def _criteria_snapshot(rule: ValidationRule) -> dict[str, object]:
    return rule.model_dump(mode="json")


def _base_result(
    rule: ValidationRule, candidate: CandidateRecord | None, status: ValidationOutcome, reason: str
) -> ValidationResult:
    return ValidationResult(
        candidate_id=candidate.candidate_id if candidate else None,
        spec_id=rule.spec_id,
        status=status,
        reason=reason,
        candidate_kind=candidate.candidate_kind if candidate else None,
        target_metric=candidate.target_metric if candidate else None,
        target_unit=candidate.target_unit if candidate else None,
        pair_count=0,
        validated_scenarios=[],
        distinct_initial_states=0,
        distinct_task_patterns=0,
        distinct_workload_patterns=0,
        replicate_effects=[],
        criteria_snapshot=_criteria_snapshot(rule),
        evidence_ids=[],
    )


def validate_candidates(
    candidate_report: CandidateDiscoveryReport,
    observations: Sequence[ValidationObservation],
    config: Session12Config,
    *,
    candidate_report_bytes: bytes,
    observation_bytes: bytes,
    config_bytes: bytes,
) -> IndependentValidationReport:
    """Validate each configured candidate against independent, predeclared evidence."""
    by_spec: dict[str, list[ValidationObservation]] = defaultdict(list)
    for row in observations:
        by_spec[row.spec_id].append(row)
    candidate_by_spec: dict[str, CandidateRecord] = {}
    for candidate in candidate_report.candidates:
        if candidate.spec_id in candidate_by_spec:
            raise IndependentValidationError(
                "duplicate_candidate_spec", f"duplicate candidate spec_id {candidate.spec_id!r}"
            )
        candidate_by_spec[candidate.spec_id] = candidate

    global_seed_splits: dict[int, set[str]] = defaultdict(set)
    for row in observations:
        global_seed_splits[row.seed].add(row.split)
    split_leaks = {seed for seed, splits in global_seed_splits.items() if len(splits) > 1}

    results: list[ValidationResult] = []
    audit_by_observation: dict[tuple[str, str], ObservationAudit] = {}
    configured_specs = {rule.spec_id for rule in config.rules}
    for row in sorted(
        observations, key=lambda item: (item.spec_id, item.split, item.observation_id)
    ):
        if row.split in {"discovery", "selection"}:
            entry = ObservationAudit(
                observation_id=row.observation_id,
                spec_id=row.spec_id,
                split=row.split,
                disposition="training_reference",
                reason="training row used only to verify evidence linkage and disjointness",
            )
        elif row.split == "replay":
            entry = ObservationAudit(
                observation_id=row.observation_id,
                spec_id=row.spec_id,
                split=row.split,
                disposition="excluded",
                reason="replay split is excluded from the independent validation estimate",
            )
        elif row.spec_id not in configured_specs:
            entry = ObservationAudit(
                observation_id=row.observation_id,
                spec_id=row.spec_id,
                split=row.split,
                disposition="excluded",
                reason="no predeclared validation rule for this candidate spec_id",
            )
        else:
            entry = ObservationAudit(
                observation_id=row.observation_id,
                spec_id=row.spec_id,
                split=row.split,
                disposition="excluded",
                reason="candidate did not contribute to a complete eligible validation contrast",
            )
        audit_by_observation[(row.observation_id, row.spec_id)] = entry

    def add_result(result: ValidationResult) -> None:
        results.append(result)
        if result.status == "invalidated":
            for row in by_spec.get(result.spec_id, []):
                if row.split == "validation":
                    audit_by_observation[(row.observation_id, row.spec_id)] = ObservationAudit(
                        observation_id=row.observation_id,
                        spec_id=row.spec_id,
                        split=row.split,
                        disposition="excluded",
                        reason=f"candidate invalidated: {result.reason}",
                    )

    for rule in config.rules:
        candidate = candidate_by_spec.get(rule.spec_id)
        if candidate is None:
            add_result(
                _base_result(
                    rule,
                    None,
                    "invalidated",
                    "configured candidate spec_id is absent from the candidate-discovery report",
                )
            )
            continue
        if (
            candidate.lifecycle_status != "provisional"
            or candidate.selection_outcome != "shortlisted"
        ):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "only shortlisted provisional candidates are eligible for independent validation",
                )
            )
            continue
        sign_positive = rule.expected_effect_sign == "positive"
        expected_direction = (
            ("increase" if sign_positive else "decrease")
            if candidate.candidate_kind == "main_effect"
            else ("positive_interaction" if sign_positive else "negative_interaction")
        )
        if candidate.effect_direction != expected_direction:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "predeclared direction disagrees with the candidate-discovery direction",
                )
            )
            continue
        if candidate.estimated_effect is None or abs(candidate.estimated_effect) <= 1e-12:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "candidate has no non-zero discovery effect to validate",
                )
            )
            continue
        if set(rule.factor_levels) != set(candidate.variable_ids):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "predeclared factor levels do not match candidate variable IDs",
                )
            )
            continue
        if any(
            factor_id not in candidate.factor_ranges
            or levels.low < candidate.factor_ranges[factor_id].minimum_observed - 1e-9
            or levels.high > candidate.factor_ranges[factor_id].maximum_observed + 1e-9
            for factor_id, levels in rule.factor_levels.items()
        ):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "predeclared validation levels lie outside the candidate's discovery range",
                )
            )
            continue
        candidate_rows = by_spec.get(rule.spec_id, [])
        training_rows = [row for row in candidate_rows if row.split in {"discovery", "selection"}]
        validation_rows = [row for row in candidate_rows if row.split == "validation"]
        candidate_evidence = set(candidate.evidence_ids)
        linked_training = {
            row.evidence_id for row in training_rows if row.evidence_id in candidate_evidence
        }
        if len(linked_training) < config.minimum_training_evidence_links:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "candidate does not link to the required number of original discovery/selection evidence IDs",
                )
            )
            continue
        if split_leaks:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "one or more seeds are reused across discovery, selection, validation or replay splits",
                )
            )
            continue
        if not validation_rows:
            add_result(
                _base_result(
                    rule, candidate, "inconclusive", "no validation observations were supplied"
                )
            )
            continue
        wrong_metadata = [
            row
            for row in validation_rows
            if row.candidate_id != candidate.candidate_id
            or row.metric_id != candidate.target_metric
            or row.metric_unit != candidate.target_unit
            or row.backend_id != candidate.backend_id
            or row.evidence_label != candidate.evidence_label
        ]
        if wrong_metadata:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "validation result metadata conflicts with candidate metric, unit, backend, evidence label or candidate ID",
                )
            )
            continue
        out_of_range = [
            row
            for row in validation_rows
            if row.quality == "measured"
            and row.value is not None
            and not config.metric_min_value <= row.value <= config.metric_max_value
        ]
        if out_of_range:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "measured validation metric is outside the predeclared metric bounds",
                )
            )
            continue
        scenario_ids = {row.scenario_id for row in validation_rows}
        if not scenario_ids.issubset(set(config.allowed_validation_scenarios)):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "validation contains a scenario not allowlisted in the predeclared config",
                )
            )
            continue
        train_scenarios = {row.scenario_id for row in training_rows}
        train_states = {row.initial_state_id for row in training_rows}
        train_tasks = {row.task_pattern_id for row in training_rows}
        train_workloads = {row.workload_pattern_id for row in training_rows}
        validation_states = {row.initial_state_id for row in validation_rows}
        validation_tasks = {row.task_pattern_id for row in validation_rows}
        validation_workloads = {row.workload_pattern_id for row in validation_rows}
        if not train_scenarios or not train_states or not train_tasks or not train_workloads:
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "training rows lack scenario/state/task/workload context needed to prove independent validation",
                )
            )
            continue
        if (
            scenario_ids & train_scenarios
            or validation_states & train_states
            or validation_tasks & train_tasks
            or validation_workloads & train_workloads
        ):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "validation reuses a training scenario, initial state, task pattern or workload pattern",
                )
            )
            continue

        blocks: dict[tuple[int, int], list[ValidationObservation]] = defaultdict(list)
        for row in validation_rows:
            blocks[(row.seed, row.replicate_index)].append(row)
        # A seed must identify one validation replicate index for this candidate.
        seed_indices: dict[int, set[int]] = defaultdict(set)
        for seed, replicate_index in blocks:
            seed_indices[seed].add(replicate_index)
        if any(len(indices) > 1 for indices in seed_indices.values()):
            add_result(
                _base_result(
                    rule,
                    candidate,
                    "invalidated",
                    "the same validation seed is reused for multiple replicate indices",
                )
            )
            continue

        effects: list[float] = []
        evidence_ids: set[str] = set()
        included_scenarios: set[str] = set()
        included_states: set[str] = set()
        included_tasks: set[str] = set()
        included_workloads: set[str] = set()
        bad_protocol = None
        for (seed, replicate_index), group in sorted(blocks.items()):
            cell_values: dict[str, float] = {}
            seen_cells: set[str] = set()
            for row in group:
                if row.quality != "measured" or row.value is None:
                    # Explicitly unmeasured rows invalidate this block for estimation but remain audited.
                    continue
                try:
                    cell = _cell_for(row, candidate, rule)
                except ValueError as exc:
                    bad_protocol = str(exc)
                    break
                if cell in seen_cells:
                    bad_protocol = f"replicate {replicate_index} seed {seed} has duplicate contrast cell {cell!r}"
                    break
                seen_cells.add(cell)
                cell_values[cell] = row.value
            if bad_protocol:
                break
            if seen_cells != _expected_cells(candidate.candidate_kind):
                continue
            contexts = {
                (r.scenario_id, r.initial_state_id, r.task_pattern_id, r.workload_pattern_id)
                for r in group
            }
            if len(contexts) != 1:
                bad_protocol = f"replicate {replicate_index} does not hold scenario/state/task/workload constant across contrast cells"
                break
            nuisance_values = {
                tuple(
                    sorted(
                        (key, value)
                        for key, value in r.factor_values.items()
                        if key not in candidate.variable_ids
                    )
                )
                for r in group
            }
            if len(nuisance_values) > 1:
                bad_protocol = f"replicate {replicate_index} changes untested nuisance factors across contrast cells"
                break
            effects.append(_effect_for_cells(cell_values, candidate.candidate_kind))
            included_scenarios.add(group[0].scenario_id)
            included_states.add(group[0].initial_state_id)
            included_tasks.add(group[0].task_pattern_id)
            included_workloads.add(group[0].workload_pattern_id)
            evidence_ids.update(
                r.evidence_id for r in group if r.quality == "measured" and r.value is not None
            )
        if bad_protocol:
            add_result(_base_result(rule, candidate, "invalidated", bad_protocol))
            continue

        n = len(effects)
        mean = _mean(effects) if n else None
        sd = _sample_sd(effects, mean) if n and mean is not None else None
        if n >= 2 and mean is not None and sd is not None:
            margin = _t_critical_975(n - 1) * sd / math.sqrt(n)
            ci_low, ci_high = mean - margin, mean + margin
        else:
            ci_low = ci_high = None
        concordant_fraction = (
            (
                sum(1 for effect in effects if effect > 0) / n
                if sign_positive
                else sum(1 for effect in effects if effect < 0) / n
            )
            if n
            else None
        )
        retention = abs(mean) / abs(candidate.estimated_effect) if mean is not None else None
        context_ok = (
            len(included_scenarios) >= rule.minimum_distinct_scenarios
            and len(included_states) >= rule.minimum_distinct_initial_states
            and len(included_tasks) >= rule.minimum_distinct_task_patterns
            and len(included_workloads) >= rule.minimum_distinct_workload_patterns
        )
        criteria_snapshot = _criteria_snapshot(rule) | {
            "candidate_discovery_effect": candidate.estimated_effect,
            "predeclared_direction": rule.expected_effect_sign,
            "distinct_scenario_count": len(included_scenarios),
            "distinct_initial_state_count": len(included_states),
            "distinct_task_pattern_count": len(included_tasks),
            "distinct_workload_pattern_count": len(included_workloads),
            "confidence_method": "two-sided 95% Student-t interval; exact tabulated critical values through df=30, Cornish-Fisher approximation thereafter",
        }
        if n < rule.minimum_replicates:
            status: ValidationOutcome = "inconclusive"
            reason = (
                f"only {n} complete measured paired replicates; {rule.minimum_replicates} required"
            )
        elif not context_ok:
            status = "inconclusive"
            reason = "validation does not meet the predeclared scenario/initial-state/task/workload diversity criteria"
        elif (
            mean is None
            or ci_low is None
            or ci_high is None
            or concordant_fraction is None
            or retention is None
        ):
            status = "inconclusive"
            reason = "insufficient complete paired effects to calculate uncertainty"
        else:
            ci_supports_direction = ci_low > 0 if sign_positive else ci_high < 0
            ci_excludes_expected_direction = ci_high < 0 if sign_positive else ci_low > 0
            practical_ok = abs(mean) >= rule.minimum_absolute_effect
            concordance_ok = concordant_fraction >= rule.minimum_concordant_fraction
            retention_ok = retention >= rule.minimum_effect_retention_fraction
            if ci_supports_direction and practical_ok and concordance_ok and retention_ok:
                status = "validated"
                reason = "held-out effect direction, uncertainty, replication, practical-impact and context-diversity criteria passed"
            elif (
                ci_excludes_expected_direction
                or not concordance_ok
                or (ci_supports_direction and not practical_ok)
                or (ci_supports_direction and not retention_ok)
            ):
                status = "rejected"
                reason = "independent validation failed one or more predeclared direction, replication, retention or practical-impact criteria"
            else:
                status = "inconclusive"
                reason = "validation confidence interval does not establish the predeclared effect direction"
        add_result(
            ValidationResult(
                candidate_id=candidate.candidate_id,
                spec_id=rule.spec_id,
                status=status,
                reason=reason,
                candidate_kind=candidate.candidate_kind,
                target_metric=candidate.target_metric,
                target_unit=candidate.target_unit,
                pair_count=n,
                mean_effect=mean,
                sample_sd_effect=sd,
                confidence_interval_95_low=ci_low,
                confidence_interval_95_high=ci_high,
                concordant_fraction=concordant_fraction,
                effect_retention_fraction=retention,
                validated_scenarios=sorted(included_scenarios),
                distinct_initial_states=len(included_states),
                distinct_task_patterns=len(included_tasks),
                distinct_workload_patterns=len(included_workloads),
                replicate_effects=effects,
                criteria_snapshot=criteria_snapshot,
                evidence_ids=sorted(evidence_ids),
            )
        )
        for row in validation_rows:
            if row.evidence_id in evidence_ids:
                audit_by_observation[(row.observation_id, row.spec_id)] = ObservationAudit(
                    observation_id=row.observation_id,
                    spec_id=row.spec_id,
                    split=row.split,
                    disposition="included_validation",
                    reason="measured row contributed to a complete predeclared validation contrast",
                )
            elif row.quality != "measured":
                audit_by_observation[(row.observation_id, row.spec_id)] = ObservationAudit(
                    observation_id=row.observation_id,
                    spec_id=row.spec_id,
                    split=row.split,
                    disposition="excluded",
                    reason=f"quality={row.quality}; missing values are never coerced to zero",
                )
            else:
                audit_by_observation[(row.observation_id, row.spec_id)] = ObservationAudit(
                    observation_id=row.observation_id,
                    spec_id=row.spec_id,
                    split=row.split,
                    disposition="excluded",
                    reason="row was not part of a complete measured contrast",
                )

    # Replay rows and any non-primary rows are retained but never affect validation estimates.
    report_data = {
        "schema_version": "1.0.0",
        "validation_config_id": config.config_id,
        "validation_config_sha256": _sha256_bytes(config_bytes),
        "candidate_report_sha256": _sha256_bytes(candidate_report_bytes),
        "observation_input_sha256": _sha256_bytes(observation_bytes),
        "training_splits_excluded_from_estimation": ["discovery", "selection"],
        "replay_excluded_from_estimation": True,
        "results": [item.model_dump(mode="json") for item in results],
        "audit": [
            item.model_dump(mode="json")
            for item in sorted(
                audit_by_observation.values(),
                key=lambda item: (item.spec_id, item.split, item.observation_id, item.disposition),
            )
        ],
        "overall_limitations": [
            "Validation outcomes apply only to the predeclared tested backend/scenarios and listed conditions.",
            "A validated candidate is not yet a validated operational knowledge record or policy authorization.",
            "No randomization, physical calibration or causal identification beyond the declared contrast is inferred by this validator.",
            "The Student-t interval uses a fixed deterministic critical-value table through 30 degrees of freedom and a Cornish-Fisher approximation above that.",
            "The tool performs offline statistical checks only; it does not execute runs or alter policy.",
        ],
    }
    report_data["report_id"] = "valreport-" + _sha256_value(report_data)[:24]
    try:
        return IndependentValidationReport.model_validate(report_data)
    except Exception as exc:
        raise IndependentValidationError(
            "report_contract_failure",
            f"internal report did not satisfy output contract: {type(exc).__name__}",
        ) from None


def save_report_atomic(
    report: IndependentValidationReport, path: str | Path, max_bytes: int
) -> str:
    destination = Path(path)
    payload = (
        json.dumps(
            report.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > max_bytes:
        raise IndependentValidationError(
            "report_too_large", "validation report exceeds configured max_report_bytes"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_name, destination)
        except FileExistsError:
            if destination.read_bytes() != payload:
                raise IndependentValidationError(
                    "output_conflict", "refusing to overwrite a different existing report"
                ) from None
        os.chmod(destination, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return _sha256_bytes(payload)


def validate_files(
    config_path: str | Path, candidate_report_path: str | Path, observations_path: str | Path
) -> tuple[IndependentValidationReport, Session12Config]:
    config, config_bytes = load_config(config_path)
    candidate_report, candidate_report_bytes = load_candidate_report(candidate_report_path, config)
    observations, observation_bytes = read_observations(observations_path, config)
    report = validate_candidates(
        candidate_report,
        observations,
        config,
        candidate_report_bytes=candidate_report_bytes,
        observation_bytes=observation_bytes,
        config_bytes=config_bytes,
    )
    return report, config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Independently validate provisional RESILIANT-Z candidates from predeclared held-out data; does not execute experiments."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        report, config = validate_files(args.config, args.candidate_report, args.observations)
        digest = save_report_atomic(report, args.output, config.max_report_bytes)
    except IndependentValidationError as exc:
        print(f"ERROR [{exc.code}]: {exc.detail}")
        return 2
    print(f"Validation report: {report.report_id}")
    print(f"Candidates: {len(report.results)}")
    for result in report.results:
        effect = (
            "unavailable"
            if result.mean_effect is None
            else f"{result.mean_effect:.6g} {result.target_unit or ''}".strip()
        )
        print(
            f"  {result.spec_id}: {result.status} ({result.pair_count} replicates, effect={effect})"
        )
    print(f"Report SHA-256: {digest}")
    print("No simulator, model provider, network endpoint or cloud job was invoked.")
    print("Validation status does not itself create or promote a fleet-knowledge record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
