from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.experiment_compiler import (
    CompiledExperimentManifest,
    CompilerConfig,
    ExperimentCompileError,
    compile_hypothesis,
    load_compiler_config,
    save_manifest_atomic,
)
from resiliant_z.hypothesis_provider import HypothesisProposal
from resiliant_z.scenario_spec import load_warehouse_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = PROJECT_ROOT / "configs" / "warehouse_scenario.example.v1.json"
CONFIG_PATH = PROJECT_ROOT / "configs" / "experiment-compiler" / "session7_config.v1.json"
HYPOTHESIS_PATH = PROJECT_ROOT / "configs" / "experiment-compiler" / "session7_hypothesis.v1.json"


@pytest.fixture()
def context():
    scenario = load_warehouse_scenario(SCENARIO_PATH)
    config = load_compiler_config(CONFIG_PATH)
    proposal = HypothesisProposal.model_validate_json(HYPOTHESIS_PATH.read_text(encoding="utf-8"))
    return scenario, config, proposal


def test_allowlisted_hypothesis_compiles_to_typed_provisional_manifest(context):
    scenario, config, proposal = context
    manifest = compile_hypothesis(proposal, scenario, config)
    assert isinstance(manifest, CompiledExperimentManifest)
    assert manifest.status == "compiled_provisional"
    assert manifest.promotion_status == "provisional_not_validated"
    assert manifest.automatic_execution is False
    assert manifest.seed_allocation == "deferred_to_session_8_planner"
    assert manifest.run_count == 6
    assert manifest.focus.parameter_id == "traffic_demand"
    assert manifest.focus.control_value == 0.55
    assert manifest.focus.treatment_value == 1.05


def test_manifest_id_is_deterministic(context):
    scenario, config, proposal = context
    first = compile_hypothesis(proposal, scenario, config)
    second = compile_hypothesis(proposal.model_dump(mode="json"), scenario, config)
    assert first.manifest_id == second.manifest_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_control_and_treatment_differ_only_on_focus_variable(context):
    scenario, config, proposal = context
    manifest = compile_hypothesis(proposal, scenario, config)
    factor_differences = [
        key
        for key in manifest.control.scenario_factors
        if manifest.control.scenario_factors[key] != manifest.treatment.scenario_factors[key]
    ]
    policy_differences = [
        key
        for key in manifest.control.policy_parameters
        if manifest.control.policy_parameters[key] != manifest.treatment.policy_parameters[key]
    ]
    assert factor_differences == ["traffic_demand"]
    assert policy_differences == []


