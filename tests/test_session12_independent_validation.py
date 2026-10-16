from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.independent_validation import (
    IndependentValidationError,
    Session12Config,
    ValidationObservation,
    ValidationRule,
    _t_critical_975,
    load_candidate_report,
    load_config,
    read_observations,
    save_report_atomic,
    validate_candidates,
    validate_files,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "independent-validation" / "session12_config.v1.json"
CANDIDATE_PATH = ROOT / "configs" / "independent-validation" / "session12_candidate_report.v1.json"
OBS_PATH = ROOT / "configs" / "independent-validation" / "session12_observations.v1.jsonl"


def _inputs():
    config, config_bytes = load_config(CONFIG_PATH)
    candidate_report, candidate_bytes = load_candidate_report(CANDIDATE_PATH, config)
    observations, observations_bytes = read_observations(OBS_PATH, config)
    return config, config_bytes, candidate_report, candidate_bytes, observations, observations_bytes


def _evaluate(
    rows=None,
    config=None,
    candidate_report=None,
    candidate_bytes=None,
    observations_bytes=None,
    config_bytes=None,
):
    defaults = _inputs()
    config = config or defaults[0]
    config_bytes = config_bytes or defaults[1]
    candidate_report = candidate_report or defaults[2]
    candidate_bytes = candidate_bytes or defaults[3]
    observations = rows if rows is not None else defaults[4]
    observations_bytes = observations_bytes or defaults[5]
    return validate_candidates(
        candidate_report,
        observations,
        config,
        candidate_report_bytes=candidate_bytes,
        observation_bytes=observations_bytes,
        config_bytes=config_bytes,
    )


def _row_dicts():
    return [
        json.loads(line)
        for line in OBS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _model_rows(items):
    return [ValidationObservation.model_validate(item) for item in items]


def _result(report, spec_id="priority_queue_main_effect"):
    return next(result for result in report.results if result.spec_id == spec_id)


def test_synthetic_fixture_validates_both_predeclared_candidates():
    report, _ = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    assert [item.status for item in report.results] == ["validated", "validated"]
    assert _result(report).pair_count == 6
    assert _result(report, "junction_priority_interaction").pair_count == 6


def test_main_effect_contrast_is_high_minus_low():
    report, _ = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    result = _result(report)
    assert result.mean_effect == pytest.approx(sum([5.8, 6.0, 6.2, 5.9, 6.1, 6.0]) / 6)
    assert (
        result.confidence_interval_95_low < result.mean_effect < result.confidence_interval_95_high
    )


def test_interaction_is_difference_in_differences():
    report, _ = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    result = _result(report, "junction_priority_interaction")
    assert result.mean_effect == pytest.approx(sum([3.9, 4.1, 4.0, 4.2, 3.8, 4.1]) / 6)
    assert result.status == "validated"


def test_report_id_and_effects_are_deterministic_for_same_input_bytes():
    first, _ = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    second, _ = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    assert first.report_id == second.report_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_confidence_critical_values_use_deterministic_student_t_lookup():
    assert _t_critical_975(1) == 12.706
    assert _t_critical_975(5) == 2.571
    assert _t_critical_975(30) == 2.042
    assert 1.95 < _t_critical_975(100) < 1.99
    with pytest.raises(ValueError):
        _t_critical_975(0)


def test_training_validation_seed_leak_invalidates_candidates():
    data = _row_dicts()
    candidate = next(
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "discovery"
    )
    candidate["seed"] = 1001  # seed already occurs in the validation split
    # Keep row identity unique; only the seed allocation has leaked.
    report = _evaluate(rows=_model_rows(data))
    assert all(result.status == "invalidated" for result in report.results)
    assert "seeds are reused" in _result(report).reason


def test_validation_scenario_overlap_invalidates_candidate():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["scenario_id"] = "warehouse-training-v1"
    config, *_ = _inputs()
    changed_config = config.model_copy(
        update={
            "allowed_validation_scenarios": [
                "warehouse-training-v1",
                "warehouse-layout-b",
                "warehouse-task-mix-c",
            ]
        }
    )
    report = _evaluate(
        rows=_model_rows(data),
        config=changed_config,
        config_bytes=b"allowlist includes training scenario",
    )
    assert _result(report).status == "invalidated"
    assert "reuses a training scenario" in _result(report).reason


def test_validation_initial_state_overlap_invalidates_candidate():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["initial_state_id"] = "train-state-a"
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "initial state" in _result(report).reason


def test_training_evidence_linkage_is_required():
    config, config_bytes, candidate_report, _, observations, observation_bytes = _inputs()
    candidate = next(
        item for item in candidate_report.candidates if item.spec_id == "priority_queue_main_effect"
    )
    candidate = candidate.model_copy(update={"evidence_ids": []})
    new_candidates = [
        candidate if item.spec_id == candidate.spec_id else item
        for item in candidate_report.candidates
    ]
    changed_report = candidate_report.model_copy(update={"candidates": new_candidates})
    report = _evaluate(
        rows=observations,
        config=config,
        candidate_report=changed_report,
        candidate_bytes=b"changed",
        observations_bytes=observation_bytes,
        config_bytes=config_bytes,
    )
    assert _result(report).status == "invalidated"
    assert "does not link" in _result(report).reason


def test_not_shortlisted_candidate_is_invalidated():
    config, config_bytes, candidate_report, _, observations, observation_bytes = _inputs()
    candidate = next(
        item for item in candidate_report.candidates if item.spec_id == "priority_queue_main_effect"
    ).model_copy(update={"selection_outcome": "not_shortlisted"})
    candidates = [
        candidate if item.spec_id == candidate.spec_id else item
        for item in candidate_report.candidates
    ]
    report_src = candidate_report.model_copy(update={"candidates": candidates})
    report = _evaluate(
        rows=observations,
        config=config,
        candidate_report=report_src,
        candidate_bytes=b"candidate report changed",
        observations_bytes=observation_bytes,
        config_bytes=config_bytes,
    )
    assert _result(report).status == "invalidated"
    assert "shortlisted provisional" in _result(report).reason


def test_wrong_candidate_or_metric_metadata_invalidates_candidate():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["metric_unit"] = "seconds"
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "metadata conflicts" in _result(report).reason


def test_out_of_range_metric_invalidates_candidate():
    config, *_ = _inputs()
    narrow = config.model_copy(update={"metric_min_value": 0.0, "metric_max_value": 25.0})
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["value"] = 999.0
    report = _evaluate(rows=_model_rows(data), config=narrow, config_bytes=b"narrow config")
    assert _result(report).status == "invalidated"
    assert "metric bounds" in _result(report).reason


def test_missing_quality_reduces_complete_pairs_and_is_not_zero():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["value"] = None
    row["quality"] = "missing"
    row["reason"] = "sensor window absent"
    report = _evaluate(rows=_model_rows(data))
    result = _result(report)
    assert result.pair_count == 5
    assert result.status == "inconclusive"
    assert any(
        a.observation_id == row["observation_id"] and a.disposition == "excluded"
        for a in report.audit
    )


def test_measured_zero_is_allowed():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect"
        and item["split"] == "validation"
        and item["factor_values"]["priority_ratio"] == 0.2
    )
    row["value"] = 0.0
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).pair_count == 6


