"""Paired sensitivity analysis for the explicit bypass-detour assumption.

This is a CPU-only discrete-event experiment, not Isaac Sim evidence. It varies
only the configured detour occupancy cost while keeping the bypass ratio fixed,
so observed differences are attributable to that assumption rather than re-tuning
policy selection at every cost level.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

from resiliant_z.experiments.planner import REPLAY_CONDITIONS
from resiliant_z.fleet_pipeline import _arm_summary, _paired_delta, _write_json, _write_jsonl
from resiliant_z.models import ExperimentManifest, ExperimentParameters, SimulationRun
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator
from resiliant_z.simulation.surrogate import current_git_sha

DEFAULT_DETOUR_COST_LEVELS_SECONDS = (0.0, 2.5, 5.0, 10.0, 20.0, 30.0)
POLICY_ARMS = ("baseline", "static", "conditioned")
COMPARISON_PAIRS = (
    ("static_vs_baseline", "static", "baseline"),
    ("conditioned_vs_baseline", "conditioned", "baseline"),
    ("conditioned_vs_static", "conditioned", "static"),
)
COMPARISON_METRICS = (
    "throughput_tasks_per_min",
    "completion_fraction",
    "average_wait_seconds",
    "queue_growth_per_min",
    "bypass_task_count",
    "bypass_detour_total_seconds",
    "policy_objective_score",
)
CSV_FIELDS = (
    "condition",
    "scenario_id",
    "traffic_demand",
    "priority_ratio",
    "detour_cost_seconds",
    "policy",
    "bypass_ratio",
    "run_count",
    "mean_throughput_tasks_per_min",
    "mean_started_task_wait_seconds",
    "completion_fraction",
    "not_started_fraction",
    "mean_queue_growth_per_min",
    "mean_bypass_detour_total_seconds",
    "bypass_tasks_total",
    "bypass_intervention_fraction",
    "mean_policy_objective_score",
)


def _level_key(value: float) -> str:
    """Compact, stable string key for a detour-level value."""
    return format(float(value), ".15g")


def _cost_tag(value: float) -> str:
    """Return an experiment-ID-safe cost label (for example, 2p5)."""
    return _level_key(value).replace("-", "m").replace(".", "p")


def _make_manifests(
    *,
    detour_cost_levels_seconds: tuple[float, ...],
    replay_seeds: tuple[int, ...],
    bypass_ratio: float,
) -> list[ExperimentManifest]:
    git_sha = current_git_sha()
    manifests: list[ExperimentManifest] = []
    for cost in detour_cost_levels_seconds:
        for condition_name, condition in REPLAY_CONDITIONS.items():
            for seed in replay_seeds:
                arms = (
                    ("baseline", 0.0, "static"),
                    ("static", bypass_ratio, "static"),
                    ("conditioned", bypass_ratio, "conditioned"),
                )
                for arm, ratio, routing_policy in arms:
                    manifests.append(
                        ExperimentManifest(
                            experiment_id=(
                                f"SENS-D{_cost_tag(cost)}-{condition_name.upper()}-"
                                f"{arm.upper()}-S{seed}"
                            ),
                            scenario_id=condition["scenario_id"],
                            stage="replay",
                            seed=seed,
                            parameters=ExperimentParameters(
                                traffic_demand=condition["traffic_demand"],
                                priority_ratio=condition["priority_ratio"],
                                bypass_ratio=ratio,
                                routing_policy=routing_policy,
                                bypass_detour_seconds=cost,
                            ),
                            git_sha=git_sha,
                        )
                    )
    return manifests


def _arm_from_run(run: SimulationRun) -> str:
    parts = run.experiment.experiment_id.split("-")
    # Format: SENS-D<cost>-<condition>-<arm>-S<seed>.
    if len(parts) != 5 or parts[0] != "SENS" or parts[3].lower() not in POLICY_ARMS:
        raise ValueError(f"Unexpected sensitivity experiment ID: {run.experiment.experiment_id}")
    return parts[3].lower()


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _metric_row(condition_name: str, condition: dict, cost: float, arm: str, summary: dict) -> dict:
    task_counts = summary["task_counts"]
    return {
        "condition": condition_name,
        "scenario_id": condition["scenario_id"],
        "traffic_demand": condition["traffic_demand"],
        "priority_ratio": condition["priority_ratio"],
        "detour_cost_seconds": cost,
        "policy": arm,
        "bypass_ratio": 0.0 if arm == "baseline" else summary.get("bypass_ratio", ""),
        "run_count": summary["run_count"],
        "mean_throughput_tasks_per_min": summary["mean_throughput_tasks_per_min"],
        "mean_started_task_wait_seconds": summary["mean_started_task_wait_seconds"],
        "completion_fraction": task_counts["completion_fraction"],
        "not_started_fraction": task_counts["not_started_fraction"],
        "mean_queue_growth_per_min": summary["mean_queue_growth_per_min"],
        "mean_bypass_detour_total_seconds": summary["mean_bypass_detour_total_seconds"],
        "bypass_tasks_total": summary["bypass_tasks_total"],
        "bypass_intervention_fraction": summary["bypass_intervention_fraction"],
        "mean_policy_objective_score": summary["mean_policy_objective_score"],
    }


def run_detour_sensitivity(
    output_dir: str | Path = "artifacts/fleet-sensitivity",
    *,
    replay_seeds: int = 12,
    detour_cost_levels_seconds: tuple[float, ...] = DEFAULT_DETOUR_COST_LEVELS_SECONDS,
    bypass_ratio: float = 0.45,
    first_seed: int = 71_001,
) -> dict:
    """Run paired cost sensitivity across the nominal and high-risk conditions.

    A fixed bypass ratio isolates the detour-cost assumption. The default ratio
    (0.45) is the value selected by the current policy-selection run; this command
    does not tune or re-select the policy separately at each cost level.
    """
    if replay_seeds < 3:
        raise ValueError("Use at least three paired replay seeds")
    if first_seed < 0 or first_seed + replay_seeds - 1 > 2**31 - 1:
        raise ValueError("first_seed and replay_seeds exceed the supported seed range")
    if not math.isfinite(bypass_ratio) or not 0.0 <= bypass_ratio <= 0.5:
        raise ValueError("bypass_ratio must be finite and within [0.0, 0.5]")

    levels = tuple(float(value) for value in detour_cost_levels_seconds)
    if not levels:
        raise ValueError("At least one detour-cost level is required")
    if len(set(levels)) != len(levels):
        raise ValueError("Detour-cost levels must be unique")
    if any(not math.isfinite(value) or value < 0.0 or value > 30.0 for value in levels):
        raise ValueError("Detour-cost levels must be finite and within [0.0, 30.0]")
    if 0.0 not in levels:
        raise ValueError("Include a zero-second detour level as the reference condition")

    seeds = tuple(range(first_seed, first_seed + replay_seeds))
    manifests = _make_manifests(
        detour_cost_levels_seconds=levels,
        replay_seeds=seeds,
        bypass_ratio=bypass_ratio,
    )
    simulator = DiscreteEventFleetSimulator()
    runs = [simulator.run(manifest) for manifest in manifests]

    # Organize each cost level and condition while retaining paired seeds.
    runs_by_cost_condition_arm: dict[tuple[float, str, str], list[SimulationRun]] = {}
    for run in runs:
        cost = float(run.experiment.parameters.bypass_detour_seconds)
        condition_name = next(
            name for name, condition in REPLAY_CONDITIONS.items()
            if condition["scenario_id"] == run.experiment.scenario_id
        )
        arm = _arm_from_run(run)
        runs_by_cost_condition_arm.setdefault((cost, condition_name, arm), []).append(run)

    conditions_summary: dict[str, dict] = {}
    csv_rows: list[dict] = []
    zero_level = 0.0
    for condition_name, condition in REPLAY_CONDITIONS.items():
        cost_results: dict[str, dict] = {}
        for cost in levels:
            by_arm = {
                arm: sorted(
                    runs_by_cost_condition_arm[(cost, condition_name, arm)],
                    key=lambda item: item.experiment.seed,
                )
                for arm in POLICY_ARMS
            }
            if any(len(arm_runs) != replay_seeds for arm_runs in by_arm.values()):
                raise ValueError(f"Unexpected run count for {condition_name} at detour {cost}s")

            policy_summaries = {arm: _arm_summary(arm_runs) for arm, arm_runs in by_arm.items()}
            for arm, policy_summary in policy_summaries.items():
                policy_summary["bypass_ratio"] = 0.0 if arm == "baseline" else bypass_ratio
                csv_rows.append(_metric_row(condition_name, condition, cost, arm, policy_summary))

            paired_comparisons = {
                comparison_name: {
                    metric: _paired_delta(by_arm[baseline_arm], by_arm[treatment_arm], metric)
                    for metric in COMPARISON_METRICS
                }
                for comparison_name, treatment_arm, baseline_arm in COMPARISON_PAIRS
            }
            zero_by_arm = {
                arm: runs_by_cost_condition_arm[(zero_level, condition_name, arm)]
                for arm in POLICY_ARMS
            }
            cost_effects_vs_zero = {
                arm: _paired_delta(
                    zero_by_arm[arm], by_arm[arm], "policy_objective_score"
                )
                for arm in POLICY_ARMS
            }
            cost_results[_level_key(cost)] = {
                "detour_cost_seconds": cost,
                "policies": policy_summaries,
                "paired_comparisons": paired_comparisons,
                "objective_score_effect_vs_zero_detour": cost_effects_vs_zero,
            }
        conditions_summary[condition_name] = {
            "scenario_id": condition["scenario_id"],
            "traffic_demand": condition["traffic_demand"],
            "priority_ratio": condition["priority_ratio"],
            "detour_levels": cost_results,
        }

    summary = {
        "project": "RESILIANT-Z",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": current_git_sha(),
        "backend": "discrete_event",
        "evidence_label": "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM",
        "experiment": "paired bypass-detour sensitivity analysis",
        "counts": {
            "total_runs": len(runs),
            "detour_cost_levels": len(levels),
            "conditions": len(REPLAY_CONDITIONS),
            "policy_arms": len(POLICY_ARMS),
            "paired_seeds_per_arm_condition_level": replay_seeds,
        },
        "protocol": {
            "detour_cost_levels_seconds": list(levels),
            "selected_bypass_ratio_held_fixed": bypass_ratio,
            "seeds": list(seeds),
            "comparison": "common seed within each policy arm, operating condition, and detour level",
            "cost_sweep": (
                "the bypass ratio is held fixed while bypass_detour_seconds varies; policy selection "
                "is not rerun at each cost level"
            ),
            "reference_level_seconds": zero_level,
            "objective_weights": {
                "completion_shortfall": 0.40,
                "not_started_fraction": 0.20,
                "normalized_started_wait": 0.20,
                "normalized_queue_growth": 0.10,
                "bypass_detour_capacity_fraction": 0.05,
                "bypass_intervention_fraction": 0.05,
            },
        },
        "conditions": conditions_summary,
    }

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary)
    _write_jsonl(output / "manifests.jsonl", [manifest.model_dump(mode="json") for manifest in manifests])
    _write_jsonl(output / "runs.jsonl", [run.model_dump(mode="json") for run in runs])
    _write_csv(output / "sensitivity.csv", csv_rows)
    (output / "report.md").write_text(_build_report(summary), encoding="utf-8")
    return summary


def _build_report(summary: dict) -> str:
    """Render a compact human-readable report from the exact JSON summary."""
    lines = [
        "# RESILIANT-Z detour-cost sensitivity analysis",
        "",
        f"- Evidence label: **{summary['evidence_label']}**",
        f"- Total runs: **{summary['counts']['total_runs']}**",
        f"- Fixed bypass ratio for static and conditioned arms: **{summary['protocol']['selected_bypass_ratio_held_fixed']:.2f}**",
        f"- Paired seeds per policy/condition/cost: **{summary['counts']['paired_seeds_per_arm_condition_level']}**",
        f"- Detour levels (simulated seconds): **{', '.join(f'{x:g}' for x in summary['protocol']['detour_cost_levels_seconds'])}**",
        "",
        "The experiment holds the bypass ratio constant and varies only the explicit robot-occupancy detour penalty. It does not reselect the policy at each level. The combined objective is a predefined design score, not an empirically calibrated business utility.",
        "",
    ]
    for condition_name, condition in summary["conditions"].items():
        lines.extend([
            f"## {condition_name.replace('_', ' ').title()} condition",
            "",
            f"Scenario `{condition['scenario_id']}`; traffic demand `{condition['traffic_demand']}`; priority ratio `{condition['priority_ratio']}`.",
            "",
            "| Detour (s) | Baseline score | Static score | Conditioned score | Conditioned − static score (95% CI) | Static bypass tasks | Conditioned bypass tasks |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for _, level in condition["detour_levels"].items():
            policies = level["policies"]
            delta = level["paired_comparisons"]["conditioned_vs_static"]["policy_objective_score"]
            lines.append(
                f"| {level['detour_cost_seconds']:g} | "
                f"{policies['baseline']['mean_policy_objective_score']:.5f} | "
                f"{policies['static']['mean_policy_objective_score']:.5f} | "
                f"{policies['conditioned']['mean_policy_objective_score']:.5f} | "
                f"{delta['mean_delta_treatment_minus_baseline']:+.5f} "
                f"([{delta['ci95_low']:+.5f}, {delta['ci95_high']:+.5f}]) | "
                f"{policies['static']['bypass_tasks_total']} | "
                f"{policies['conditioned']['bypass_tasks_total']} |"
            )
        lines.extend(["", "### Cost effect relative to zero-second detour", ""])
        lines.append(
            "| Detour (s) | Policy | Objective-score delta vs 0 s (95% CI) | Mean throughput (tasks/min) | Started-task wait (s) | Completion fraction | Mean applied detour (s/run) |"
        )
        lines.append("|---:|---|---:|---:|---:|---:|---:|")
        for _, level in condition["detour_levels"].items():
            for arm in POLICY_ARMS:
                policy = level["policies"][arm]
                delta = level["objective_score_effect_vs_zero_detour"][arm]
                task_counts = policy["task_counts"]
                lines.append(
                    f"| {level['detour_cost_seconds']:g} | {arm} | "
                    f"{delta['mean_delta_treatment_minus_baseline']:+.5f} "
                    f"([{delta['ci95_low']:+.5f}, {delta['ci95_high']:+.5f}]) | "
                    f"{policy['mean_throughput_tasks_per_min']:.3f} | "
                    f"{policy['mean_started_task_wait_seconds']:.2f} | "
                    f"{task_counts['completion_fraction']:.3%} | "
                    f"{policy['mean_bypass_detour_total_seconds']:.2f} |"
                )
        lines.append("")

    lines.extend([
        "## Interpretation guardrails",
        "",
        "- These are deterministic, paired runs of the CPU-only discrete-event model; they are not Isaac Sim or physical-robot results.",
        "- The 2.5-second default is a design assumption, not a calibrated travel-time measurement.",
        "- The fixed bypass ratio prevents cost-specific re-tuning from being conflated with sensitivity to the detour assumption.",
        "- Confidence intervals are unadjusted exploratory 95% Student-t intervals across multiple metrics and cost levels; treat borderline results cautiously.",
        "- Review `sensitivity.csv` for the long-form table, `summary.json` for paired comparisons, and the JSONL files for run-level provenance.",
        "",
    ])
    return "\n".join(lines)
