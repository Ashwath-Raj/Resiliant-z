"""Compile provisional fleet hypotheses into a bounded, non-executing experiment DSL.

The compiler trusts the registered scenario and local compiler configuration, never
model-generated code. Version 1 emits paired single-factor manifests only; seed
allocation and run-state tracking are deliberately deferred to Session 8.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from resiliant_z.hypothesis_provider import HypothesisProposal
from resiliant_z.scenario_spec import WarehouseScenario, load_warehouse_scenario

SchemaVersion = Literal["1.0.0"]
ParameterKind = Literal["scenario_factor", "policy_parameter"]
ParameterType = Literal["float", "integer"]
BackendId = Literal["discrete_event", "surrogate"]
Direction = Literal["increase", "decrease", "no_change", "non_monotonic"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompilerConfig(StrictModel):
    """Trusted limits for semantic compilation; not supplied by the LLM."""

    schema_version: SchemaVersion = "1.0.0"
    config_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    allowed_scenario_ids: list[str] = Field(min_length=1, max_length=50)
    allowed_backends: list[BackendId] = Field(min_length=1, max_length=2)
    allowed_metrics: list[str] = Field(min_length=1, max_length=100)
    parameter_types: dict[str, ParameterType] = Field(min_length=1, max_length=100)
    supported_interactions: list[str] = Field(default_factory=list, max_length=20)
    default_horizon_seconds: float = Field(default=300.0, gt=0, le=86400, allow_inf_nan=False)
    max_horizon_seconds: float = Field(default=3600.0, gt=0, le=86400, allow_inf_nan=False)
    default_replicates_per_arm: int = Field(default=3, ge=1, le=100)
    max_replicates_per_arm: int = Field(default=12, ge=1, le=100)
    max_run_count: int = Field(default=48, ge=2, le=200)
    max_hypothesis_bytes: int = Field(default=32768, ge=512, le=262144)
    max_manifest_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @model_validator(mode="after")
    def validate_limits_and_registry(self) -> CompilerConfig:
        for name, items in (
            ("allowed_scenario_ids", self.allowed_scenario_ids),
            ("allowed_backends", self.allowed_backends),
            ("allowed_metrics", self.allowed_metrics),
            ("supported_interactions", self.supported_interactions),
        ):
            if len(set(items)) != len(items):
                raise ValueError(f"{name} must contain unique entries")
        if self.default_horizon_seconds > self.max_horizon_seconds:
            raise ValueError("default_horizon_seconds cannot exceed max_horizon_seconds")
        if self.default_replicates_per_arm > self.max_replicates_per_arm:
            raise ValueError("default_replicates_per_arm cannot exceed max_replicates_per_arm")
        if 2 * self.default_replicates_per_arm > self.max_run_count:
            raise ValueError("default replicate count exceeds max_run_count")
        for item in self.allowed_metrics:
            if not item.strip():
                raise ValueError("allowed_metrics entries must be non-empty")
        for interaction in self.supported_interactions:
            parts = interaction.split(":")
            if len(parts) != 2 or not all(parts):
                raise ValueError("interaction IDs must use 'parameter_a:parameter_b' form")
            if parts[0] == parts[1]:
                raise ValueError("an interaction must refer to two different parameters")
        return self


def load_compiler_config(path: str | Path) -> CompilerConfig:
    return CompilerConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


class RegisteredParameter(StrictModel):
    kind: ParameterKind
    parameter_id: str = Field(min_length=1, max_length=128)
    value_type: ParameterType
    unit: str = Field(min_length=1, max_length=256)
    min_value: float = Field(allow_inf_nan=False)
    max_value: float = Field(allow_inf_nan=False)
    registered_values: list[float] = Field(min_length=1, max_length=100)
    default_value: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_registry_entry(self) -> RegisteredParameter:
        if self.min_value > self.max_value:
            raise ValueError("registry min_value cannot exceed max_value")
        if len(set(self.registered_values)) != len(self.registered_values):
            raise ValueError("registered_values must be unique")
        if any(
            value < self.min_value or value > self.max_value for value in self.registered_values
        ):
            raise ValueError("registered_values must lie within the registered range")
        if self.value_type == "integer":
            all_values = self.registered_values + (
                [] if self.default_value is None else [self.default_value]
            )
            if any(not float(value).is_integer() for value in all_values):
                raise ValueError("integer parameters require integer registry values")
        if (
            self.default_value is not None
            and not self.min_value <= self.default_value <= self.max_value
        ):
            raise ValueError("default_value must lie within the registered range")
        return self


class ExperimentArm(StrictModel):
    arm_id: Literal["control", "treatment"]
    scenario_factors: dict[str, float] = Field(min_length=1, max_length=100)
    policy_parameters: dict[str, float] = Field(min_length=1, max_length=100)


class FocusComparison(StrictModel):
    parameter_id: str
    kind: ParameterKind
    unit: str
    value_type: ParameterType
    control_value: float
    treatment_value: float
    comparison_rule: Literal["nearest_distinct_registered_level"] = (
        "nearest_distinct_registered_level"
    )


class CompiledExperimentManifest(StrictModel):
    """Typed DSL output; contains no commands or executable generated code."""

    schema_version: SchemaVersion = "1.0.0"
    manifest_id: str = Field(pattern=r"^exp-[0-9a-f]{24}$")
    compiler_version: Literal["session7.semantic-compiler.v1"] = "session7.semantic-compiler.v1"
    status: Literal["compiled_provisional"] = "compiled_provisional"
    hypothesis_id: str
    hypothesis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_config_id: str
    compiler_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_label: str
    backend_id: BackendId
    target_metric: str
    predicted_direction: Direction
    design_kind: Literal["paired_single_factor"] = "paired_single_factor"
    registry: list[RegisteredParameter] = Field(min_length=2, max_length=100)
    focus: FocusComparison
    control: ExperimentArm
    treatment: ExperimentArm
    interaction_terms: list[str] = Field(default_factory=list, max_length=20)
    horizon_seconds: float = Field(gt=0, allow_inf_nan=False)
    replicates_per_arm: int = Field(ge=1, le=100)
    run_count: int = Field(ge=2, le=200)
    max_run_count_at_compile: int = Field(ge=2, le=200)
    seed_allocation: Literal["deferred_to_session_8_planner"] = "deferred_to_session_8_planner"
    automatic_execution: Literal[False] = False
    promotion_status: Literal["provisional_not_validated"] = "provisional_not_validated"
    notice: Literal[
        "Compilation creates a specification only; it does not execute a backend or establish causality."
    ] = "Compilation creates a specification only; it does not execute a backend or establish causality."

    @model_validator(mode="after")
    def validate_manifest_invariants(self) -> CompiledExperimentManifest:
        if self.run_count != 2 * self.replicates_per_arm:
            raise ValueError("run_count must equal two arms multiplied by replicates_per_arm")
        if self.run_count > self.max_run_count_at_compile:
            raise ValueError("run_count exceeds max_run_count_at_compile")
        if self.focus.parameter_id not in {item.parameter_id for item in self.registry}:
            raise ValueError("focus parameter is not present in the registry")
        control_focus = _arm_value(self.control, self.focus.kind, self.focus.parameter_id)
        treatment_focus = _arm_value(self.treatment, self.focus.kind, self.focus.parameter_id)
        if not math.isclose(control_focus, self.focus.control_value, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("control arm focus value does not match focus metadata")
        if not math.isclose(treatment_focus, self.focus.treatment_value, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("treatment arm focus value does not match focus metadata")
        if math.isclose(control_focus, treatment_focus, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("control and treatment must differ on the focus parameter")
        if self.automatic_execution is not False:
            raise ValueError("automatic execution must remain disabled")
        return self


class ExperimentCompileError(ValueError):
    """Actionable, credential-free compile rejection."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _arm_value(arm: ExperimentArm, kind: ParameterKind, parameter_id: str) -> float:
    values = arm.scenario_factors if kind == "scenario_factor" else arm.policy_parameters
    return values[parameter_id]


