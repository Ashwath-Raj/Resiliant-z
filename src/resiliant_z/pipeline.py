"""Reproducible first end-to-end benchmark pipeline."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from resiliant_z.evidence.analyzer import analyze_discovery
from resiliant_z.experiments.planner import factorial_manifests, replay_manifests
from resiliant_z.llm.nebius import (
    NebiusConfigurationError,
    NebiusRequestError,
    generate_hypotheses_with_nebius,
    local_hypotheses,
    nebius_is_configured,
)
from resiliant_z.models import DiscoveryDecision, SimulationRun
from resiliant_z.simulation.surrogate import SurrogateSimulator, current_git_sha

HypothesesMode = Literal["auto", "local", "nebius"]


def _select_hypotheses(mode: HypothesesMode, context: dict) -> tuple[dict, str, str]:
    if mode == "local":
        return local_hypotheses().model_dump(mode="json"), "local_baseline", "none"
    if mode == "nebius" and not nebius_is_configured():
        raise NebiusConfigurationError(
            "Token Factory was explicitly requested, but NEBIUS_API_KEY and/or NEBIUS_MODEL is missing."
        )
    if mode == "nebius" or (mode == "auto" and nebius_is_configured()):
        try:
            result, model_id = generate_hypotheses_with_nebius(context)
            return result.model_dump(mode="json"), "nebius_token_factory", model_id
        except (NebiusRequestError, NebiusConfigurationError) as exc:
            if mode == "nebius":
                raise
            return (
                local_hypotheses().model_dump(mode="json"),
                "local_fallback_after_nebius_error",
                f"error: {exc}",
            )
    return local_hypotheses().model_dump(mode="json"), "local_baseline", "none"


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _save_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _mean(runs: list[SimulationRun], key: str) -> float:
    values = [float(getattr(run.metrics, key)) for run in runs]
    return statistics.fmean(values) if values else 0.0


def _build_report(summary: dict, decision: DiscoveryDecision) -> str:
    replay = summary["policy_replay"]
    llm = summary["hypothesis_generation"]
    lines = [
        "# RESILIANT-Z benchmark report",
        "",
        "> **EVIDENCE LABEL: SYNTHETIC SURROGATE — NOT ISAAC SIM. This report does not contain Isaac Sim results.**",
        "",
        "## Run provenance",
        "",
        f"- Created (UTC): `{summary['created_at']}`",
        f"- Git commit: `{summary['git_sha']}`",
        f"- Backend: `{summary['backend']}`",
        f"- Hypothesis source: `{llm['source']}`",
        f"- Model ID: `{llm['model_id']}`",
        "",
        "## Hypothesis generation",
        "",
        f"- Number of hypotheses: {len(llm['hypotheses']['hypotheses'])}",
        f"- Proposed experiment: {llm['hypotheses']['recommended_experiment']}",
        "",
        "## Evidence comparison",
        "",
        f"- Decision: **{decision.status.upper()}**",
        f"- Main-effects RMSE (discovery): `{decision.discovery_main_effect_rmse:.6f}`",
        f"- Interaction-model RMSE (discovery): `{decision.discovery_interaction_rmse:.6f}`",
        f"- Main-effects RMSE (held-out): `{decision.validation_main_effect_rmse:.6f}`",
        f"- Interaction-model RMSE (held-out): `{decision.validation_interaction_rmse:.6f}`",
        f"- High-demand × high-priority interaction coefficient: `{decision.interaction_effect:.6f}`",
        f"- Held-out RMSE improvement: `{decision.validation_improvement_fraction:.1%}`",
        f"- Held-out interaction contrast: `{decision.validation_interaction_effect}`",
        f"- Held-out interaction 95% CI: `[{decision.validation_interaction_ci_lower}, {decision.validation_interaction_ci_upper}]`",
        "",
        "## Policy replay",
        "",
        f"- Paired seeds: {replay['paired_seed_count']}",
        f"- Baseline mean throughput: `{replay['baseline_mean_throughput']:.4f}` tasks/min",
        f"- Policy mean throughput: `{replay['policy_mean_throughput']:.4f}` tasks/min",
        f"- Mean throughput change: `{replay['throughput_change_percent']:.2f}%`",
        f"- Baseline mean wait: `{replay['baseline_mean_wait_seconds']:.2f}` seconds",
        f"- Policy mean wait: `{replay['policy_mean_wait_seconds']:.2f}` seconds",
        f"- Mean wait change: `{replay['wait_change_percent']:.2f}%`",
        "",
        "## Limitations and correct interpretation",
        "",
        *[f"- {item}" for item in decision.limitations],
        "- The current experiment matrix is preregistered; the model proposes hypotheses but does not yet adaptively select each experiment.",
        "- The benchmark's policy response is a controlled surrogate intervention, not validated robot-control software.",
        "",
        "## Artifacts",
        "",
        "- `summary.json`: top-level run and result summary.",
        "- `hypotheses.json`: schema-validated hypotheses and source metadata.",
        "- `discovery.json`: evidence-based model comparison result.",
        "- `manifests.jsonl`: all planned experiment manifests.",
        "- `runs.jsonl`: all measured surrogate outputs with provenance.",
    ]
    return "\n".join(lines) + "\n"


def run_demo(
    output_dir: str | Path = "artifacts/demo",
    hypotheses_mode: HypothesesMode = "auto",
    *,
    seeds_per_cell: int = 5,
    replay_seeds: int = 12,
) -> dict:
    """Run discovery, held-out validation and paired policy replay in the local surrogate."""
    if seeds_per_cell < 3:
        raise ValueError("Use at least three seeds per factorial condition")
    if replay_seeds < 3:
        raise ValueError("Use at least three paired replay seeds")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    simulator = SurrogateSimulator()
    discovery_manifests = factorial_manifests(
        stage="discovery", seeds_per_cell=seeds_per_cell, first_seed=10_000
    )
    validation_manifests = factorial_manifests(
        stage="validation", seeds_per_cell=seeds_per_cell, first_seed=20_000
    )

    # Hypotheses are generated from an observed high-demand/high-priority pilot summary.
    # The pilot is itself a surrogate run and is recorded with all other runs.
    pilot_manifest = next(
        m
        for m in discovery_manifests
        if m.parameters.traffic_demand == 1.05 and m.parameters.priority_ratio == 0.50
    )
    pilot_run = simulator.run(pilot_manifest)
    hypothesis_context = {
        "scenario_id": pilot_manifest.scenario_id,
        "observation": "Throughput under high demand and high priority fraction",
        "observed_metrics": pilot_run.metrics.model_dump(mode="json"),
        "model_limitations": [
            "Initial expected-throughput model includes individual factors but no interaction term.",
            "The observations are synthetic surrogate data, not Isaac Sim data.",
        ],
        "allowed_factors": ["traffic_demand", "priority_ratio", "bypass_ratio"],
    }
    hypotheses, hypothesis_source, model_id = _select_hypotheses(
        hypotheses_mode, hypothesis_context
    )

    discovery_runs = [
        pilot_run if m.experiment_id == pilot_manifest.experiment_id else simulator.run(m)
        for m in discovery_manifests
    ]
    validation_runs = [simulator.run(m) for m in validation_manifests]
    decision = analyze_discovery(discovery_runs, validation_runs)

    # Bounded policy replay uses matched seeds to reduce noise in before/after comparison.
    seeds = range(30_001, 30_001 + replay_seeds)
    policy_manifests = replay_manifests(seeds=seeds, bypass_ratio=0.45)
    replay_runs = [simulator.run(m) for m in policy_manifests]
    baseline_runs = [r for r in replay_runs if "BASELINE" in r.run_id]
    policy_runs = [r for r in replay_runs if "POLICY" in r.run_id]

    baseline_throughput = _mean(baseline_runs, "throughput_tasks_per_min")
    policy_throughput = _mean(policy_runs, "throughput_tasks_per_min")
    baseline_wait = _mean(baseline_runs, "average_wait_seconds")
    policy_wait = _mean(policy_runs, "average_wait_seconds")
    throughput_pct = (
        (policy_throughput - baseline_throughput) / max(baseline_throughput, 1e-9) * 100
    )
    wait_pct = (policy_wait - baseline_wait) / max(baseline_wait, 1e-9) * 100

    # The pilot is one of the discovery runs; do not duplicate its provenance row.
    all_runs = [*discovery_runs, *validation_runs, *replay_runs]
    all_manifests = [*discovery_manifests, *validation_manifests, *policy_manifests]
    created_at = datetime.now(UTC).isoformat()
    replay_summary = {
        "paired_seed_count": replay_seeds,
        "baseline_mean_throughput": round(baseline_throughput, 6),
        "policy_mean_throughput": round(policy_throughput, 6),
        "throughput_change_percent": round(throughput_pct, 3),
        "baseline_mean_wait_seconds": round(baseline_wait, 6),
        "policy_mean_wait_seconds": round(policy_wait, 6),
        "wait_change_percent": round(wait_pct, 3),
        "baseline_mean_queue_growth": round(_mean(baseline_runs, "queue_growth_per_min"), 6),
        "policy_mean_queue_growth": round(_mean(policy_runs, "queue_growth_per_min"), 6),
    }
    summary = {
        "project": "RESILIANT-Z",
        "created_at": created_at,
        "git_sha": current_git_sha(),
        "backend": "surrogate",
        "evidence_label": "SYNTHETIC SURROGATE — NOT ISAAC SIM",
        "counts": {
            "total_runs": len(all_runs),
            "discovery_runs": len(discovery_runs),
            "validation_runs": len(validation_runs),
            "replay_runs": len(replay_runs),
        },
        "hypothesis_generation": {
            "source": hypothesis_source,
            "model_id": model_id,
            "hypotheses": hypotheses,
        },
        "discovery": decision.model_dump(mode="json"),
        "policy_replay": replay_summary,
        "reproducibility": {
            "seeds_per_factorial_cell": seeds_per_cell,
            "discovery_seed_range": [
                min(m.seed for m in discovery_manifests),
                max(m.seed for m in discovery_manifests),
            ],
            "validation_seed_range": [
                min(m.seed for m in validation_manifests),
                max(m.seed for m in validation_manifests),
            ],
            "policy": "Use bypass_ratio=0.45 when the high-demand/high-priority condition is detected.",
            "policy_is_auto_promoted": False,
        },
    }

    _save_json(output / "summary.json", summary)
    _save_json(
        output / "hypotheses.json",
        {"source": hypothesis_source, "model_id": model_id, **hypotheses},
    )
    _save_json(output / "discovery.json", decision.model_dump(mode="json"))
    _save_jsonl(output / "manifests.jsonl", [m.model_dump(mode="json") for m in all_manifests])
    _save_jsonl(output / "runs.jsonl", [r.model_dump(mode="json") for r in all_runs])
    (output / "report.md").write_text(_build_report(summary, decision), encoding="utf-8")
    return summary
