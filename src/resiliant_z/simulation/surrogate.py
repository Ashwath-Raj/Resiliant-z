"""Fast, deterministic test surrogate—not a physics simulator or Isaac Sim evidence.

The benchmark has a planted interaction so we can verify that the evidence pipeline
can detect and validate one before connecting a real simulator. Thresholds below are
part of the surrogate's generated dynamics; the analysis code does not read them.
"""

from __future__ import annotations

import random
import subprocess
from datetime import UTC, datetime

from resiliant_z.models import ExperimentManifest, ScenarioMetrics, SimulationRun


def current_git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short=12", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1,
            ).stdout.strip()
            or "uncommitted"
        )
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"


class SurrogateSimulator:
    """Run a simple seeded queue/congestion model for local development and CI."""

    name = "surrogate"

    def run(self, manifest: ExperimentManifest) -> SimulationRun:
        run_started_at = datetime.now(UTC)
        p = manifest.parameters
        rng = random.Random(manifest.seed)

        # Bypass diverts some traffic away from the monitored critical junction.
        effective_demand = p.traffic_demand * (1.0 - 0.70 * p.bypass_ratio)
        occupancy = min(
            0.98,
            max(
                0.02,
                0.12
                + 0.52 * effective_demand
                + 0.10 * p.priority_ratio
                - 0.10 * p.bypass_ratio
                + rng.gauss(0.0, 0.008),
            ),
        )

        # Planted benchmark interaction: higher traffic demand and a high priority
        # fraction jointly reduce throughput. This is an explicit test fixture, not
        # a claim that these numbers describe real robots or a real warehouse.
        interaction_pressure = (
            max(0.0, effective_demand - 0.80) * max(0.0, p.priority_ratio - 0.30) * 4.0
        )
        throughput = max(
            0.05,
            1.20
            - 0.28 * effective_demand
            - 0.12 * p.priority_ratio
            - 1.50 * interaction_pressure
            + rng.gauss(0.0, 0.008),
        )
        queue_growth = max(0.0, p.traffic_demand - throughput) + 0.70 * interaction_pressure
        wait_seconds = max(
            0.1,
            5.0 + 40.0 * occupancy + 24.0 * queue_growth + rng.gauss(0.0, 0.45),
        )
        metrics = ScenarioMetrics(
            throughput_tasks_per_min=round(throughput, 6),
            average_wait_seconds=round(wait_seconds, 6),
            queue_growth_per_min=round(queue_growth, 6),
            junction_occupancy=round(occupancy, 6),
            deadlock_events=None,
        )
        return SimulationRun(
            run_id=f"{manifest.experiment_id}-seed-{manifest.seed}",
            experiment=manifest,
            backend="surrogate",
            metrics=metrics,
            started_at=run_started_at,
            ended_at=datetime.now(UTC),
            notes=[
                "SURROGATE ONLY: this run did not execute in NVIDIA Isaac Sim.",
                "The benchmark dynamics include a deliberately planted interaction.",
                "No deadlock detector is implemented; deadlock_events is unmeasured.",
            ],
        )
