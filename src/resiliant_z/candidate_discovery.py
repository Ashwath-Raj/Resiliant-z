"""Deterministic, split-aware discovery of provisional fleet relationships.

This module estimates predeclared main effects and two-factor interactions from
local result summaries. It never executes a simulator, calls a model provider,
or promotes a candidate to validated knowledge. Discovery/selection evidence
only is used to estimate candidate effects; validation/replay rows are audited
but excluded from fitting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Literal["1.0.0"]
EvidenceSplit = Literal["discovery", "selection", "validation", "replay"]
BackendId = Literal["discrete_event", "surrogate"]
Quality = Literal["measured", "missing", "stale", "not_applicable", "not_measured"]
CandidateKind = Literal["main_effect", "interaction"]
CandidateOutcome = Literal["shortlisted", "not_shortlisted", "insufficient_evidence"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class FactorDefinition(StrictModel):
    factor_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$"
    )
    unit: str = Field(min_length=1, max_length=256)
    min_value: float = Field(allow_inf_nan=False)
    max_value: float = Field(allow_inf_nan=False)
    calibration_status: Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]

    @model_validator(mode="after")
    def valid_range(self) -> FactorDefinition:
        if not self.unit.strip():
            raise ValueError("factor unit must not be blank")
        if self.min_value >= self.max_value:
            raise ValueError("factor min_value must be less than max_value")
        return self


class CandidateSpec(StrictModel):
    spec_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
    kind: CandidateKind
    variable_ids: list[str] = Field(min_length=1, max_length=2)
    label: str = Field(min_length=8, max_length=256)

    @model_validator(mode="after")
    def valid_design(self) -> CandidateSpec:
        expected = 1 if self.kind == "main_effect" else 2
        if len(self.variable_ids) != expected:
            raise ValueError(f"{self.kind} spec requires exactly {expected} variable(s)")
        if len(set(self.variable_ids)) != len(self.variable_ids):
            raise ValueError("variable_ids must be unique")
        return self


class CandidateDiscoveryConfig(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    config_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: BackendId
    evidence_label: str = Field(min_length=1, max_length=256)
    target_metric: str = Field(min_length=1, max_length=128)
    target_unit: str = Field(min_length=1, max_length=128)
    factor_registry: list[FactorDefinition] = Field(min_length=1, max_length=50)
    candidate_specs: list[CandidateSpec] = Field(min_length=1, max_length=25)
    minimum_observations: int = Field(default=12, ge=6, le=10000)
    minimum_absolute_effect: float = Field(default=1.0, ge=0.0, allow_inf_nan=False)
    confidence_z_value: float = Field(default=1.96, gt=0.0, le=4.0, allow_inf_nan=False)
    max_input_bytes: int = Field(default=8_388_608, ge=1024, le=67_108_864)
    max_observations: int = Field(default=10_000, ge=6, le=100_000)
    max_evidence_ids_per_candidate: int = Field(default=500, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_registry(self) -> CandidateDiscoveryConfig:
        factor_ids = [item.factor_id for item in self.factor_registry]
        spec_ids = [item.spec_id for item in self.candidate_specs]
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("factor_registry IDs must be unique")
        if len(set(spec_ids)) != len(spec_ids):
            raise ValueError("candidate spec IDs must be unique")
        allowed = set(factor_ids)
        for spec in self.candidate_specs:
            unknown = set(spec.variable_ids) - allowed
            if unknown:
                raise ValueError(
                    f"candidate spec {spec.spec_id!r} has unregistered variables: {sorted(unknown)}"
                )
        if not self.target_unit.strip() or not self.evidence_label.strip():
            raise ValueError("target_unit and evidence_label must not be blank")
        return self


class DiscoveryObservation(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    observation_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"
    )
    evidence_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    seed: int = Field(ge=0, le=2_147_483_647)
    split: EvidenceSplit
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: BackendId
    evidence_label: str = Field(min_length=1, max_length=256)
    metric_id: str = Field(min_length=1, max_length=128)
    metric_unit: str = Field(min_length=1, max_length=128)
    value: float | None = Field(default=None, allow_inf_nan=False)
    quality: Quality
    reason: str | None = Field(default=None, max_length=512)
    factor_values: dict[str, float] = Field(default_factory=dict, max_length=50)
    model_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def valid_observation(self) -> DiscoveryObservation:
        if self.quality == "measured":
            if self.value is None:
                raise ValueError("measured observation requires a numeric value; zero is valid")
        else:
            if self.value is not None:
                raise ValueError("unmeasured observation values must be null, never zero-filled")
            if not self.reason or not self.reason.strip():
                raise ValueError("unmeasured observations require a reason")
        if any(not name.strip() for name in self.factor_values):
            raise ValueError("factor value names must not be blank")
        if any(not math.isfinite(value) for value in self.factor_values.values()):
            raise ValueError("factor values must be finite")
        if not self.metric_unit.strip() or not self.evidence_label.strip():
            raise ValueError("metric_unit and evidence_label must not be blank")
        return self


class FactorRange(StrictModel):
    minimum_observed: float = Field(allow_inf_nan=False)
    maximum_observed: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=256)
    calibration_status: Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]


class CandidateFinding(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    candidate_id: str = Field(pattern=r"^cand-[0-9a-f]{24}$")
    spec_id: str
    label: str
    candidate_kind: CandidateKind
    variable_ids: list[str]
    target_metric: str
    target_unit: str
    scenario_id: str
    backend_id: BackendId
    evidence_label: str
    model_version: str
    observation_count: int = Field(ge=0)
    degrees_of_freedom: int = Field(ge=0)
    effect_contrast_definition: str
    estimated_effect: float | None = Field(default=None, allow_inf_nan=False)
    standard_error: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    confidence_interval_95_low: float | None = Field(default=None, allow_inf_nan=False)
    confidence_interval_95_high: float | None = Field(default=None, allow_inf_nan=False)
    effect_direction: Literal[
        "increase", "decrease", "positive_interaction", "negative_interaction", "unclear"
    ]
    factor_ranges: dict[str, FactorRange]
    evidence_ids: list[str] = Field(max_length=500)
    selection_outcome: CandidateOutcome
    selection_reason: str
    lifecycle_status: Literal["provisional"] = "provisional"
    method_id: Literal["coded-ols-normal-approx-v1"] = "coded-ols-normal-approx-v1"


class ObservationAudit(StrictModel):
    observation_id: str
    split: EvidenceSplit
    disposition: Literal["eligible_for_candidate_discovery", "excluded"]
    reason: str


class CandidateDiscoveryReport(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    batch_id: str = Field(pattern=r"^candbatch-[0-9a-f]{24}$")
    status: Literal["provisional_candidates_only"] = "provisional_candidates_only"
    config_id: str
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    backend_id: BackendId
    evidence_label: str
    target_metric: str
    target_unit: str
    training_splits: list[Literal["discovery", "selection"]] = ["discovery", "selection"]
    total_observations_received: int = Field(ge=0)
    eligible_observations: int = Field(ge=0)
    excluded_observation_count: int = Field(ge=0)
    excluded_reasons: dict[str, int]
    candidates: list[CandidateFinding] = Field(max_length=25)
    audit: list[ObservationAudit] = Field(max_length=10000)
    selection_procedure: str
    model_version: Literal["candidate-discovery.ols-coded.v1"] = "candidate-discovery.ols-coded.v1"
    limitations: list[str]


class CandidateDiscoveryError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def load_config(path: str | Path) -> CandidateDiscoveryConfig:
    source = Path(path)
    try:
        raw = source.read_bytes()
        if len(raw) > 1_048_576:
            raise CandidateDiscoveryError(
                "config_too_large", "candidate discovery config exceeds 1 MiB"
            )
        return CandidateDiscoveryConfig.model_validate_json(raw)
    except CandidateDiscoveryError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise CandidateDiscoveryError(
            "config_invalid", f"could not load config: {type(exc).__name__}"
        ) from None


def read_observations_jsonl(
    path: str | Path, config: CandidateDiscoveryConfig
) -> list[DiscoveryObservation]:
    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise CandidateDiscoveryError(
            "input_read_error", f"could not read observation input: {type(exc).__name__}"
        ) from None
    if len(raw) > config.max_input_bytes:
        raise CandidateDiscoveryError(
            "input_too_large", "observation JSONL exceeds configured byte limit"
        )
    rows: list[DiscoveryObservation] = []
    try:
        text = raw.decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(DiscoveryObservation.model_validate_json(line))
            except Exception as exc:
                raise CandidateDiscoveryError(
                    "invalid_observation",
                    f"invalid observation at line {line_number}: {type(exc).__name__}",
                ) from None
            if len(rows) > config.max_observations:
                raise CandidateDiscoveryError(
                    "too_many_observations", "observation count exceeds configured limit"
                )
    except UnicodeError:
        raise CandidateDiscoveryError(
            "input_encoding_error", "observation JSONL must be UTF-8"
        ) from None
    _validate_observation_set(rows, config)
    return rows


def _validate_observation_set(
    rows: Sequence[DiscoveryObservation], config: CandidateDiscoveryConfig
) -> None:
    if len(rows) > config.max_observations:
        raise CandidateDiscoveryError(
            "too_many_observations", "observation count exceeds configured limit"
        )
    observation_ids = [row.observation_id for row in rows]
    run_ids = [row.run_id for row in rows]
    if len(set(observation_ids)) != len(observation_ids):
        raise CandidateDiscoveryError("duplicate_observation_id", "observation IDs must be unique")
    if len(set(run_ids)) != len(run_ids):
        raise CandidateDiscoveryError(
            "duplicate_run_id", "each run may contribute at most one observation"
        )
    split_by_seed: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        split_by_seed[row.seed].add(row.split)
        unknown = set(row.factor_values) - {factor.factor_id for factor in config.factor_registry}
        if unknown:
            raise CandidateDiscoveryError(
                "unknown_factor",
                f"observation {row.observation_id!r} contains unregistered factors: {sorted(unknown)}",
            )
        definitions = {factor.factor_id: factor for factor in config.factor_registry}
        for key, value in row.factor_values.items():
            spec = definitions[key]
            if value < spec.min_value or value > spec.max_value:
                raise CandidateDiscoveryError(
                    "factor_out_of_range",
                    f"observation {row.observation_id!r} has {key!r} outside registered range",
                )
    overlap = {seed: sorted(splits) for seed, splits in split_by_seed.items() if len(splits) > 1}
    if overlap:
        first_seed = sorted(overlap)[0]
        raise CandidateDiscoveryError(
            "split_seed_overlap",
            f"seed {first_seed} appears across evidence splits; seed partitions must be disjoint",
        )


def _invert(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    work = [row[:] + [1.0 if i == j else 0.0 for j in range(size)] for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(work[row][col]))
        if abs(work[pivot][col]) < 1e-10:
            raise ArithmeticError("singular design matrix")
        work[col], work[pivot] = work[pivot], work[col]
        divisor = work[col][col]
        work[col] = [value / divisor for value in work[col]]
        for row in range(size):
            if row == col:
                continue
            multiplier = work[row][col]
            work[row] = [
                value - multiplier * base for value, base in zip(work[row], work[col], strict=True)
            ]
    return [row[size:] for row in work]


def _fit_effect(
    rows: Sequence[DiscoveryObservation], spec: CandidateSpec, config: CandidateDiscoveryConfig
) -> tuple[
    int,
    int,
    float | None,
    float | None,
    float | None,
    float | None,
    dict[str, FactorRange],
    list[str],
    str,
]:
    usable = [
        row for row in rows if all(variable in row.factor_values for variable in spec.variable_ids)
    ]
    n = len(usable)
    p = 2 if spec.kind == "main_effect" else 4
    factor_defs = {item.factor_id: item for item in config.factor_registry}
    ranges: dict[str, FactorRange] = {}
    for variable in spec.variable_ids:
        values = [row.factor_values[variable] for row in usable]
        if values:
            ranges[variable] = FactorRange(
                minimum_observed=min(values),
                maximum_observed=max(values),
                unit=factor_defs[variable].unit,
                calibration_status=factor_defs[variable].calibration_status,
            )
    evidence_ids = sorted({row.evidence_id for row in usable})[
        : config.max_evidence_ids_per_candidate
    ]
    if n < max(config.minimum_observations, p + 2):
        return (
            n,
            max(0, n - p),
            None,
            None,
            None,
            None,
            ranges,
            evidence_ids,
            "insufficient matching measured observations",
        )
    raw_x: list[list[float]] = []
    raw_y: list[float] = []
    for row in usable:
        coded: list[float] = []
        for variable in spec.variable_ids:
            low, high = ranges[variable].minimum_observed, ranges[variable].maximum_observed
            if math.isclose(low, high, rel_tol=0.0, abs_tol=1e-12):
                return (
                    n,
                    max(0, n - p),
                    None,
                    None,
                    None,
                    None,
                    ranges,
                    evidence_ids,
                    f"factor {variable} has no observed variation",
                )
            coded.append(2.0 * (row.factor_values[variable] - low) / (high - low) - 1.0)
        design = (
            [1.0, coded[0]]
            if spec.kind == "main_effect"
            else [1.0, coded[0], coded[1], coded[0] * coded[1]]
        )
        raw_x.append(design)
        raw_y.append(float(row.value))
    xtx = [[sum(row[i] * row[j] for row in raw_x) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * y for row, y in zip(raw_x, raw_y, strict=True)) for i in range(p)]
    try:
        inverse = _invert(xtx)
    except ArithmeticError:
        return (
            n,
            max(0, n - p),
            None,
            None,
            None,
            None,
            ranges,
            evidence_ids,
            "candidate design matrix is rank-deficient",
        )
    beta = [sum(inverse[i][j] * xty[j] for j in range(p)) for i in range(p)]
    residuals = [
        y - sum(a * b for a, b in zip(row, beta, strict=True))
        for row, y in zip(raw_x, raw_y, strict=True)
    ]
    dof = n - p
    if dof <= 0:
        return (
            n,
            max(0, dof),
            None,
            None,
            None,
            None,
            ranges,
            evidence_ids,
            "insufficient degrees of freedom",
        )
    residual_variance = sum(value * value for value in residuals) / dof
    coefficient_variance = residual_variance * inverse[p - 1][p - 1]
    scale = 2.0 if spec.kind == "main_effect" else 4.0
    effect = beta[p - 1] * scale
    standard_error = math.sqrt(max(0.0, coefficient_variance)) * scale
    low_ci = effect - config.confidence_z_value * standard_error
    high_ci = effect + config.confidence_z_value * standard_error
    return (
        n,
        dof,
        effect,
        standard_error,
        low_ci,
        high_ci,
        ranges,
        evidence_ids,
        "estimated from registered coded linear model",
    )


def discover_candidates(
    observations: Sequence[DiscoveryObservation],
    config: CandidateDiscoveryConfig,
) -> CandidateDiscoveryReport:
    _validate_observation_set(observations, config)
    audit: list[ObservationAudit] = []
    excluded_reasons: Counter[str] = Counter()
    fit_rows: list[DiscoveryObservation] = []
    for row in observations:
        reason: str | None = None
        if row.split not in {"discovery", "selection"}:
            reason = "split_not_permitted_for_candidate_discovery"
        elif row.scenario_id != config.scenario_id:
            reason = "scenario_mismatch"
        elif row.backend_id != config.backend_id:
            reason = "backend_mismatch"
        elif row.evidence_label != config.evidence_label:
            reason = "evidence_label_mismatch"
        elif row.metric_id != config.target_metric:
            reason = "metric_mismatch"
        elif row.metric_unit != config.target_unit:
            reason = "metric_unit_mismatch"
        elif row.quality != "measured":
            reason = f"quality_{row.quality}"
        elif row.value is None:
            reason = "measured_value_missing"
        if reason is None:
            fit_rows.append(row)
            audit.append(
                ObservationAudit(
                    observation_id=row.observation_id,
                    split=row.split,
                    disposition="eligible_for_candidate_discovery",
                    reason="matches target metric, scenario, backend, label and allowed split",
                )
            )
        else:
            excluded_reasons[reason] += 1
            audit.append(
                ObservationAudit(
                    observation_id=row.observation_id,
                    split=row.split,
                    disposition="excluded",
                    reason=reason,
                )
            )
    fit_rows.sort(key=lambda item: item.observation_id)
    eligible_digest = _digest([row.model_dump(mode="json") for row in fit_rows])
    config_digest = _digest(config)
    findings: list[CandidateFinding] = []
    for spec in config.candidate_specs:
        n, dof, effect, stderr, low_ci, high_ci, ranges, evidence_ids, fit_reason = _fit_effect(
            fit_rows, spec, config
        )
        variables_ok = all(variable in ranges for variable in spec.variable_ids) and len(
            ranges
        ) == len(spec.variable_ids)
        if (
            effect is None
            or stderr is None
            or low_ci is None
            or high_ci is None
            or not variables_ok
        ):
            outcome: CandidateOutcome = "insufficient_evidence"
            direction = "unclear"
            reason = fit_reason
        else:
            if spec.kind == "main_effect":
                direction = "increase" if effect > 0 else "decrease" if effect < 0 else "unclear"
            else:
                direction = (
                    "positive_interaction"
                    if effect > 0
                    else "negative_interaction"
                    if effect < 0
                    else "unclear"
                )
            interval_excludes_zero = low_ci > 0.0 or high_ci < 0.0
            practically_relevant = abs(effect) >= config.minimum_absolute_effect
            if interval_excludes_zero and practically_relevant:
                outcome = "shortlisted"
                reason = "exploratory interval excludes zero and effect meets configured practical threshold; candidate remains provisional"
            else:
                outcome = "not_shortlisted"
                reason = (
                    "effect does not meet both the configured practical threshold and interval rule"
                )
        identity = _digest(
            {
                "spec_id": spec.spec_id,
                "config_sha256": config_digest,
                "eligible_input_sha256": eligible_digest,
            }
        )[:24]
        model_versions = sorted(
            {
                row.model_version
                for row in fit_rows
                if all(v in row.factor_values for v in spec.variable_ids)
            }
        )
        model_version = ",".join(model_versions)[:128] or "unknown"
        findings.append(
            CandidateFinding(
                candidate_id=f"cand-{identity}",
                spec_id=spec.spec_id,
                label=spec.label,
                candidate_kind=spec.kind,
                variable_ids=spec.variable_ids,
                target_metric=config.target_metric,
                target_unit=config.target_unit,
                scenario_id=config.scenario_id,
                backend_id=config.backend_id,
                evidence_label=config.evidence_label,
                model_version=model_version,
                observation_count=n,
                degrees_of_freedom=dof,
                effect_contrast_definition=(
                    "predicted high-vs-low change across the observed factor range"
                    if spec.kind == "main_effect"
                    else "difference-in-differences contrast across both observed factor ranges"
                ),
                estimated_effect=effect,
                standard_error=stderr,
                confidence_interval_95_low=low_ci,
                confidence_interval_95_high=high_ci,
                effect_direction=direction,
                factor_ranges=ranges,
                evidence_ids=evidence_ids,
                selection_outcome=outcome,
                selection_reason=reason,
                lifecycle_status="provisional",
            )
        )
    batch_digest = _digest(
        {
            "config": config_digest,
            "eligible_input": eligible_digest,
            "candidates": [c.model_dump(mode="json") for c in findings],
        }
    )[:24]
    return CandidateDiscoveryReport(
        batch_id=f"candbatch-{batch_digest}",
        config_id=config.config_id,
        config_sha256=config_digest,
        eligible_input_sha256=eligible_digest,
        scenario_id=config.scenario_id,
        backend_id=config.backend_id,
        evidence_label=config.evidence_label,
        target_metric=config.target_metric,
        target_unit=config.target_unit,
        total_observations_received=len(observations),
        eligible_observations=len(fit_rows),
        excluded_observation_count=len(observations) - len(fit_rows),
        excluded_reasons=dict(sorted(excluded_reasons.items())),
        candidates=findings,
        audit=sorted(audit, key=lambda item: item.observation_id),
        selection_procedure="Predeclared coded OLS: a one-factor model for each main-effect spec and a four-term coded OLS model (intercept, both main effects, product term) for each interaction spec. Candidate is shortlisted only if the exploratory normal-approximate 95% interval excludes zero and the absolute contrast meets the configured practical-effect threshold.",
        limitations=[
            "All candidates remain provisional; this stage does not validate causal relationships or authorize policy changes.",
            "Only discovery and selection splits contribute to fitted coefficients; validation and replay observations are audit-only.",
            "Intervals use a normal critical value and are exploratory; they are not independent confirmation or a substitute for Session 12 validation.",
            "The coded linear model captures only predeclared main effects and two-factor interactions; nonlinear or omitted-variable effects may be missed.",
            "Factor ranges are those observed in the supplied data and do not establish safe operating envelopes.",
        ],
    )


def save_report_atomic(report: CandidateDiscoveryReport, path: str | Path) -> str:
    destination = Path(path)
    payload = (report.model_dump_json(indent=2) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_name, destination)
        except FileExistsError:
            if destination.read_bytes() != payload:
                raise FileExistsError(
                    f"refusing to overwrite existing candidate report with different content: {destination}"
                ) from None
        os.chmod(destination, 0o600)
        return hashlib.sha256(payload).hexdigest()
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover provisional fleet candidates from offline observations; does not execute runs."
    )
    parser.add_argument(
        "--config", required=True, help="trusted versioned candidate-discovery config JSON"
    )
    parser.add_argument("--input", required=True, help="observation JSONL file")
    parser.add_argument(
        "--output",
        required=True,
        help="new report JSON path; conflicting files are not overwritten",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        observations = read_observations_jsonl(args.input, config)
        report = discover_candidates(observations, config)
        digest = save_report_atomic(report, args.output)
    except CandidateDiscoveryError as exc:
        print(f"ERROR {exc.code}: {exc.detail}")
        return 2
    except (OSError, ValueError) as exc:
        print(f"ERROR candidate_discovery_failed: {type(exc).__name__}")
        return 2
    print(f"Candidate batch: {report.batch_id}")
    print(
        f"Eligible observations: {report.eligible_observations}/{report.total_observations_received}"
    )
    print(
        f"Candidates shortlisted (still provisional): {sum(c.selection_outcome == 'shortlisted' for c in report.candidates)}"
    )
    print(f"Report SHA-256: {digest}")
    print("No simulation, model-provider request, network call, or cloud job was invoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
