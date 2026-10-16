from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.telemetry import (
    NumericObservation,
    TelemetryWindow,
    aggregate_telemetry,
)
from resiliant_z.telemetry_io import load_telemetry_jsonl, write_telemetry_jsonl

PAYLOAD_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PAYLOAD_ROOT / "configs" / "telemetry" / "session3_fixture.v1.jsonl"
BASE = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


def observation(
    value: int | float | None, unit: str, quality: str = "measured"
) -> NumericObservation:
    reason = None if quality == "measured" else f"fixture explicitly marks this value {quality}"
    return NumericObservation(value=value, unit=unit, quality=quality, reason=reason)


def make_window(
    start_offset: int,
    *,
    duration: int = 10,
    active: int | float = 2,
    idle: int | float = 1,
    arrived: int = 2,
    started: int = 1,
    completed: int = 1,
    queue: int | float | None = 3,
    queue_quality: str = "measured",
    priority: float | None = 0.5,
    priority_quality: str = "measured",
    occupancy: float | None = 0.25,
    occupancy_quality: str = "measured",
    pressure: int | float | None = 1,
    pressure_quality: str = "measured",
    run_id: str = "run-test",
    scenario_id: str = "scenario-test",
    backend_id: str = "local_discrete_event",
) -> TelemetryWindow:
    start = BASE + timedelta(seconds=start_offset)
    end = start + timedelta(seconds=duration)
    return TelemetryWindow(
        run_id=run_id,
        scenario_id=scenario_id,
        backend_id=backend_id,
        window_start=start,
        window_end=end,
        sampling_interval_s=duration,
        active_robots=observation(active, "robots"),
        idle_robots=observation(idle, "robots"),
        tasks_arrived=observation(arrived, "tasks"),
        tasks_started=observation(started, "tasks"),
        tasks_completed=observation(completed, "tasks"),
        queue_length=observation(queue, "tasks", queue_quality),
        priority_ratio=observation(priority, "ratio", priority_quality),
        junction_occupancy=observation(occupancy, "ratio", occupancy_quality),
        junction_pressure=observation(pressure, "robots", pressure_quality),
    )


def test_fixture_loads_as_versioned_telemetry_and_preserves_quality_states() -> None:
    records = load_telemetry_jsonl(FIXTURE)
    assert len(records) == 3
    assert {record.schema_version for record in records} == {"1.0"}
    assert records[1].queue_length.quality == "missing"
    assert records[1].priority_ratio.quality == "stale"
    assert records[1].junction_occupancy.quality == "not_measured"
    assert records[2].junction_occupancy.quality == "not_applicable"
    assert records[0].queue_length.value == 2


def test_measured_zero_is_distinct_from_all_unavailable_states() -> None:
    measured_zero = NumericObservation(value=0, unit="tasks", quality="measured")
    missing = NumericObservation(value=None, unit="tasks", quality="missing", reason="field absent")
    stale = NumericObservation(
        value=None, unit="tasks", quality="stale", reason="older than freshness limit"
    )
    not_applicable = NumericObservation(
        value=None,
        unit="tasks",
        quality="not_applicable",
        reason="this backend has no task queue",
    )
    not_measured = NumericObservation(
        value=None,
        unit="tasks",
        quality="not_measured",
        reason="no detector is implemented",
    )
    assert measured_zero.value == 0 and measured_zero.quality == "measured"
    assert [
        missing.quality,
        stale.quality,
        not_applicable.quality,
        not_measured.quality,
    ] == [
        "missing",
        "stale",
        "not_applicable",
        "not_measured",
    ]


def test_unavailable_values_cannot_be_silently_encoded_as_zero() -> None:
    with pytest.raises(ValidationError, match="unavailable values must use value=null"):
        NumericObservation(value=0, unit="tasks", quality="missing", reason="absent")
    with pytest.raises(ValidationError, match="requires a numeric value"):
        NumericObservation(value=None, unit="tasks", quality="measured")
    with pytest.raises(ValidationError, match="require a non-empty reason"):
        NumericObservation(value=None, unit="tasks", quality="stale")