def _within(value: float, allowed_values: list[float]) -> bool:
    return any(
        math.isclose(value, candidate, rel_tol=0.0, abs_tol=1e-9) for candidate in allowed_values
    )


def _registered_parameters(
    scenario: WarehouseScenario, config: CompilerConfig
) -> list[RegisteredParameter]:
    ids = [item.factor_id for item in scenario.scenario_factors] + [
        item.parameter_id for item in scenario.policy_parameters
    ]
    missing_types = sorted(set(ids) - set(config.parameter_types))
    unknown_types = sorted(set(config.parameter_types) - set(ids))
    if missing_types or unknown_types:
        raise ExperimentCompileError(
            "parameter_type_registry_mismatch",
            f"parameter_types must exactly cover scenario parameters; missing={missing_types}, unknown={unknown_types}",
        )
    registry: list[RegisteredParameter] = []
    for factor in scenario.scenario_factors:
        if config.parameter_types[factor.factor_id] == "integer" and any(
            not float(value).is_integer() for value in factor.test_levels
        ):
            raise ExperimentCompileError(
                "invalid_parameter_type_registry",
                f"factor {factor.factor_id!r} is typed integer but its registered test levels are not all integers",
            )
        registry.append(
            RegisteredParameter(
                kind="scenario_factor",
                parameter_id=factor.factor_id,
                value_type=config.parameter_types[factor.factor_id],
                unit=factor.unit,
                min_value=factor.min_value,
                max_value=factor.max_value,
                registered_values=factor.test_levels,
            )
        )
    for parameter in scenario.policy_parameters:
        registered_values = set(parameter.candidate_values + [parameter.default_value])
        if config.parameter_types[parameter.parameter_id] == "integer" and any(
            not float(value).is_integer() for value in registered_values
        ):
            raise ExperimentCompileError(
                "invalid_parameter_type_registry",
                f"policy parameter {parameter.parameter_id!r} is typed integer but its registered values are not all integers",
            )
        registry.append(
            RegisteredParameter(
                kind="policy_parameter",
                parameter_id=parameter.parameter_id,
                value_type=config.parameter_types[parameter.parameter_id],
                unit=parameter.unit,
                min_value=parameter.min_value,
                max_value=parameter.max_value,
                registered_values=sorted(
                    set(parameter.candidate_values + [parameter.default_value])
                ),
                default_value=parameter.default_value,
            )
        )
    return registry


