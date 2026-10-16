"""Tests for the paired bypass-detour sensitivity experiment."""

import json

import pytest

from resiliant_z.sensitivity import run_detour_sensitivity


def test_sensitivity_sweeps_costs_with_paired_policies_and_writes_artifacts(tmp_path):
    output = tmp_path / "sensitivity"
    summary = run_detour_sensitivity(
        output_dir=output,
        replay_seeds=3,
        detour_cost_levels_seconds=(0.0, 2.5),
        bypass_ratio=0.45,
        first_seed=81_000,
    )

    assert summary["evidence_label"] == "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM"
    assert summary["counts"] == {
        "total_runs": 36,
        "detour_cost_levels": 2,
        "conditions": 2,
        "policy_arms": 3,
        "paired_seeds_per_arm_condition_level": 3,
    }
    assert set(summary["conditions"]) == {"nominal", "high_risk"}

    high_risk = summary["conditions"]["high_risk"]["detour_levels"]
    no_detour = high_risk["0"]
    with_detour = high_risk["2.5"]
    assert no_detour["policies"]["baseline"]["bypass_tasks_total"] == 0
    assert with_detour["policies"]["baseline"]["mean_bypass_detour_total_seconds"] == 0.0
    assert no_detour["policies"]["static"]["mean_bypass_detour_total_seconds"] == 0.0
    assert with_detour["policies"]["static"]["mean_bypass_detour_total_seconds"] > 0.0
    assert (
        with_detour["paired_comparisons"]["conditioned_vs_static"]["policy_objective_score"][
            "paired_seed_count"
        ]
        == 3
    )
    assert (
        with_detour["objective_score_effect_vs_zero_detour"]["conditioned"]["paired_seed_count"]
        == 3
    )

    # With no bypasses the detour assumption is inert, so the reference baseline
    # should be identical at each cost level for the same paired seeds.
    assert (
        no_detour["policies"]["baseline"]["mean_policy_objective_score"]
        == with_detour["policies"]["baseline"]["mean_policy_objective_score"]
    )

    assert (output / "summary.json").is_file()
    assert (output / "runs.jsonl").is_file()
    assert (output / "manifests.jsonl").is_file()
    assert (output / "sensitivity.csv").is_file()
    report = (output / "report.md").read_text()
    assert "Interpretation guardrails" in report
    assert "NOT ISAAC SIM" in report
    saved = json.loads((output / "summary.json").read_text())
    assert saved["counts"]["total_runs"] == 36


def test_sensitivity_requires_zero_reference_level_and_valid_costs(tmp_path):
    with pytest.raises(ValueError, match="zero-second"):
        run_detour_sensitivity(
            output_dir=tmp_path / "missing-zero",
            replay_seeds=3,
            detour_cost_levels_seconds=(2.5, 5.0),
        )
    with pytest.raises(ValueError, match="unique"):
        run_detour_sensitivity(
            output_dir=tmp_path / "duplicate",
            replay_seeds=3,
            detour_cost_levels_seconds=(0.0, 2.5, 2.5),
        )
    with pytest.raises(ValueError, match="within \\[0.0, 30.0\\]"):
        run_detour_sensitivity(
            output_dir=tmp_path / "too-large",
            replay_seeds=3,
            detour_cost_levels_seconds=(0.0, 30.1),
        )


def test_sensitivity_requires_at_least_three_paired_seeds(tmp_path):
    with pytest.raises(ValueError, match="at least three"):
        run_detour_sensitivity(
            output_dir=tmp_path / "too-few",
            replay_seeds=2,
            detour_cost_levels_seconds=(0.0, 2.5),
        )