def test_schema_rejects_wrong_units_bad_ratios_and_naive_datetimes() -> None:
    base = make_window(0).model_dump(mode="python")
    base["priority_ratio"] = NumericObservation(value=1.2, unit="ratio", quality="measured")
    with pytest.raises(ValidationError, match="priority_ratio must be between 0 and 1"):
        TelemetryWindow.model_validate(base)

    base = make_window(0).model_dump(mode="python")
    base["queue_length"] = NumericObservation(value=1, unit="robots", quality="measured")
    with pytest.raises(ValidationError, match="queue_length must use unit 'tasks'"):
        TelemetryWindow.model_validate(base)

    base = make_window(0).model_dump(mode="python")
    base["window_start"] = datetime(2026, 10, 16, 8, 0)
    with pytest.raises(ValidationError, match="window_start must include a timezone"):
        TelemetryWindow.model_validate(base)


def test_sampling_interval_must_match_window_duration() -> None:
    base = make_window(0).model_dump(mode="python")
    base["sampling_interval_s"] = 9
    with pytest.raises(ValidationError, match="must match the window duration"):
        TelemetryWindow.model_validate(base)


def test_aggregation_sums_interval_events_and_time_weights_state_means() -> None:
    records = [
        make_window(0, active=2, arrived=2, started=1, completed=1, queue=1),
        make_window(10, active=4, arrived=3, started=2, completed=2, queue=3),
        make_window(20, active=0, arrived=1, started=1, completed=1, queue=5),
    ]
    aggregate = aggregate_telemetry(
        records, window_start=BASE, window_end=BASE + timedelta(seconds=30)
    )
    assert aggregate.telemetry_coverage_ratio == pytest.approx(1.0)
    assert aggregate.metrics["tasks_arrived"].value == 6
    assert aggregate.metrics["tasks_started"].value == 4
    assert aggregate.metrics["tasks_completed"].value == 4
    assert aggregate.metrics["active_robots"].value == pytest.approx(2.0)
    assert aggregate.metrics["queue_length"].value == pytest.approx(3.0)
    assert aggregate.metrics["active_robots"].aggregation == "time_weighted_mean"
    assert aggregate.metrics["tasks_arrived"].aggregation == "sum"


def test_missing_stale_and_unmeasured_statuses_propagate_without_false_values() -> None:
    records = [
        make_window(0, queue=2, priority=0.5),
        make_window(
            10,
            queue=None,
            queue_quality="missing",
            priority=None,
            priority_quality="stale",
            occupancy=None,
            occupancy_quality="not_measured",
        ),
        make_window(
            20,
            queue=0,
            priority=0.25,
            occupancy=None,
            occupancy_quality="not_applicable",
        ),
    ]
    aggregate = aggregate_telemetry(
        records, window_start=BASE, window_end=BASE + timedelta(seconds=30)
    )
    assert aggregate.metrics["queue_length"].value is None
    assert aggregate.metrics["queue_length"].quality_flags == ["measured", "missing"]
    assert aggregate.metrics["priority_ratio"].value is None
    assert aggregate.metrics["priority_ratio"].quality_flags == ["measured", "stale"]
    assert aggregate.metrics["junction_occupancy"].value is None
    assert set(aggregate.metrics["junction_occupancy"].quality_flags) == {
        "measured",
        "not_measured",
        "not_applicable",
    }
    # An unrelated unavailable metric does not invalidate fully measured event counts.
    assert aggregate.metrics["tasks_arrived"].value == 6


