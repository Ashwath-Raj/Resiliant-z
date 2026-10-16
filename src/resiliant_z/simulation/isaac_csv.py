"""Import the standardized metrics CSV exported by the Isaac Sim host runner.

This is a bridge contract, not an Isaac Sim launcher. A row is only genuine Isaac
Sim evidence when produced by a recorded, actual Isaac Sim execution.
"""

from __future__ import annotations

import csv
from datetime import datetime
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


def _optional_float(row: dict[str, str | None], column: str) -> float | None:
    value = (row.get(column) or "").strip()
    return float(value) if value else None


def _optional_datetime(row: dict[str, str | None], column: str) -> datetime | None:
    value = (row.get(column) or "").strip()
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _optional_deadlock_count(row: dict[str, str | None]) -> int | None:
    value = (row.get("deadlock_events") or "").strip()
    return None if not value or value.lower() in {"null", "unmeasured"} else int(value)


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
                    schema_version=row.get("schema_version") or "1.0",
                    experiment_id=row["experiment_id"],
                    scenario_id=row["scenario_id"],
                    scenario_version=row.get("scenario_version") or None,
                    scenario_config_sha256=row.get("scenario_config_sha256") or None,
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
                    throughput_tasks_per_min=_optional_float(row, "throughput_tasks_per_min"),
                    average_wait_seconds=_optional_float(row, "average_wait_seconds"),
                    queue_growth_per_min=_optional_float(row, "queue_growth_per_min"),
                    junction_occupancy=_optional_float(row, "junction_occupancy"),
                    deadlock_events=_optional_deadlock_count(row),
                )
                run_id = (row.get("run_id") or "").strip()
                if not run_id:
                    raise ValueError("run_id cannot be blank")
                parsed.append(
                    SimulationRun(
                        run_id=run_id,
                        experiment=manifest,
                        backend="isaac_sim_import",
                        backend_version=row.get("backend_version") or None,
                        metrics=metrics,
                        started_at=_optional_datetime(row, "started_at"),
                        ended_at=_optional_datetime(row, "ended_at"),
                        status=row.get("status") or "completed",
                        failure_reason=row.get("failure_reason") or None,
                        log_artifact=row.get("log_artifact") or None,
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
