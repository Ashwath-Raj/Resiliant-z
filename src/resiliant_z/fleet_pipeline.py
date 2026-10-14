"""End-to-end local discrete-event fleet benchmark (no Token Factory required)."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from resiliant_z.evidence.analyzer import analyze_discovery
from resiliant_z.experiments.planner import factorial_manifests, replay_manifests
from resiliant_z.llm.nebius import local_hypotheses
from resiliant_z.models import SimulationRun
from resiliant_z.simulation.discrete_event import DiscreteEventFleetSimulator
from resiliant_z.simulation.surrogate import current_git_sha


def _mean(runs: list[SimulationRun], key: str) -> float:
    values = [float(getattr(run.metrics, key)) for run in runs]
    return statistics.fmean(values) if values else 0.0


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def run_fleet_demo(
    output_dir: str | Path = "artifacts/fleet-demo",
    *,
    seeds_per_cell: int = 5,
    replay_seeds: int = 12,
) -> dict:
    """Run a seeded CPU queueing model, held-out analysis, and paired policy replay.

    This mode is intentionally independent of Token Factory. It is an intermediate
    engineering testbed and must not be described as Isaac Sim evidence.
    """
    if seeds_per_cell < 3:
        raise ValueError("Use at least three seeds per factorial condition")
    if replay_seeds < 3:
        raise ValueError("Use at least three paired replay seeds")
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

    manifests = replay_manifests(
        seeds=range(60_001, 60_001 + replay_seeds), bypass_ratio=0.45
    )
    replay_runs = [simulator.run(m) for m in manifests]
    baseline = [r for r in replay_runs if "BASELINE" in r.run_id]
    policy = [r for r in replay_runs if "POLICY" in r.run_id]
    base_t, policy_t = _mean(baseline, "throughput_tasks_per_min"), _mean(policy, "throughput_tasks_per_min")
    base_w, policy_w = _mean(baseline, "average_wait_seconds"), _mean(policy, "average_wait_seconds")
    replay_summary = {
        "paired_seed_count": replay_seeds,
        "baseline_mean_throughput": round(base_t, 6),
        "policy_mean_throughput": round(policy_t, 6),
        "throughput_change_percent": round((policy_t - base_t) / max(base_t, 1e-9) * 100, 3),
        "baseline_mean_wait_seconds": round(base_w, 6),
        "policy_mean_wait_seconds": round(policy_w, 6),
        "wait_change_percent": round((policy_w - base_w) / max(base_w, 1e-9) * 100, 3),
        "baseline_mean_queue_growth": round(_mean(baseline, "queue_growth_per_min"), 6),
        "policy_mean_queue_growth": round(_mean(policy, "queue_growth_per_min"), 6),
    }
    hypotheses = local_hypotheses().model_dump(mode="json")
    all_runs = [*discovery_runs, *validation_runs, *replay_runs]
    all_manifests = [*discovery_manifests, *validation_manifests, *manifests]
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
            "replay_runs": len(replay_runs),
        },
        "discovery": decision.model_dump(mode="json"),
        "policy_replay": replay_summary,
        "model_assumptions": {
            "robots": simulator.robot_count,
            "duration_seconds": simulator.duration_seconds,
            "arrivals": "Poisson process at 0.20 * traffic_demand tasks/second",
            "priority_effect": "priority-first service order with longer service windows",
            "geometry_and_collisions": "not modelled",
            "deadlocks": "not modelled; reported zero is not a safety result",
        },
    }
    _write_json(output / "summary.json", summary)
    _write_json(output / "hypotheses.json", {"source": "local_baseline", "model_id": "none", **hypotheses})
    _write_json(output / "discovery.json", decision.model_dump(mode="json"))
    _write_jsonl(output / "manifests.jsonl", [m.model_dump(mode="json") for m in all_manifests])
    _write_jsonl(output / "runs.jsonl", [r.model_dump(mode="json") for r in all_runs])

    lines = [
        "# RESILIANT-Z local discrete-event benchmark",
        "",
        f"> **EVIDENCE LABEL: {summary['evidence_label']}**",
        "",
        "This backend models queues and service capacity; it does not model robot geometry, collisions, sensors, or physics.",
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
        "## Paired policy replay",
        "",
        f"- Paired seeds: {replay_seeds}",
        f"- Baseline throughput: `{base_t:.4f}` tasks/min",
        f"- Bypass-policy throughput: `{policy_t:.4f}` tasks/min",
        f"- Throughput change: `{replay_summary['throughput_change_percent']:.2f}%`",
        f"- Baseline average wait: `{base_w:.2f}` seconds",
        f"- Policy average wait: `{policy_w:.2f}` seconds",
        f"- Wait change: `{replay_summary['wait_change_percent']:.2f}%`",
        "",
        "## Explicit limitations",
        "",
        *[f"- {item}" for item in decision.limitations],
        "- The queueing model contains explicit scenario assumptions; outcomes cannot be generalized to physical robots without Isaac Sim validation.",
        "- This benchmark does not call Token Factory and does not require a GPU.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