def _parse_hypothesis(
    hypothesis: HypothesisProposal | Mapping[str, object] | str,
) -> HypothesisProposal:
    try:
        if isinstance(hypothesis, HypothesisProposal):
            # Re-validate a plain dump so downstream code has one parsing path.
            return HypothesisProposal.model_validate(hypothesis.model_dump(mode="python"))
        if isinstance(hypothesis, str):
            try:
                parsed = json.loads(hypothesis)
            except json.JSONDecodeError as exc:
                raise ExperimentCompileError(
                    "malformed_json",
                    f"hypothesis JSON is invalid at line {exc.lineno}, column {exc.colno}",
                ) from None
            if not isinstance(parsed, dict):
                raise ExperimentCompileError(
                    "invalid_hypothesis_shape", "the hypothesis document must be one JSON object"
                )
            return HypothesisProposal.model_validate(parsed)
        return HypothesisProposal.model_validate(hypothesis)
    except ExperimentCompileError:
        raise
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        raise ExperimentCompileError(
            "invalid_hypothesis_schema", f"missing or invalid fields: {fields}"
        ) from None
    except (TypeError, ValueError):
        raise ExperimentCompileError(
            "invalid_hypothesis_schema", "hypothesis could not be parsed as the registered schema"
        ) from None


def compile_hypothesis(
    hypothesis: HypothesisProposal | Mapping[str, object] | str,
    scenario: WarehouseScenario,
    config: CompilerConfig,
    *,
    backend_id: BackendId = "discrete_event",
    horizon_seconds: float | None = None,
    replicates_per_arm: int | None = None,
    interaction_terms: list[str] | None = None,
) -> CompiledExperimentManifest:
    """Compile one trusted-schema proposal to deterministic bounded DSL output.

    Only one registered variable changes between the control and treatment arms.
    Interactions are explicitly rejected unless an interaction design is added in
    a future compiler version; merely adding a string to model output never enables it.
    """
    try:
        hypothesis_size = (
            len(hypothesis.encode("utf-8"))
            if isinstance(hypothesis, str)
            else len(_canonical_bytes(hypothesis))
        )
    except (TypeError, ValueError):
        raise ExperimentCompileError(
            "invalid_hypothesis_schema", "hypothesis could not be serialized safely"
        ) from None
    if hypothesis_size > config.max_hypothesis_bytes:
        raise ExperimentCompileError(
            "hypothesis_too_large",
            f"hypothesis input is {hypothesis_size} bytes; maximum is {config.max_hypothesis_bytes}",
        )
    proposal = _parse_hypothesis(hypothesis)
    interaction_terms = list(interaction_terms or [])
    if scenario.scenario_id not in config.allowed_scenario_ids:
        raise ExperimentCompileError(
            "unsupported_scenario", f"scenario_id {scenario.scenario_id!r} is not allowlisted"
        )
    if proposal.scenario_id != scenario.scenario_id:
        raise ExperimentCompileError(
            "scenario_mismatch", "hypothesis scenario_id must match the trusted scenario"
        )
    if backend_id not in config.allowed_backends:
        raise ExperimentCompileError(
            "unsupported_backend", f"backend {backend_id!r} is not allowlisted"
        )
    if proposal.target_metric not in config.allowed_metrics:
        raise ExperimentCompileError(
            "unregistered_metric", f"target metric {proposal.target_metric!r} is not allowlisted"
        )
    if len(set(interaction_terms)) != len(interaction_terms):
        raise ExperimentCompileError("duplicate_interaction", "interaction terms must be unique")
    unsupported_interactions = sorted(set(interaction_terms) - set(config.supported_interactions))
    if unsupported_interactions:
        raise ExperimentCompileError(
            "unsupported_interaction",
            f"interaction terms are not registered: {unsupported_interactions}",
        )
    if interaction_terms:
        raise ExperimentCompileError(
            "design_not_implemented",
            "Session 7 compiler version 1 supports paired single-factor designs only; interaction designs are deferred",
        )

    horizon = config.default_horizon_seconds if horizon_seconds is None else horizon_seconds
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, (int, float))
        or not math.isfinite(float(horizon))
        or horizon <= 0
    ):
        raise ExperimentCompileError(
            "invalid_horizon", "horizon_seconds must be a finite positive number"
        )
    if horizon > config.max_horizon_seconds:
        raise ExperimentCompileError(
            "horizon_limit_exceeded",
            f"horizon_seconds exceeds configured maximum {config.max_horizon_seconds}",
        )
    repeats = (
        config.default_replicates_per_arm if replicates_per_arm is None else replicates_per_arm
    )
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ExperimentCompileError(
            "invalid_replicates", "replicates_per_arm must be a positive integer"
        )
    if repeats > config.max_replicates_per_arm:
        raise ExperimentCompileError(
            "replicate_limit_exceeded",
            f"replicates_per_arm exceeds configured maximum {config.max_replicates_per_arm}",
        )
    run_count = 2 * repeats
    if run_count > config.max_run_count:
        raise ExperimentCompileError(
            "run_limit_exceeded",
            f"paired design requires {run_count} runs; maximum is {config.max_run_count}",
        )

    registry = _registered_parameters(scenario, config)
    factor_registry = {item.factor_id: item for item in scenario.scenario_factors}
    policy_registry = {item.parameter_id: item for item in scenario.policy_parameters}
    factor_ids = set(factor_registry)
    policy_ids = set(policy_registry)
    if set(proposal.factor_values) != factor_ids:
        raise ExperimentCompileError(
            "factor_registry_mismatch",
            f"factor_values must exactly match registered factors: {sorted(factor_ids)}",
        )
    if set(proposal.policy_values) != policy_ids:
        raise ExperimentCompileError(
            "policy_registry_mismatch",
            f"policy_values must exactly match registered policy parameters: {sorted(policy_ids)}",
        )
    focus_id = proposal.focus_variable_id
    if focus_id in factor_ids:
        focus_kind: ParameterKind = "scenario_factor"
        focus_entry = factor_registry[focus_id]
        control_candidates = [
            value
            for value in focus_entry.test_levels
            if not math.isclose(value, proposal.factor_values[focus_id], rel_tol=0.0, abs_tol=1e-9)
        ]
        treatment_value = proposal.factor_values[focus_id]
        if not _within(treatment_value, focus_entry.test_levels):
            raise ExperimentCompileError(
                "factor_value_out_of_registry",
                f"{focus_id!r} must use one of the registered test levels {focus_entry.test_levels}",
            )
        if not control_candidates:
            raise ExperimentCompileError(
                "no_control_level",
                f"factor {focus_id!r} has no registered level distinct from the treatment",
            )
        control_value = min(
            control_candidates, key=lambda value: (abs(value - treatment_value), value)
        )
    elif focus_id in policy_ids:
        focus_kind = "policy_parameter"
        focus_entry = policy_registry[focus_id]
        allowed_values = sorted(set(focus_entry.candidate_values + [focus_entry.default_value]))
        treatment_value = proposal.policy_values[focus_id]
        if not _within(treatment_value, allowed_values):
            raise ExperimentCompileError(
                "policy_value_out_of_registry",
                f"{focus_id!r} must use a registered candidate/default value {allowed_values}",
            )
        control_candidates = [
            value
            for value in allowed_values
            if not math.isclose(value, treatment_value, rel_tol=0.0, abs_tol=1e-9)
        ]
        if not control_candidates:
            raise ExperimentCompileError(
                "no_control_level", f"policy parameter {focus_id!r} has no registered control value"
            )
        control_value = min(
            control_candidates, key=lambda value: (abs(value - treatment_value), value)
        )
    else:
        raise ExperimentCompileError(
            "unregistered_focus_variable", f"focus variable {focus_id!r} is not registered"
        )

    for factor_id, factor in factor_registry.items():
        value = proposal.factor_values[factor_id]
        if not math.isfinite(value) or value < factor.min_value or value > factor.max_value:
            raise ExperimentCompileError(
                "factor_value_out_of_range",
                f"factor {factor_id!r} must be between {factor.min_value} and {factor.max_value}",
            )
        if not _within(value, factor.test_levels):
            raise ExperimentCompileError(
                "factor_value_out_of_registry",
                f"factor {factor_id!r} must use registered test levels {factor.test_levels}",
            )
        if config.parameter_types[factor_id] == "integer" and not float(value).is_integer():
            raise ExperimentCompileError(
                "parameter_type_mismatch", f"factor {factor_id!r} is registered as integer"
            )
    for parameter_id, parameter in policy_registry.items():
        value = proposal.policy_values[parameter_id]
        allowed_values = list(parameter.candidate_values) + [parameter.default_value]
        if not math.isfinite(value) or value < parameter.min_value or value > parameter.max_value:
            raise ExperimentCompileError(
                "policy_value_out_of_range",
                f"policy parameter {parameter_id!r} must be between {parameter.min_value} and {parameter.max_value}",
            )
        if not _within(value, allowed_values):
            raise ExperimentCompileError(
                "policy_value_out_of_registry",
                f"policy parameter {parameter_id!r} must use registered candidate/default values {sorted(set(allowed_values))}",
            )
        if config.parameter_types[parameter_id] == "integer" and not float(value).is_integer():
            raise ExperimentCompileError(
                "parameter_type_mismatch",
                f"policy parameter {parameter_id!r} is registered as integer",
            )

    factors_control = dict(proposal.factor_values)
    factors_treatment = dict(proposal.factor_values)
    policies_control = dict(proposal.policy_values)
    policies_treatment = dict(proposal.policy_values)
    if focus_kind == "scenario_factor":
        factors_control[focus_id] = control_value
    else:
        policies_control[focus_id] = control_value

    registered_by_id = {item.parameter_id: item for item in registry}
    focus_definition = registered_by_id[focus_id]
    comparison = FocusComparison(
        parameter_id=focus_id,
        kind=focus_kind,
        unit=focus_definition.unit,
        value_type=focus_definition.value_type,
        control_value=control_value,
        treatment_value=treatment_value,
    )
    control_arm = ExperimentArm(
        arm_id="control", scenario_factors=factors_control, policy_parameters=policies_control
    )
    treatment_arm = ExperimentArm(
        arm_id="treatment", scenario_factors=factors_treatment, policy_parameters=policies_treatment
    )
    # A paired single-factor manifest must differ in exactly the declared coordinate.
    factor_differences = [
        key
        for key in factors_control
        if not math.isclose(factors_control[key], factors_treatment[key], rel_tol=0.0, abs_tol=1e-9)
    ]
    policy_differences = [
        key
        for key in policies_control
        if not math.isclose(
            policies_control[key], policies_treatment[key], rel_tol=0.0, abs_tol=1e-9
        )
    ]
    expected_differences = [focus_id] if focus_kind == "scenario_factor" else []
    expected_policy_differences = [focus_id] if focus_kind == "policy_parameter" else []
    if (
        factor_differences != expected_differences
        or policy_differences != expected_policy_differences
    ):
        raise ExperimentCompileError(
            "paired_design_invariant_failed",
            "control and treatment must differ only on the declared focus variable",
        )

    provisional = {
        "schema_version": "1.0.0",
        "compiler_version": "session7.semantic-compiler.v1",
        "status": "compiled_provisional",
        "hypothesis_id": proposal.hypothesis_id,
        "hypothesis_sha256": _sha256(proposal),
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": _sha256(scenario),
        "compiler_config_id": config.config_id,
        "compiler_config_sha256": _sha256(config),
        "evidence_label": scenario.evidence_label,
        "backend_id": backend_id,
        "target_metric": proposal.target_metric,
        "predicted_direction": proposal.predicted_direction,
        "design_kind": "paired_single_factor",
        "registry": [item.model_dump(mode="json") for item in registry],
        "focus": comparison.model_dump(mode="json"),
        "control": control_arm.model_dump(mode="json"),
        "treatment": treatment_arm.model_dump(mode="json"),
        "interaction_terms": [],
        "horizon_seconds": float(horizon),
        "replicates_per_arm": repeats,
        "run_count": run_count,
        "max_run_count_at_compile": config.max_run_count,
        "seed_allocation": "deferred_to_session_8_planner",
        "automatic_execution": False,
        "promotion_status": "provisional_not_validated",
        "notice": "Compilation creates a specification only; it does not execute a backend or establish causality.",
    }
    manifest_id = "exp-" + hashlib.sha256(_canonical_bytes(provisional)).hexdigest()[:24]
    try:
        manifest = CompiledExperimentManifest.model_validate(
            {"manifest_id": manifest_id, **provisional}
        )
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        raise ExperimentCompileError(
            "compiler_manifest_invalid", f"generated manifest failed its own schema: {fields}"
        ) from None
    manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8")
    if len(manifest_bytes) > config.max_manifest_bytes:
        raise ExperimentCompileError(
            "manifest_too_large",
            f"compiled manifest is {len(manifest_bytes)} bytes; maximum is {config.max_manifest_bytes}",
        )
    return manifest


