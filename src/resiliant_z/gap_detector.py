"""Persistent, evidence-gated model/reality-gap detection for RESILIANT-Z.

The detector consumes held-out BaselineEvaluation records; it never launches a
simulator, calls a model provider, or changes routing policy. A breach becomes
an active gap only after the configured number of contiguous measured windows.
Missing observations are never interpreted as zero or as evidence of recovery.
The JSON state file is designed for a single writer process.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resiliant_z.baseline import BaselineEvaluation

SchemaVersion = Literal["1.0"]
GapStatus = Literal[
    "candidate",
    "open",
    "normal",
    "cleared",
    "insufficient_evidence",
    "out_of_order",
]
GapEventType = Literal[
    "gap_candidate",
    "gap_opened",
    "gap_persisted",
    "gap_clear_pending",
    "gap_cleared",
    "normal_window",
    "insufficient_evidence",
    "out_of_order_window",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricGapRule(StrictModel):
    """Metric-specific threshold and persistence requirements.

    `absolute_residual_threshold` is in the exact unit used by the baseline
    profile. An optional standardized threshold is an additional OR condition,
    not a replacement for the unit-aware threshold.
    """

    absolute_residual_threshold: float = Field(gt=0, allow_inf_nan=False)
    standardized_residual_threshold: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    consecutive_breach_windows: int = Field(default=3, ge=1, le=1000)
    consecutive_clear_windows: int = Field(default=2, ge=1, le=1000)


class GapDetectorConfig(StrictModel):
    schema_version: SchemaVersion = "1.0"
    detector_id: str = Field(min_length=1, max_length=128)
    rules: dict[str, MetricGapRule] = Field(min_length=1)
    history_limit: int = Field(default=1000, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_rules(self) -> GapDetectorConfig:
        if any(not metric.strip() for metric in self.rules):
            raise ValueError("rule metric names must be non-empty")
        return self


class GapMetricState(StrictModel):
    schema_version: SchemaVersion = "1.0"
    series_key: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    baseline_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    consecutive_breach_windows: int = Field(default=0, ge=0)
    consecutive_clear_windows: int = Field(default=0, ge=0)
    active: bool = False
    last_window_start: datetime | None = None
    last_window_end: datetime | None = None
    last_run_id: str | None = None
    last_residual: float | None = None
    last_standardized_residual: float | None = None

    @model_validator(mode="after")
    def validate_state(self) -> GapMetricState:
        for name in ("last_window_start", "last_window_end"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must include a timezone")
        if self.last_window_start is not None and self.last_window_end is not None:
            if self.last_window_end <= self.last_window_start:
                raise ValueError("last_window_end must be later than last_window_start")
        for name in ("last_residual", "last_standardized_residual"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        return self


class GapEvent(StrictModel):
    schema_version: SchemaVersion = "1.0"
    event_id: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    event_type: GapEventType
    status: GapStatus
    baseline_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    window_start: datetime
    window_end: datetime
    residual: float | None = None
    standardized_residual: float | None = None
    absolute_threshold: float = Field(gt=0, allow_inf_nan=False)
    standardized_threshold: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    consecutive_breach_windows: int = Field(ge=0)
    consecutive_clear_windows: int = Field(ge=0)
    active: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event(self) -> GapEvent:
        for name in ("window_start", "window_end"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be later than window_start")
        for name in ("residual", "standardized_residual"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        return self


class GapDetectorState(StrictModel):
    schema_version: SchemaVersion = "1.0"
    detector_id: str = Field(min_length=1)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    series: dict[str, GapMetricState] = Field(default_factory=dict)
    events: list[GapEvent] = Field(default_factory=list)


class GapAssessment(StrictModel):
    schema_version: SchemaVersion = "1.0"
    status: GapStatus
    event_type: GapEventType
    detector_id: str
    baseline_id: str
    scenario_id: str
    backend_id: str
    run_id: str
    metric_name: str
    window_start: datetime
    window_end: datetime
    residual: float | None = None
    standardized_residual: float | None = None
    active: bool
    consecutive_breach_windows: int = Field(ge=0)
    consecutive_clear_windows: int = Field(ge=0)
    reason: str
    event_id: str


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _config_fingerprint(config: GapDetectorConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _series_key(baseline_id: str, scenario_id: str, backend_id: str, metric_name: str) -> str:
    identity = "\0".join((baseline_id, scenario_id, backend_id, metric_name))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class GapDetector:
    """Apply persistence thresholds and durably store state and bounded history.

    Only contiguous windows count toward streaks. A gap in the time series resets
    the streak to the current window; an older/overlapping window is rejected
    without changing that metric's state. Missing/stale/not-measured values break
    streaks but do not clear an already-open gap.
    """

    def __init__(self, config: GapDetectorConfig, state_path: str | Path | None = None):
        self.config = config
        self.state_path = Path(state_path) if state_path is not None else None
        fingerprint = _config_fingerprint(config)
        if self.state_path is not None and self.state_path.exists():
            loaded = GapDetectorState.model_validate_json(
                self.state_path.read_text(encoding="utf-8")
            )
            if loaded.detector_id != config.detector_id:
                raise ValueError("persisted state detector_id does not match configuration")
            if loaded.config_sha256 != fingerprint:
                raise ValueError(
                    "persisted state configuration fingerprint differs; choose a new state path or migrate explicitly"
                )
            self.state = loaded
        else:
            self.state = GapDetectorState(detector_id=config.detector_id, config_sha256=fingerprint)

    @property
    def events(self) -> tuple[GapEvent, ...]:
        """Return an immutable snapshot of retained event history."""
        return tuple(self.state.events)

    def active_gaps(self) -> tuple[GapMetricState, ...]:
        """Return currently active metric gaps, sorted deterministically."""
        return tuple(
            sorted(
                (item for item in self.state.series.values() if item.active),
                key=lambda item: (
                    item.baseline_id,
                    item.scenario_id,
                    item.backend_id,
                    item.metric_name,
                ),
            )
        )

    def ingest(
        self,
        evaluation: BaselineEvaluation,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[GapAssessment]:
        """Ingest one held-out baseline evaluation and persist its outcomes."""
        start = _utc(window_start, "window_start")
        end = _utc(window_end, "window_end")
        if end <= start:
            raise ValueError("window_end must be later than window_start")
        if evaluation.baseline_id.strip() == "":
            raise ValueError("baseline_id must not be empty")

        results: list[GapAssessment] = []
        new_series = dict(self.state.series)
        new_events = list(self.state.events)
        for metric_name, rule in sorted(self.config.rules.items()):
            key = _series_key(
                evaluation.baseline_id,
                evaluation.scenario_id,
                evaluation.backend_id,
                metric_name,
            )
            current = new_series.get(key)
            if current is None:
                current = GapMetricState(
                    series_key=key,
                    detector_id=self.config.detector_id,
                    baseline_id=evaluation.baseline_id,
                    scenario_id=evaluation.scenario_id,
                    backend_id=evaluation.backend_id,
                    metric_name=metric_name,
                )

            # Reject duplicate/overlapping/older windows. The state remains untouched.
            if current.last_window_end is not None and start < current.last_window_end.astimezone(
                UTC
            ):
                status: GapStatus = "out_of_order"
                event_type: GapEventType = "out_of_order_window"
                residual = evaluation.metrics.get(metric_name)
                residual_value = residual.residual if residual is not None else None
                standardized_value = (
                    residual.standardized_residual if residual is not None else None
                )
                reason = (
                    "window overlaps or precedes the last accepted window; state was not changed"
                )
                active = current.active
                breach_count = current.consecutive_breach_windows
                clear_count = current.consecutive_clear_windows
                updated = current
            else:
                contiguous = (
                    current.last_window_end is None
                    or start == current.last_window_end.astimezone(UTC)
                )
                if not contiguous:
                    current = current.model_copy(
                        update={"consecutive_breach_windows": 0, "consecutive_clear_windows": 0}
                    )
                metric_result = evaluation.metrics.get(metric_name)
                unavailable_reason = evaluation.unavailable_metrics.get(metric_name)
                if metric_result is None:
                    status = "insufficient_evidence"
                    event_type = "insufficient_evidence"
                    residual_value = None
                    standardized_value = None
                    reason = unavailable_reason or "metric was not evaluated by the baseline"
                    breach_count = 0
                    clear_count = 0
                    active = current.active
                else:
                    residual_value = metric_result.residual
                    standardized_value = metric_result.standardized_residual
                    absolute_breach = abs(residual_value) >= rule.absolute_residual_threshold
                    standardized_breach = (
                        rule.standardized_residual_threshold is not None
                        and standardized_value is not None
                        and abs(standardized_value) >= rule.standardized_residual_threshold
                    )
                    breach = absolute_breach or standardized_breach
                    if breach:
                        breach_count = current.consecutive_breach_windows + 1 if contiguous else 1
                        clear_count = 0
                        if current.active:
                            status = "open"
                            event_type = "gap_persisted"
                            reason = "active gap remains above at least one configured threshold"
                            active = True
                        elif breach_count >= rule.consecutive_breach_windows:
                            status = "open"
                            event_type = "gap_opened"
                            reason = (
                                "breach threshold met for the required consecutive measured windows"
                            )
                            active = True
                        else:
                            status = "candidate"
                            event_type = "gap_candidate"
                            reason = "threshold breached but persistence requirement is not yet met"
                            active = False
                    else:
                        breach_count = 0
                        if current.active:
                            clear_count = current.consecutive_clear_windows + 1 if contiguous else 1
                            if clear_count >= rule.consecutive_clear_windows:
                                status = "cleared"
                                event_type = "gap_cleared"
                                reason = (
                                    "required consecutive measured below-threshold windows observed"
                                )
                                active = False
                                clear_count = 0
                            else:
                                status = "open"
                                event_type = "gap_clear_pending"
                                reason = "below-threshold window observed; waiting for required clear streak"
                                active = True
                        else:
                            clear_count = 0
                            status = "normal"
                            event_type = "normal_window"
                            reason = "all configured residual thresholds are below limits"
                            active = False

                updated = current.model_copy(
                    update={
                        "consecutive_breach_windows": breach_count,
                        "consecutive_clear_windows": clear_count,
                        "active": active,
                        "last_window_start": start,
                        "last_window_end": end,
                        "last_run_id": evaluation.run_id,
                        "last_residual": residual_value,
                        "last_standardized_residual": standardized_value,
                    }
                )
                new_series[key] = updated

            event_payload = {
                "detector_id": self.config.detector_id,
                "baseline_id": evaluation.baseline_id,
                "scenario_id": evaluation.scenario_id,
                "backend_id": evaluation.backend_id,
                "run_id": evaluation.run_id,
                "metric_name": metric_name,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "status": status,
            }
            event_id = hashlib.sha256(
                json.dumps(event_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            assessment = GapAssessment(
                status=status,
                event_type=event_type,
                detector_id=self.config.detector_id,
                baseline_id=evaluation.baseline_id,
                scenario_id=evaluation.scenario_id,
                backend_id=evaluation.backend_id,
                run_id=evaluation.run_id,
                metric_name=metric_name,
                window_start=start,
                window_end=end,
                residual=residual_value,
                standardized_residual=standardized_value,
                active=active,
                consecutive_breach_windows=breach_count,
                consecutive_clear_windows=clear_count,
                reason=reason,
                event_id=event_id,
            )
            results.append(assessment)
            new_events.append(
                GapEvent(
                    event_id=event_id,
                    detector_id=self.config.detector_id,
                    event_type=event_type,
                    status=status,
                    baseline_id=evaluation.baseline_id,
                    scenario_id=evaluation.scenario_id,
                    backend_id=evaluation.backend_id,
                    run_id=evaluation.run_id,
                    metric_name=metric_name,
                    window_start=start,
                    window_end=end,
                    residual=residual_value,
                    standardized_residual=standardized_value,
                    absolute_threshold=rule.absolute_residual_threshold,
                    standardized_threshold=rule.standardized_residual_threshold,
                    consecutive_breach_windows=breach_count,
                    consecutive_clear_windows=clear_count,
                    active=active,
                    reason=reason,
                )
            )

        new_events = new_events[-self.config.history_limit :]
        new_state = GapDetectorState(
            detector_id=self.config.detector_id,
            config_sha256=_config_fingerprint(self.config),
            series=new_series,
            events=new_events,
        )
        self._persist(new_state)
        self.state = new_state
        return results

    def _persist(self, state: GapDetectorState) -> None:
        if self.state_path is None:
            return
        parent = self.state_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(state.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.", suffix=".tmp", dir=parent
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.state_path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
