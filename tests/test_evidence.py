from resiliant_z.evidence.analyzer import analyze_discovery
from resiliant_z.experiments.planner import factorial_manifests
from resiliant_z.simulation.surrogate import SurrogateSimulator


def test_interaction_is_detected_and_validates_on_new_seeds():
    simulator = SurrogateSimulator()
    discovery = [
        simulator.run(m)
        for m in factorial_manifests(stage="discovery", seeds_per_cell=5, first_seed=10_000)
    ]
    validation = [
        simulator.run(m)
        for m in factorial_manifests(stage="validation", seeds_per_cell=5, first_seed=20_000)
    ]
    decision = analyze_discovery(discovery, validation)
    assert decision.status == "validated"
    assert decision.interaction_effect < -0.08
    assert decision.validation_interaction_rmse < decision.validation_main_effect_rmse
    assert len(decision.limitations) >= 3