def save_manifest_atomic(path: str | Path, manifest: CompiledExperimentManifest) -> None:
    """Write typed compiler output atomically without executing any planned runs."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile one provisional hypothesis to a bounded experiment manifest (no execution)."
    )
    parser.add_argument(
        "--hypothesis", required=True, help="Path to one HypothesisProposal JSON object"
    )
    parser.add_argument("--scenario", default="configs/warehouse_scenario.example.v1.json")
    parser.add_argument("--config", default="configs/experiment-compiler/session7_config.v1.json")
    parser.add_argument("--output", required=True, help="Output path for compiled manifest JSON")
    parser.add_argument(
        "--backend", choices=("discrete_event", "surrogate"), default="discrete_event"
    )
    parser.add_argument("--horizon-seconds", type=float, default=None)
    parser.add_argument("--replicates-per-arm", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        config = load_compiler_config(args.config)
        scenario = load_warehouse_scenario(args.scenario)
        raw_hypothesis = Path(args.hypothesis).read_text(encoding="utf-8")
        manifest = compile_hypothesis(
            raw_hypothesis,
            scenario,
            config,
            backend_id=args.backend,
            horizon_seconds=args.horizon_seconds,
            replicates_per_arm=args.replicates_per_arm,
        )
        save_manifest_atomic(args.output, manifest)
    except (OSError, ExperimentCompileError, ValidationError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"Compiled provisional manifest: {manifest.manifest_id}")
    print(f"Scenario/backend: {manifest.scenario_id} / {manifest.backend_id}")
    print(
        f"Design: {manifest.design_kind}; runs={manifest.run_count}; horizon={manifest.horizon_seconds:g}s"
    )
    print(
        f"Focus: {manifest.focus.parameter_id} {manifest.focus.control_value:g} -> {manifest.focus.treatment_value:g} {manifest.focus.unit}"
    )
    print(f"Output: {args.output}")
    print("No backend was executed. Seed allocation is deferred to Session 8.")
    return 0


if __name__ == "__main__":  # pragma: no cover - covered by main-level test
    raise SystemExit(main())
