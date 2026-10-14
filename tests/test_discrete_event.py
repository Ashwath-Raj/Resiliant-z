from resiliant_z.experiments.planner import (
    factorial_manifests,
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
    assert any("physics-based digital twin" in note for note in first.notes)


def test_low_demand_has_less_junction_pressure_than_high_priority_overload():
    sim = DiscreteEventFleetSimulator()
    manifests = factorial_manifests(stage="discovery", seeds_per_cell=5, first_seed=9000)
    low = [m for m in manifests if m.parameters.traffic_demand == 0.55 and m.parameters.priority_ratio == 0.15]
    high = [m for m in manifests if m.parameters.traffic_demand == 1.05 and m.parameters.priority_ratio == 0.50]
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
