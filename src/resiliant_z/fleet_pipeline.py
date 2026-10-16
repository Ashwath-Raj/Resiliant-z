"""End-to-end local discrete-event fleet benchmark (no Token Factory required)."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from resiliant_z.evidence.analyzer import analyze_discovery
from resiliant_z.experiments.planner import (
    POLICY_BYPASS_CANDIDATES,
    REPLAY_CONDITIONS,
    factorial_manifests,
    policy_comparison_manifests,
    policy_selection_manifests,
)
from resiliant_z.llm.nebius import local_hypotheses
from resiliant_z.models import SimulationRun
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator
from resiliant_z.simulation.surrogate import current_git_sha

# Predeclared weights for the policy-selection loss. Each component is normalized
# to [0, 1]; lower scores are preferred. The weights are design choices, not learned.
POLICY_OBJECTIVE_WEIGHTS = {
    "completion_shortfall": 0.40,
    "not_started_fraction": 0.20,
    "normalized_started_wait": 0.20,
    "normalized_queue_growth": 0.10,
    "bypass_detour_capacity_fraction": 0.05,
    "bypass_intervention_fraction": 0.05,
}
WAIT_NORMALIZATION_SECONDS = 60.0


def _mean(runs: list[SimulationRun], key: str) -> float:
    values = [float(getattr(run.metrics, key)) for run in runs]
    return statistics.fmean(values) if values else 0.0


def _pooled_started_wait(runs: list[SimulationRun]) -> tuple[float, int]:
    """Return task-weighted wait mean and its observed route-start sample count."""
    count = sum(run.metrics.route_service_started_count or 0 for run in runs)
    total = sum(run.metrics.route_service_wait_total_seconds or 0.0 for run in runs)
    return (total / count if count else 0.0), count


def _policy_objective_components(run: SimulationRun) -> dict[str, float]:
    """Calculate transparent, normalized operational penalties for one run."""
    metrics = run.metrics
    parameters = run.experiment.parameters
    arrivals = metrics.task_arrivals or 0
    completions = metrics.task_completions or 0
    not_started = metrics.tasks_not_started_by_horizon or 0
    bypass_tasks = metrics.bypass_task_count or 0
    bypass_detour_seconds = metrics.bypass_detour_total_seconds or 0.0

    completion_shortfall = max(0.0, 1.0 - completions / arrivals) if arrivals else 0.0
    not_started_fraction = min(1.0, not_started / arrivals) if arrivals else 0.0
    normalized_started_wait = min(1.0, metrics.average_wait_seconds / WAIT_NORMALIZATION_SECONDS)
    arrival_rate_per_minute = 12.0 * parameters.traffic_demand
    normalized_queue_growth = min(1.0, metrics.queue_growth_per_min / arrival_rate_per_minute)
    available_robot_seconds = (
        DiscreteEventFleetSimulator.robot_count * DiscreteEventFleetSimulator.duration_seconds
    )
    bypass_detour_capacity_fraction = min(1.0, bypass_detour_seconds / available_robot_seconds)
    bypass_intervention_fraction = min(1.0, bypass_tasks / arrivals) if arrivals else 0.0

    return {
        "completion_shortfall": completion_shortfall,
        "not_started_fraction": not_started_fraction,
        "normalized_started_wait": normalized_started_wait,
        "normalized_queue_growth": normalized_queue_growth,
        "bypass_detour_capacity_fraction": bypass_detour_capacity_fraction,
        "bypass_intervention_fraction": bypass_intervention_fraction,
    }


def _policy_objective_score(run: SimulationRun) -> float:
    """Weighted normalized penalty; lower is better, with fixed published weights."""
    components = _policy_objective_components(run)
    return sum(weight * components[name] for name, weight in POLICY_OBJECTIVE_WEIGHTS.items())


def _task_counts(runs: list[SimulationRun]) -> dict[str, float | int]:
    arrivals = sum(run.metrics.task_arrivals or 0 for run in runs)
    completions = sum(run.metrics.task_completions or 0 for run in runs)
    started = sum(run.metrics.route_service_started_count or 0 for run in runs)
    not_started = sum(run.metrics.tasks_not_started_by_horizon or 0 for run in runs)
    return {
        "arrivals": arrivals,
        "completions": completions,
        "completion_fraction": completions / arrivals if arrivals else 0.0,
        "route_service_started": started,
        "not_started_by_horizon": not_started,
        "not_started_fraction": not_started / arrivals if arrivals else 0.0,
    }


def _t_critical_975(degrees_of_freedom: int) -> float:
    """Two-sided 95% Student-t critical values for small paired samples."""
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
    }
    return table.get(degrees_of_freedom, 1.96 if degrees_of_freedom >= 30 else 12.706)


def _paired_delta(
    baseline: list[SimulationRun], treatment: list[SimulationRun], metric: str
) -> dict:
    """Paired per-seed differences and t interval; positive means treatment minus baseline."""
    baseline_by_seed = {run.experiment.seed: run for run in baseline}
    treatment_by_seed = {run.experiment.seed: run for run in treatment}
    common_seeds = sorted(baseline_by_seed.keys() & treatment_by_seed.keys())
    if len(common_seeds) < 3:
        raise ValueError("Paired replay comparisons require at least three common seeds")

    def value(run: SimulationRun) -> float:
        if metric == "completion_fraction":
            arrivals = run.metrics.task_arrivals or 0
            completions = run.metrics.task_completions or 0
            return completions / arrivals if arrivals else 0.0
        if metric == "policy_objective_score":
            return _policy_objective_score(run)
        return float(getattr(run.metrics, metric))

    differences = [
        value(treatment_by_seed[seed]) - value(baseline_by_seed[seed]) for seed in common_seeds
    ]
    mean_delta = statistics.fmean(differences)
    sample_variance = sum((item - mean_delta) ** 2 for item in differences) / (len(differences) - 1)
    standard_error = (sample_variance / len(differences)) ** 0.5
    margin = _t_critical_975(len(differences) - 1) * standard_error
    return {
        "paired_seed_count": len(differences),
        "mean_delta_treatment_minus_baseline": round(mean_delta, 6),
        "ci95_low": round(mean_delta - margin, 6),
        "ci95_high": round(mean_delta + margin, 6),
        "metric": metric,
    }


def _arm_summary(runs: list[SimulationRun]) -> dict:
    task_counts = _task_counts(runs)
    started_wait, started_wait_samples = _pooled_started_wait(runs)
    return {
        "run_count": len(runs),
        "mean_throughput_tasks_per_min": round(_mean(runs, "throughput_tasks_per_min"), 6),
        "mean_started_task_wait_seconds": round(started_wait, 6),
        "started_task_wait_sample_count": started_wait_samples,
        "mean_queue_growth_per_min": round(_mean(runs, "queue_growth_per_min"), 6),
        "mean_bypass_detour_total_seconds": round(_mean(runs, "bypass_detour_total_seconds"), 6),
        "mean_policy_objective_score": round(
            statistics.fmean(_policy_objective_score(run) for run in runs) if runs else 0.0,
            6,
        ),
        "mean_policy_objective_components": {
            name: round(
                statistics.fmean(_policy_objective_components(run)[name] for run in runs)
                if runs
                else 0.0,
                6,
            )
            for name in POLICY_OBJECTIVE_WEIGHTS
        },
        "task_counts": task_counts,
        "bypass_tasks_total": sum(run.metrics.bypass_task_count or 0 for run in runs),
        "bypass_intervention_fraction": (
            sum(run.metrics.bypass_task_count or 0 for run in runs)
            / sum(run.metrics.task_arrivals or 0 for run in runs)
            if sum(run.metrics.task_arrivals or 0 for run in runs)
            else 0.0
        ),
        "high_risk_context_arrivals_total": sum(
            run.metrics.high_risk_context_arrival_count or 0 for run in runs
        ),
        "conditional_policy_triggers_total": sum(
            run.metrics.conditional_policy_trigger_count or 0 for run in runs
        ),
        "mean_censored_wait_observation_seconds": round(
            _mean(runs, "censored_wait_observation_seconds"), 6
        ),
    }


def _summarize_policy_comparison(
    runs: list[SimulationRun], *, replay_seeds: int, selected_bypass_ratio: float
) -> dict:
    """Summarize three policies under nominal and high-risk operating conditions."""
    result: dict[str, dict] = {}
    for condition_name, condition in REPLAY_CONDITIONS.items():
        condition_runs = [
            run for run in runs if run.experiment.scenario_id == condition["scenario_id"]
        ]
        by_arm: dict[str, list[SimulationRun]] = {"baseline": [], "static": [], "conditioned": []}
        for run in condition_runs:
            parts = run.experiment.experiment_id.split("-")
            if len(parts) < 4 or parts[0] != "REPLAY":
                raise ValueError(f"Unexpected replay ID: {run.experiment.experiment_id}")
            arm = parts[2].lower()
            if arm not in by_arm:
                raise ValueError(f"Unknown policy arm {arm!r} in {run.experiment.experiment_id}")
            by_arm[arm].append(run)
        for arm, arm_runs in by_arm.items():
            if len(arm_runs) != replay_seeds:
                raise ValueError(
                    f"Expected {replay_seeds} runs for {condition_name}/{arm}; got {len(arm_runs)}"
                )

        comparisons: dict[str, dict] = {}
        pairs = (
            ("static_vs_baseline", "static", "baseline"),
            ("conditioned_vs_baseline", "conditioned", "baseline"),
            ("conditioned_vs_static", "conditioned", "static"),
        )
        for comparison_name, treatment_arm, baseline_arm in pairs:
            comparisons[comparison_name] = {
                metric: _paired_delta(by_arm[baseline_arm], by_arm[treatment_arm], metric)
                for metric in (
                    "throughput_tasks_per_min",
                    "completion_fraction",
                    "average_wait_seconds",
                    "queue_growth_per_min",
                    "bypass_task_count",
                    "bypass_detour_total_seconds",
                    "policy_objective_score",
                )
            }

        result[condition_name] = {
            "scenario_id": condition["scenario_id"],
            "traffic_demand": condition["traffic_demand"],
            "priority_ratio": condition["priority_ratio"],
            "policies": {arm: _arm_summary(arm_runs) for arm, arm_runs in by_arm.items()},
            "paired_comparisons": comparisons,
            "conditioned_activation": {
                "eligible_high_risk_arrivals": sum(
                    run.metrics.high_risk_context_arrival_count or 0
                    for run in by_arm["conditioned"]
                ),
                "junction_pressure_triggers": sum(
                    run.metrics.conditional_policy_trigger_count or 0
                    for run in by_arm["conditioned"]
                ),
                "actual_bypass_tasks": sum(
                    run.metrics.bypass_task_count or 0 for run in by_arm["conditioned"]
                ),
            },
        }
    return {
        "paired_seed_count_per_condition": replay_seeds,
        "selected_bypass_ratio": selected_bypass_ratio,
        "conditions": result,
        "comparison_protocol": (
            "baseline, static-control and discovery-conditioned arms use paired seeds within each "
            "condition; policy-selection seeds are disjoint from replay seeds"
        ),
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _select_bypass_ratio(runs: list[SimulationRun]) -> tuple[float, list[dict]]:
    """Select a treatment using policy-selection seeds only.

    Minimize the predeclared weighted normalized operational penalty. The final
    paired replay uses different seeds. Component scores and weights are emitted
    in the artifacts so the trade-off is auditable.
    """
    if not runs:
        raise ValueError("Cannot select a policy without candidate runs")
    grouped: dict[float, list[SimulationRun]] = {}
    for run in runs:
        ratio = run.experiment.parameters.bypass_ratio
        grouped.setdefault(ratio, []).append(run)

    candidate_results: list[dict] = []
    for ratio, candidate_runs in sorted(grouped.items()):
        waits, wait_samples = _pooled_started_wait(candidate_runs)
        candidate_results.append(
            {
                "bypass_ratio": ratio,
                "seed_count": len(candidate_runs),
                "mean_completed_tasks": round(_mean(candidate_runs, "task_completions"), 6),
                "mean_throughput_tasks_per_min": round(
                    _mean(candidate_runs, "throughput_tasks_per_min"), 6
                ),
                "pooled_started_task_wait_seconds": round(waits, 6),
                "started_task_wait_sample_count": wait_samples,
                "mean_queue_growth_per_min": round(
                    _mean(candidate_runs, "queue_growth_per_min"), 6
                ),
                "mean_bypass_detour_total_seconds": round(
                    _mean(candidate_runs, "bypass_detour_total_seconds"), 6
                ),
                "mean_bypass_intervention_fraction": round(
                    sum(run.metrics.bypass_task_count or 0 for run in candidate_runs)
                    / sum(run.metrics.task_arrivals or 0 for run in candidate_runs),
                    6,
                ),
                "mean_policy_objective_score": round(
                    statistics.fmean(_policy_objective_score(run) for run in candidate_runs),
                    6,
                ),
                "mean_policy_objective_components": {
                    name: round(
                        statistics.fmean(
                            _policy_objective_components(run)[name] for run in candidate_runs
                        ),
                        6,
                    )
                    for name in POLICY_OBJECTIVE_WEIGHTS
                },
            }
        )

    # Minimum loss wins; the bypass ratio is a deterministic tie-break only.
    winner = min(
        candidate_results,
        key=lambda row: (row["mean_policy_objective_score"], row["bypass_ratio"]),
    )
    return float(winner["bypass_ratio"]), candidate_results


def run_fleet_demo(
    output_dir: str | Path = "artifacts/fleet-demo",
    *,
    seeds_per_cell: int = 5,
    replay_seeds: int = 12,
    policy_selection_seeds: int = 5,
) -> dict:
    """Run a seeded CPU queueing model, held-out analysis, and paired policy replay.

    This mode is intentionally independent of Token Factory. It is an intermediate
    engineering testbed and must not be described as Isaac Sim evidence.
    """
    if seeds_per_cell < 3:
        raise ValueError("Use at least three seeds per factorial condition")
    if replay_seeds < 3:
        raise ValueError("Use at least three paired replay seeds")
    if policy_selection_seeds < 3:
        raise ValueError("Use at least three policy-selection seeds per candidate")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    simulator = DiscreteEventFleetSimulator()

    discovery_manifests = factorial_manifests(
        stage="discovery", seeds_per_cell=seeds_per_cell, first_seed=40_000
    )
    validation_manifests = factorial_manifests(
        stage="validation", seeds_per_cell=seeds_per_cell, first_seed=50_000
    )
    discovery_runs = [simulator.run(m) for m in discovery_manifests]
    validation_runs = [simulator.run(m) for m in validation_manifests]
    decision = analyze_discovery(discovery_runs, validation_runs, backend="discrete_event")

    # Policy activation is gated by the independently validated interaction.
    # Candidate selection and final replay use disjoint seed ranges.
    selection_manifests = []
    selection_runs: list[SimulationRun] = []
    candidate_results: list[dict] = []
    if decision.status == "validated":
        selection_manifests = policy_selection_manifests(
            seeds_per_candidate=policy_selection_seeds,
            first_seed=55_000,
            bypass_candidates=POLICY_BYPASS_CANDIDATES,
        )
        selection_runs = [simulator.run(m) for m in selection_manifests]
        selected_bypass_ratio, candidate_results = _select_bypass_ratio(selection_runs)
        selection_status = "selected_after_validated_discovery"
    else:
        selected_bypass_ratio = 0.0
        selection_status = "blocked_because_discovery_was_not_validated"

    policy_selection = {
        "status": selection_status,
        "discovery_status": decision.status,
        "selected_bypass_ratio": selected_bypass_ratio,
        "candidate_bypass_ratios": list(POLICY_BYPASS_CANDIDATES),
        "seeds_per_candidate": policy_selection_seeds,
        "candidate_results": candidate_results,
        "selection_objective": (
            "minimize a weighted normalized operational penalty: completion shortfall, tasks not "
            "started by the horizon, started-task wait, queue growth, applied bypass detour capacity, "
            "and bypass intervention frequency; lower bypass ratio breaks exact score ties"
        ),
        "selection_objective_weights": POLICY_OBJECTIVE_WEIGHTS,
        "selection_objective_normalization": {
            "started_task_wait_seconds": WAIT_NORMALIZATION_SECONDS,
            "queue_growth": "normalized by model arrival rate (12 * traffic_demand tasks/min), capped at 1",
            "bypass_detour_capacity": "applied detour seconds / (robot count * simulated horizon seconds), capped at 1",
            "other_fractions": "bounded fractions in [0, 1]",
        },
        "seed_protocol": (
            "all candidates share seeds within policy selection; final paired replay uses a "
            "disjoint seed range"
        ),
    }

    manifests = policy_comparison_manifests(
        seeds=range(60_001, 60_001 + replay_seeds),
        selected_bypass_ratio=selected_bypass_ratio,
    )
    replay_runs = [simulator.run(m) for m in manifests]
    replay_summary = _summarize_policy_comparison(
        replay_runs,
        replay_seeds=replay_seeds,
        selected_bypass_ratio=selected_bypass_ratio,
    )
    hypotheses = local_hypotheses().model_dump(mode="json")
    all_runs = [*discovery_runs, *validation_runs, *selection_runs, *replay_runs]
    all_manifests = [*discovery_manifests, *validation_manifests, *selection_manifests, *manifests]
    summary = {
        "project": "RESILIANT-Z",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": current_git_sha(),
        "backend": "discrete_event",
        "evidence_label": "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM",
        "hypothesis_generation": {
            "source": "local_baseline",
            "model_id": "none",
            "hypotheses": hypotheses,
        },
        "counts": {
            "total_runs": len(all_runs),
            "discovery_runs": len(discovery_runs),
            "validation_runs": len(validation_runs),
            "policy_selection_runs": len(selection_runs),
            "replay_runs": len(replay_runs),
        },
        "discovery": decision.model_dump(mode="json"),
        "policy_selection": policy_selection,
        "policy_replay": replay_summary,
        "model_assumptions": {
            "robots": simulator.robot_count,
            "duration_seconds": simulator.duration_seconds,
            "arrivals": "Poisson process at 0.20 * traffic_demand tasks/second",
            "priority_effect": "priority-first service order with longer service windows",
            "bypass_detour_seconds": "2.5s default extra robot-occupancy time after a bypass route completes; configurable 0-30s and not empirically calibrated",
            "conditional_policy": "bypass only when demand and priority are in the predefined high-risk envelope and junction queue pressure reaches the trigger",
            "policy_thresholds": "predeclared midpoints between factorial design levels, not discovered thresholds",
            "paired_randomness": "per-task random variates are pre-sampled for policy comparisons",
            "geometry_and_collisions": "not modelled",
            "deadlocks": "not modelled or measured; the metric is null",
        },
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "hypotheses.json", {"source": "local_baseline", "model_id": "none", **hypotheses}
    )
    _write_json(output / "discovery.json", decision.model_dump(mode="json"))
    _write_jsonl(output / "manifests.jsonl", [m.model_dump(mode="json") for m in all_manifests])
    _write_jsonl(output / "runs.jsonl", [r.model_dump(mode="json") for r in all_runs])

    lines = [
        "# RESILIANT-Z local discrete-event benchmark",
        "",
        f"> **EVIDENCE LABEL: {summary['evidence_label']}**",
        "",
        "This backend models queues and service capacity; it does not model robot geometry, collisions, sensors, or physics.",
        "Wait metrics are separated: the reported started-task mean excludes tasks whose route service had not started by the horizon; those right-censored tasks and their horizon-limited wait-observation mean are reported separately.",
        "The bypass route adds a default 2.5 simulated seconds to robot return/availability after its route service completes. This is an explicit uncalibrated scenario cost, not measured travel time.",
        "",
        "## Reproducibility",
        "",
        f"- UTC created: `{summary['created_at']}`",
        f"- Git SHA: `{summary['git_sha']}`",
        f"- Seeded run count: `{summary['counts']['total_runs']}`",
        f"- Hypothesis source: `{summary['hypothesis_generation']['source']}`",
        "",
        "## Held-out evidence comparison",
        "",
        f"- Decision: **{decision.status.upper()}**",
        f"- Main-effects RMSE (held-out): `{decision.validation_main_effect_rmse:.6f}`",
        f"- Interaction-model RMSE (held-out): `{decision.validation_interaction_rmse:.6f}`",
        f"- Discovery interaction coefficient: `{decision.interaction_effect:.6f}`",
        f"- Held-out interaction contrast: `{decision.validation_interaction_effect:.6f}`",
        f"- Held-out interaction 95% CI: `[{decision.validation_interaction_ci_lower:.6f}, {decision.validation_interaction_ci_upper:.6f}]`",
        f"- Relative held-out RMSE improvement: `{decision.validation_improvement_fraction:.1%}`",
        "",
        "## Evidence-gated policy selection",
        "",
        f"- Selection status: **{policy_selection['status']}**",
        f"- Discovery gate: `{decision.status}`",
        f"- Selection runs: `{len(selection_runs)}`",
        f"- Selected bypass ratio: `{selected_bypass_ratio:.2f}`",
        f"- Predeclared objective: {policy_selection['selection_objective']}",
        f"- Objective weights: `{json.dumps(POLICY_OBJECTIVE_WEIGHTS, sort_keys=True)}`",
        "- Candidate scores (selection seeds only; lower policy objective score is preferred):",
        *(
            [
                f"  - bypass `{row['bypass_ratio']:.2f}`: objective score `{row['mean_policy_objective_score']:.5f}`; "
                f"completed `{row['mean_completed_tasks']:.2f}` tasks/run; "
                f"throughput `{row['mean_throughput_tasks_per_min']:.3f}` tasks/min; "
                f"queue growth `{row['mean_queue_growth_per_min']:.3f}`/min; "
                f"started-task wait `{row['pooled_started_task_wait_seconds']:.2f}` s; "
                f"detour `{row['mean_bypass_detour_total_seconds']:.2f}` s/run; "
                f"bypass rate `{row['mean_bypass_intervention_fraction']:.1%}`"
                for row in candidate_results
            ]
            or ["  - No candidates evaluated because discovery was not validated."]
        ),
        "- Policy selection seeds and final replay seeds are disjoint.",
        "",
        "## Three-policy comparison on held-out paired seeds",
        "",
        f"- Paired seeds per operating condition: `{replay_seeds}`",
        f"- Selected static bypass ratio: `{selected_bypass_ratio:.2f}`",
        "- Policy arms: baseline (no bypass), static control (selected ratio always eligible), and discovery-conditioned (same ratio only when the validated high-risk envelope and live junction-pressure trigger are both present).",
        "- Operating-envelope thresholds are midpoints between the predefined factorial levels; they are not claimed to be discovered thresholds.",
        "- Static-control selection uses high-risk policy-selection runs only; all final replay seeds are disjoint from selection seeds.",
        "",
    ]
    for condition_name, condition_result in replay_summary["conditions"].items():
        lines.extend(
            [
                f"### {condition_name.replace('_', ' ').title()} condition",
                "",
                f"- Workload: traffic demand `{condition_result['traffic_demand']}`, priority ratio `{condition_result['priority_ratio']}`.",
                "- Policy metrics (means across paired seeds):",
            ]
        )
        for arm_name, arm_result in condition_result["policies"].items():
            task_counts = arm_result["task_counts"]
            lines.append(
                f"  - **{arm_name}**: throughput `{arm_result['mean_throughput_tasks_per_min']:.3f}` tasks/min; "
                f"started-task wait `{arm_result['mean_started_task_wait_seconds']:.2f}` s "
                f"(n={arm_result['started_task_wait_sample_count']} tasks); "
                f"completion `{task_counts['completions']}/{task_counts['arrivals']}` "
                f"({task_counts['completion_fraction']:.1%}); "
                f"queue growth `{arm_result['mean_queue_growth_per_min']:.3f}`/min; "
                f"objective score `{arm_result['mean_policy_objective_score']:.5f}`; "
                f"applied bypass detour `{arm_result['mean_bypass_detour_total_seconds']:.2f}` s/run; "
                f"bypass tasks `{arm_result['bypass_tasks_total']}`; "
                f"conditional triggers `{arm_result['conditional_policy_triggers_total']}`."
            )
        lines.append("- Paired treatment-minus-baseline differences (95% Student-t intervals):")
        for comparison_name, metrics in condition_result["paired_comparisons"].items():
            lines.append(f"  - **{comparison_name}**:")
            for metric_name, stats in metrics.items():
                lines.append(
                    f"    - `{metric_name}`: mean delta `{stats['mean_delta_treatment_minus_baseline']:.4f}`; "
                    f"95% CI `[{stats['ci95_low']:.4f}, {stats['ci95_high']:.4f}]` (n={stats['paired_seed_count']})."
                )
        activation = condition_result["conditioned_activation"]
        lines.extend(
            [
                f"- Conditioned policy counters: `{activation['eligible_high_risk_arrivals']}` high-risk-envelope arrivals, "
                f"`{activation['junction_pressure_triggers']}` pressure triggers, "
                f"`{activation['actual_bypass_tasks']}` actual bypass tasks.",
                "",
            ]
        )
    lines.extend(
        [
            "## Explicit limitations",
            "",
            *[f"- {item}" for item in decision.limitations],
            "- The queueing model contains explicit scenario assumptions; outcomes cannot be generalized to physical robots without Isaac Sim validation.",
            "- Policy-condition thresholds are predeclared design midpoints, not learned thresholds.",
            "- This benchmark does not call Token Factory and does not require a GPU.",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
