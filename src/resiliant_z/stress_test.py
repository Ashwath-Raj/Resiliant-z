"""Paired workload robustness experiment. Local discrete-event model, not Isaac Sim."""

from __future__ import annotations

import argparse
import csv
import math
from datetime import UTC, datetime
from pathlib import Path

from resiliant_z.fleet_pipeline import _arm_summary, _paired_delta, _write_json, _write_jsonl
from resiliant_z.models import ExperimentManifest, ExperimentParameters
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator
from resiliant_z.simulation.surrogate import current_git_sha

TRAFFIC_DEMAND_LEVELS = (0.55, 0.80, 1.05, 1.20)
PRIORITY_RATIO_LEVELS = (0.15, 0.30, 0.50)
POLICY_ARMS = ("baseline", "static", "conditioned")
BYPASS_RATIO = 0.45
DETOUR_COST_SECONDS = 2.5
PAIRS = (
    ("static_vs_baseline", "static", "baseline"),
    ("conditioned_vs_baseline", "conditioned", "baseline"),
    ("conditioned_vs_static", "conditioned", "static"),
)
METRICS = (
    "throughput_tasks_per_min",
    "completion_fraction",
    "average_wait_seconds",
    "queue_growth_per_min",
    "bypass_task_count",
    "bypass_detour_total_seconds",
    "policy_objective_score",
)
CSV_FIELDS = (
    "traffic_demand",
    "priority_ratio",
    "policy",
    "bypass_ratio",
    "detour_cost_seconds",
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
    "high_risk_arrivals_total",
    "conditional_triggers_total",
)


def _tag(value: float) -> str:
    return format(float(value), ".15g").replace("-", "m").replace(".", "p")


def _make_manifests(*, demands, priorities, seeds, bypass_ratio, detour_cost_seconds):
    sha = current_git_sha()
    result = []
    for demand in demands:
        for priority in priorities:
            for seed in seeds:
                for arm in POLICY_ARMS:
                    result.append(
                        ExperimentManifest(
                            experiment_id=f"STRESS-D{_tag(demand)}-P{_tag(priority)}-{arm.upper()}-S{seed}",
                            scenario_id=f"stress_d{_tag(demand)}_p{_tag(priority)}_v1",
                            stage="replay",
                            seed=seed,
                            git_sha=sha,
                            parameters=ExperimentParameters(
                                traffic_demand=demand,
                                priority_ratio=priority,
                                bypass_ratio=0.0 if arm == "baseline" else bypass_ratio,
                                bypass_detour_seconds=detour_cost_seconds,
                                routing_policy="conditioned" if arm == "conditioned" else "static",
                            ),
                        )
                    )
    return result


def _metric_row(demand, priority, arm, s):
    counts = s["task_counts"]
    return {
        "traffic_demand": demand,
        "priority_ratio": priority,
        "policy": arm,
        "bypass_ratio": 0.0 if arm == "baseline" else BYPASS_RATIO,
        "detour_cost_seconds": DETOUR_COST_SECONDS,
        "run_count": s["run_count"],
        "mean_throughput_tasks_per_min": s["mean_throughput_tasks_per_min"],
        "mean_started_task_wait_seconds": s["mean_started_task_wait_seconds"],
        "completion_fraction": counts["completion_fraction"],
        "not_started_fraction": counts["not_started_fraction"],
        "mean_queue_growth_per_min": s["mean_queue_growth_per_min"],
        "mean_bypass_detour_total_seconds": s["mean_bypass_detour_total_seconds"],
        "bypass_tasks_total": s["bypass_tasks_total"],
        "bypass_intervention_fraction": s["bypass_intervention_fraction"],
        "mean_policy_objective_score": s["mean_policy_objective_score"],
        "high_risk_arrivals_total": s.get(
            "high_risk_context_arrivals_total", s.get("high_risk_arrivals_total", "")
        ),
        "conditional_triggers_total": s.get(
            "conditional_policy_triggers_total", s.get("conditional_triggers_total", "")
        ),
    }


