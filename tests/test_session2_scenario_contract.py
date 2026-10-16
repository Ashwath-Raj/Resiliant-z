from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.models import ExperimentManifest, ExperimentParameters, SimulationRun
from resiliant_z.scenario_spec import WarehouseScenario, load_warehouse_scenario
from resiliant_z.simulation.backend_contract import (
    SimulationBackend,
    run_with_backend,
)
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = PROJECT_ROOT / "configs" / "warehouse_scenario.example.v1.json"


def _manifest() -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id="SESSION2-BACKEND-CONTRACT-SMOKE",
        scenario_id="priority_junction_nominal_v1",
        stage="replay",
        seed=20261016,
        parameters=ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.0,
        ),
        git_sha="session2-local-test",
    )


def test_example_warehouse_scenario_parses_and_has_required_scene_elements() -> None:
    scenario = load_warehouse_scenario(SCENARIO_PATH)

    assert scenario.schema_version == "1.0.0"
    assert len(scenario.layout.intersections) >= 2
    assert scenario.layout.shelves
    assert scenario.layout.charging_areas
    assert scenario.layout.task_stations
    assert scenario.layout.robot_spawns
    assert scenario.evidence_label == "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM"


def test_scenario_factors_are_separate_from_policy_parameters() -> None:
    scenario = load_warehouse_scenario(SCENARIO_PATH)

    factor_ids = {factor.factor_id for factor in scenario.scenario_factors}
    policy_ids = {parameter.parameter_id for parameter in scenario.policy_parameters}
    assert factor_ids == {"traffic_demand", "priority_ratio"}
    assert policy_ids == {"bypass_ratio"}
    assert factor_ids.isdisjoint(policy_ids)
    assert all(factor.unit.strip() for factor in scenario.scenario_factors)
    assert all(parameter.unit.strip() for parameter in scenario.policy_parameters)


def test_unknown_node_reference_is_rejected() -> None:
    data = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    data["layout"]["aisles"][0]["start_node_id"] = "NOT_A_REAL_NODE"

    with pytest.raises(ValidationError, match="unknown node"):
        WarehouseScenario.model_validate(data)


def test_factor_test_levels_must_stay_inside_declared_range() -> None:
    data = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    data["scenario_factors"][0]["test_levels"] = [0.55, 1.25]

    with pytest.raises(ValidationError, match="test_levels"):
        WarehouseScenario.model_validate(data)


def test_local_discrete_event_backend_satisfies_shared_backend_contract() -> None:
    backend = DiscreteEventFleetSimulator()
    assert isinstance(backend, SimulationBackend)

    run = run_with_backend(backend, _manifest())

    assert isinstance(run, SimulationRun)
    assert run.backend == "discrete_event"
    assert run.status == "completed"
    assert run.experiment.experiment_id == "SESSION2-BACKEND-CONTRACT-SMOKE"
    assert run.experiment.seed == 20261016


def test_backend_returning_wrong_type_is_rejected() -> None:
    class BrokenBackend:
        name = "broken"

        def run(self, manifest: ExperimentManifest) -> object:
            del manifest
            return {"status": "pretending to be a run"}

    with pytest.raises(TypeError, match="expected SimulationRun"):
        run_with_backend(BrokenBackend(), _manifest())  # type: ignore[arg-type]