def test_insufficient_context_diversity_is_inconclusive():
    data = _row_dicts()
    for row in data:
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation":
            row["scenario_id"] = "warehouse-layout-b"
            row["initial_state_id"] = "only-state"
            row["task_pattern_id"] = "only-task"
            row["workload_pattern_id"] = "only-workload"
    report = _evaluate(rows=_model_rows(data))
    result = _result(report)
    assert result.status == "inconclusive"
    assert "diversity criteria" in result.reason


def test_opposite_confirmatory_effect_is_rejected():
    data = _row_dicts()
    main = [
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation"
    ]
    groups = {}
    for row in main:
        groups.setdefault((row["seed"], row["replicate_index"]), []).append(row)
    for group in groups.values():
        low = next(row for row in group if row["factor_values"]["priority_ratio"] == 0.2)
        high = next(row for row in group if row["factor_values"]["priority_ratio"] == 0.8)
        high["value"] = low["value"] - 6.0
    report = _evaluate(rows=_model_rows(data))
    result = _result(report)
    assert result.status == "rejected"
    assert result.mean_effect < 0


def test_effect_below_practical_threshold_is_rejected_when_precise():
    data = _row_dicts()
    main = [
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation"
    ]
    groups = {}
    for row in main:
        groups.setdefault((row["seed"], row["replicate_index"]), []).append(row)
    for group in groups.values():
        low = next(row for row in group if row["factor_values"]["priority_ratio"] == 0.2)
        high = next(row for row in group if row["factor_values"]["priority_ratio"] == 0.8)
        high["value"] = low["value"] + 0.5
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "rejected"


def test_no_validation_rows_is_inconclusive():
    rows = _model_rows(
        [
            row
            for row in _row_dicts()
            if row["spec_id"] != "priority_queue_main_effect" or row["split"] != "validation"
        ]
    )
    report = _evaluate(rows=rows)
    assert _result(report).status == "inconclusive"


def test_unknown_configured_candidate_is_invalidated():
    config, _, _, _, observations, _ = _inputs()
    unknown_rule = config.rules[0].model_copy(update={"spec_id": "missing_candidate_spec"})
    changed_config = config.model_copy(update={"rules": [unknown_rule, config.rules[1]]})
    report = _evaluate(rows=observations, config=changed_config, config_bytes=b"changed config")
    assert report.results[0].status == "invalidated"
    assert report.results[0].candidate_id is None


def test_unallowlisted_validation_scenario_is_invalidated():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["scenario_id"] = "unknown-scenario"
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "not allowlisted" in _result(report).reason


