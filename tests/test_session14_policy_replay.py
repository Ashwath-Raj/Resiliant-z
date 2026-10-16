from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.knowledge_model import (
    append_record,
    build_knowledge_records,
    build_policy_proposal,
    load_ledger,
    load_policy_config,
    records_from_ledger,
)
from resiliant_z.policy_replay import (
    NumericObservation,
    ReplayError,
    ReplayPair,
    ReplaySide,
    Session14Config,
    evaluate_paired_replay,
    load_config,
    load_replay_pairs,
    write_report_no_clobber,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION13_CONFIG = ROOT / "configs/knowledge/session13_policy_boundaries.v1.json"
CANDIDATE_REPORT = ROOT / "configs/knowledge/session13_candidate_report.fixture.v1.json"
VALIDATION_REPORT = ROOT / "configs/knowledge/session13_validation_report.fixture.v1.json"
CONFIG_PATH = ROOT / "configs/policy-replay/session14_config.v1.json"
PAIR_PATH = ROOT / "configs/policy-replay/session14_replay_pairs.v1.jsonl"


def build_context(tmp_path: Path, *, eligible: bool = True):
    policy_config, policy_config_bytes = load_policy_config(SESSION13_CONFIG)
    records = build_knowledge_records(
        CANDIDATE_REPORT,
        VALIDATION_REPORT,
        SESSION13_CONFIG,
        created_at_utc="2026-10-16T00:00:00Z",
    )
    record = records[0]
    if eligible:
        provenance = record.provenance.model_copy(
            update={
                "backend_id": "isaac_sim_physics",
                "evidence_label": "ISAAC SIM PHYSICS-CALIBRATED FLEET",
            }
        )
        conditions = [
            c.model_copy(update={"calibration_status": "calibrated"}) for c in record.conditions
        ]
        record = record.model_copy(
            update={
                "operational_gate_status": "eligible_for_policy_review",
                "operational_gate_reasons": [],
                "provenance": provenance,
                "conditions": conditions,
            }
        )
    ledger = tmp_path / "knowledge.jsonl"
    append_record(ledger, record)
    entries = load_ledger(ledger)
    effective = records_from_ledger(entries)[0][1]
    config, config_bytes = load_config(CONFIG_PATH)
    proposal = build_policy_proposal(
        record,
        effective,
        policy_config,
        policy_config_bytes,
        created_at_utc="2026-10-16T00:00:00Z",
    )
    proposal_bytes = json.dumps(
        proposal.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    pairs, pairs_bytes = make_pairs(record, proposal, config)
    return (
        record,
        effective,
        ledger.read_bytes(),
        policy_config,
        policy_config_bytes,
        config,
        config_bytes,
        proposal,
        proposal_bytes,
        pairs,
        pairs_bytes,
    )


def make_pairs(record, proposal, config, *, benefits=(2, 2, 3, 2, 3, 2), measured_guardrails=True):
    pairs = []
    parameter_id = proposal.policy_parameter_id or "alternate_route_preference"
    current = proposal.current_value if proposal.current_value is not None else 0.5
    proposed = proposal.proposed_value if proposal.proposed_value is not None else 0.55
    conditions = {}
    for condition in record.conditions:
        conditions[condition.variable_id] = NumericObservation(
            value=(condition.minimum_observed + condition.maximum_observed) / 2,
            unit=condition.unit,
            quality="measured",
        )
    for index, improvement in enumerate(benefits, start=1):
        scenario_id = record.validated_scenarios[(index - 1) % len(record.validated_scenarios)]
        baseline_metrics = {
            config.primary_metric_id: NumericObservation(
                value=10.0, unit=config.primary_metric_unit, quality="measured"
            )
        }
        candidate_metrics = {
            config.primary_metric_id: NumericObservation(
                value=10.0 - improvement, unit=config.primary_metric_unit, quality="measured"
            )
        }
        for rule in config.guardrail_metrics:
            if measured_guardrails:
                baseline_metrics[rule.metric_id] = NumericObservation(
                    value=0.0, unit=rule.unit, quality="measured"
                )
                candidate_metrics[rule.metric_id] = NumericObservation(
                    value=0.0, unit=rule.unit, quality="measured"
                )
            else:
                baseline_metrics[rule.metric_id] = NumericObservation(
                    value=None,
                    unit=rule.unit,
                    quality="not_measured",
                    reason="synthetic backend did not measure this guardrail",
                )
                candidate_metrics[rule.metric_id] = NumericObservation(
                    value=None,
                    unit=rule.unit,
                    quality="not_measured",
                    reason="synthetic backend did not measure this guardrail",
                )
        common = {
            "seed": 1000 + index,
            "scenario_id": scenario_id,
            "backend_id": record.provenance.backend_id,
            "initial_state_id": f"initial-{index}",
            "task_pattern_id": f"tasks-{index}",
            "workload_pattern_id": f"load-{index}",
        }
        baseline_params = {parameter_id: current, "junction_avoidance_bias": 0.4}
        candidate_params = {parameter_id: proposed, "junction_avoidance_bias": 0.4}
        if parameter_id == "junction_avoidance_bias":
            baseline_params = {"alternate_route_preference": 0.5, parameter_id: current}
            candidate_params = {"alternate_route_preference": 0.5, parameter_id: proposed}
        # Both policies must have identical parameter keys and only the proposed parameter may change.
        baseline = ReplaySide(
            run_id=f"baseline-{index}",
            policy_parameters=baseline_params,
            metrics=baseline_metrics,
            **common,
        )
        candidate = ReplaySide(
            run_id=f"candidate-{index}",
            policy_parameters=candidate_params,
            metrics=candidate_metrics,
            **common,
        )
        pairs.append(
            ReplayPair(
                pair_id=f"pair-{index}",
                conditions=conditions,
                baseline=baseline,
                candidate=candidate,
            )
        )
    pairs_bytes = b"".join(
        (
            json.dumps(pair.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for pair in pairs
    )
    return pairs, pairs_bytes


def evaluate(context, *, allow=True, pairs=None, pairs_bytes=None):
    (
        record,
        effective,
        ledger_bytes,
        pc,
        pcb,
        config,
        cb,
        proposal,
        pb,
        default_pairs,
        default_bytes,
    ) = context
    return evaluate_paired_replay(
        proposal,
        pb,
        record,
        effective,
        ledger_bytes,
        pc,
        pcb,
        config,
        cb,
        default_pairs if pairs is None else pairs,
        default_bytes if pairs_bytes is None else pairs_bytes,
        allow_candidate_replay=allow,
    )


def test_session14_config_parses_and_is_bounded():
    config, raw = load_config(CONFIG_PATH)
    assert config.maximum_replay_pairs == 10000
    assert config.max_absolute_policy_delta == 0.1
    assert hashlib.sha256(raw).hexdigest()


def test_replay_fixture_contains_unmeasured_not_zero_safety_metrics():
    pairs, _ = load_replay_pairs(PAIR_PATH, 64 * 1024 * 1024, 10000)
    assert len(pairs) == 4
    assert pairs[0].baseline.metrics["deadlock_events"].quality == "not_measured"
    assert pairs[0].baseline.metrics["deadlock_events"].value is None


def test_candidate_analysis_reports_benefit_but_safety_unmeasured_blocks_operational_review(
    tmp_path,
):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, pairs_bytes = make_pairs(record, proposal, config, measured_guardrails=False)
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.report_status == "analyzed"
    assert report.candidate_effect_status == "candidate_benefit_observed"
    assert report.paired_summary and report.paired_summary.n_pairs == 6
    assert report.operational_review_status == "blocked_guardrails_unmeasured"
    assert report.live_policy_modified is False and report.automatic_application_allowed is False
    assert all(a.disposition == "included" for a in report.pair_audit)


def test_synthetic_knowledge_remains_blocked_even_with_replay_flag(tmp_path):
    ctx = build_context(tmp_path, eligible=False)
    report = evaluate(ctx)
    assert report.report_status == "blocked"
    assert "knowledge_operational_gate_blocked" in report.blocker_codes
    assert report.candidate_effect_status == "not_analyzed"
    assert report.live_policy_modified is False


def test_candidate_replay_requires_explicit_flag(tmp_path):
    report = evaluate(build_context(tmp_path), allow=False)
    assert report.report_status == "blocked"
    assert "candidate_replay_not_explicitly_authorized" in report.blocker_codes


def test_regression_is_detected(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    worse_pairs, worse_bytes = make_pairs(
        record, proposal, config, benefits=(-2, -2, -3, -2, -3, -2)
    )
    report = evaluate(ctx, pairs=worse_pairs, pairs_bytes=worse_bytes)
    assert report.candidate_effect_status == "candidate_regression_observed"
    assert report.operational_review_status == "not_eligible_for_review"


def test_missing_guardrails_never_count_as_zero(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, pairs_bytes = make_pairs(record, proposal, config, measured_guardrails=False)
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert all(item.status == "unmeasured_or_missing" for item in report.guardrails)
    assert report.operational_review_status == "blocked_guardrails_unmeasured"


def test_measured_zero_guardrails_are_valid(tmp_path):
    report = evaluate(build_context(tmp_path))
    assert all(item.status == "measured_pass" for item in report.guardrails)


def test_measured_guardrail_regression_blocks_review(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, _ = make_pairs(record, proposal, config)
    first = pairs[0]
    candidate_metrics = dict(first.candidate.metrics)
    candidate_metrics["collision_count"] = NumericObservation(
        value=1.0, unit="events", quality="measured"
    )
    changed_candidate = first.candidate.model_copy(update={"metrics": candidate_metrics})
    pairs[0] = first.model_copy(update={"candidate": changed_candidate})
    pairs_bytes = b"".join(
        (
            json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for p in pairs
    )
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.operational_review_status == "blocked_guardrail_regression"
    assert any(g.status == "regression_detected" for g in report.guardrails)


def test_outside_validated_condition_envelope_excluded(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, _ = make_pairs(record, proposal, config)
    pair = pairs[0]
    conditions = dict(pair.conditions)
    target = record.conditions[0]
    conditions[target.variable_id] = NumericObservation(
        value=target.maximum_observed + 1.0, unit=target.unit, quality="measured"
    )
    pairs[0] = pair.model_copy(update={"conditions": conditions})
    pairs_bytes = b"".join(
        (
            json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for p in pairs
    )
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.pair_audit[0].disposition == "excluded"
    assert any(
        code.startswith("condition_outside_validated_envelope:")
        for code in report.pair_audit[0].reason_codes
    )
    assert report.paired_summary and report.paired_summary.n_pairs == 5


def test_missing_primary_metric_is_excluded_not_zero(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, _ = make_pairs(record, proposal, config)
    first = pairs[0]
    metrics = dict(first.candidate.metrics)
    metrics[config.primary_metric_id] = NumericObservation(
        value=None, unit=config.primary_metric_unit, quality="missing", reason="fixture absent"
    )
    candidate = first.candidate.model_copy(update={"metrics": metrics})
    pairs[0] = first.model_copy(update={"candidate": candidate})
    pairs_bytes = b"".join(
        (
            json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for p in pairs
    )
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.pair_audit[0].disposition == "excluded"
    assert "primary_metric_unmeasured" in report.pair_audit[0].reason_codes


def test_parameter_delta_must_match_proposal(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, _ = make_pairs(record, proposal, config)
    first = pairs[0]
    values = dict(first.candidate.policy_parameters)
    values[proposal.policy_parameter_id] = proposal.proposed_value + 0.01
    candidate = first.candidate.model_copy(update={"policy_parameters": values})
    pairs[0] = first.model_copy(update={"candidate": candidate})
    pairs_bytes = b"".join(
        (
            json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for p in pairs
    )
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.pair_audit[0].disposition == "excluded"
    assert "candidate_policy_value_mismatch" in report.pair_audit[0].reason_codes


def test_policy_config_hash_mismatch_blocks(tmp_path):
    ctx = build_context(tmp_path)
    record, effective, ledger, pc, pcb, config, cb, proposal, pb, pairs, pair_bytes = ctx
    corrupt = proposal.model_copy(update={"policy_config_sha256": "0" * 64})
    corrupt_bytes = json.dumps(corrupt.model_dump(mode="json"), sort_keys=True).encode()
    report = evaluate_paired_replay(
        corrupt,
        corrupt_bytes,
        record,
        effective,
        ledger,
        pc,
        pcb,
        config,
        cb,
        pairs,
        pair_bytes,
        allow_candidate_replay=True,
    )
    assert report.report_status == "blocked"
    assert "proposal_policy_config_hash_mismatch" in report.blocker_codes


def test_wrong_provenance_blocks(tmp_path):
    ctx = build_context(tmp_path)
    record, effective, ledger, pc, pcb, config, cb, proposal, pb, pairs, pair_bytes = ctx
    changed = record.model_copy(
        update={
            "provenance": record.provenance.model_copy(update={"candidate_report_sha256": "f" * 64})
        }
    )
    report = evaluate_paired_replay(
        proposal,
        pb,
        changed,
        effective,
        ledger,
        pc,
        pcb,
        config,
        cb,
        pairs,
        pair_bytes,
        allow_candidate_replay=True,
    )
    assert report.report_status == "blocked"
    assert "proposal_candidate_provenance_mismatch" in report.blocker_codes


def test_stale_condition_is_excluded(tmp_path):
    ctx = build_context(tmp_path)
    record, _, _, _, _, config, _, proposal, _, _, _ = ctx
    pairs, _ = make_pairs(record, proposal, config)
    first = pairs[0]
    conditions = dict(first.conditions)
    key = record.conditions[0].variable_id
    conditions[key] = NumericObservation(
        value=None, unit=record.conditions[0].unit, quality="stale", reason="telemetry expired"
    )
    pairs[0] = first.model_copy(update={"conditions": conditions})
    pairs_bytes = b"".join(
        (
            json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        for p in pairs
    )
    report = evaluate(ctx, pairs=pairs, pairs_bytes=pairs_bytes)
    assert report.pair_audit[0].disposition == "excluded"
    assert any(
        code.startswith("condition_unmeasured:") for code in report.pair_audit[0].reason_codes
    )


def test_pair_model_rejects_seed_mismatch():
    base = ReplaySide(
        run_id="a",
        seed=1,
        scenario_id="s",
        backend_id="b",
        initial_state_id="i",
        task_pattern_id="t",
        workload_pattern_id="w",
        policy_parameters={"p": 0.1},
        metrics={},
    )
    candidate = base.model_copy(update={"run_id": "b", "seed": 2})
    with pytest.raises(ValidationError, match="seed"):
        ReplayPair(pair_id="pair", conditions={}, baseline=base, candidate=candidate)


def test_unmeasured_numeric_observation_requires_no_value_and_reason():
    with pytest.raises(ValidationError, match="unmeasured observations must not carry"):
        NumericObservation(value=0, unit="events", quality="not_measured", reason="not observed")
    with pytest.raises(ValidationError, match="require a numeric value"):
        NumericObservation(value=None, unit="events", quality="measured")


def test_policy_parameter_limits_are_checked_even_for_direct_config_construction():
    payload = json.loads(CONFIG_PATH.read_text())
    payload["parameter_bounds"]["alternate_route_preference"]["minimum"] = 2.0
    payload["parameter_bounds"]["alternate_route_preference"]["maximum"] = 1.0
    with pytest.raises(ValidationError, match="minimum must be less than maximum"):
        Session14Config.model_validate(payload)


def test_duplicate_replay_seeds_are_rejected(tmp_path):
    pairs, raw = load_replay_pairs(PAIR_PATH, 64 * 1024 * 1024, 10000)
    duplicate = pairs[0].model_copy(update={"pair_id": "another-pair"})
    path = tmp_path / "pairs.jsonl"
    path.write_text(raw.decode() + json.dumps(duplicate.model_dump(mode="json")) + "\n")
    with pytest.raises(ReplayError, match="replay_identity_duplicate"):
        load_replay_pairs(path, 64 * 1024 * 1024, 10000)


def test_report_is_deterministic_for_identical_bytes(tmp_path):
    ctx = build_context(tmp_path)
    first = evaluate(ctx)
    second = evaluate(ctx)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.report_id == second.report_id


def test_report_no_clobber_is_idempotent_and_refuses_different_bytes(tmp_path):
    report = evaluate(build_context(tmp_path))
    output = tmp_path / "report.json"
    one = write_report_no_clobber(report, output, 8 * 1024 * 1024)
    two = write_report_no_clobber(report, output, 8 * 1024 * 1024)
    assert one == two
    changed = report.model_copy(update={"limitations": report.limitations + ["changed"]})
    with pytest.raises(ReplayError, match="output_conflict"):
        write_report_no_clobber(changed, output, 8 * 1024 * 1024)


def test_conflicting_policy_parameter_is_rejected_in_config():
    payload = json.loads(CONFIG_PATH.read_text())
    payload["allowed_policy_parameters"].append("alternate_route_preference")
    with pytest.raises(ValidationError, match="must be unique"):
        Session14Config.model_validate(payload)


def test_report_always_declares_no_live_policy_change(tmp_path):
    report = evaluate(build_context(tmp_path))
    assert report.live_policy_modified is False
    assert report.automatic_application_allowed is False
    assert report.human_approval_required is True


def test_source_hashes_cover_all_inputs(tmp_path):
    report = evaluate(build_context(tmp_path))
    assert set(report.source_sha256) == {
        "policy_proposal",
        "knowledge_ledger",
        "policy_config",
        "session14_config",
        "replay_pairs",
    }
    assert all(len(value) == 64 for value in report.source_sha256.values())
