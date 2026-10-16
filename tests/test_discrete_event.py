import pytest
from pydantic import ValidationError

from resiliant_z.experiments.planner import (
    factorial_manifests,
    policy_comparison_manifests,
    policy_selection_manifests,
)
from resiliant_z.models import ExperimentManifest, ExperimentParameters
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator


def test_discrete_event_metrics_are_seed_deterministic():
    manifest = ExperimentManifest(
        experiment_id="DES-DETERMINISM",
        stage="discovery",
        seed=4242,
        parameters=ExperimentParameters(
            traffic_demand=1.05,
            priority_ratio=0.50,
            bypass_ratio=0.0,
        ),
    )
    sim = DiscreteEventFleetSimulator()
    first = sim.run(manifest)
    second = sim.run(manifest)
    assert first.metrics == second.metrics
    assert first.backend == "discrete_event"
    assert first.metrics.throughput_tasks_per_min > 0
    assert first.metrics.junction_occupancy <= 1
    assert first.metrics.deadlock_events is None
    assert first.ended_at is not None
    assert any("physics-based digital twin" in note for note in first.notes)


def test_low_demand_has_less_junction_pressure_than_high_priority_overload():
    sim = DiscreteEventFleetSimulator()
    manifests = factorial_manifests(stage="discovery", seeds_per_cell=5, first_seed=9000)
    low = [
        m
        for m in manifests
        if m.parameters.traffic_demand == 0.55 and m.parameters.priority_ratio == 0.15
    ]
    high = [
        m
        for m in manifests
        if m.parameters.traffic_demand == 1.05 and m.parameters.priority_ratio == 0.50
    ]
    low_runs = [sim.run(m) for m in low]
    high_runs = [sim.run(m) for m in high]
    mean_low_occ = sum(r.metrics.junction_occupancy for r in low_runs) / len(low_runs)
    mean_high_occ = sum(r.metrics.junction_occupancy for r in high_runs) / len(high_runs)
    mean_low_wait = sum(r.metrics.average_wait_seconds for r in low_runs) / len(low_runs)
    mean_high_wait = sum(r.metrics.average_wait_seconds for r in high_runs) / len(high_runs)
    assert mean_high_occ > mean_low_occ
    assert mean_high_wait > mean_low_wait


def test_wait_metrics_separate_started_tasks_from_right_censored_tasks():
    manifest = ExperimentManifest(
        experiment_id="DES-CENSORING",
        stage="replay",
        seed=13579,
        parameters=ExperimentParameters(
            traffic_demand=1.05,
            priority_ratio=0.50,
            bypass_ratio=0.0,
        ),
    )
    result = DiscreteEventFleetSimulator().run(manifest)
    metrics = result.metrics

    assert metrics.task_arrivals is not None
    assert metrics.task_completions is not None
    assert metrics.route_service_started_count is not None
    assert metrics.tasks_not_started_by_horizon is not None
    assert metrics.route_service_wait_total_seconds is not None
    assert metrics.censored_wait_observation_seconds is not None
    assert metrics.task_arrivals == (
        metrics.route_service_started_count + metrics.tasks_not_started_by_horizon
    )
    assert metrics.task_completions <= metrics.route_service_started_count
    if metrics.route_service_started_count:
        expected_mean = (
            metrics.route_service_wait_total_seconds / metrics.route_service_started_count
        )
        assert abs(metrics.average_wait_seconds - expected_mean) < 1e-5
    else:
        assert metrics.average_wait_seconds == 0.0
    assert any("right-censored" in note for note in result.notes)


def test_policy_selection_manifests_are_paired_and_bounded():
    manifests = policy_selection_manifests(seeds_per_candidate=3, first_seed=7000)
    assert len(manifests) == 12
    assert {m.stage for m in manifests} == {"policy_selection"}
    candidates = {m.parameters.bypass_ratio for m in manifests}
    assert candidates == {0.0, 0.15, 0.30, 0.45}
    seeds_by_candidate = {
        ratio: {m.seed for m in manifests if m.parameters.bypass_ratio == ratio}
        for ratio in candidates
    }
    assert len({tuple(sorted(seeds)) for seeds in seeds_by_candidate.values()}) == 1
    assert all(m.parameters.traffic_demand == 1.05 for m in manifests)
    assert all(m.parameters.priority_ratio == 0.50 for m in manifests)


