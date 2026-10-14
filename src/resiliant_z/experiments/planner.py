"""Reproducible, bounded factorial plan for the first benchmark.

Factor levels are experimental design settings, not claimed discovered thresholds.
"""

from __future__ import annotations

from collections.abc import Iterable

from resiliant_z.models import ExperimentManifest, ExperimentParameters
from resiliant_z.simulation.surrogate import current_git_sha

DEMAND_LEVELS = (0.55, 1.05)
PRIORITY_LEVELS = (0.15, 0.50)


def factorial_manifests(
    *, stage: str, seeds_per_cell: int, first_seed: int, bypass_ratio: float = 0.0
) -> list[ExperimentManifest]:
    if stage not in {"discovery", "validation"}:
        raise ValueError("factorial_manifests only supports discovery or validation")
    if seeds_per_cell < 2:
        raise ValueError("At least two independent seeds per condition are required")
    if first_seed < 0:
        raise ValueError("first_seed must be non-negative")
    sha = current_git_sha()
    manifests: list[ExperimentManifest] = []
    counter = 0
    for demand_index, demand in enumerate(DEMAND_LEVELS):
        for priority_index, priority in enumerate(PRIORITY_LEVELS):
            for replicate in range(seeds_per_cell):
                counter += 1
                manifests.append(
                    ExperimentManifest(
                        experiment_id=(
                            f"{stage[:3].upper()}-D{demand_index}-P{priority_index}-R{replicate + 1:02d}"
                        ),
                        stage=stage,  # type: ignore[arg-type]
                        seed=first_seed + counter,
                        parameters=ExperimentParameters(
                            traffic_demand=demand,
                            priority_ratio=priority,
                            bypass_ratio=bypass_ratio,
                        ),
                        git_sha=sha,
                    )
                )
    return manifests


def replay_manifests(*, seeds: Iterable[int], bypass_ratio: float) -> list[ExperimentManifest]:
    sha = current_git_sha()
    manifests: list[ExperimentManifest] = []
    for seed in seeds:
        for arm, bypass in (("baseline", 0.0), ("policy", bypass_ratio)):
            manifests.append(
                ExperimentManifest(
                    experiment_id=f"REPLAY-{arm.upper()}-S{seed}",
                    stage="replay",
                    seed=seed,
                    parameters=ExperimentParameters(
                        traffic_demand=1.05,
                        priority_ratio=0.50,
                        bypass_ratio=bypass,
                    ),
                    git_sha=sha,
                )
            )
    return manifests
