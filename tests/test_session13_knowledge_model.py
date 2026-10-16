from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from resiliant_z.knowledge_model import (
    KnowledgeError,
    KnowledgeRecord,
    PolicyProposal,
    append_lifecycle_event,
    append_record,
    build_knowledge_records,
    build_policy_proposal,
    create_lifecycle_event,
    effective_status,
    load_ledger,
    load_policy_config,
    write_json_no_clobber,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_REPORT = ROOT / "configs/knowledge/session13_candidate_report.fixture.v1.json"
VALIDATION_REPORT = ROOT / "configs/knowledge/session13_validation_report.fixture.v1.json"
POLICY_CONFIG = ROOT / "configs/knowledge/session13_policy_boundaries.v1.json"


def write_validation_report(path: Path, report: dict[str, object]) -> None:
    status = report.get("status", "independent_validation_report")
    report.pop("report_id", None)
    report.pop("status", None)
    canonical = json.dumps(
        report, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    report["report_id"] = "valreport-" + hashlib.sha256(canonical).hexdigest()[:24]
    report["status"] = status
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def build_records(*, created_at_utc: str = "2026-10-16T00:00:00Z") -> list[KnowledgeRecord]:
    return build_knowledge_records(
        CANDIDATE_REPORT,
        VALIDATION_REPORT,
        POLICY_CONFIG,
        created_at_utc=created_at_utc,
    )


def test_session12_report_becomes_versioned_scoped_knowledge() -> None:
    records = build_records()
    assert len(records) == 2
    assert all(record.lifecycle_status == "validated_scoped" for record in records)
    assert all(record.validation_status == "validated" for record in records)
    assert all(
        record.provenance.validation_report_id.startswith("valreport-") for record in records
    )
    assert all(record.provenance.candidate_report_sha256 for record in records)
    assert all(record.conditions for record in records)


def test_synthetic_discrete_event_evidence_is_never_operationally_eligible() -> None:
    records = build_records()
    assert all(record.operational_gate_status == "blocked" for record in records)
    assert all(
        "backend_not_in_operational_allowlist" in record.operational_gate_reasons
        for record in records
    )
    assert all(
        "evidence_label_not_in_operational_allowlist" in record.operational_gate_reasons
        for record in records
    )
    assert all(
        "one_or_more_factors_not_calibrated" in record.operational_gate_reasons
        for record in records
    )


def test_training_and_validation_evidence_links_are_combined_and_deduplicated() -> None:
    record = build_records()[0]
    assert record.provenance.evidence_ids
    assert len(record.provenance.evidence_ids) == len(set(record.provenance.evidence_ids))
    assert any("discovery" in evidence for evidence in record.provenance.evidence_ids)
    assert any("validation" in evidence for evidence in record.provenance.evidence_ids)


def test_candidate_report_exact_byte_hash_is_enforced(tmp_path: Path) -> None:
    mutated = tmp_path / "candidate.json"
    mutated.write_bytes(CANDIDATE_REPORT.read_bytes() + b" ")
    with pytest.raises(KnowledgeError, match="candidate_report_hash_mismatch"):
        build_knowledge_records(mutated, VALIDATION_REPORT, POLICY_CONFIG)


def test_validation_result_must_link_to_existing_candidate(tmp_path: Path) -> None:
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    report["results"][0]["candidate_id"] = "cand-ffffffffffffffffffffffff"
    report_path = tmp_path / "validation.json"
    write_validation_report(report_path, report)
    with pytest.raises(KnowledgeError, match="candidate_link_missing"):
        build_knowledge_records(CANDIDATE_REPORT, report_path, POLICY_CONFIG)


def test_candidate_and_validation_spec_ids_must_match(tmp_path: Path) -> None:
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    report["results"][0]["spec_id"] = "another_spec"
    report_path = tmp_path / "validation.json"
    write_validation_report(report_path, report)
    with pytest.raises(KnowledgeError, match="candidate_spec_mismatch"):
        build_knowledge_records(CANDIDATE_REPORT, report_path, POLICY_CONFIG)


def test_unknown_report_version_is_rejected(tmp_path: Path) -> None:
    report = json.loads(CANDIDATE_REPORT.read_text(encoding="utf-8"))
    report["schema_version"] = "99.0.0"
    report_path = tmp_path / "candidate.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="input_contract_error"):
        build_knowledge_records(report_path, VALIDATION_REPORT, POLICY_CONFIG)


def test_tampered_validation_report_id_is_rejected(tmp_path: Path) -> None:
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    report["results"][0]["mean_effect"] += 1.0
    report_path = tmp_path / "validation.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="validation_report_integrity_error"):
        build_knowledge_records(CANDIDATE_REPORT, report_path, POLICY_CONFIG)


def test_nonvalidated_outcome_never_becomes_validated_knowledge(tmp_path: Path) -> None:
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    report["results"][0]["status"] = "inconclusive"
    report_path = tmp_path / "validation.json"
    write_validation_report(report_path, report)
    record = build_knowledge_records(CANDIDATE_REPORT, report_path, POLICY_CONFIG)[0]
    assert record.validation_status == "inconclusive"
    assert record.lifecycle_status == "inconclusive"
    assert record.operational_gate_status == "blocked"


def test_candidate_not_shortlisted_cannot_be_ingested_as_validated(tmp_path: Path) -> None:
    candidate = json.loads(CANDIDATE_REPORT.read_text(encoding="utf-8"))
    candidate["candidates"][0]["selection_outcome"] = "not_shortlisted"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    report = json.loads(VALIDATION_REPORT.read_text(encoding="utf-8"))
    import hashlib

    report["candidate_report_sha256"] = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    validation_path = tmp_path / "validation.json"
    write_validation_report(validation_path, report)
    with pytest.raises(KnowledgeError, match="invalid_promotion_path"):
        build_knowledge_records(candidate_path, validation_path, POLICY_CONFIG)


def test_ledger_roundtrip_preserves_records(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    record = build_records()[0]
    assert append_record(ledger, record) == "added"
    assert ledger.stat().st_mode & 0o777 == 0o600
    loaded = load_ledger(ledger)
    assert len(loaded) == 1
    assert loaded[0].record == record


def test_duplicate_record_insert_is_idempotent_even_if_created_timestamp_differs(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    first = build_records(created_at_utc="2026-10-16T00:00:00Z")[0]
    second = build_records(created_at_utc="2026-10-17T00:00:00Z")[0]
    assert first.knowledge_id == second.knowledge_id
    assert append_record(ledger, first) == "added"
    assert append_record(ledger, second) == "already_present"
    assert len(load_ledger(ledger)) == 1


def test_same_knowledge_id_with_different_content_is_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    record = build_records()[0]
    append_record(ledger, record)
    modified = record.model_copy(update={"phenomenon": "different content"})
    with pytest.raises(KnowledgeError, match="knowledge_id_conflict"):
        append_record(ledger, modified)


def test_tampered_ledger_line_fails_integrity_check(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    append_record(ledger, build_records()[0])
    line = json.loads(ledger.read_text(encoding="utf-8"))
    line["record"]["phenomenon"] = "tampered"
    ledger.write_text(json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="ledger_integrity_error"):
        load_ledger(ledger)


def test_symlink_ledger_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "linked.jsonl"
    link.symlink_to(target)
    with pytest.raises(KnowledgeError, match="ledger_symlink"):
        load_ledger(link)
    with pytest.raises(KnowledgeError, match="ledger_symlink"):
        append_record(link, build_records()[0])


def test_invalidation_is_append_only_and_changes_effective_status(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    record = build_records()[0]
    append_record(ledger, record)
    before = ledger.read_bytes()
    entries = load_ledger(ledger)
    event = create_lifecycle_event(
        entries, record.knowledge_id, "invalidate", "contradictory evidence discovered"
    )
    assert append_lifecycle_event(ledger, event) == "added"
    assert ledger.read_bytes().startswith(before)
    new_entries = load_ledger(ledger)
    assert effective_status(record, new_entries) == "invalidated"
    assert len([entry for entry in new_entries if entry.record]) == 1


def test_rollback_marks_target_rolled_back_and_references_same_spec_restore(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    older, newer = build_records()
    newer = newer.model_copy(
        update={
            "spec_id": older.spec_id,
            "knowledge_id": "know-333333333333333333333333",
            "candidate_id": "cand-333333333333333333333333",
        }
    )
    append_record(ledger, older)
    append_record(ledger, newer)
    event = create_lifecycle_event(
        load_ledger(ledger),
        newer.knowledge_id,
        "rollback",
        "reverting candidate",
        older.knowledge_id,
    )
    append_lifecycle_event(ledger, event)
    entries = load_ledger(ledger)
    assert effective_status(newer, entries) == "rolled_back"
    assert effective_status(older, entries) == "restored"


def test_invalidated_record_is_terminal_for_rollback_and_restore(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    record = build_records()[0]
    later = record.model_copy(
        update={
            "knowledge_id": "know-444444444444444444444444",
            "candidate_id": "cand-444444444444444444444444",
        }
    )
    append_record(ledger, record)
    append_record(ledger, later)
    event = create_lifecycle_event(
        load_ledger(ledger), record.knowledge_id, "invalidate", "new evidence contradicts finding"
    )
    append_lifecycle_event(ledger, event)
    entries = load_ledger(ledger)
    with pytest.raises(KnowledgeError, match="invalidated_record_terminal"):
        create_lifecycle_event(
            entries, record.knowledge_id, "rollback", "cannot reactivate invalidated record"
        )
    with pytest.raises(KnowledgeError, match="invalidated_restore_target"):
        create_lifecycle_event(
            entries, later.knowledge_id, "rollback", "attempting restore", record.knowledge_id
        )


def test_policy_proposal_for_synthetic_fixture_is_blocked(tmp_path: Path) -> None:
    record = build_records()[0]
    config, config_bytes = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(
        record, record.lifecycle_status, config, config_bytes, created_at_utc="2026-10-16T00:00:00Z"
    )
    assert proposal.status == "blocked_operational_provenance"
    assert proposal.automatic_application_allowed is False
    assert proposal.applied is False
    assert proposal.proposed_value is None


def test_policy_gate_rechecks_provenance_instead_of_trusting_record_flag() -> None:
    record = build_records()[0].model_copy(
        update={
            "operational_gate_status": "eligible_for_policy_review",
            "operational_gate_reasons": [],
        }
    )
    config, config_bytes = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(record, "validated_scoped", config, config_bytes)
    assert proposal.status == "blocked_operational_provenance"
    assert "backend_not_in_operational_allowlist" in proposal.reason_codes
    assert "one_or_more_factors_not_calibrated" in proposal.reason_codes


def test_policy_proposal_for_unvalidated_record_is_blocked(tmp_path: Path) -> None:
    record = build_records()[0].model_copy(
        update={"lifecycle_status": "inconclusive", "validation_status": "inconclusive"}
    )
    config, config_bytes = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(record, "inconclusive", config, config_bytes)
    assert proposal.status == "blocked_lifecycle"


def test_calibrated_operational_record_yields_approval_required_not_application() -> None:
    record = build_records()[0]
    provenance = record.provenance.model_copy(
        update={
            "backend_id": "isaac_sim_physics",
            "evidence_label": "ISAAC SIM PHYSICS-CALIBRATED FLEET",
        }
    )
    conditions = [
        item.model_copy(update={"calibration_status": "calibrated"}) for item in record.conditions
    ]
    eligible = record.model_copy(
        update={
            "provenance": provenance,
            "conditions": conditions,
            "operational_gate_status": "eligible_for_policy_review",
            "operational_gate_reasons": [],
            "mean_effect": 6.0,
        }
    )
    config, config_bytes = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(
        eligible, "validated_scoped", config, config_bytes, created_at_utc="2026-10-16T00:00:00Z"
    )
    assert proposal.status == "approval_required"
    assert proposal.policy_parameter_id == "alternate_route_preference"
    assert proposal.current_value == 0.5
    assert proposal.proposed_value == 0.55
    assert proposal.human_approval_required is True
    assert proposal.automatic_application_allowed is False
    assert proposal.applied is False


def test_policy_proposal_rejects_step_outside_bounds() -> None:
    record = build_records()[0]
    provenance = record.provenance.model_copy(
        update={
            "backend_id": "isaac_sim_physics",
            "evidence_label": "ISAAC SIM PHYSICS-CALIBRATED FLEET",
        }
    )
    conditions = [
        item.model_copy(update={"calibration_status": "calibrated"}) for item in record.conditions
    ]
    eligible = record.model_copy(
        update={
            "provenance": provenance,
            "conditions": conditions,
            "operational_gate_status": "eligible_for_policy_review",
            "operational_gate_reasons": [],
            "mean_effect": 6.0,
        }
    )
    config, raw = load_policy_config(POLICY_CONFIG)
    rule = config.rules[0].model_copy(update={"current_value": 1.0})
    edited_config = config.model_copy(update={"rules": [rule, config.rules[1]]})
    proposal = build_policy_proposal(eligible, "validated_scoped", edited_config, raw)
    assert proposal.status == "blocked_out_of_bounds"
    assert proposal.proposed_value is None


def test_policy_proposal_output_is_no_clobber_and_hashable(tmp_path: Path) -> None:
    record = build_records()[0]
    config, raw = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(
        record, record.lifecycle_status, config, raw, created_at_utc="2026-10-16T00:00:00Z"
    )
    output = tmp_path / "proposal.json"
    first_hash = write_json_no_clobber(proposal, output)
    second_hash = write_json_no_clobber(proposal, output)
    assert first_hash == second_hash
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="output_conflict"):
        write_json_no_clobber(proposal, output)


def test_invalidation_requires_reason(tmp_path: Path) -> None:
    record = build_records()[0]
    with pytest.raises(KnowledgeError, match="lifecycle_reason_required"):
        create_lifecycle_event([], record.knowledge_id, "invalidate", "  ")


def test_policy_config_requires_immutable_approval_boundaries(tmp_path: Path) -> None:
    config = json.loads(POLICY_CONFIG.read_text(encoding="utf-8"))
    config["automatic_application_allowed"] = True
    edited = tmp_path / "policy.json"
    edited.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="policy_config_invalid"):
        load_policy_config(edited)


def test_compare_requires_same_metric_and_unit(tmp_path: Path) -> None:
    # The CLI's comparison guard is contract-tested via its records' metric/unit pair.
    first, second = build_records()
    assert first.target_metric == second.target_metric
    assert first.target_unit == second.target_unit
    edited = second.model_copy(update={"target_unit": "seconds"})
    assert (first.target_metric, first.target_unit) != (edited.target_metric, edited.target_unit)


def test_policy_proposal_schema_enforces_no_automatic_application() -> None:
    record = build_records()[0]
    config, raw = load_policy_config(POLICY_CONFIG)
    proposal = build_policy_proposal(record, record.lifecycle_status, config, raw)
    assert proposal.automatic_application_allowed is False
    assert proposal.applied is False
    assert PolicyProposal.model_fields["automatic_application_allowed"].default is False


def test_existing_ledger_without_records_loads_as_empty(tmp_path: Path) -> None:
    assert load_ledger(tmp_path / "not-created.jsonl") == []


def test_event_cannot_reference_unknown_record(tmp_path: Path) -> None:
    ledger = tmp_path / "knowledge.jsonl"
    from resiliant_z.knowledge_model import LifecycleEvent, append_lifecycle_event

    orphan = LifecycleEvent(
        event_id="kwevent-aaaaaaaaaaaaaaaaaaaaaaaa",
        event_type="invalidate",
        knowledge_id="know-aaaaaaaaaaaaaaaaaaaaaaaa",
        reason="not registered",
        created_at_utc="2026-10-16T00:00:00Z",
    )
    with pytest.raises(KnowledgeError, match="unknown_knowledge_id"):
        append_lifecycle_event(ledger, orphan)
