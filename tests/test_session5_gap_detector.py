from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.baseline import evaluate_baseline, fit_baseline
from resiliant_z.gap_detector import (
    GapDetector,
    GapDetectorConfig,
    MetricGapRule,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FIXTURE = PROJECT_ROOT / "configs" / "gap-detector" / "session5_config.v1.json"
EVALUATION_FIXTURE = PROJECT_ROOT / "configs" / "gap-detector" / "session5_evaluations.v1.jsonl"
START = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)


def measured(value: int | float, unit: str = "tasks") -> dict[str, object]:
    return {"value": value, "unit": unit, "quality": "measured", "reason": None}


def observation(value: int | float | None, quality: str, unit: str = "tasks") -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "quality": quality,
        "reason": None if quality == "measured" else f"marked {quality} in test",
    }


def telemetry_record(
    run_id: str, value: int | float | None, *, quality: str = "measured"
) -> dict[str, object]:
    metric = (
        measured(value)
        if quality == "measured" and value is not None
        else observation(value, quality)
    )
    return {
        "run_id": run_id,
        "scenario_id": "warehouse-v1",
        "backend_id": "local-discrete-event",
        "window_start": START.isoformat(),
        "window_end": (START + timedelta(seconds=60)).isoformat(),
        "queue_length": metric,
    }


def training_profile():
    records = [
        telemetry_record("train-a", 2),
        telemetry_record("train-b", 4),
        telemetry_record("train-c", 6),
    ]
    return fit_baseline(records, baseline_id="baseline-queue", minimum_samples_per_metric=3)


def evaluation(run_id: str, value: int | float | None, *, quality: str = "measured"):
    return evaluate_baseline(training_profile(), telemetry_record(run_id, value, quality=quality))


def config(*, breaches: int = 2, clears: int = 2) -> GapDetectorConfig:
    return GapDetectorConfig(
        detector_id="session5-test-detector",
        rules={
            "queue_length": MetricGapRule(
                absolute_residual_threshold=3.0,
                standardized_residual_threshold=1.5,
                consecutive_breach_windows=breaches,
                consecutive_clear_windows=clears,
            )
        },
    )


def times(index: int) -> tuple[datetime, datetime]:
    start = START + timedelta(seconds=60 * index)
    return start, start + timedelta(seconds=60)


def ingest(
    detector: GapDetector,
    index: int,
    run_id: str,
    value: int | float | None,
    *,
    quality: str = "measured",
):
    start, end = times(index)
    return detector.ingest(
        evaluation(run_id, value, quality=quality), window_start=start, window_end=end
    )[0]


