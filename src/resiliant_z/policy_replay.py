"""Fail-closed policy proposal checks and paired replay analysis for RESILIANT-Z Session 14.

This module analyzes already-produced replay records. It does not launch a simulator,
contact a service, mutate a live controller, or apply a policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resiliant_z.knowledge_model import (
    KnowledgeRecord,
    PolicyProposal,
    PolicyUpdateConfig,
    load_ledger,
    load_policy_config,
    records_from_ledger,
)

SCHEMA_VERSION = "1.0.0"
MAX_REPLAY_INPUT_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
Quality = Literal["measured", "missing", "stale", "not_measured", "not_applicable", "invalid"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ReplayError(ValueError):
    """Stable, machine-readable policy replay error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class NumericObservation(StrictModel):
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=64)
    quality: Quality
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def quality_matches_value(self) -> NumericObservation:
        if self.quality == "measured":
            if self.value is None:
                raise ValueError("measured observations require a numeric value; zero is valid")
        elif self.value is not None:
            raise ValueError("unmeasured observations must not carry a numeric value")
        if self.quality != "measured" and not (self.reason and self.reason.strip()):
            raise ValueError("unmeasured observations require a reason")
        return self


class ParameterBounds(StrictModel):
    minimum: float = Field(allow_inf_nan=False)
    maximum: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_bounds(self) -> ParameterBounds:
        if self.minimum >= self.maximum:
            raise ValueError("parameter bounds minimum must be less than maximum")
        return self


class GuardrailMetric(StrictModel):
    metric_id: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=64)
    expected_change: Literal["non_increase", "non_decrease"] = "non_increase"


