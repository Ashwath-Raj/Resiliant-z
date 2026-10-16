import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.models import (
    ExperimentManifest,
    ExperimentParameters,
    ScenarioMetrics,
    SimulationRun,
)
from resiliant_z.simulation.isaac_csv import import_isaac_metrics_csv


def test_parameter_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        ExperimentParameters(traffic_demand=9.0, priority_ratio=0.5, bypass_ratio=0.1)


def test_isaac_csv_contract_validation(tmp_path):
    path = tmp_path / "metrics.csv"
    columns = [
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
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "ISAAC-001",
                "experiment_id": "DISC-001",
                "scenario_id": "warehouse_v1",
                "stage": "discovery",
                "seed": 101,
                "traffic_demand": 0.55,
                "priority_ratio": 0.15,
                "bypass_ratio": 0.0,
                "throughput_tasks_per_min": 0.8,
                "average_wait_seconds": 20.0,
                "queue_growth_per_min": 0.0,
                "junction_occupancy": 0.4,
                "deadlock_events": 0,
                "git_sha": "abc123",
            }
        )
    runs = import_isaac_metrics_csv(path)
    assert len(runs) == 1
    assert runs[0].backend == "isaac_sim_import"
    assert runs[0].metrics.throughput_tasks_per_min == 0.8
    assert runs[0].metrics.deadlock_events == 0
    assert runs[0].started_at is None
    assert runs[0].provenance is not None
    assert runs[0].provenance.code_sha == "abc123"


def test_isaac_csv_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("run_id,experiment_id\nr1,e1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        import_isaac_metrics_csv(path)


def test_versioned_manifest_and_run_round_trip():
    scenario_hash = "a" * 64
    started_at = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    ended_at = datetime(2026, 10, 16, 8, 1, tzinfo=UTC)
    manifest = ExperimentManifest(
        schema_version="1.0",
        experiment_id="ROUNDTRIP-001",
        scenario_id="priority_junction_v1",
        scenario_version="1.2",
        scenario_config_sha256=scenario_hash,
        stage="replay",
        seed=42,
        parameters=ExperimentParameters(
            traffic_demand=0.55,
            priority_ratio=0.15,
            bypass_ratio=0.0,
        ),
        git_sha="abc123",
    )
    run = SimulationRun(
        schema_version="1.0",
        run_id="ROUNDTRIP-001-seed-42",
        experiment=manifest,
        backend="discrete_event",
        backend_version="cpu-v1",
        metrics=ScenarioMetrics(
            throughput_tasks_per_min=None,
            average_wait_seconds=None,
            queue_growth_per_min=None,
            junction_occupancy=None,
            deadlock_events=None,
        ),
        started_at=started_at,
        ended_at=ended_at,
        status="incomplete",
        failure_reason="fixture stopped before metrics were measured",
        log_artifact="logs/roundtrip.log",
    )

    assert run.provenance is not None
    assert run.provenance.code_sha == "abc123"
    assert run.provenance.scenario_config_sha256 == scenario_hash
    assert run.provenance.simulator_version == "cpu-v1"
    assert SimulationRun.model_validate_json(run.model_dump_json()) == run
    payload = json.loads(run.model_dump_json())
    schema_dir = Path(__file__).parents[1] / "docs" / "three-phase-program" / "schemas"
    result_schema = json.loads((schema_dir / "run-result.v1.schema.json").read_text())
    manifest_schema = json.loads((schema_dir / "run-manifest.v1.schema.json").read_text())
    assert payload.keys() == result_schema["properties"].keys()
    assert payload["experiment"].keys() == manifest_schema["properties"].keys()
    assert payload["metrics"].keys() == result_schema["properties"]["metrics"]["properties"].keys()
    assert set(result_schema["required"]) <= payload.keys()
    assert set(manifest_schema["required"]) <= payload["experiment"].keys()


def test_legacy_manifest_and_run_payload_remain_valid():
    run = SimulationRun.model_validate(
        {
            "run_id": "LEGACY-001",
            "experiment": {
                "experiment_id": "LEGACY-001",
                "scenario_id": "priority_junction_v1",
                "stage": "discovery",
                "seed": 7,
                "parameters": {
                    "traffic_demand": 0.55,
                    "priority_ratio": 0.15,
                    "bypass_ratio": 0.0,
                },
                "git_sha": "def456",
            },
            "backend": "surrogate",
            "metrics": {
                "throughput_tasks_per_min": 0.8,
                "average_wait_seconds": 20.0,
                "queue_growth_per_min": 0.0,
                "junction_occupancy": 0.4,
                "deadlock_events": 0,
            },
        }
    )

    assert run.schema_version == "1.0"
    assert run.experiment.schema_version == "1.0"
    assert run.experiment.scenario_version == "1"
    assert run.ended_at is None
    assert run.metrics.deadlock_events == 0
    assert run.provenance is not None
    assert run.provenance.code_sha == "def456"


def test_invalid_run_contract_fields_are_rejected():
    with pytest.raises(ValidationError):
        ExperimentManifest(
            schema_version="2.0",
            experiment_id="BAD-VERSION",
            stage="discovery",
            seed=1,
            parameters=ExperimentParameters(
                traffic_demand=0.55,
                priority_ratio=0.15,
                bypass_ratio=0.0,
            ),
        )

    with pytest.raises(ValidationError):
        ExperimentManifest(
            experiment_id="BAD-CONFIG-HASH",
            scenario_config_sha256="not-a-sha256",
            stage="discovery",
            seed=1,
            parameters=ExperimentParameters(
                traffic_demand=0.55,
                priority_ratio=0.15,
                bypass_ratio=0.0,
            ),
        )

    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="BAD-STATUS",
            experiment=ExperimentManifest(
                experiment_id="BAD-STATUS",
                stage="discovery",
                seed=1,
                parameters=ExperimentParameters(
                    traffic_demand=0.55,
                    priority_ratio=0.15,
                    bypass_ratio=0.0,
                ),
            ),
            backend="discrete_event",
            status="cancelled",
            metrics=ScenarioMetrics(),
        )

    with pytest.raises(ValidationError, match="completed runs require"):
        SimulationRun(
            run_id="MISSING-METRICS",
            experiment=ExperimentManifest(
                experiment_id="MISSING-METRICS",
                stage="discovery",
                seed=1,
                parameters=ExperimentParameters(
                    traffic_demand=0.55,
                    priority_ratio=0.15,
                    bypass_ratio=0.0,
                ),
            ),
            backend="discrete_event",
            metrics=ScenarioMetrics(),
        )


