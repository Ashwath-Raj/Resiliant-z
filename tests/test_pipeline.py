import json

from resiliant_z.pipeline import run_demo


def test_demo_writes_artifacts_and_labels_surrogate_honestly(tmp_path):
    summary = run_demo(
        output_dir=tmp_path,
        hypotheses_mode="local",
        seeds_per_cell=3,
        replay_seeds=3,
    )
    assert summary["backend"] == "surrogate"
    assert "NOT ISAAC SIM" in summary["evidence_label"]
    assert summary["discovery"]["status"] == "validated"
    assert summary["discovery"]["validation_interaction_ci_upper"] < 0
    assert summary["counts"]["discovery_runs"] == 12
    assert summary["counts"]["validation_runs"] == 12
    assert summary["counts"]["replay_runs"] == 6
    assert (tmp_path / "runs.jsonl").is_file()
    assert (tmp_path / "manifests.jsonl").is_file()
    assert "SURROGATE" in (tmp_path / "report.md").read_text()
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["hypothesis_generation"]["source"] == "local_baseline"


def test_local_fleet_demo_labels_discrete_event_not_isaac(tmp_path):
    from resiliant_z.fleet_pipeline import run_fleet_demo

    summary = run_fleet_demo(
        output_dir=tmp_path / "fleet",
        seeds_per_cell=5,
        replay_seeds=3,
    )
    assert summary["backend"] == "discrete_event"
    assert "NOT ISAAC SIM" in summary["evidence_label"]
    assert summary["counts"]["discovery_runs"] == 20
    assert summary["counts"]["validation_runs"] == 20
    assert summary["counts"]["policy_selection_runs"] == 20
    assert summary["counts"]["replay_runs"] == 6
    assert summary["policy_selection"]["status"] == "selected_after_validated_discovery"
    selected_ratio = summary["policy_selection"]["selected_bypass_ratio"]
    assert selected_ratio in {0.0, 0.15, 0.30, 0.45}
    assert summary["policy_replay"]["selected_bypass_ratio"] == selected_ratio
    manifests = [
        json.loads(line)
        for line in (tmp_path / "fleet" / "manifests.jsonl").read_text().splitlines()
    ]
    selected_seeds = {m["seed"] for m in manifests if m["stage"] == "policy_selection"}
    replay_seeds = {m["seed"] for m in manifests if m["stage"] == "replay"}
    assert selected_seeds.isdisjoint(replay_seeds)
    for seed in replay_seeds:
        pair = [m for m in manifests if m["stage"] == "replay" and m["seed"] == seed]
        assert len(pair) == 2
        assert {m["parameters"]["bypass_ratio"] for m in pair} == {0.0, selected_ratio}
    assert (tmp_path / "fleet" / "report.md").is_file()
    text = (tmp_path / "fleet" / "report.md").read_text()
    assert "queueing model" in text
    assert "Evidence-gated policy selection" in text
    assert "held-out seeds" in text


def test_unvalidated_discovery_blocks_policy_activation(monkeypatch, tmp_path):
    from resiliant_z import fleet_pipeline
    from resiliant_z.models import DiscoveryDecision

    def inconclusive(*args, **kwargs):
        return DiscoveryDecision(
            status="inconclusive",
            claim="No stable interaction was validated in this test.",
            interaction_effect=0.0,
            discovery_main_effect_rmse=1.0,
            discovery_interaction_rmse=1.0,
            validation_main_effect_rmse=1.0,
            validation_interaction_rmse=1.0,
            validation_improvement_fraction=0.0,
            sample_count_discovery=12,
            sample_count_validation=12,
            validation_interaction_effect=0.0,
            validation_interaction_ci_lower=-1.0,
            validation_interaction_ci_upper=1.0,
            limitations=["test fixture"],
        )

    monkeypatch.setattr(fleet_pipeline, "analyze_discovery", inconclusive)
    summary = fleet_pipeline.run_fleet_demo(
        output_dir=tmp_path / "blocked", seeds_per_cell=3, replay_seeds=3
    )
    assert summary["policy_selection"]["status"] == "blocked_because_discovery_was_not_validated"
    assert summary["counts"]["policy_selection_runs"] == 0
    assert summary["policy_selection"]["selected_bypass_ratio"] == 0.0
    assert summary["policy_replay"]["selected_bypass_ratio"] == 0.0