def test_conditioned_policy_requires_high_risk_envelope_and_live_junction_pressure():
    sim = DiscreteEventFleetSimulator()
    high_risk = ExperimentManifest(
        experiment_id="DES-CONDITIONED-HIGH",
        stage="replay",
        seed=20261014,
        scenario_id="priority_junction_high_risk_v1",
        parameters=ExperimentParameters(
            traffic_demand=1.05,
            priority_ratio=0.50,
            bypass_ratio=0.45,
            routing_policy="conditioned",
        ),
    )
    high_result = sim.run(high_risk)
    assert high_result.metrics.high_risk_context_arrival_count > 0
    assert high_result.metrics.conditional_policy_trigger_count > 0
    assert high_result.metrics.bypass_task_count > 0

    nominal = high_risk.model_copy(
        update={
            "experiment_id": "DES-CONDITIONED-NOMINAL",
            "scenario_id": "priority_junction_nominal_v1",
            "seed": 20261015,
            "parameters": ExperimentParameters(
                traffic_demand=0.55,
                priority_ratio=0.15,
                bypass_ratio=0.45,
                routing_policy="conditioned",
            ),
        }
    )
    nominal_result = sim.run(nominal)
    assert nominal_result.metrics.high_risk_context_arrival_count == 0
    assert nominal_result.metrics.conditional_policy_trigger_count == 0
    assert nominal_result.metrics.bypass_task_count == 0


def test_static_policy_can_divert_in_nominal_context_but_conditioned_policy_cannot():
    sim = DiscreteEventFleetSimulator()
    common = {
        "stage": "replay",
        "seed": 61001,
        "scenario_id": "priority_junction_nominal_v1",
    }
    static = ExperimentManifest(
        experiment_id="DES-STATIC-NOMINAL",
        **common,
        parameters=ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.45,
            routing_policy="static",
        ),
    )
    conditioned = ExperimentManifest(
        experiment_id="DES-CONDITIONED-NOMINAL",
        **common,
        parameters=ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.45,
            routing_policy="conditioned",
        ),
    )
    static_result = sim.run(static)
    conditioned_result = sim.run(conditioned)
    assert static_result.metrics.bypass_task_count > 0
    assert conditioned_result.metrics.bypass_task_count == 0


def test_policy_arms_share_task_workload_for_same_condition_and_seed():
    sim = DiscreteEventFleetSimulator()
    manifests = policy_comparison_manifests(seeds=[62001], selected_bypass_ratio=0.30)
    high = [m for m in manifests if m.scenario_id == "priority_junction_high_risk_v1"]
    results = [sim.run(m) for m in high]
    assert len(results) == 3
    assert len({run.metrics.task_arrivals for run in results}) == 1
    assert len({run.metrics.high_risk_context_arrival_count for run in results}) == 1


def test_bypass_detour_cost_is_explicit_and_reduces_robot_availability():
    sim = DiscreteEventFleetSimulator()
    base = ExperimentManifest(
        experiment_id="DES-BYPASS-DET0",
        stage="replay",
        seed=74123,
        scenario_id="priority_junction_high_risk_v1",
        parameters=ExperimentParameters(
            traffic_demand=1.05,
            priority_ratio=0.50,
            bypass_ratio=0.45,
            routing_policy="static",
            bypass_detour_seconds=0.0,
        ),
    )
    costly = base.model_copy(
        update={
            "experiment_id": "DES-BYPASS-DET12",
            "parameters": base.parameters.model_copy(update={"bypass_detour_seconds": 12.0}),
        }
    )

    no_detour_result = sim.run(base)
    costly_result = sim.run(costly)

    assert no_detour_result.metrics.bypass_task_count == costly_result.metrics.bypass_task_count
    assert no_detour_result.metrics.bypass_detour_total_seconds == 0.0
    assert costly_result.metrics.bypass_detour_total_seconds > 0.0
    assert costly_result.metrics.task_completions <= no_detour_result.metrics.task_completions
    assert any("not measured real-world travel cost" in note for note in costly_result.notes)


def test_bypass_detour_parameter_is_bounded():
    manifest = ExperimentManifest(
        experiment_id="DES-BYPASS-BOUND",
        stage="replay",
        seed=1,
        parameters=ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.0,
            bypass_detour_seconds=2.5,
        ),
    )
    assert manifest.parameters.bypass_detour_seconds == 2.5
    with pytest.raises(ValidationError):
        ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.0,
            bypass_detour_seconds=-0.1,
        )
    with pytest.raises(ValidationError):
        ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.0,
            bypass_detour_seconds=30.1,
        )
