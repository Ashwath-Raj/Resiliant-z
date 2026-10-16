from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.baseline import BaselineProfile, evaluate_baseline, fit_baseline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "configs" / "baseline" / "session4_fixture.v1.jsonl"


def measured(value: float | int, unit: str = "tasks") -> dict[str, object]:
    return {"value": value, "unit": unit, "quality": "measured", "reason": None}


def observation(value: float | int | None, quality: str, unit: str = "tasks") -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "quality": quality,
        "reason": None if quality == "measured" else f"fixture marks value {quality}",
    }


def record(
    run_id: str,
    value: float | int,
    *,
    scenario: str = "warehouse-v1",
    backend: str = "local-discrete-event",
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "scenario_id": scenario,
        "backend_id": backend,
        "window_start": "2026-10-16T08:00:00Z",
        "window_end": "2026-10-16T08:00:10Z",
        "queue_length": measured(value, "tasks"),
        "completed_tasks": measured(value + 1, "tasks"),
    }


def make_training() -> list[dict[str, object]]:
    return [record("train-a", 2), record("train-b", 4), record("train-c", 6)]


def test_fit_profile_uses_only_measured_windows_and_computes_mean() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    assert profile.schema_version == "1.0"
    assert profile.method == "per_metric_training_mean"
    assert profile.metrics["queue_length"].predicted_mean == pytest.approx(4.0)
    assert profile.metrics["queue_length"].sample_count == 3
    assert profile.metrics["queue_length"].distinct_training_runs == 3


def test_evaluation_residual_is_observed_minus_prediction() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    result = evaluate_baseline(profile, record("holdout-a", 10))
    queue = result.metrics["queue_length"]
    assert queue.predicted == pytest.approx(4.0)
    assert queue.observed == pytest.approx(10.0)
    assert queue.residual == pytest.approx(6.0)
    assert queue.absolute_residual == pytest.approx(6.0)
    assert queue.standardized_residual is not None


def test_measured_zero_is_not_treated_as_missing() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    result = evaluate_baseline(profile, record("holdout-zero", 0))
    assert result.metrics["queue_length"].observed == 0
    assert "queue_length" not in result.unavailable_metrics


def test_missing_or_stale_metrics_are_excluded_from_residuals() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    current = record("holdout-a", 5)
    current["queue_length"] = observation(None, "missing")
    current["completed_tasks"] = observation(3, "stale")
    result = evaluate_baseline(profile, current)
    assert "queue_length" not in result.metrics
    assert "queue_length" in result.unavailable_metrics
    assert "stale" in result.unavailable_metrics["completed_tasks"]


def test_fit_rejects_mixed_scenario_or_backend() -> None:
    with pytest.raises(ValueError, match="share one scenario_id and backend_id"):
        fit_baseline(
            [record("train-a", 1), record("train-b", 2, backend="isaac-sim")], baseline_id="bad"
        )


def test_fit_requires_distinct_training_run_ids() -> None:
    with pytest.raises(ValueError, match="two distinct training run IDs"):
        fit_baseline([record("same", 1), record("same", 2)], baseline_id="bad")


def test_eval_rejects_training_data_leakage() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    with pytest.raises(ValueError, match="holdout leakage"):
        evaluate_baseline(profile, record("train-a", 4))


def test_eval_rejects_scenario_and_backend_mismatch() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    with pytest.raises(ValueError, match="scenario_id"):
        evaluate_baseline(profile, record("holdout-a", 4, scenario="different"))
    with pytest.raises(ValueError, match="backend_id"):
        evaluate_baseline(profile, record("holdout-b", 4, backend="different-backend"))


def test_metric_unit_mismatch_fails_closed() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    current = record("holdout-a", 4)
    current["queue_length"] = measured(4, "robots")
    with pytest.raises(ValueError, match="unit mismatch"):
        evaluate_baseline(profile, current)


def test_low_sample_metrics_are_reported_as_excluded() -> None:
    training = make_training()
    for item in training:
        item["rare_metric"] = (
            observation(7, "measured")
            if item["run_id"] == "train-a"
            else observation(None, "missing")
        )
    profile = fit_baseline(training, baseline_id="baseline-001", minimum_samples_per_metric=3)
    assert "rare_metric" not in profile.metrics
    assert "rare_metric" in profile.excluded_metrics


def test_zero_variance_has_no_infinite_standardized_residual() -> None:
    training = [record("train-a", 3), record("train-b", 3), record("train-c", 3)]
    profile = fit_baseline(training, baseline_id="baseline-constant")
    result = evaluate_baseline(profile, record("holdout-a", 4))
    assert result.metrics["queue_length"].baseline_sample_stddev == 0
    assert result.metrics["queue_length"].standardized_residual is None


def test_profile_round_trips_through_json() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    payload = json.loads(profile.model_dump_json())
    restored = BaselineProfile.model_validate(payload)
    assert restored == profile


def test_fixture_contains_explicit_train_and_holdout_records() -> None:
    lines = [line for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    assert len(rows) >= 4
    ids = {row["run_id"] for row in rows}
    assert {"train-a", "train-b", "train-c", "holdout-a"}.issubset(ids)


def test_telemetry_model_dump_is_accepted() -> None:
    class RecordLike:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return record("holdout-a", 9)

    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    result = evaluate_baseline(profile, RecordLike())
    assert result.metrics["queue_length"].residual == pytest.approx(5.0)


def test_schema_contract_rejects_extra_profile_fields() -> None:
    profile = fit_baseline(make_training(), baseline_id="baseline-001")
    data = profile.model_dump()
    data["unreviewed_field"] = True
    with pytest.raises(ValidationError):
        BaselineProfile.model_validate(data)