def test_factor_value_outside_predeclared_levels_invalidates_candidate():
    data = _row_dicts()
    row = next(
        item
        for item in data
        if item["spec_id"] == "priority_queue_main_effect" and item["split"] == "validation"
    )
    row["factor_values"]["priority_ratio"] = 0.5
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "predeclared low/high level" in _result(report).reason


def test_nuisance_factor_change_inside_pair_invalidates_candidate():
    data = _row_dicts()
    group = [
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect"
        and row["split"] == "validation"
        and row["seed"] == 1001
    ]
    group[0]["factor_values"]["robot_count"] = 8
    group[1]["factor_values"]["robot_count"] = 10
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "nuisance factors" in _result(report).reason


def test_duplicate_observation_ids_are_rejected_by_reader(tmp_path):
    data = _row_dicts()[:2]
    data[1]["observation_id"] = data[0]["observation_id"]
    path = tmp_path / "duplicate.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in data), encoding="utf-8")
    config, _ = load_config(CONFIG_PATH)
    with pytest.raises(IndependentValidationError, match="duplicate_observation_id"):
        read_observations(path, config)


def test_empty_observation_file_is_rejected(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    config, _ = load_config(CONFIG_PATH)
    with pytest.raises(IndependentValidationError, match="observations_empty"):
        read_observations(path, config)


def test_config_rejects_reversed_factor_levels():
    config_dict = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config_dict["rules"][0]["factor_levels"]["priority_ratio"] = {"low": 0.8, "high": 0.2}
    with pytest.raises(ValidationError, match="strictly less"):
        Session12Config.model_validate(config_dict)


def test_replay_data_is_audited_but_excluded_from_estimate():
    data = _row_dicts()
    replay = next(
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation"
    ).copy()
    replay.update(
        {
            "observation_id": "obs-replay-extra",
            "evidence_id": "ev-replay-extra",
            "run_id": "run-ffffffffffffffffffffffff",
            "seed": 9001,
            "replicate_index": 90,
            "split": "replay",
            "scenario_id": "warehouse-replay-only",
            "initial_state_id": "replay-state",
            "task_pattern_id": "replay-task",
            "workload_pattern_id": "replay-workload",
        }
    )
    data.append(replay)
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).pair_count == 6
    assert any(
        item.observation_id == "obs-replay-extra" and item.disposition == "excluded"
        for item in report.audit
    )


def test_report_is_written_atomically_and_refuses_different_existing_content(tmp_path):
    report, config = validate_files(CONFIG_PATH, CANDIDATE_PATH, OBS_PATH)
    output = tmp_path / "report.json"
    first_hash = save_report_atomic(report, output, config.max_report_bytes)
    assert output.exists()
    assert save_report_atomic(report, output, config.max_report_bytes) == first_hash
    output.write_text('{"different": true}\n', encoding="utf-8")
    with pytest.raises(IndependentValidationError, match="output_conflict"):
        save_report_atomic(report, output, config.max_report_bytes)


def test_observation_rejects_unmeasured_numeric_value():
    data = _row_dicts()[0]
    data["quality"] = "stale"
    data["value"] = 0.0
    with pytest.raises(ValidationError, match="must be null"):
        ValidationObservation.model_validate(data)


def test_candidate_levels_outside_discovery_range_are_invalidated():
    config, _, _, _, observations, _ = _inputs()
    rule_data = config.rules[0].model_dump(mode="python")
    rule_data["factor_levels"] = {"priority_ratio": {"low": 0.1, "high": 0.8}}
    rule = ValidationRule.model_validate(rule_data)
    changed = config.model_copy(update={"rules": [rule, config.rules[1]]})
    report = _evaluate(rows=observations, config=changed, config_bytes=b"out-of-range levels")
    assert _result(report).status == "invalidated"
    assert "outside the candidate's discovery range" in _result(report).reason


def test_discovery_and_selection_splits_must_not_reuse_a_seed():
    data = _row_dicts()
    first_discovery = next(
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "discovery"
    )
    first_selection = next(
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "selection"
    )
    first_selection["seed"] = first_discovery["seed"]
    report = _evaluate(rows=_model_rows(data))
    assert _result(report).status == "invalidated"
    assert "seeds are reused" in _result(report).reason


def test_early_protocol_invalidation_keeps_all_validation_rows_in_audit():
    data = _row_dicts()
    for row in data:
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation":
            row["scenario_id"] = "unknown-scenario"
    report = _evaluate(rows=_model_rows(data))
    result = _result(report)
    assert result.status == "invalidated"
    validation_rows = [
        row
        for row in data
        if row["spec_id"] == "priority_queue_main_effect" and row["split"] == "validation"
    ]
    audited = [
        entry
        for entry in report.audit
        if entry.spec_id == "priority_queue_main_effect" and entry.split == "validation"
    ]
    assert len(audited) == len(validation_rows)
    assert all(entry.disposition == "excluded" for entry in audited)
    assert all("invalidated" in entry.reason for entry in audited)
