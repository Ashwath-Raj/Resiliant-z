"""Versioned, backend-independent telemetry contracts and deterministic aggregation.

Telemetry values are only treated as measured when their quality status explicitly
says ``measured``. This module has no simulator, network, or model-provider imports.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    model_validator,
)

TelemetryQuality = Literal[
    "measured",
    "missing",
    "stale",
    "not_applicable",
    "not_measured",
]
MetricName = Literal[
    "active_robots",
    "idle_robots",
    "tasks_arrived",
    "tasks_started",
    "tasks_completed",
    "queue_length",
    "priority_ratio",
    "junction_occupancy",
    "junction_pressure",
]

_COUNT_METRICS = frozenset(
    {
        "active_robots",
        "idle_robots",
        "tasks_arrived",
        "tasks_started",
        "tasks_completed",
        "queue_length",
        "junction_pressure",
    }
)
_SUM_METRICS = frozenset({"tasks_arrived", "tasks_started", "tasks_completed"})
_EXPECTED_UNITS = {
    "active_robots": "robots",
    "idle_robots": "robots",
    "tasks_arrived": "tasks",
    "tasks_started": "tasks",
    "tasks_completed": "tasks",
    "queue_length": "tasks",
    "priority_ratio": "ratio",
    "junction_occupancy": "ratio",
    "junction_pressure": "robots",
}


class NumericObservation(BaseModel):
    """One metric value, or an explicit explanation for why it is unavailable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Annotated[StrictInt | StrictFloat, Field(allow_inf_nan=False)] | None = None
    unit: str = Field(min_length=1, max_length=40)
    quality: TelemetryQuality
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_quality_value_pair(self) -> NumericObservation:
        if self.quality == "measured":
            if self.value is None:
                raise ValueError(
                    "quality='measured' requires a numeric value; measured zero is valid"
                )
            if not math.isfinite(float(self.value)):
                raise ValueError("measured value must be finite")
        else:
            if self.value is not None:
                raise ValueError(
                    "unavailable values must use value=null; do not encode them as zero"
                )
            if not self.reason or not self.reason.strip():
                raise ValueError("unavailable values require a non-empty reason")
        return self


class TelemetryWindow(BaseModel):
    """A window of interval counts and interval-mean state measurements.

    Task arrival/start/completion fields are counts of events in this interval.
    Robot counts, queue length, priority ratio and junction metrics are interval
    means. Each record uses a half-open interval [window_start, window_end).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1, max_length=160)
    scenario_id: str = Field(min_length=1, max_length=160)
    backend_id: str = Field(min_length=1, max_length=120)
    window_start: datetime
    window_end: datetime
    sampling_interval_s: float = Field(gt=0, le=86_400)
    active_robots: NumericObservation
    idle_robots: NumericObservation
    tasks_arrived: NumericObservation
    tasks_started: NumericObservation
    tasks_completed: NumericObservation
    queue_length: NumericObservation
    priority_ratio: NumericObservation
    junction_occupancy: NumericObservation
    junction_pressure: NumericObservation

    @model_validator(mode="after")
    def validate_window_and_metric_semantics(self) -> TelemetryWindow:
        for field_name in ("window_start", "window_end"):
            timestamp = getattr(self, field_name)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        start = self.window_start.astimezone(UTC)
        end = self.window_end.astimezone(UTC)
        if end <= start:
            raise ValueError("window_end must be later than window_start")
        duration = (end - start).total_seconds()
        if not math.isclose(duration, self.sampling_interval_s, rel_tol=0.0, abs_tol=0.001):
            raise ValueError("sampling_interval_s must match the window duration within 1 ms")

        for metric_name, expected_unit in _EXPECTED_UNITS.items():
            observation = getattr(self, metric_name)
            if observation.unit != expected_unit:
                raise ValueError(f"{metric_name} must use unit {expected_unit!r}")
            if observation.quality != "measured":
                continue
            numeric_value = float(observation.value)
            if metric_name in _COUNT_METRICS:
                if numeric_value < 0 or not numeric_value.is_integer():
                    raise ValueError(f"{metric_name} must be a non-negative integer when measured")
            if (
                metric_name in {"priority_ratio", "junction_occupancy"}
                and not 0.0 <= numeric_value <= 1.0
            ):
                raise ValueError(f"{metric_name} must be between 0 and 1 when measured")
        return self


class AggregatedMetric(BaseModel):
    """Window result; incomplete data never gets presented as a complete value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float | int | None
    unit: str
    aggregation: Literal["sum", "time_weighted_mean"]
    quality_flags: list[TelemetryQuality]
    measured_duration_s: float = Field(ge=0)
    requested_duration_s: float = Field(gt=0)
    coverage_ratio: float = Field(ge=0, le=1)