def run_fleet_stress_test(
    output_dir="artifacts/fleet-stress-test",
    *,
    replay_seeds=12,
    first_seed=81001,
    traffic_demand_levels=TRAFFIC_DEMAND_LEVELS,
    priority_ratio_levels=PRIORITY_RATIO_LEVELS,
    bypass_ratio=BYPASS_RATIO,
    detour_cost_seconds=DETOUR_COST_SECONDS,
):
    if replay_seeds < 3:
        raise ValueError("Use at least three paired replay seeds")
    if first_seed < 0 or first_seed + replay_seeds - 1 > 2**31 - 1:
        raise ValueError("first_seed and replay_seeds exceed supported seed range")
    if not math.isfinite(bypass_ratio) or not 0 <= bypass_ratio <= 0.5:
        raise ValueError("bypass_ratio must be finite and within [0.0, 0.5]")
    if not math.isfinite(detour_cost_seconds) or not 0 <= detour_cost_seconds <= 30:
        raise ValueError("detour_cost_seconds must be finite and within [0.0, 30.0]")
    demands, priorities = (
        tuple(map(float, traffic_demand_levels)),
        tuple(map(float, priority_ratio_levels)),
    )
    if not demands or len(set(demands)) != len(demands):
        raise ValueError("Traffic-demand levels must be non-empty and unique")
    if not priorities or len(set(priorities)) != len(priorities):
        raise ValueError("Priority-ratio levels must be non-empty and unique")
    if any(not math.isfinite(x) or not 0.4 <= x <= 1.2 for x in demands):
        raise ValueError("Traffic-demand levels must be finite and within [0.4, 1.2]")
    if any(not math.isfinite(x) or not 0.1 <= x <= 0.6 for x in priorities):
        raise ValueError("Priority-ratio levels must be finite and within [0.1, 0.6]")
    seeds = tuple(range(first_seed, first_seed + replay_seeds))
    manifests = _make_manifests(
        demands=demands,
        priorities=priorities,
        seeds=seeds,
        bypass_ratio=bypass_ratio,
        detour_cost_seconds=detour_cost_seconds,
    )
    simulator = DiscreteEventFleetSimulator()
    runs = [simulator.run(m) for m in manifests]
    grouped = {}
    for run in runs:
        p = run.experiment.parameters
        arm = run.experiment.experiment_id.split("-")[3].lower()
        grouped.setdefault((p.traffic_demand, p.priority_ratio, arm), []).append(run)
    conditions, rows = {}, []
    for demand in demands:
        for priority in priorities:
            key = f"demand_{_tag(demand)}__priority_{_tag(priority)}"
            by_arm = {
                arm: sorted(grouped[(demand, priority, arm)], key=lambda r: r.experiment.seed)
                for arm in POLICY_ARMS
            }
            if any(len(rs) != replay_seeds for rs in by_arm.values()):
                raise ValueError(f"Unexpected run count in {key}")
            for seed in seeds:
                for arm in POLICY_ARMS:
                    if sum(r.experiment.seed == seed for r in by_arm[arm]) != 1:
                        raise ValueError(f"Missing/duplicate paired seed {seed} in {key}/{arm}")
            summaries = {arm: _arm_summary(rs) for arm, rs in by_arm.items()}
            rows.extend(_metric_row(demand, priority, arm, s) for arm, s in summaries.items())
            comparisons = {
                label: {
                    metric: _paired_delta(by_arm[base], by_arm[treatment], metric)
                    for metric in METRICS
                }
                for label, treatment, base in PAIRS
            }
            conditions[key] = {
                "traffic_demand": demand,
                "priority_ratio": priority,
                "scenario_id": f"stress_d{_tag(demand)}_p{_tag(priority)}_v1",
                "policies": summaries,
                "paired_comparisons": comparisons,
            }
    summary = {
        "project": "RESILIANT-Z",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": current_git_sha(),
        "backend": "discrete_event",
        "evidence_label": "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM",
        "experiment": "paired workload stress test",
        "counts": {
            "total_runs": len(runs),
            "traffic_demand_levels": len(demands),
            "priority_ratio_levels": len(priorities),
            "workload_cells": len(demands) * len(priorities),
            "policy_arms": len(POLICY_ARMS),
            "paired_seeds_per_arm_cell": replay_seeds,
        },
        "protocol": {
            "traffic_demand_levels": list(demands),
            "priority_ratio_levels": list(priorities),
            "selected_bypass_ratio_held_fixed": bypass_ratio,
            "bypass_detour_seconds_held_fixed": detour_cost_seconds,
            "seeds": list(seeds),
            "policy_arms": list(POLICY_ARMS),
            "comparison": "same seed within each workload cell across baseline/static/conditioned arms",
            "factor_levels_are": "experimental design settings, not calibrated real-world thresholds",
            "limitations": [
                "CPU-only discrete-event model; not Isaac Sim or a physics simulator",
                "No geometry, collisions, kinematics, sensors, or true deadlock modeling",
                "deadlock_events is unmeasured; it is not safety evidence",
                "Started-task wait excludes tasks not started by the horizon; inspect not-started/censored metrics",
                "Confidence intervals are exploratory, unadjusted paired Student-t intervals",
            ],
        },
        "conditions": conditions,
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary)
    _write_jsonl(output / "manifests.jsonl", [m.model_dump(mode="json") for m in manifests])
    _write_jsonl(output / "runs.jsonl", [r.model_dump(mode="json") for r in runs])
    with (output / "stress_test.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (output / "report.md").write_text(_build_report(summary), encoding="utf-8")
    return summary


def _build_report(summary):
    c = summary["counts"]
    lines = [
        "# RESILIANT-Z workload stress test",
        "",
        f"- Generated: {summary['created_at']}",
        f"- Git SHA: `{summary['git_sha']}`",
        f"- Evidence: **{summary['evidence_label']}**",
        f"- Total runs: {c['total_runs']}",
        f"- Workload cells: {c['workload_cells']}",
        f"- Arms per cell: {c['policy_arms']}",
        f"- Paired seeds per arm/cell: {c['paired_seeds_per_arm_cell']}",
        "",
        "## Protocol",
        "",
        f"- Traffic demand: {summary['protocol']['traffic_demand_levels']}",
        f"- Priority ratio: {summary['protocol']['priority_ratio_levels']}",
        f"- Fixed bypass ratio: {summary['protocol']['selected_bypass_ratio_held_fixed']}",
        f"- Fixed detour cost: {summary['protocol']['bypass_detour_seconds_held_fixed']} s",
        "- These are design settings, not real-world calibrated thresholds.",
        "",
        "## Policy outcomes by workload cell",
        "",
        "| Demand | Priority | Policy | Throughput/min | Started wait (s) | Completion | Queue growth/min | Objective | Bypass tasks |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in summary["conditions"].values():
        for arm in POLICY_ARMS:
            s = cell["policies"][arm]
            t = s["task_counts"]
            lines.append(
                f"| {cell['traffic_demand']:.2f} | {cell['priority_ratio']:.2f} | {arm} "
                f"| {s['mean_throughput_tasks_per_min']:.3f} "
                f"| {s['mean_started_task_wait_seconds']:.3f} "
                f"| {t['completion_fraction']:.4f} | {s['mean_queue_growth_per_min']:.3f} "
                f"| {s['mean_policy_objective_score']:.4f} | {s['bypass_tasks_total']} |"
            )
    lines += [
        "",
        "## Interpretation guardrails",
        "",
        "- Compare policies within each workload cell using paired comparisons in summary.json.",
        "- Lower objective score is better under the current configured weights.",
        "- Started-task wait excludes tasks not started by the 900-second horizon.",
        "- This model does not establish physical safety, collision avoidance, or warehouse validity.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run RESILIANT-Z paired workload stress test.")
    parser.add_argument("--output-dir", default="artifacts/fleet-stress-test")
    parser.add_argument("--replay-seeds", type=int, default=12)
    parser.add_argument("--first-seed", type=int, default=81001)
    parser.add_argument(
        "--traffic-demands", type=float, nargs="+", default=list(TRAFFIC_DEMAND_LEVELS)
    )
    parser.add_argument(
        "--priority-ratios", type=float, nargs="+", default=list(PRIORITY_RATIO_LEVELS)
    )
    parser.add_argument("--bypass-ratio", type=float, default=BYPASS_RATIO)
    parser.add_argument("--detour-cost-seconds", type=float, default=DETOUR_COST_SECONDS)
    a = parser.parse_args()
    result = run_fleet_stress_test(
        a.output_dir,
        replay_seeds=a.replay_seeds,
        first_seed=a.first_seed,
        traffic_demand_levels=tuple(a.traffic_demands),
        priority_ratio_levels=tuple(a.priority_ratios),
        bypass_ratio=a.bypass_ratio,
        detour_cost_seconds=a.detour_cost_seconds,
    )
    print("RESILIANT-Z workload stress test complete")
    print(f"Evidence: {result['evidence_label']}")
    print(
        f"Runs: {result['counts']['total_runs']}; workload cells: {result['counts']['workload_cells']}"
    )
    print(f"Artifacts: {Path(a.output_dir).resolve()}")
    print(f"Report: {Path(a.output_dir, 'report.md').resolve()}")


if __name__ == "__main__":
    main()
