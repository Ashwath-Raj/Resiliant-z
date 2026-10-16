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


def _rmse(
    runs: Sequence[SimulationRun], coefficients: np.ndarray, include_interaction: bool
) -> float:
    residuals = _targets(runs) - _design(runs, include_interaction) @ coefficients
    return float(np.sqrt(np.mean(np.square(residuals))))


def _t_critical_975(df: int) -> float:
    """Conservative two-sided 95% t critical value for small cell counts."""
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
    return table.get(df, 1.96 if df >= 30 else 12.706)


def _validation_interaction_contrast(
    runs: Sequence[SimulationRun],
) -> tuple[float, float, float]:
    """Return high-demand × high-priority difference-in-differences and CI.

    The contrast is computed only on held-out runs: mean(HH)-mean(HL)-mean(LH)+mean(LL).
    A conservative t critical value based on the smallest cell degrees of freedom
    is used. At least two samples per factorial cell are required.
    """
    cells: dict[tuple[bool, bool], list[float]] = {
        (False, False): [],
        (False, True): [],
        (True, False): [],
        (True, True): [],
    }
    for run in runs:
        key = (
            run.experiment.parameters.traffic_demand >= DEMAND_SPLIT,
            run.experiment.parameters.priority_ratio >= PRIORITY_SPLIT,
        )
        cells[key].append(run.metrics.throughput_tasks_per_min)
    if any(len(values) < 2 for values in cells.values()):
        raise ValueError("Validation must contain at least two runs in every 2x2 factor cell")

    means = {key: float(np.mean(values)) for key, values in cells.items()}
    # Contrast signs: LL +1, LH -1, HL -1, HH +1.
    effect = (
        means[(True, True)] - means[(True, False)] - means[(False, True)] + means[(False, False)]
    )
    variances = {key: float(np.var(values, ddof=1)) / len(values) for key, values in cells.items()}
    standard_error = float(np.sqrt(sum(variances.values())))
    min_df = min(len(values) - 1 for values in cells.values())
    margin = _t_critical_975(min_df) * standard_error
    return effect, effect - margin, effect + margin


def analyze_discovery(
    discovery_runs: Sequence[SimulationRun],
    validation_runs: Sequence[SimulationRun],
    *,
    backend: str = "surrogate",
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

    validation_effect, validation_ci_lower, validation_ci_upper = _validation_interaction_contrast(
        validation_runs
    )
    # Require a negative effect in discovery and an independently estimated 95% CI
    # below zero on held-out runs. The interaction model must also predict better
    # than the main-effects model. This avoids forcing an arbitrary RMSE percentage.
    validated = (
        interaction_effect < 0.0
        and validation_ci_upper < 0.0
        and validation_interaction_rmse < validation_main_rmse
    )
    if validated:
        status = "validated"
    elif interaction_effect >= 0.0 or validation_ci_lower > 0.0:
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
        validation_interaction_effect=round(validation_effect, 6),
        validation_interaction_ci_lower=round(validation_ci_lower, 6),
        validation_interaction_ci_upper=round(validation_ci_upper, 6),
        limitations=[
            (
                "The initial benchmark uses a synthetic surrogate with a planted interaction."
                if backend == "surrogate"
                else "The backend is a simplified discrete-event queueing model, not a physics-based simulator; the interaction emerges from queue saturation plus the explicit priority-service-time assumption."
                if backend == "discrete_event"
                else f"Backend {backend!r} is not a substitute for independently documented physical evidence."
            ),
            "Factor splits are predefined experimental design levels, not discovered numeric thresholds.",
            "The held-out interaction interval uses a conservative cell-wise t approximation; inspect sample sizes and distributions before research claims.",
            "Validation is held out by random seed, not by a new warehouse layout or simulator.",
            "Do not describe these results as Isaac Sim results or real-world robot evidence.",
        ],
    )
