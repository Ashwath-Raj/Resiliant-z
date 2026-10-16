from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.experiment_compiler import CompiledExperimentManifest
from resiliant_z.experiment_planner import (
    ALLOWED_TRANSITIONS,
    PlannerConfig,
    PlannerError,
    RunRegistry,
    load_planner_config,
    plan_experiment,
    save_plan_atomic,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    PROJECT_ROOT / "configs" / "experiment-planner" / "session8_manifest_fixture.v1.json"
)
CONFIG_PATH = PROJECT_ROOT / "configs" / "experiment-planner" / "session8_config.v1.json"


@pytest.fixture()
def context():
    manifest = CompiledExperimentManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    config = load_planner_config(CONFIG_PATH)
    return manifest, config


def test_plan_generation_is_deterministic(context):
    manifest, config = context
    first = plan_experiment(manifest, config)
    second = plan_experiment(manifest.model_dump(mode="json"), config)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.plan_id == second.plan_id


def test_plan_allocates_four_splits_and_paired_runs(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    assert [allocation.split for allocation in plan.seed_allocations] == [
        "discovery",
        "selection",
        "validation",
        "replay",
    ]
    assert plan.run_count == 24
    assert len(plan.runs) == 24
    assert plan.status == "planned"
    assert plan.automatic_execution is False
    assert plan.evidence_status == "not_executed_not_evidence"


def test_seed_allocations_are_disjoint_across_splits(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    all_seeds = [seed for allocation in plan.seed_allocations for seed in allocation.seeds]
    assert len(all_seeds) == len(set(all_seeds))


def test_common_random_numbers_are_shared_within_each_pair(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    grouped = {}
    for run in plan.runs:
        grouped.setdefault((run.split, run.replicate_index), []).append(run)
    assert len(grouped) == 12
    for pair in grouped.values():
        assert {run.arm_id for run in pair} == {"control", "treatment"}
        assert pair[0].seed == pair[1].seed


def test_discovery_selection_validation_replay_use_different_seeds(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    split_seeds = {entry.split: set(entry.seeds) for entry in plan.seed_allocations}
    for left, left_seeds in split_seeds.items():
        for right, right_seeds in split_seeds.items():
            if left != right:
                assert left_seeds.isdisjoint(right_seeds)


def test_every_run_records_selection_reason_and_source_provenance(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    assert plan.source_manifest_id == manifest.manifest_id
    assert len(plan.source_manifest_sha256) == 64
    assert all("common random numbers" in run.selection_reason for run in plan.runs)
    assert all(run.source_manifest_sha256 == plan.source_manifest_sha256 for run in plan.runs)


def test_control_and_treatment_differ_only_on_declared_focus(context):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    for split in {run.split for run in plan.runs}:
        for replicate in range(config.replicates_per_split):
            pair = [
                run for run in plan.runs if run.split == split and run.replicate_index == replicate
            ]
            control = next(run for run in pair if run.arm_id == "control")
            treatment = next(run for run in pair if run.arm_id == "treatment")
            scenario_differences = [
                key
                for key in control.scenario_factors
                if control.scenario_factors[key] != treatment.scenario_factors[key]
            ]
            policy_differences = [
                key
                for key in control.policy_parameters
                if control.policy_parameters[key] != treatment.policy_parameters[key]
            ]
            if manifest.focus.kind == "scenario_factor":
                assert scenario_differences == [manifest.focus.parameter_id]
                assert policy_differences == []
            else:
                assert scenario_differences == []
                assert policy_differences == [manifest.focus.parameter_id]


def test_run_limit_is_enforced(context):
    manifest, config = context
    restricted = PlannerConfig.model_validate(
        config.model_dump(mode="python") | {"max_total_runs": 8}
    )
    with pytest.raises(PlannerError, match="run_limit_exceeded"):
        plan_experiment(manifest, restricted)


def test_replicates_cannot_exceed_compiler_accepted_count(context):
    manifest, config = context
    oversized = PlannerConfig.model_validate(
        config.model_dump(mode="python") | {"replicates_per_split": manifest.replicates_per_arm + 1}
    )
    with pytest.raises(PlannerError, match="replicate_limit_exceeded"):
        plan_experiment(manifest, oversized)


def test_manifest_with_an_extra_arm_difference_is_rejected(context):
    manifest, config = context
    altered_treatment = manifest.treatment.model_copy(
        update={"scenario_factors": manifest.treatment.scenario_factors | {"priority_ratio": 0.8}}
    )
    altered_manifest = manifest.model_copy(update={"treatment": altered_treatment})
    with pytest.raises(PlannerError, match="not_single_factor_pair"):
        plan_experiment(altered_manifest, config)


def test_malformed_manifest_json_is_rejected(context):
    _, config = context
    with pytest.raises(PlannerError, match="malformed_manifest_json"):
        plan_experiment('{"manifest_id": ', config)


def test_unknown_manifest_fields_are_rejected(context):
    manifest, config = context
    edited = manifest.model_dump(mode="json") | {"shell_command": "echo unsafe"}
    with pytest.raises(PlannerError, match="invalid_compiled_manifest"):
        plan_experiment(edited, config)


def test_config_requires_all_four_split_roles():
    with pytest.raises(ValidationError, match="seed_splits"):
        PlannerConfig.model_validate(
            {
                "config_id": "bad-split-config",
                "root_seed": 10,
                "seed_splits": ["discovery", "selection", "validation", "validation"],
            }
        )


def test_plan_atomic_save_is_idempotent_for_identical_content(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    path = tmp_path / "plan.json"
    save_plan_atomic(path, plan)
    first = path.read_bytes()
    save_plan_atomic(path, plan)
    assert path.read_bytes() == first
    assert json.loads(path.read_text(encoding="utf-8"))["plan_id"] == plan.plan_id


def test_plan_atomic_save_refuses_conflicting_overwrite(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    path = tmp_path / "plan.json"
    path.write_text('{"different": true}\n', encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        save_plan_atomic(path, plan)


def test_registry_registration_is_idempotent_and_persists(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    path = tmp_path / "registry.json"
    registry = RunRegistry(path)
    assert registry.register_plan(plan) == 24
    assert registry.register_plan(plan) == 0
    assert len(registry.snapshot.runs) == 24
    restored = RunRegistry(path)
    assert len(restored.snapshot.runs) == 24
    assert all(entry.status == "planned" for entry in restored.snapshot.runs.values())


def test_run_registry_enforces_valid_lifecycle(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    registry = RunRegistry(tmp_path / "registry.json")
    registry.register_plan(plan)
    run_id = plan.runs[0].run_id
    assert registry.transition(run_id, "validated").status == "validated"
    assert registry.transition(run_id, "queued").status == "queued"
    assert registry.transition(run_id, "running").status == "running"
    assert registry.transition(run_id, "succeeded").status == "succeeded"
    assert len([event for event in registry.snapshot.events if event.run_id == run_id]) == 5
    assert RunRegistry(tmp_path / "registry.json").snapshot.runs[run_id].status == "succeeded"


def test_invalid_transition_is_rejected(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    registry = RunRegistry(tmp_path / "registry.json")
    registry.register_plan(plan)
    with pytest.raises(PlannerError, match="invalid_state_transition"):
        registry.transition(plan.runs[0].run_id, "running")


def test_failed_run_can_never_be_promoted_to_success(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    registry = RunRegistry(tmp_path / "registry.json")
    registry.register_plan(plan)
    run_id = plan.runs[0].run_id
    registry.transition(run_id, "validated")
    registry.transition(run_id, "queued")
    registry.transition(run_id, "failed", "local executor returned non-zero exit code")
    with pytest.raises(PlannerError, match="invalid_state_transition"):
        registry.transition(run_id, "succeeded")
    assert registry.snapshot.runs[run_id].status == "failed"


def test_terminal_failure_states_require_a_reason(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    registry = RunRegistry(tmp_path / "registry.json")
    registry.register_plan(plan)
    run_id = plan.runs[0].run_id
    registry.transition(run_id, "validated")
    registry.transition(run_id, "queued")
    with pytest.raises(PlannerError, match="transition_reason_required"):
        registry.transition(run_id, "failed")


def test_unknown_run_transition_is_rejected(context, tmp_path):
    _, config = context
    registry = RunRegistry(tmp_path / "registry.json")
    with pytest.raises(PlannerError, match="unknown_run"):
        registry.transition("run-000000000000000000000000", "invalidated", "not found")


def test_failed_or_incomplete_status_cannot_skip_state_machine(context, tmp_path):
    manifest, config = context
    plan = plan_experiment(manifest, config)
    registry = RunRegistry(tmp_path / "registry.json")
    registry.register_plan(plan)
    run_id = plan.runs[0].run_id
    with pytest.raises(PlannerError, match="invalid_state_transition"):
        registry.transition(run_id, "succeeded")
    assert registry.snapshot.runs[run_id].status == "planned"


def test_run_registry_rejects_corrupt_existing_file(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text('{"runs": [}', encoding="utf-8")
    with pytest.raises(PlannerError, match="invalid_registry"):
        RunRegistry(path)


def test_state_transition_table_has_no_outgoing_edges_from_invalidated():
    assert ALLOWED_TRANSITIONS["invalidated"] == frozenset()
