"""Import the standardized metrics CSV exported by the Isaac Sim host runner.

This is a bridge contract, not an Isaac Sim launcher. A row is only genuine Isaac
Sim evidence when produced by a recorded, actual Isaac Sim execution.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from resiliant_z.models import (
    ExperimentManifest,
    ExperimentParameters,
    ScenarioMetrics,
    SimulationRun,
)

REQUIRED_COLUMNS = {
    "run_id",
    "experiment_id",
    "scenario_id",
    "stage",
    "seed",
    "traffic_demand",
    "priority_ratio",
    "bypass_ratio",
    "throughput_tasks_per_min",
    "average_wait_seconds",
    "queue_growth_per_min",
    "junction_occupancy",
    "deadlock_events",
    "git_sha",
}


def import_isaac_metrics_csv(path: str | Path) -> list[SimulationRun]:
    """Parse the shared CSV contract and validate every field before analysis."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    parsed: list[SimulationRun] = []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Metrics CSV is empty or has no header")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError("Metrics CSV missing required columns: " + ", ".join(sorted(missing)))
        for line_number, row in enumerate(reader, start=2):
            try:
                manifest = ExperimentManifest(
                    experiment_id=row["experiment_id"],
                    scenario_id=row["scenario_id"],
                    stage=row["stage"],
                    seed=int(row["seed"]),
                    parameters=ExperimentParameters(
                        traffic_demand=float(row["traffic_demand"]),
                        priority_ratio=float(row["priority_ratio"]),
                        bypass_ratio=float(row["bypass_ratio"]),
                    ),
                    git_sha=row["git_sha"],
                )
                metrics = ScenarioMetrics(
                    throughput_tasks_per_min=float(row["throughput_tasks_per_min"]),
                    average_wait_seconds=float(row["average_wait_seconds"]),
                    queue_growth_per_min=float(row["queue_growth_per_min"]),
                    junction_occupancy=float(row["junction_occupancy"]),
                    deadlock_events=int(row["deadlock_events"]),
                )
                run_id = row["run_id"].strip()
                if not run_id:
                    raise ValueError("run_id cannot be blank")
                parsed.append(
                    SimulationRun(
                        run_id=run_id,
                        experiment=manifest,
                        backend="isaac_sim_import",
                        metrics=metrics,
                        started_at=datetime.now(UTC),
                        notes=[
                            f"Imported from {source.name}.",
                            "Verify run provenance against the simulator host logs before using as hackathon evidence.",
                        ],
                    )
                )
            except (ValueError, ValidationError, TypeError) as exc:
                raise ValueError(f"Invalid metrics row at CSV line {line_number}: {exc}") from exc
    if not parsed:
        raise ValueError("Metrics CSV contains no data rows")
    return parsed