class Session14Config(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    config_id: str = Field(min_length=1, max_length=128)
    allowed_policy_parameters: list[str] = Field(min_length=1, max_length=64)
    parameter_bounds: dict[str, ParameterBounds]
    max_absolute_policy_delta: float = Field(gt=0.0, le=1.0, allow_inf_nan=False)
    minimum_complete_pairs: int = Field(default=4, ge=2, le=1000)
    maximum_replay_pairs: int = Field(default=10000, ge=1, le=100000)
    primary_metric_id: str = Field(min_length=1, max_length=128)
    primary_metric_unit: str = Field(min_length=1, max_length=64)
    primary_metric_direction: Literal["lower_is_better", "higher_is_better"]
    minimum_practical_improvement: float = Field(gt=0.0, allow_inf_nan=False)
    guardrail_metrics: list[GuardrailMetric] = Field(default_factory=list, max_length=50)
    require_all_guardrails_measured_for_review: Literal[True] = True
    max_config_bytes: int = Field(default=MAX_CONFIG_BYTES, ge=1024, le=MAX_CONFIG_BYTES)
    max_input_bytes: int = Field(default=MAX_REPLAY_INPUT_BYTES, ge=1024, le=MAX_REPLAY_INPUT_BYTES)
    max_report_bytes: int = Field(default=MAX_REPORT_BYTES, ge=1024, le=MAX_REPORT_BYTES)

    @model_validator(mode="after")
    def unique_config_fields(self) -> Session14Config:
        if len(self.allowed_policy_parameters) != len(set(self.allowed_policy_parameters)):
            raise ValueError("allowed_policy_parameters must be unique")
        if set(self.allowed_policy_parameters) != set(self.parameter_bounds):
            raise ValueError("parameter_bounds keys must exactly match allowed_policy_parameters")
        metric_ids = [item.metric_id for item in self.guardrail_metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("guardrail metric IDs must be unique")
        if self.primary_metric_id in metric_ids:
            raise ValueError("primary metric must not also be declared as a guardrail")
        return self


class ReplaySide(StrictModel):
    run_id: str = Field(min_length=1, max_length=200)
    seed: int = Field(ge=0, le=2**31 - 1)
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: str = Field(min_length=1, max_length=128)
    initial_state_id: str = Field(min_length=1, max_length=128)
    task_pattern_id: str = Field(min_length=1, max_length=128)
    workload_pattern_id: str = Field(min_length=1, max_length=128)
    policy_parameters: dict[str, float]
    metrics: dict[str, NumericObservation]

    @model_validator(mode="after")
    def finite_policy_parameters(self) -> ReplaySide:
        if any(not math.isfinite(value) for value in self.policy_parameters.values()):
            raise ValueError("policy parameters must be finite")
        return self


class ReplayPair(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    pair_id: str = Field(min_length=1, max_length=200)
    split: Literal["replay"] = "replay"
    conditions: dict[str, NumericObservation]
    baseline: ReplaySide
    candidate: ReplaySide

    @model_validator(mode="after")
    def pair_is_matched(self) -> ReplayPair:
        left, right = self.baseline, self.candidate
        for field in (
            "seed",
            "scenario_id",
            "backend_id",
            "initial_state_id",
            "task_pattern_id",
            "workload_pattern_id",
        ):
            if getattr(left, field) != getattr(right, field):
                raise ValueError(f"baseline and candidate must match on {field}")
        if left.run_id == right.run_id:
            raise ValueError("baseline and candidate run_id values must differ")
        if set(left.policy_parameters) != set(right.policy_parameters):
            raise ValueError("baseline and candidate must declare identical policy parameter keys")
        return self


class PairAudit(StrictModel):
    pair_id: str
    seed: int
    disposition: Literal["included", "excluded", "blocked"]
    reason_codes: list[str] = Field(default_factory=list)


class PairedSummary(StrictModel):
    metric_id: str
    unit: str
    direction: Literal["lower_is_better", "higher_is_better"]
    n_pairs: int = Field(ge=0)
    mean_baseline: float | None = None
    mean_candidate: float | None = None
    mean_raw_delta_candidate_minus_baseline: float | None = None
    mean_improvement: float | None = None
    sample_sd_improvement: float | None = None
    confidence_interval_95_low: float | None = None
    confidence_interval_95_high: float | None = None
    confidence_method: str = (
        "two-sided Student-t; tabulated critical values df<=30, normal approximation above 30"
    )
    effect_status: Literal[
        "insufficient_pairs",
        "candidate_benefit_observed",
        "candidate_regression_observed",
        "inconclusive",
    ]


class GuardrailSummary(StrictModel):
    metric_id: str
    unit: str
    measured_pairs: int = Field(ge=0)
    required_pairs: int = Field(ge=0)
    status: Literal[
        "measured_pass", "regression_detected", "unmeasured_or_missing", "unit_mismatch"
    ]
    worsening_pair_ids: list[str] = Field(default_factory=list)


class PolicyReplayReport(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    report_id: str = Field(pattern=r"^replayreport-[0-9a-f]{24}$")
    report_status: Literal["blocked", "analyzed"]
    candidate_effect_status: Literal[
        "not_analyzed",
        "insufficient_pairs",
        "candidate_benefit_observed",
        "candidate_regression_observed",
        "inconclusive",
    ]
    operational_review_status: Literal[
        "blocked_policy_gate",
        "blocked_guardrails_unmeasured",
        "blocked_guardrail_regression",
        "not_eligible_for_review",
        "eligible_for_human_review_not_applied",
    ]
    knowledge_id: str
    proposal_id: str
    policy_parameter_id: str | None
    current_value: float | None
    proposed_value: float | None
    blocker_codes: list[str] = Field(default_factory=list)
    source_sha256: dict[str, str]
    pair_audit: list[PairAudit]
    paired_summary: PairedSummary | None = None
    guardrails: list[GuardrailSummary] = Field(default_factory=list)
    live_policy_modified: Literal[False] = False
    automatic_application_allowed: Literal[False] = False
    human_approval_required: Literal[True] = True
    limitations: list[str]


_T_CRIT_95 = {
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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_limited(path: str | Path, limit: int, label: str) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ReplayError("unsafe_input_path", f"{label} must be a regular non-symlink file")
    try:
        raw = source.read_bytes()
    except OSError:
        raise ReplayError("input_read_error", f"could not read {label}") from None
    if len(raw) > limit:
        raise ReplayError("input_too_large", f"{label} exceeds the configured byte limit")
    return raw


def load_config(path: str | Path) -> tuple[Session14Config, bytes]:
    raw = _read_limited(path, MAX_CONFIG_BYTES, "session14_config")
    try:
        return Session14Config.model_validate_json(raw), raw
    except Exception as exc:
        raise ReplayError(
            "config_invalid", f"Session 14 config failed validation: {type(exc).__name__}"
        ) from None


def load_replay_pairs(
    path: str | Path, max_bytes: int, max_pairs: int
) -> tuple[list[ReplayPair], bytes]:
    raw = _read_limited(path, max_bytes, "replay_pairs")
    pairs: list[ReplayPair] = []
    try:
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                pairs.append(ReplayPair.model_validate(data))
            except Exception as exc:
                raise ReplayError(
                    "replay_pair_invalid",
                    f"invalid replay pair at line {line_number}: {type(exc).__name__}",
                ) from None
            if len(pairs) > max_pairs:
                raise ReplayError(
                    "replay_pair_limit_exceeded", "replay pair count exceeds configured maximum"
                )
    except UnicodeDecodeError:
        raise ReplayError(
            "replay_input_encoding_invalid", "replay-pair file must be UTF-8"
        ) from None
    if not pairs:
        raise ReplayError("replay_pairs_empty", "at least one replay pair is required")
    pair_ids = [item.pair_id for item in pairs]
    seeds = [item.baseline.seed for item in pairs]
    run_ids = [side.run_id for item in pairs for side in (item.baseline, item.candidate)]
    if (
        len(pair_ids) != len(set(pair_ids))
        or len(seeds) != len(set(seeds))
        or len(run_ids) != len(set(run_ids))
    ):
        raise ReplayError(
            "replay_identity_duplicate",
            "pair IDs, replay seeds and run IDs must be globally unique",
        )
    return pairs, raw


def load_proposal(path: str | Path, limit: int = MAX_CONFIG_BYTES) -> tuple[PolicyProposal, bytes]:
    raw = _read_limited(path, limit, "policy_proposal")
    try:
        return PolicyProposal.model_validate_json(raw), raw
    except Exception as exc:
        raise ReplayError(
            "policy_proposal_invalid", f"policy proposal failed validation: {type(exc).__name__}"
        ) from None


def _lookup_record(
    ledger_path: str | Path, knowledge_id: str
) -> tuple[KnowledgeRecord, str, bytes]:
    raw = _read_limited(ledger_path, 64 * 1024 * 1024, "knowledge_ledger")
    try:
        entries = load_ledger(ledger_path)
        records = records_from_ledger(entries)
    except Exception as exc:
        raise ReplayError(
            "knowledge_ledger_invalid",
            f"knowledge ledger failed integrity checks: {type(exc).__name__}",
        ) from None
    for record, status in records:
        if record.knowledge_id == knowledge_id:
            return record, status, raw
    raise ReplayError(
        "knowledge_record_missing", "proposal knowledge_id is not present in the ledger"
    )


def _promotion_blockers(
    proposal: PolicyProposal,
    proposal_bytes: bytes,
    record: KnowledgeRecord,
    ledger_status: str,
    policy_config: PolicyUpdateConfig,
    policy_config_bytes: bytes,
    config: Session14Config,
    *,
    allow_candidate_replay: bool,
) -> list[str]:
    blockers: list[str] = []
    if proposal.status != "approval_required":
        blockers.append("proposal_not_approval_required")
    if (
        proposal.automatic_application_allowed
        or proposal.applied
        or not proposal.human_approval_required
    ):
        blockers.append("proposal_safety_invariant_failed")
    if not allow_candidate_replay:
        blockers.append("candidate_replay_not_explicitly_authorized")
    if (
        ledger_status not in {"validated_scoped", "restored"}
        or record.lifecycle_status != "validated_scoped"
    ):
        blockers.append("knowledge_lifecycle_not_currently_validated")
    if record.validation_status != "validated":
        blockers.append("knowledge_not_independently_validated")
    if record.operational_gate_status != "eligible_for_policy_review":
        blockers.append("knowledge_operational_gate_blocked")
    if record.operational_gate_reasons:
        blockers.append("knowledge_operational_gate_has_blocker_reasons")
    if record.provenance.backend_id not in policy_config.allowed_operational_backends:
        blockers.append("knowledge_backend_not_allowlisted")
    if record.provenance.evidence_label not in policy_config.allowed_operational_evidence_labels:
        blockers.append("knowledge_evidence_label_not_allowlisted")
    if policy_config.require_calibrated_factors and any(
        c.calibration_status != "calibrated" for c in record.conditions
    ):
        blockers.append("knowledge_conditions_not_calibrated")
    if len(set(record.validated_scenarios)) < policy_config.minimum_validated_scenarios:
        blockers.append("knowledge_context_diversity_insufficient")
    if not record.provenance.evidence_ids:
        blockers.append("knowledge_evidence_links_missing")
    if proposal.knowledge_id != record.knowledge_id or proposal.spec_id != record.spec_id:
        blockers.append("proposal_knowledge_identity_mismatch")
    if proposal.source_candidate_report_sha256 != record.provenance.candidate_report_sha256:
        blockers.append("proposal_candidate_provenance_mismatch")
    if proposal.source_validation_report_sha256 != record.provenance.validation_report_sha256:
        blockers.append("proposal_validation_provenance_mismatch")
    if (
        proposal.policy_config_id != policy_config.config_id
        or proposal.policy_config_sha256 != _sha256(policy_config_bytes)
    ):
        blockers.append("proposal_policy_config_hash_mismatch")
    rule = next((r for r in policy_config.rules if r.spec_id == record.spec_id), None)
    if rule is None:
        blockers.append("policy_rule_not_found")
    elif proposal.target_metric != rule.target_metric or record.target_metric != rule.target_metric:
        blockers.append("policy_target_metric_mismatch")
    parameter_id = proposal.policy_parameter_id
    if not parameter_id or parameter_id not in config.allowed_policy_parameters:
        blockers.append("policy_parameter_not_allowlisted")
    elif proposal.current_value is None or proposal.proposed_value is None:
        blockers.append("proposal_parameter_values_missing")
    else:
        bounds = config.parameter_bounds[parameter_id]
        delta = proposal.proposed_value - proposal.current_value
        if not bounds.minimum <= proposal.current_value <= bounds.maximum:
            blockers.append("current_parameter_out_of_bounds")
        if not bounds.minimum <= proposal.proposed_value <= bounds.maximum:
            blockers.append("proposed_parameter_out_of_bounds")
        if delta == 0.0 or abs(delta) > config.max_absolute_policy_delta:
            blockers.append("policy_delta_out_of_bounds")
        if rule is not None:
            expected_delta = (
                rule.step_size if rule.update_direction == "increase" else -rule.step_size
            )
            if not math.isclose(delta, expected_delta, rel_tol=0.0, abs_tol=1e-9):
                blockers.append("proposal_step_does_not_match_predeclared_rule")
    return sorted(set(blockers))


def _pair_condition_blockers(pair: ReplayPair, record: KnowledgeRecord) -> list[str]:
    reasons: list[str] = []
    if pair.baseline.backend_id != record.provenance.backend_id:
        reasons.append("replay_backend_mismatch")
    if pair.baseline.scenario_id not in record.validated_scenarios:
        reasons.append("scenario_outside_validated_scenarios")
    for condition in record.conditions:
        observation = pair.conditions.get(condition.variable_id)
        if observation is None:
            reasons.append(f"condition_missing:{condition.variable_id}")
            continue
        if observation.quality != "measured" or observation.value is None:
            reasons.append(f"condition_unmeasured:{condition.variable_id}")
            continue
        if observation.unit != condition.unit:
            reasons.append(f"condition_unit_mismatch:{condition.variable_id}")
            continue
        if condition.calibration_status != "calibrated":
            reasons.append(f"condition_not_calibrated:{condition.variable_id}")
            continue
        if not condition.minimum_observed <= observation.value <= condition.maximum_observed:
            reasons.append(f"condition_outside_validated_envelope:{condition.variable_id}")
    return reasons


def _student_t_critical_95(df: int) -> float:
    return _T_CRIT_95.get(df, 1.96)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))


def _audit_guardrail(metric: GuardrailMetric, pairs: list[ReplayPair]) -> GuardrailSummary:
    measured = 0
    worsening: list[str] = []
    unit_mismatch = False
    for pair in pairs:
        left = pair.baseline.metrics.get(metric.metric_id)
        right = pair.candidate.metrics.get(metric.metric_id)
        if (
            left is None
            or right is None
            or left.quality != "measured"
            or right.quality != "measured"
            or left.value is None
            or right.value is None
        ):
            continue
        if left.unit != metric.unit or right.unit != metric.unit:
            unit_mismatch = True
            continue
        measured += 1
        if metric.expected_change == "non_increase" and right.value > left.value:
            worsening.append(pair.pair_id)
        elif metric.expected_change == "non_decrease" and right.value < left.value:
            worsening.append(pair.pair_id)
    if unit_mismatch:
        status = "unit_mismatch"
    elif worsening:
        status = "regression_detected"
    elif measured != len(pairs):
        status = "unmeasured_or_missing"
    else:
        status = "measured_pass"
    return GuardrailSummary(
        metric_id=metric.metric_id,
        unit=metric.unit,
        measured_pairs=measured,
        required_pairs=len(pairs),
        status=status,
        worsening_pair_ids=sorted(worsening),
    )


def _build_summary(pairs: list[ReplayPair], config: Session14Config) -> PairedSummary:
    usable: list[tuple[float, float]] = []
    for pair in pairs:
        baseline = pair.baseline.metrics.get(config.primary_metric_id)
        candidate = pair.candidate.metrics.get(config.primary_metric_id)
        if baseline is None or candidate is None:
            continue
        if (
            baseline.quality != "measured"
            or candidate.quality != "measured"
            or baseline.value is None
            or candidate.value is None
        ):
            continue
        if (
            baseline.unit != config.primary_metric_unit
            or candidate.unit != config.primary_metric_unit
        ):
            continue
        usable.append((baseline.value, candidate.value))
    n = len(usable)
    if n == 0:
        return PairedSummary(
            metric_id=config.primary_metric_id,
            unit=config.primary_metric_unit,
            direction=config.primary_metric_direction,
            n_pairs=0,
            effect_status="insufficient_pairs",
        )
    baseline_values = [x for x, _ in usable]
    candidate_values = [x for _, x in usable]
    improvements = [
        (left - right) if config.primary_metric_direction == "lower_is_better" else (right - left)
        for left, right in usable
    ]
    mean_improvement = _mean(improvements)
    sd = _sample_sd(improvements)
    if n < config.minimum_complete_pairs:
        effect_status: Literal[
            "insufficient_pairs",
            "candidate_benefit_observed",
            "candidate_regression_observed",
            "inconclusive",
        ] = "insufficient_pairs"
    else:
        half_width = _student_t_critical_95(n - 1) * sd / math.sqrt(n)
        low, high = mean_improvement - half_width, mean_improvement + half_width
        if low > 0 and mean_improvement >= config.minimum_practical_improvement:
            effect_status = "candidate_benefit_observed"
        elif high < 0:
            effect_status = "candidate_regression_observed"
        else:
            effect_status = "inconclusive"
        return PairedSummary(
            metric_id=config.primary_metric_id,
            unit=config.primary_metric_unit,
            direction=config.primary_metric_direction,
            n_pairs=n,
            mean_baseline=_mean(baseline_values),
            mean_candidate=_mean(candidate_values),
            mean_raw_delta_candidate_minus_baseline=_mean([right - left for left, right in usable]),
            mean_improvement=mean_improvement,
            sample_sd_improvement=sd,
            confidence_interval_95_low=low,
            confidence_interval_95_high=high,
            effect_status=effect_status,
        )
    return PairedSummary(
        metric_id=config.primary_metric_id,
        unit=config.primary_metric_unit,
        direction=config.primary_metric_direction,
        n_pairs=n,
        mean_baseline=_mean(baseline_values),
        mean_candidate=_mean(candidate_values),
        mean_raw_delta_candidate_minus_baseline=_mean([right - left for left, right in usable]),
        mean_improvement=mean_improvement,
        sample_sd_improvement=sd,
        effect_status=effect_status,
    )


def evaluate_paired_replay(
    proposal: PolicyProposal,
    proposal_bytes: bytes,
    record: KnowledgeRecord,
    ledger_status: str,
    ledger_bytes: bytes,
    policy_config: PolicyUpdateConfig,
    policy_config_bytes: bytes,
    config: Session14Config,
    config_bytes: bytes,
    pairs: list[ReplayPair],
    pairs_bytes: bytes,
    *,
    allow_candidate_replay: bool = False,
) -> PolicyReplayReport:
    blockers = _promotion_blockers(
        proposal,
        proposal_bytes,
        record,
        ledger_status,
        policy_config,
        policy_config_bytes,
        config,
        allow_candidate_replay=allow_candidate_replay,
    )
    source_hashes = {
        "policy_proposal": _sha256(proposal_bytes),
        "knowledge_ledger": _sha256(ledger_bytes),
        "policy_config": _sha256(policy_config_bytes),
        "session14_config": _sha256(config_bytes),
        "replay_pairs": _sha256(pairs_bytes),
    }
    audit: list[PairAudit] = []
    if blockers:
        audit = [
            PairAudit(
                pair_id=p.pair_id,
                seed=p.baseline.seed,
                disposition="blocked",
                reason_codes=blockers,
            )
            for p in pairs
        ]
        status: Literal["blocked", "analyzed"] = "blocked"
        effect_status = "not_analyzed"
        summary = None
        guards: list[GuardrailSummary] = []
        operational_review_status: Literal[
            "blocked_policy_gate",
            "blocked_guardrails_unmeasured",
            "blocked_guardrail_regression",
            "not_eligible_for_review",
            "eligible_for_human_review_not_applied",
        ] = "blocked_policy_gate"
    else:
        analyzed: list[ReplayPair] = []
        for pair in pairs:
            reasons = _pair_condition_blockers(pair, record)
            expected_current = proposal.current_value
            expected_candidate = proposal.proposed_value
            parameter_id = proposal.policy_parameter_id
            assert (
                parameter_id is not None
                and expected_current is not None
                and expected_candidate is not None
            )
            for side_name, side, expected in (
                ("baseline", pair.baseline, expected_current),
                ("candidate", pair.candidate, expected_candidate),
            ):
                if parameter_id not in side.policy_parameters or not math.isclose(
                    side.policy_parameters[parameter_id], expected, rel_tol=0.0, abs_tol=1e-9
                ):
                    reasons.append(f"{side_name}_policy_value_mismatch")
                for key in side.policy_parameters:
                    if key != parameter_id and not math.isclose(
                        side.policy_parameters[key],
                        pair.baseline.policy_parameters[key],
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    ):
                        reasons.append(f"unexpected_policy_change:{key}")
            baseline_metric = pair.baseline.metrics.get(config.primary_metric_id)
            candidate_metric = pair.candidate.metrics.get(config.primary_metric_id)
            if baseline_metric is None or candidate_metric is None:
                reasons.append("primary_metric_missing")
            elif (
                baseline_metric.quality != "measured"
                or candidate_metric.quality != "measured"
                or baseline_metric.value is None
                or candidate_metric.value is None
            ):
                reasons.append("primary_metric_unmeasured")
            elif (
                baseline_metric.unit != config.primary_metric_unit
                or candidate_metric.unit != config.primary_metric_unit
            ):
                reasons.append("primary_metric_unit_mismatch")
            reasons = sorted(set(reasons))
            if reasons:
                audit.append(
                    PairAudit(
                        pair_id=pair.pair_id,
                        seed=pair.baseline.seed,
                        disposition="excluded",
                        reason_codes=reasons,
                    )
                )
            else:
                analyzed.append(pair)
                audit.append(
                    PairAudit(pair_id=pair.pair_id, seed=pair.baseline.seed, disposition="included")
                )
        summary = _build_summary(analyzed, config)
        guards = [_audit_guardrail(item, analyzed) for item in config.guardrail_metrics]
        status = "analyzed"
        effect_status = summary.effect_status
        if effect_status != "candidate_benefit_observed":
            operational_review_status = "not_eligible_for_review"
        elif any(g.status == "regression_detected" for g in guards):
            operational_review_status = "blocked_guardrail_regression"
        elif any(g.status != "measured_pass" for g in guards):
            operational_review_status = "blocked_guardrails_unmeasured"
        else:
            operational_review_status = "eligible_for_human_review_not_applied"
    report_body = {
        "source_sha256": source_hashes,
        "knowledge_id": record.knowledge_id,
        "proposal_id": proposal.proposal_id,
        "status": status,
        "blockers": blockers,
        "pair_audit": [a.model_dump(mode="json") for a in audit],
        "summary": summary.model_dump(mode="json") if summary else None,
        "guards": [g.model_dump(mode="json") for g in guards],
        "operational_review_status": operational_review_status,
    }
    report_id = "replayreport-" + hashlib.sha256(_canonical(report_body)).hexdigest()[:24]
    return PolicyReplayReport(
        report_id=report_id,
        report_status=status,
        candidate_effect_status=effect_status,
        operational_review_status=operational_review_status,
        knowledge_id=record.knowledge_id,
        proposal_id=proposal.proposal_id,
        policy_parameter_id=proposal.policy_parameter_id,
        current_value=proposal.current_value,
        proposed_value=proposal.proposed_value,
        blocker_codes=blockers,
        source_sha256=source_hashes,
        pair_audit=audit,
        paired_summary=summary,
        guardrails=guards,
        limitations=[
            "This report analyzes already-produced paired replay records; it does not execute a simulator or mutate a controller.",
            "Synthetic or uncalibrated evidence cannot pass the operational knowledge gate.",
            "Safety-related metrics remain unmeasured unless the selected backend explicitly measures them; missing values are never treated as zero.",
            "Even eligible results require separate human review; policy application is never automatic.",
        ],
    )


def write_report_no_clobber(
    report: PolicyReplayReport, destination: str | Path, max_bytes: int
) -> str:
    target = Path(destination)
    if target.is_symlink():
        raise ReplayError("unsafe_output_path", "report output must not be a symlink")
    payload = (
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    if len(payload) > max_bytes:
        raise ReplayError(
            "report_too_large", "serialized replay report exceeds configured byte limit"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_name, target)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
                    raise ReplayError(
                        "output_conflict",
                        "refusing to overwrite existing report with different bytes",
                    ) from None
            return _sha256(payload)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    except ReplayError:
        raise
    except OSError:
        raise ReplayError("output_write_error", "could not safely write replay report") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze paired policy replay artifacts; never runs or applies a live policy."
    )
    parser.add_argument("--session14-config", required=True)
    parser.add_argument("--policy-config", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--replay-pairs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--allow-candidate-replay-analysis",
        action="store_true",
        help="Explicitly include a candidate replay for analysis; does not authorize a live policy update.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config, config_bytes = load_config(args.session14_config)
        policy_config, policy_config_bytes = load_policy_config(args.policy_config)
        proposal, proposal_bytes = load_proposal(args.proposal)
        pairs, pairs_bytes = load_replay_pairs(
            args.replay_pairs, config.max_input_bytes, config.maximum_replay_pairs
        )
        record, ledger_status, ledger_bytes = _lookup_record(args.ledger, proposal.knowledge_id)
        report = evaluate_paired_replay(
            proposal,
            proposal_bytes,
            record,
            ledger_status,
            ledger_bytes,
            policy_config,
            policy_config_bytes,
            config,
            config_bytes,
            pairs,
            pairs_bytes,
            allow_candidate_replay=args.allow_candidate_replay_analysis,
        )
        digest = write_report_no_clobber(report, args.output, config.max_report_bytes)
        print(f"Replay report: {report.report_id}")
        print(
            f"Report status: {report.report_status}; candidate effect: {report.candidate_effect_status}"
        )
        print(f"Operational review: {report.operational_review_status}")
        if report.blocker_codes:
            print("Blockers: " + ", ".join(report.blocker_codes))
        if report.paired_summary:
            summary = report.paired_summary
            print(
                f"Paired metric={summary.metric_id} n={summary.n_pairs} mean_improvement={summary.mean_improvement}"
            )
        print(f"Report SHA-256: {digest}")
        print("live_policy_modified=false; automatic_application_allowed=false")
        print("No simulator, network endpoint, model provider, or cloud job was invoked.")
        return 0
    except (ReplayError, OSError, ValueError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