def test_fixture_config_and_evaluation_jsonl_are_valid() -> None:
    cfg_payload = json.loads(CONFIG_FIXTURE.read_text(encoding="utf-8"))
    parsed = GapDetectorConfig.model_validate(cfg_payload)
    assert parsed.rules["queue_length"].consecutive_breach_windows == 2
    lines = [
        json.loads(line)
        for line in EVALUATION_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 4
    assert all(
        "evaluation" in item and "window_start" in item and "window_end" in item for item in lines
    )


def test_gap_is_candidate_then_opens_after_required_contiguous_breaches(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    first = ingest(detector, 0, "holdout-0", 12)
    second = ingest(detector, 1, "holdout-1", 13)
    assert first.status == "candidate"
    assert not first.active
    assert second.status == "open"
    assert second.active
    assert second.event_type == "gap_opened"
    assert len(detector.active_gaps()) == 1


def test_breach_after_gap_opens_remains_active(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 0, "holdout-0", 12)
    opened = ingest(detector, 1, "holdout-1", 13)
    persisted = ingest(detector, 2, "holdout-2", 14)
    assert opened.active and persisted.active
    assert persisted.event_type == "gap_persisted"


def test_active_gap_requires_consecutive_measured_clear_windows_to_close(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 0, "holdout-0", 12)
    ingest(detector, 1, "holdout-1", 13)
    pending = ingest(detector, 2, "holdout-2", 4)
    cleared = ingest(detector, 3, "holdout-3", 5)
    assert pending.status == "open" and pending.active
    assert pending.event_type == "gap_clear_pending"
    assert cleared.status == "cleared" and not cleared.active
    assert cleared.event_type == "gap_cleared"
    assert not detector.active_gaps()


def test_missing_observation_never_clears_open_gap(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 0, "holdout-0", 12)
    ingest(detector, 1, "holdout-1", 13)
    result = ingest(detector, 2, "holdout-2", None, quality="missing")
    assert result.status == "insufficient_evidence"
    assert result.active
    assert len(detector.active_gaps()) == 1


def test_missing_observation_breaks_breach_streak_without_false_zero(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 0, "holdout-0", 12)
    missing = ingest(detector, 1, "holdout-1", None, quality="missing")
    next_breach = ingest(detector, 2, "holdout-2", 13)
    assert missing.status == "insufficient_evidence"
    assert next_breach.status == "candidate"
    assert not next_breach.active
    assert next_breach.consecutive_breach_windows == 1


def test_below_threshold_windows_do_not_open_gap(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    for index, value in enumerate((4, 5, 3)):
        result = ingest(detector, index, f"normal-{index}", value)
    assert result.status == "normal"
    assert not result.active
    assert not detector.active_gaps()


def test_measured_zero_is_valid_and_can_breach_threshold(tmp_path: Path) -> None:
    detector = GapDetector(config(breaches=1), tmp_path / "state.json")
    result = ingest(detector, 0, "zero-value", 0)
    assert result.residual is not None
    assert result.residual < 0
    assert result.status == "open"


def test_out_of_order_or_duplicate_window_does_not_change_state(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 1, "newer", 12)
    newer_state = detector.state.series.copy()
    rejected = ingest(detector, 0, "older", 13)
    assert rejected.status == "out_of_order"
    assert detector.state.series == newer_state


def test_time_gap_resets_consecutive_breach_streak(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    first = ingest(detector, 0, "first", 12)
    after_gap = ingest(detector, 2, "after-gap", 13)
    assert first.status == "candidate"
    assert after_gap.status == "candidate"
    assert after_gap.consecutive_breach_windows == 1


def test_state_and_event_history_survive_detector_restart(tmp_path: Path) -> None:
    path = tmp_path / "detector-state.json"
    first_process = GapDetector(config(), path)
    ingest(first_process, 0, "holdout-0", 12)
    assert path.is_file()
    restarted = GapDetector(config(), path)
    result = ingest(restarted, 1, "holdout-1", 13)
    assert result.status == "open"
    assert result.active
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0"
    assert len(saved["events"]) == 2
    reloaded = GapDetector(config(), path)
    assert len(reloaded.active_gaps()) == 1
    assert len(reloaded.events) == 2


def test_state_history_is_bounded_by_configured_limit(tmp_path: Path) -> None:
    bounded_config = GapDetectorConfig(
        detector_id="bounded-history",
        history_limit=2,
        rules={
            "queue_length": MetricGapRule(
                absolute_residual_threshold=99.0, consecutive_breach_windows=1
            )
        },
    )
    detector = GapDetector(bounded_config, tmp_path / "state.json")
    for index in range(4):
        ingest(detector, index, f"run-{index}", 4)
    assert len(detector.events) == 2


def test_state_refuses_silent_threshold_configuration_change(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    detector = GapDetector(config(), path)
    ingest(detector, 0, "holdout-0", 4)
    changed = config(breaches=3)
    with pytest.raises(ValueError, match="configuration fingerprint differs"):
        GapDetector(changed, path)


def test_corrupted_persistent_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValidationError):
        GapDetector(config(), path)


def test_naive_datetimes_are_rejected(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    with pytest.raises(ValueError, match="window_start must include a timezone"):
        detector.ingest(
            evaluation("naive-test", 5),
            window_start=datetime(2026, 10, 16, 8, 0),
            window_end=datetime(2026, 10, 16, 8, 1, tzinfo=UTC),
        )


def test_config_rejects_non_positive_thresholds() -> None:
    with pytest.raises(ValidationError):
        MetricGapRule(absolute_residual_threshold=0)
    with pytest.raises(ValidationError):
        MetricGapRule(absolute_residual_threshold=1, standardized_residual_threshold=0)


def test_history_records_insufficient_evidence_and_out_of_order_reason(tmp_path: Path) -> None:
    detector = GapDetector(config(), tmp_path / "state.json")
    ingest(detector, 1, "latest", 5)
    ingest(detector, 0, "older", 12)
    assert detector.events[-1].event_type == "out_of_order_window"
    assert "state was not changed" in detector.events[-1].reason
