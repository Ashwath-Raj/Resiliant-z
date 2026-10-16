"""Transparent baseline predictions and residuals for RESILIANT-Z telemetry.

This module deliberately does not detect model/reality gaps or change policies;
those behaviours belong to later sessions. It computes a constant per-metric
reference mean from explicitly measured windows in one scenario/backend cohort.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean, stdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Literal["1.0"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: str = Field(min_length=1)
    predicted_mean: float
    sample_stddev: float
    sample_count: int = Field(ge=2)
    distinct_training_runs: int = Field(ge=2)

    @model_validator(mode="after")
    def values_are_finite_and_valid(self) -> MetricBaseline:
        if not math.isfinite(self.predicted_mean):
            raise ValueError("predicted_mean must be finite")
        if not math.isfinite(self.sample_stddev) or self.sample_stddev < 0:
            raise ValueError("sample_stddev must be finite and non-negative")
        if self.distinct_training_runs > self.sample_count:
            raise ValueError("distinct_training_runs cannot exceed sample_count")
        return self


class BaselineProfile(StrictModel):
    schema_version: SchemaVersion = "1.0"
    baseline_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    method: Literal["per_metric_training_mean"] = "per_metric_training_mean"
    training_run_ids: list[str] = Field(min_length=2)
    training_window_count: int = Field(ge=2)
    minimum_samples_per_metric: int = Field(ge=2)
    metrics: dict[str, MetricBaseline] = Field(min_length=1)
    excluded_metrics: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_training_identity(self) -> BaselineProfile:
        if len(set(self.training_run_ids)) != len(self.training_run_ids):
            raise ValueError("training_run_ids must be unique")
        if len(self.training_run_ids) < 2:
            raise ValueError("baseline requires at least two distinct training runs")
        if len(self.training_run_ids) > self.training_window_count:
            raise ValueError("training_run_ids cannot exceed training_window_count")
        return self


class MetricResidual(StrictModel):
    unit: str = Field(min_length=1)
    observed: float
    predicted: float
    residual: float
    absolute_residual: float
    standardized_residual: float | None
    baseline_sample_stddev: float
    baseline_sample_count: int = Field(ge=2)

    @model_validator(mode="after")
    def values_are_consistent(self) -> MetricResidual:
        numeric_values = (self.observed, self.predicted, self.residual, self.absolute_residual)
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("residual values must be finite")
        if not math.isclose(
            self.residual, self.observed - self.predicted, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise ValueError("residual must equal observed minus predicted")
        if not math.isclose(self.absolute_residual, abs(self.residual), rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("absolute_residual must equal abs(residual)")
        if self.baseline_sample_stddev < 0 or not math.isfinite(self.baseline_sample_stddev):
            raise ValueError("baseline_sample_stddev must be finite and non-negative")
        if self.standardized_residual is not None and not math.isfinite(self.standardized_residual):
            raise ValueError("standardized_residual must be finite when present")
        return self


class BaselineEvaluation(StrictModel):
    schema_version: SchemaVersion = "1.0"
    baseline_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    method: Literal["per_metric_training_mean"] = "per_metric_training_mean"
    metrics: dict[str, MetricResidual] = Field(default_factory=dict)
    unavailable_metrics: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def no_metric_is_both_available_and_unavailable(self) -> BaselineEvaluation:
        overlap = set(self.metrics).intersection(self.unavailable_metrics)
        if overlap:
            raise ValueError(f"metrics cannot be both evaluated and unavailable: {sorted(overlap)}")
        return self


def _as_mapping(record: Any) -> Mapping[str, Any]:
    if isinstance(record, Mapping):
        return record
    dump = getattr(record, "model_dump", None)
    if callable(dump):
        value = dump(mode="json")
        if isinstance(value, Mapping):
            return value
    raise TypeError("each telemetry record must be a mapping or provide model_dump(mode='json')")


def _identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    run_id = record.get("run_id")
    scenario_id = record.get("scenario_id")
    backend_id = record.get("backend_id")
    for label, value in (
        ("run_id", run_id),
        ("scenario_id", scenario_id),
        ("backend_id", backend_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"telemetry record requires non-empty {label}")
    return run_id, scenario_id, backend_id


def _metric_observations(record: Mapping[str, Any]) -> dict[str, tuple[float, str, str]]:
    """Return top-level measured NumericObservation-like fields only."""
    observations: dict[str, tuple[float, str, str]] = {}
    for name, raw in record.items():
        if not isinstance(raw, Mapping) or not {"value", "unit", "quality"}.issubset(raw):
            continue
        quality = raw.get("quality")
        unit = raw.get("unit")
        value = raw.get("value")
        if not isinstance(unit, str) or not unit:
            raise ValueError(f"metric {name!r} must carry a non-empty unit")
        if quality != "measured" or value is None:
            observations[name] = (math.nan, unit, str(quality or "unknown"))
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"measured metric {name!r} must have a finite numeric value")
        observations[name] = (float(value), unit, "measured")
    return observations


def fit_baseline(
    records: Sequence[Any],
    *,
    baseline_id: str,
    minimum_samples_per_metric: int = 3,
) -> BaselineProfile:
    """Fit per-metric means using measured windows from one scenario/backend.

    At least two distinct training run IDs are required. Metrics below the
    sample threshold or with inconsistent units are excluded and documented.
    Unmeasured/missing/stale/not-applicable observations are never imputed.
    """
    if not baseline_id.strip():
        raise ValueError("baseline_id must not be empty")
    if minimum_samples_per_metric < 2:
        raise ValueError("minimum_samples_per_metric must be at least 2")
    if len(records) < 2:
        raise ValueError("baseline fitting requires at least two telemetry windows")

    normalized = [_as_mapping(record) for record in records]
    identities = [_identity(record) for record in normalized]
    scenario_ids = {item[1] for item in identities}
    backend_ids = {item[2] for item in identities}
    if len(scenario_ids) != 1 or len(backend_ids) != 1:
        raise ValueError("baseline training records must share one scenario_id and backend_id")
    run_ids = sorted({item[0] for item in identities})
    if len(run_ids) < 2:
        raise ValueError("baseline fitting requires at least two distinct training run IDs")

    values: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    seen_units: dict[str, set[str]] = defaultdict(set)
    for record in normalized:
        for metric, (value, unit, quality) in _metric_observations(record).items():
            seen_units[metric].add(unit)
            if quality == "measured" and math.isfinite(value):
                values[metric].append((value, unit, _identity(record)[0]))

    profiles: dict[str, MetricBaseline] = {}
    excluded: dict[str, str] = {}
    all_names = sorted(set(values).union(seen_units))
    for metric in all_names:
        unit_set = seen_units[metric]
        observations = values[metric]
        if len(unit_set) != 1:
            excluded[metric] = f"inconsistent units across training records: {sorted(unit_set)}"
            continue
        if len(observations) < minimum_samples_per_metric:
            excluded[metric] = (
                f"only {len(observations)} measured samples; requires {minimum_samples_per_metric}"
            )
            continue
        metric_run_count = len({run_id for _, _, run_id in observations})
        if metric_run_count < 2:
            excluded[metric] = "measured values come from fewer than two distinct training runs"
            continue
        raw_values = [value for value, _, _ in observations]
        profiles[metric] = MetricBaseline(
            unit=next(iter(unit_set)),
            predicted_mean=fmean(raw_values),
            sample_stddev=stdev(raw_values),
            sample_count=len(raw_values),
            distinct_training_runs=metric_run_count,
        )
    if not profiles:
        details = "; ".join(f"{key}: {value}" for key, value in sorted(excluded.items()))
        raise ValueError(f"no metrics met baseline requirements{': ' + details if details else ''}")
    return BaselineProfile(
        baseline_id=baseline_id,
        scenario_id=next(iter(scenario_ids)),
        backend_id=next(iter(backend_ids)),
        training_run_ids=run_ids,
        training_window_count=len(normalized),
        minimum_samples_per_metric=minimum_samples_per_metric,
        metrics=profiles,
        excluded_metrics=excluded,
    )


def evaluate_baseline(profile: BaselineProfile, record: Any) -> BaselineEvaluation:
    """Generate observed-minus-predicted residuals without raising gap alarms."""
    normalized = _as_mapping(record)
    run_id, scenario_id, backend_id = _identity(normalized)
    if scenario_id != profile.scenario_id:
        raise ValueError("evaluation scenario_id does not match baseline scenario_id")
    if backend_id != profile.backend_id:
        raise ValueError("evaluation backend_id does not match baseline backend_id")
    if run_id in profile.training_run_ids:
        raise ValueError("evaluation run_id overlaps baseline training runs; holdout leakage")

    observations = _metric_observations(normalized)
    metrics: dict[str, MetricResidual] = {}
    unavailable: dict[str, str] = {}
    for metric, baseline_metric in profile.metrics.items():
        item = observations.get(metric)
        if item is None:
            unavailable[metric] = "metric absent from telemetry window"
            continue
        observed, unit, quality = item
        if quality != "measured" or not math.isfinite(observed):
            unavailable[metric] = (
                f"observation quality is {quality}; only measured values are evaluated"
            )
            continue
        if unit != baseline_metric.unit:
            raise ValueError(
                f"metric {metric!r} unit mismatch: baseline uses {baseline_metric.unit!r}, "
                f"evaluation uses {unit!r}"
            )
        residual = observed - baseline_metric.predicted_mean
        standardized = (
            residual / baseline_metric.sample_stddev if baseline_metric.sample_stddev > 0 else None
        )
        metrics[metric] = MetricResidual(
            unit=unit,
            observed=observed,
            predicted=baseline_metric.predicted_mean,
            residual=residual,
            absolute_residual=abs(residual),
            standardized_residual=standardized,
            baseline_sample_stddev=baseline_metric.sample_stddev,
            baseline_sample_count=baseline_metric.sample_count,
        )
    return BaselineEvaluation(
        baseline_id=profile.baseline_id,
        run_id=run_id,
        scenario_id=scenario_id,
        backend_id=backend_id,
        metrics=metrics,
        unavailable_metrics=unavailable,
    )
