from resiliant_z.experiments.planner import factorial_manifests
from resiliant_z.models import ExperimentManifest, ExperimentParameters
from resiliant_z.simulation.surrogate import SurrogateSimulator


def test_surrogate_is_seed_deterministic_for_metrics():
    manifest = ExperimentManifest(
        experiment_id="TEST-DETERMINISM",
        stage="discovery",
        seed=111,
        parameters=ExperimentParameters(
            traffic_demand=1.05,
            priority_ratio=0.5,
            bypass_ratio=0.0,
        ),
    )
    simulator = SurrogateSimulator()
    first = simulator.run(manifest)
    second = simulator.run(manifest)
    assert first.metrics == second.metrics
    assert first.backend == "surrogate"
    assert any("did not execute in NVIDIA Isaac Sim" in note for note in first.notes)


def test_factorial_manifest_is_bounded_and_replicated():
    manifests = factorial_manifests(stage="discovery", seeds_per_cell=3, first_seed=100)
    assert len(manifests) == 12
    assert len({m.seed for m in manifests}) == 12
    assert len({(m.parameters.traffic_demand, m.parameters.priority_ratio) for m in manifests}) == 4
    assert all(m.parameters.bypass_ratio == 0 for m in manifests)