class FleetWindowAggregate(BaseModel):
    """Deterministic aggregation summary for one run/scenario and target window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    scenario_id: str
    backend_id: str
    window_start: datetime
    window_end: datetime
    input_window_count: int = Field(ge=0)
    telemetry_coverage_ratio: float = Field(ge=0, le=1)
    quality_flags: list[TelemetryQuality]
    metrics: dict[MetricName, AggregatedMetric]


def _utc_seconds(start: datetime, end: datetime) -> float:
    duration = end.astimezone(UTC) - start.astimezone(UTC)
    return duration.total_seconds()


def _status_flags(
    observations: list[NumericObservation], *, has_gap: bool
) -> list[TelemetryQuality]:
    statuses: set[str] = {item.quality for item in observations}
    if has_gap or not observations:
        statuses.add("missing")
    order = ("measured", "missing", "stale", "not_applicable", "not_measured")
    return [status for status in order if status in statuses]


def aggregate_telemetry(
    records: list[TelemetryWindow] | tuple[TelemetryWindow, ...],
    *,
    window_start: datetime,
    window_end: datetime,
) -> FleetWindowAggregate:
    """Aggregate complete telemetry windows within a deterministic half-open range.

    Records partially crossing a requested boundary are excluded rather than
    clipped/interpolated. Any time gap prevents a metric value from being emitted
    as complete. Input records must belong to one run/scenario/backend and may not
    overlap. This function is pure: it does not read files or invoke a backend.
    """
    if window_start.tzinfo is None or window_start.utcoffset() is None:
        raise ValueError("window_start must include a timezone")
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError("window_end must include a timezone")
    requested_start = window_start.astimezone(UTC)
    requested_end = window_end.astimezone(UTC)
    if requested_end <= requested_start:
        raise ValueError("window_end must be later than window_start")
    if not records:
        raise ValueError("records must identify the run/scenario/backend to aggregate")

    identities = {(item.run_id, item.scenario_id, item.backend_id) for item in records}
    if len(identities) != 1:
        raise ValueError("all records must belong to the same run_id, scenario_id and backend_id")

    ordered = sorted(records, key=lambda item: item.window_start.astimezone(UTC))
    previous_end: datetime | None = None
    for record in ordered:
        record_start = record.window_start.astimezone(UTC)
        record_end = record.window_end.astimezone(UTC)
        if previous_end is not None and record_start < previous_end:
            raise ValueError(
                "telemetry windows overlap; overlapping intervals cannot be aggregated"
            )
        previous_end = record_end

    selected = [
        item
        for item in ordered
        if item.window_start.astimezone(UTC) >= requested_start
        and item.window_end.astimezone(UTC) <= requested_end
    ]
    requested_duration = (requested_end - requested_start).total_seconds()
    covered_duration = sum(_utc_seconds(item.window_start, item.window_end) for item in selected)
    overall_coverage = min(1.0, covered_duration / requested_duration)
    has_gap = not math.isclose(overall_coverage, 1.0, rel_tol=0.0, abs_tol=1e-9)

    first = ordered[0]
    aggregate_metrics: dict[MetricName, AggregatedMetric] = {}
    for metric_name, expected_unit in _EXPECTED_UNITS.items():
        observations = [getattr(item, metric_name) for item in selected]
        measured = [
            (observation, _utc_seconds(item.window_start, item.window_end))
            for item, observation in zip(selected, observations, strict=True)
            if observation.quality == "measured"
        ]
        measured_duration = sum(duration for _, duration in measured)
        coverage = min(1.0, measured_duration / requested_duration)
        all_observations_measured = len(measured) == len(selected) and bool(selected)
        value: float | int | None = None
        aggregation: Literal["sum", "time_weighted_mean"] = (
            "sum" if metric_name in _SUM_METRICS else "time_weighted_mean"
        )
        if (
            not has_gap
            and all_observations_measured
            and math.isclose(coverage, 1.0, rel_tol=0.0, abs_tol=1e-9)
        ):
            if aggregation == "sum":
                numeric_total = sum(float(observation.value) for observation, _ in measured)
                value = int(numeric_total)
            else:
                weighted_total = sum(
                    float(observation.value) * duration for observation, duration in measured
                )
                value = weighted_total / measured_duration
        flags = _status_flags(observations, has_gap=has_gap)
        aggregate_metrics[metric_name] = AggregatedMetric(
            value=value,
            unit=expected_unit,
            aggregation=aggregation,
            quality_flags=flags,
            measured_duration_s=measured_duration,
            requested_duration_s=requested_duration,
            coverage_ratio=coverage,
        )

    global_flags: set[TelemetryQuality] = set()
    for metric in aggregate_metrics.values():
        global_flags.update(metric.quality_flags)
    flag_order: tuple[TelemetryQuality, ...] = (
        "measured",
        "missing",
        "stale",
        "not_applicable",
        "not_measured",
    )
    return FleetWindowAggregate(
        run_id=first.run_id,
        scenario_id=first.scenario_id,
        backend_id=first.backend_id,
        window_start=window_start,
        window_end=window_end,
        input_window_count=len(selected),
        telemetry_coverage_ratio=overall_coverage,
        quality_flags=[flag for flag in flag_order if flag in global_flags],
        metrics=aggregate_metrics,
    )
