from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.candidate_discovery import (
    CandidateDiscoveryConfig,
    CandidateDiscoveryError,
    DiscoveryObservation,
    discover_candidates,
    load_config,
    read_observations_jsonl,
    save_report_atomic,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "candidate-discovery" / "session11_config.v1.json"
FIXTURE_PATH = ROOT / "configs" / "candidate-discovery" / "session11_observations.v1.jsonl"


@pytest.fixture(scope="module")
def config() -> CandidateDiscoveryConfig:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def observations(config: CandidateDiscoveryConfig) -> list[DiscoveryObservation]:
    return read_observations_jsonl(FIXTURE_PATH, config)


def test_fixture_recovers_predeclared_interaction_as_provisional(config, observations):
    report = discover_candidates(observations, config)
    finding = next(
        c for c in report.candidates if c.spec_id == "junction-occupancy-priority-interaction"
    )
    assert report.status == "provisional_candidates_only"
    assert finding.lifecycle_status == "provisional"
    assert finding.selection_outcome == "shortlisted"
    assert finding.effect_direction == "positive_interaction"
    assert finding.estimated_effect == pytest.approx(16.0, abs=1e-6)
    assert finding.confidence_interval_95_low > 0
    assert finding.evidence_label == "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM"
    assert (
        finding.factor_ranges["junction_occupancy"].calibration_status == "synthetic_uncalibrated"
    )


def test_main_effect_has_recoverable_direction(config, observations):
    report = discover_candidates(observations, config)
    finding = next(c for c in report.candidates if c.spec_id == "traffic-demand-main-effect")
    assert finding.estimated_effect == pytest.approx(4.0, abs=1e-6)
    assert finding.effect_direction == "increase"
    assert finding.selection_outcome == "shortlisted"


def test_validation_and_replay_rows_are_audited_but_excluded(config, observations):
    report = discover_candidates(observations, config)
    assert report.eligible_observations == 64
    assert report.excluded_reasons == {"split_not_permitted_for_candidate_discovery": 2}
    assert all(
        entry.split in {"discovery", "selection"}
        for entry in report.audit
        if entry.disposition == "eligible_for_candidate_discovery"
    )
    assert not any(
        entry.split in {"validation", "replay"} and entry.disposition != "excluded"
        for entry in report.audit
    )


def test_changing_validation_values_does_not_change_candidate_estimates_or_ids(
    config, observations
):
    changed = []
    for row in observations:
        if row.split == "validation":
            changed.append(row.model_copy(update={"value": -1234.5}))
        else:
            changed.append(row)
    first = discover_candidates(observations, config)
    second = discover_candidates(changed, config)
    assert [(c.candidate_id, c.estimated_effect) for c in first.candidates] == [
        (c.candidate_id, c.estimated_effect) for c in second.candidates
    ]
    assert first.batch_id == second.batch_id


def test_null_effect_is_not_shortlisted(config, observations):
    balanced = []
    for row in observations:
        if row.split in {"discovery", "selection"}:
            # Balanced, symmetric response independent of all factors.
            value = [-0.2, -0.1, 0.1, 0.2][int(row.observation_id.split("-")[-1]) % 4] + 10.0
            balanced.append(row.model_copy(update={"value": value}))
        else:
            balanced.append(row)
    report = discover_candidates(balanced, config)
    assert all(c.selection_outcome != "shortlisted" for c in report.candidates)
    assert all(c.lifecycle_status == "provisional" for c in report.candidates)


def test_duplicate_observation_id_rejected(config, observations):
    with pytest.raises(CandidateDiscoveryError, match="duplicate_observation_id"):
        discover_candidates([observations[0], observations[0]], config)


def test_duplicate_run_id_rejected(config, observations):
    duplicate = observations[1].model_copy(update={"run_id": observations[0].run_id})
    with pytest.raises(CandidateDiscoveryError, match="duplicate_run_id"):
        discover_candidates([observations[0], duplicate], config)


def test_seed_cannot_overlap_evidence_splits(config, observations):
    validation = next(row for row in observations if row.split == "validation")
    discovery = observations[0].model_copy(update={"seed": validation.seed})
    amended = [
        discovery if row.observation_id == observations[0].observation_id else row
        for row in observations
    ]
    with pytest.raises(CandidateDiscoveryError, match="split_seed_overlap"):
        discover_candidates(amended, config)


def test_unknown_factor_rejected(config, observations):
    changed = observations[0].model_copy(
        update={"factor_values": observations[0].factor_values | {"unregistered_knob": 0.1}}
    )
    with pytest.raises(CandidateDiscoveryError, match="unknown_factor"):
        discover_candidates([changed], config)


def test_factor_outside_registered_range_rejected(config, observations):
    changed = observations[0].model_copy(
        update={"factor_values": observations[0].factor_values | {"traffic_demand": 99.0}}
    )
    with pytest.raises(CandidateDiscoveryError, match="factor_out_of_range"):
        discover_candidates([changed], config)


def test_unmeasured_values_never_become_zero_evidence(config, observations):
    row = observations[0].model_copy(
        update={"quality": "missing", "value": None, "reason": "telemetry was absent"}
    )
    report = discover_candidates([row], config)
    assert report.eligible_observations == 0
    assert report.excluded_reasons == {"quality_missing": 1}


def test_measured_zero_is_valid_but_not_fabricated(config, observations):
    row = observations[0].model_copy(update={"value": 0.0})
    report = discover_candidates([row], config)
    assert report.eligible_observations == 1
    assert report.audit[0].disposition == "eligible_for_candidate_discovery"


def test_wrong_metric_unit_and_backend_are_excluded(config, observations):
    rows = [
        observations[0].model_copy(update={"metric_id": "other_metric"}),
        observations[1].model_copy(update={"metric_unit": "seconds"}),
        observations[2].model_copy(
            update={
                "backend_id": "surrogate",
                "evidence_label": "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM",
            }
        ),
    ]
    report = discover_candidates(rows, config)
    assert report.eligible_observations == 0
    assert report.excluded_reasons == {
        "backend_mismatch": 1,
        "metric_mismatch": 1,
        "metric_unit_mismatch": 1,
    }


def test_insufficient_observations_produce_inconclusive_candidates(config, observations):
    report = discover_candidates(observations[:5], config)
    assert all(c.selection_outcome == "insufficient_evidence" for c in report.candidates)
    assert all(c.estimated_effect is None for c in report.candidates)


def test_constant_factor_returns_insufficient_evidence(config, observations):
    rows = [
        row.model_copy(update={"factor_values": row.factor_values | {"traffic_demand": 0.8}})
        for row in observations
        if row.split in {"discovery", "selection"}
    ]
    report = discover_candidates(rows, config)
    main = next(c for c in report.candidates if c.spec_id == "traffic-demand-main-effect")
    assert main.selection_outcome == "insufficient_evidence"
    assert main.estimated_effect is None


def test_report_deterministic_and_atomic_write_refuses_conflict(tmp_path, config, observations):
    first = discover_candidates(observations, config)
    second = discover_candidates(observations, config)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    destination = tmp_path / "candidate-report.json"
    first_hash = save_report_atomic(first, destination)
    assert len(first_hash) == 64
    assert save_report_atomic(first, destination) == first_hash
    destination.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        save_report_atomic(first, destination)


def test_invalid_quality_cannot_carry_numeric_value():
    payload = {
        "observation_id": "obs-invalid",
        "evidence_id": "ev-invalid",
        "run_id": "run-invalid",
        "seed": 1,
        "split": "discovery",
        "scenario_id": "warehouse-cross-aisles-synthetic-v1",
        "backend_id": "discrete_event",
        "evidence_label": "LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM",
        "metric_id": "queue_growth",
        "metric_unit": "tasks",
        "value": 0,
        "quality": "missing",
        "reason": "missing metric",
        "factor_values": {},
        "model_version": "test",
    }
    with pytest.raises(ValidationError, match="unmeasured observation values must be null"):
        DiscoveryObservation.model_validate(payload)