def test_incomplete_csv_rows_preserve_unmeasured_metrics_and_failure_details(tmp_path):
    path = tmp_path / "incomplete.csv"
    columns = [
        "run_id",
        "experiment_id",
        "scenario_id",
        "scenario_version",
        "scenario_config_sha256",
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
        "backend_version",
        "started_at",
        "ended_at",
        "status",
        "failure_reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "ISAAC-INCOMPLETE-001",
                "experiment_id": "INCOMPLETE-001",
                "scenario_id": "warehouse_v1",
                "scenario_version": "1.0",
                "scenario_config_sha256": "b" * 64,
                "stage": "discovery",
                "seed": 2026,
                "traffic_demand": 0.55,
                "priority_ratio": 0.15,
                "bypass_ratio": 0.0,
                "throughput_tasks_per_min": "",
                "average_wait_seconds": "",
                "queue_growth_per_min": "",
                "junction_occupancy": "",
                "deadlock_events": "unmeasured",
                "git_sha": "abc123",
                "backend_version": "host-build-1",
                "started_at": "2026-10-16T08:00:00Z",
                "ended_at": "",
                "status": "incomplete",
                "failure_reason": "simulator stopped before first sample",
            }
        )

    run = import_isaac_metrics_csv(path)[0]
    assert run.status == "incomplete"
    assert run.failure_reason == "simulator stopped before first sample"
    assert run.metrics.throughput_tasks_per_min is None
    assert run.metrics.deadlock_events is None
    assert run.started_at == datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
    assert run.ended_at is None
    assert run.experiment.scenario_version == "1.0"
    assert run.provenance is not None
    assert run.provenance.scenario_config_sha256 == "b" * 64
