"""Compare a main-effects model with an interaction model on held-out runs."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from resiliant_z.models import DiscoveryDecision, SimulationRun


DEMAND_SPLIT = 0.80
PRIORITY_SPLIT = 0.30


def _design(runs: Sequence[SimulationRun], include_interaction: bool) -> np.ndarray:
    demand_high = np.asarray(
        [r.experiment.parameters.traffic_demand >= DEMAND_SPLIT for r in runs], dtype=float
    )
    priority_high = np.asarray(
        [r.experiment.parameters.priority_ratio >= PRIORITY_SPLIT for r in runs], dtype=float
    )
    cols = [np.ones(len(runs)), demand_high, priority_high]
    if include_interaction:
        cols.append(demand_high * priority_high)
    return np.column_stack(cols)


def _targets(runs: Sequence[SimulationRun]) -> np.ndarray:
    return np.asarray([r.metrics.throughput_tasks_per_min for r in runs], dtype=float)


def _fit(runs: Sequence[SimulationRun], include_interaction: bool) -> np.ndarray:
    x, y = _design(runs, include_interaction), _targets(runs)
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    return coefficients


def _rmse(runs: Sequence[SimulationRun], coefficients: np.ndarray, include_interaction: bool) -> float:
    residuals = _targets(runs) - _design(runs, include_interaction) @ coefficients
    return float(np.sqrt(np.mean(np.square(residuals))))


def analyze_discovery(
    discovery_runs: Sequence[SimulationRun], validation_runs: Sequence[SimulationRun]
) -> DiscoveryDecision:
    """Fit on discovery seeds, compare predictions on independent validation seeds."""
    if len(discovery_runs) < 8 or len(validation_runs) < 8:
        raise ValueError("Need at least eight discovery and eight validation runs")
    for stage, collection in (("discovery", discovery_runs), ("validation", validation_runs)):
        if any(run.experiment.stage != stage for run in collection):
            raise ValueError(f"All runs in {stage}_runs must have stage={stage!r}")
        if any(run.status != "completed" for run in collection):
            raise ValueError("Failed runs must be filtered before statistical analysis")

    main_beta = _fit(discovery_runs, include_interaction=False)
    interaction_beta = _fit(discovery_runs, include_interaction=True)
    discovery_main_rmse = _rmse(discovery_runs, main_beta, include_interaction=False)
    discovery_interaction_rmse = _rmse(discovery_runs, interaction_beta, include_interaction=True)
    validation_main_rmse = _rmse(validation_runs, main_beta, include_interaction=False)
    validation_interaction_rmse = _rmse(validation_runs, interaction_beta, include_interaction=True)

    interaction_effect = float(interaction_beta[3])
    if validation_main_rmse <= 1e-12:
        improvement = 0.0
    else:
        improvement = (validation_main_rmse - validation_interaction_rmse) / validation_main_rmse

    # These thresholds are benchmark decision criteria, not universal scientific
    # significance levels. Report the effect size and held-out prediction errors too.
    validated = interaction_effect < -0.08 and validation_interaction_rmse < validation_main_rmse * 0.60
    if validated:
        status = "validated"
    elif interaction_effect >= -0.08:
        status = "rejected"
    else:
        status = "inconclusive"

    return DiscoveryDecision(
        status=status,
        claim=(
            "The high-demand/high-priority condition has an additional negative throughput effect "
            "beyond the two main effects in this controlled benchmark."
        ),
        interaction_effect=round(interaction_effect, 6),
        discovery_main_effect_rmse=round(discovery_main_rmse, 6),
        discovery_interaction_rmse=round(discovery_interaction_rmse, 6),
        validation_main_effect_rmse=round(validation_main_rmse, 6),
        validation_interaction_rmse=round(validation_interaction_rmse, 6),
        validation_improvement_fraction=round(float(improvement), 6),
        sample_count_discovery=len(discovery_runs),
        sample_count_validation=len(validation_runs),
        limitations=[
            "The initial benchmark uses a synthetic surrogate with a planted interaction.",
            "Factor splits are predefined experimental design levels, not discovered numeric thresholds.",
            "Validation is held out by random seed, not by a new warehouse layout or simulator.",
            "Do not describe these results as Isaac Sim results or real-world robot evidence.",
        ],
    )
