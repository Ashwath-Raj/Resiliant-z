import csv

import pytest
from pydantic import ValidationError

from resiliant_z.models import ExperimentParameters
from resiliant_z.simulation.isaac_csv import import_isaac_metrics_csv


def test_parameter_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        ExperimentParameters(traffic_demand=9.0, priority_ratio=0.5, bypass_ratio=0.1)


def test_isaac_csv_contract_validation(tmp_path):
    path = tmp_path / "metrics.csv"
    columns = [
        "run_id", "experiment_id", "scenario_id", "stage", "seed", "traffic_demand",
        "priority_ratio", "bypass_ratio", "throughput_tasks_per_min", "average_wait_seconds",
        "queue_growth_per_min", "junction_occupancy", "deadlock_events", "git_sha",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({
            "run_id": "ISAAC-001", "experiment_id": "DISC-001", "scenario_id": "warehouse_v1",
            "stage": "discovery", "seed": 101, "traffic_demand": 0.55,
            "priority_ratio": 0.15, "bypass_ratio": 0.0, "throughput_tasks_per_min": 0.8,
            "average_wait_seconds": 20.0, "queue_growth_per_min": 0.0,
            "junction_occupancy": 0.4, "deadlock_events": 0, "git_sha": "abc123",
        })
    runs = import_isaac_metrics_csv(path)
    assert len(runs) == 1
    assert runs[0].backend == "isaac_sim_import"
    assert runs[0].metrics.throughput_tasks_per_min == 0.8


def test_isaac_csv_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("run_id,experiment_id\nr1,e1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        import_isaac_metrics_csv(path)
