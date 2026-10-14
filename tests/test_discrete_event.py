from resiliant_z.experiments.planner import factorial_manifests
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