def test_half_open_window_boundaries_exclude_outside_records() -> None:
    records = [
        make_window(-10, arrived=100),
        make_window(0, arrived=2),
        make_window(10, arrived=3),
    ]
    aggregate = aggregate_telemetry(
        records, window_start=BASE, window_end=BASE + timedelta(seconds=10)
    )
    assert aggregate.input_window_count == 1
    assert aggregate.metrics["tasks_arrived"].value == 2
    assert aggregate.telemetry_coverage_ratio == pytest.approx(1.0)


def test_gaps_reduce_coverage_and_prevent_complete_aggregate_values() -> None:
    records = [make_window(0, arrived=2), make_window(20, arrived=3)]
    aggregate = aggregate_telemetry(
        records, window_start=BASE, window_end=BASE + timedelta(seconds=30)
    )
    assert aggregate.telemetry_coverage_ratio == pytest.approx(2 / 3)
    assert "missing" in aggregate.quality_flags
    assert aggregate.metrics["tasks_arrived"].value is None
    assert aggregate.metrics["tasks_arrived"].coverage_ratio == pytest.approx(2 / 3)
    assert "missing" in aggregate.metrics["tasks_arrived"].quality_flags


def test_partial_boundary_windows_are_not_clipped_or_interpolated() -> None:
    record = make_window(0, duration=20, arrived=8)
    aggregate = aggregate_telemetry(
        [record],
        window_start=BASE + timedelta(seconds=10),
        window_end=BASE + timedelta(seconds=20),
    )
    assert aggregate.input_window_count == 0
    assert aggregate.telemetry_coverage_ratio == pytest.approx(0.0)
    assert aggregate.metrics["tasks_arrived"].value is None
    assert "missing" in aggregate.metrics["tasks_arrived"].quality_flags


def test_overlapping_and_mixed_identity_records_are_rejected() -> None:
    with pytest.raises(ValueError, match="windows overlap"):
        aggregate_telemetry(
            [make_window(0, duration=20), make_window(10)],
            window_start=BASE,
            window_end=BASE + timedelta(seconds=30),
        )
    with pytest.raises(ValueError, match="same run_id"):
        aggregate_telemetry(
            [make_window(0), make_window(10, run_id="other-run")],
            window_start=BASE,
            window_end=BASE + timedelta(seconds=20),
        )


def test_jsonl_persist_replay_is_backend_independent_and_no_overwrite_by_default(
    tmp_path: Path,
) -> None:
    records = load_telemetry_jsonl(FIXTURE)
    target = tmp_path / "telemetry.jsonl"
    write_telemetry_jsonl(target, records)
    replayed = load_telemetry_jsonl(target)
    assert replayed == records
    with pytest.raises(FileExistsError):
        write_telemetry_jsonl(target, records)
    assert load_telemetry_jsonl(target) == records


def test_jsonl_replay_rejects_malformed_line_with_location(tmp_path: Path) -> None:
    records = load_telemetry_jsonl(FIXTURE)
    target = tmp_path / "invalid.jsonl"
    target.write_text(records[0].model_dump_json() + "\nnot-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid\.jsonl:2: invalid telemetry record"):
        load_telemetry_jsonl(target)


def test_jsonl_writer_refuses_mixed_series_and_overlapping_windows(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="single run/scenario/backend"):
        write_telemetry_jsonl(
            tmp_path / "mixed.jsonl",
            [make_window(0), make_window(10, scenario_id="other")],
        )
    with pytest.raises(ValueError, match="windows overlap"):
        write_telemetry_jsonl(
            tmp_path / "overlap.jsonl", [make_window(0, duration=20), make_window(10)]
        )


def test_aggregate_json_serializes_without_nonstandard_nan_values() -> None:
    records = load_telemetry_jsonl(FIXTURE)
    aggregate = aggregate_telemetry(
        records, window_start=BASE, window_end=BASE + timedelta(seconds=30)
    )
    payload = json.loads(aggregate.model_dump_json())
    assert payload["schema_version"] == "1.0"
    assert payload["metrics"]["queue_length"]["value"] is None