def test_policy_focus_uses_nearest_registered_control(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["hypothesis_id"] = "HYP-BYPASS-TEST"
    edited["focus_variable_id"] = "bypass_ratio"
    edited["policy_values"]["bypass_ratio"] = 0.15
    manifest = compile_hypothesis(edited, scenario, config)
    assert manifest.focus.kind == "policy_parameter"
    assert manifest.focus.control_value == 0.0
    assert manifest.focus.treatment_value == 0.15
    assert manifest.control.scenario_factors == manifest.treatment.scenario_factors
    assert manifest.control.policy_parameters["bypass_ratio"] == 0.0


def test_unknown_factor_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["factor_values"]["warp_factor"] = 1.0
    with pytest.raises(ExperimentCompileError, match="factor_registry_mismatch"):
        compile_hypothesis(edited, scenario, config)


def test_unknown_focus_variable_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["focus_variable_id"] = "gravity_override"
    with pytest.raises(ExperimentCompileError, match="unregistered_focus_variable"):
        compile_hypothesis(edited, scenario, config)


def test_unsafe_range_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["factor_values"]["traffic_demand"] = 99.0
    with pytest.raises(
        ExperimentCompileError, match="factor_value_out_of_range|factor_value_out_of_registry"
    ):
        compile_hypothesis(edited, scenario, config)


def test_non_registered_but_in_range_factor_level_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["factor_values"]["traffic_demand"] = 0.8
    with pytest.raises(ExperimentCompileError, match="factor_value_out_of_registry"):
        compile_hypothesis(edited, scenario, config)


def test_unsupported_scenario_is_rejected(context):
    scenario, config, proposal = context
    edited_config = config.model_dump(mode="python")
    edited_config["allowed_scenario_ids"] = ["another-scenario"]
    limited_config = CompilerConfig.model_validate(edited_config)
    with pytest.raises(ExperimentCompileError, match="unsupported_scenario"):
        compile_hypothesis(proposal, scenario, limited_config)


def test_hypothesis_scenario_mismatch_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["scenario_id"] = "other-scenario"
    with pytest.raises(ExperimentCompileError, match="scenario_mismatch"):
        compile_hypothesis(edited, scenario, config)


def test_unsupported_backend_is_rejected(context):
    scenario, config, proposal = context
    with pytest.raises(ExperimentCompileError, match="unsupported_backend"):
        compile_hypothesis(proposal, scenario, config, backend_id="isaac_sim")  # type: ignore[arg-type]


def test_unregistered_metric_is_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["target_metric"] = "collision_count"
    with pytest.raises(ExperimentCompileError, match="unregistered_metric"):
        compile_hypothesis(edited, scenario, config)


def test_horizon_limit_is_enforced(context):
    scenario, config, proposal = context
    with pytest.raises(ExperimentCompileError, match="horizon_limit_exceeded"):
        compile_hypothesis(
            proposal, scenario, config, horizon_seconds=config.max_horizon_seconds + 1
        )


@pytest.mark.parametrize("horizon", [0, -1, float("inf"), float("nan")])
def test_invalid_horizon_is_rejected(context, horizon):
    scenario, config, proposal = context
    with pytest.raises(ExperimentCompileError, match="invalid_horizon"):
        compile_hypothesis(proposal, scenario, config, horizon_seconds=horizon)


def test_run_count_limit_is_enforced(context):
    scenario, config, proposal = context
    with pytest.raises(ExperimentCompileError, match="replicate_limit_exceeded|run_limit_exceeded"):
        compile_hypothesis(
            proposal, scenario, config, replicates_per_arm=config.max_replicates_per_arm + 1
        )


def test_interaction_not_in_registry_is_rejected(context):
    scenario, config, proposal = context
    with pytest.raises(ExperimentCompileError, match="unsupported_interaction"):
        compile_hypothesis(
            proposal, scenario, config, interaction_terms=["traffic_demand:bypass_ratio"]
        )


def test_registered_but_unimplemented_interaction_design_is_rejected(context):
    scenario, config, proposal = context
    data = config.model_dump(mode="python")
    data["supported_interactions"] = ["traffic_demand:bypass_ratio"]
    interaction_config = CompilerConfig.model_validate(data)
    with pytest.raises(ExperimentCompileError, match="design_not_implemented"):
        compile_hypothesis(
            proposal,
            scenario,
            interaction_config,
            interaction_terms=["traffic_demand:bypass_ratio"],
        )


def test_malformed_json_is_rejected_with_actionable_error(context):
    scenario, config, _ = context
    with pytest.raises(ExperimentCompileError, match="malformed_json"):
        compile_hypothesis('{"hypothesis_id": ', scenario, config)


def test_oversized_hypothesis_payload_is_rejected_before_parsing(context):
    scenario, config, proposal = context
    data = config.model_dump(mode="python")
    data["max_hypothesis_bytes"] = 512
    limited_config = CompilerConfig.model_validate(data)
    oversized = proposal.model_dump_json() + (" " * 600)
    with pytest.raises(ExperimentCompileError, match="hypothesis_too_large"):
        compile_hypothesis(oversized, scenario, limited_config)


def test_extra_code_fields_are_rejected(context):
    scenario, config, proposal = context
    edited = proposal.model_dump(mode="json")
    edited["shell_command"] = "rm -rf /"
    with pytest.raises(ExperimentCompileError, match="invalid_hypothesis_schema"):
        compile_hypothesis(edited, scenario, config)


def test_incomplete_parameter_type_registry_is_rejected(context):
    scenario, config, proposal = context
    data = config.model_dump(mode="python")
    del data["parameter_types"]["bypass_ratio"]
    edited_config = CompilerConfig.model_validate(data)
    with pytest.raises(ExperimentCompileError, match="parameter_type_registry_mismatch"):
        compile_hypothesis(proposal, scenario, edited_config)


def test_integer_type_cannot_be_assigned_to_fractional_registered_levels(context):
    scenario, config, proposal = context
    data = config.model_dump(mode="python")
    data["parameter_types"]["traffic_demand"] = "integer"
    edited_config = CompilerConfig.model_validate(data)
    with pytest.raises(ExperimentCompileError, match="invalid_parameter_type_registry"):
        compile_hypothesis(proposal, scenario, edited_config)


def test_manifest_atomic_save_round_trips(context, tmp_path):
    scenario, config, proposal = context
    manifest = compile_hypothesis(proposal, scenario, config)
    target = tmp_path / "nested" / "manifest.json"
    save_manifest_atomic(target, manifest)
    loaded = CompiledExperimentManifest.model_validate_json(target.read_text(encoding="utf-8"))
    assert loaded == manifest
    assert not list(target.parent.glob("*.tmp"))


def test_cli_compiles_fixture_offline(context, tmp_path):
    del context
    destination = tmp_path / "cli-output.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "resiliant_z.experiment_compiler",
            "--hypothesis",
            str(HYPOTHESIS_PATH),
            "--scenario",
            str(SCENARIO_PATH),
            "--config",
            str(CONFIG_PATH),
            "--output",
            str(destination),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = json.loads(destination.read_text(encoding="utf-8"))
    assert parsed["automatic_execution"] is False
    assert parsed["design_kind"] == "paired_single_factor"
    assert "No backend was executed" in result.stdout


def test_manifest_rejects_run_count_inconsistent_with_replicates(context):
    scenario, config, proposal = context
    manifest_data = compile_hypothesis(proposal, scenario, config).model_dump(mode="json")
    manifest_data["run_count"] = 5
    with pytest.raises(ValidationError, match="run_count must equal"):
        CompiledExperimentManifest.model_validate(manifest_data)
