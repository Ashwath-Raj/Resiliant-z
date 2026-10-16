from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.evidence.session10 import (
    EvidenceAnalysisError,
    MetricObservation,
    RunResultArtifact,
    analyze_evidence,
    load_session10_config,
    save_result_artifact_atomic,
    write_report_atomic,
)
from resiliant_z.experiment_compiler import CompiledExperimentManifest
from resiliant_z.experiment_planner import load_planner_config, plan_experiment
from resiliant_z.orchestration import ExecutionReceipt, request_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    PROJECT_ROOT / "configs" / "experiment-planner" / "session8_manifest_fixture.v1.json"
)
PLANNER_CONFIG_PATH = PROJECT_ROOT / "configs" / "experiment-planner" / "session8_config.v1.json"
CONFIG_PATH = PROJECT_ROOT / "configs" / "evidence" / "session10_config.v1.json"


@pytest.fixture
def context(tmp_path):
    manifest = CompiledExperimentManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    plan = plan_experiment(MANIFEST_PATH, load_planner_config(PLANNER_CONFIG_PATH))
    config = load_session10_config(CONFIG_PATH)
    return tmp_path, manifest, plan, config


def _run_context(plan, split: str = "validation"):
    return [run for run in plan.runs if run.split == split]


def _make_result(run, manifest, value: float, unit: str = "seconds", quality: str = "measured"):
    observation = MetricObservation(
        value=value if quality == "measured" else None,
        unit=unit,
        quality=quality,
        reason=None if quality == "measured" else f"fixture marks metric {quality}",
    )
    return RunResultArtifact(
        run_id=run.run_id,
        plan_id=run.plan_id,
        request_sha256=request_hash(run),
        scenario_id=run.scenario_id,
        scenario_sha256=run.scenario_sha256,
        backend_id=run.backend_id,
        split=run.split,
        arm_id=run.arm_id,
        replicate_index=run.replicate_index,
        seed=run.seed,
        target_metric=run.target_metric,
        metrics={run.target_metric: observation},
        evidence_label=manifest.evidence_label,
        finished_at_utc=datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
    )


def _success_receipt(
    tmp_path, run, manifest, value: float, *, unit: str = "seconds", quality: str = "measured"
):
    artifact = _make_result(run, manifest, value, unit=unit, quality=quality)
    location = f"results/{run.run_id}.json"
    result_sha256 = save_result_artifact_atomic(tmp_path / location, artifact)
    suffix = hashlib.sha256(run.run_id.encode()).hexdigest()[:24]
    started = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    return ExecutionReceipt(
        receipt_id=f"rcpt-{suffix}",
        run_id=run.run_id,
        plan_id=run.plan_id,
        request_sha256=request_hash(run),
        executor_kind="local",
        status="succeeded",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=1),
        result_location=location,
        result_sha256=result_sha256,
    )


def _failed_receipt(run, status="failed"):
    suffix = hashlib.sha256((run.run_id + status).encode()).hexdigest()[:24]
    started = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    return ExecutionReceipt(
        receipt_id=f"rcpt-{suffix}",
        run_id=run.run_id,
        plan_id=run.plan_id,
        request_sha256=request_hash(run),
        executor_kind="local",
        status=status,
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=1),
        failure_reason=f"synthetic fixture {status}",
    )


def _full_validation_receipts(tmp_path, manifest, plan, values=None):
    values = values or {0: (10.0, 12.0), 1: (10.0, 13.0), 2: (10.0, 14.0)}
    receipts = []
    for run in _run_context(plan):
        control_value, treatment_value = values[run.replicate_index]
        metric_value = control_value if run.arm_id == "control" else treatment_value
        receipts.append(_success_receipt(tmp_path, run, manifest, metric_value))
    return receipts


def test_hand_calculated_paired_effect_and_95_percent_t_interval(context):
    root, manifest, plan, config = context
    receipts = _full_validation_receipts(root, manifest, plan)

    report = analyze_evidence(plan, manifest, receipts, config, root)

    assert report.pair_count == 3
    assert report.measured_validation_runs == 6
    assert report.validation_run_coverage == 1.0
    assert [pair.effect_treatment_minus_control for pair in report.paired_deltas] == [2.0, 3.0, 4.0]
    assert report.mean_paired_effect == pytest.approx(3.0)
    assert report.sample_sd_paired_effect == pytest.approx(1.0)
    assert report.confidence_interval_95_low == pytest.approx(0.5169, abs=0.002)
    assert report.confidence_interval_95_high == pytest.approx(5.4831, abs=0.002)
    assert report.effect_size_cohens_dz == pytest.approx(3.0)
    assert report.decision == "supports_predicted_direction"
    assert report.report_status == "provisional_evidence_report"


def test_no_execution_is_not_zero_evidence(context):
    root, manifest, plan, config = context
    report = analyze_evidence(plan, manifest, [], config, root)
    assert report.pair_count == 0
    assert report.mean_paired_effect is None
    assert report.decision == "insufficient_pairs"
    assert report.audit_counts["not_executed"] == plan.run_count


def test_failed_and_incomplete_runs_are_preserved_in_audit(context):
    root, manifest, plan, config = context
    runs = _run_context(plan)
    receipts = [_failed_receipt(runs[0], "failed"), _failed_receipt(runs[1], "incomplete")]
    report = analyze_evidence(plan, manifest, receipts, config, root)
    assert report.audit_counts["failed"] == 1
    assert report.audit_counts["incomplete"] == 1
    assert report.audit_counts["not_executed"] == plan.run_count - 2
    assert report.pair_count == 0


def test_missing_quality_never_becomes_zero_and_pair_is_excluded(context):
    root, manifest, plan, config = context
    runs = _run_context(plan)
    receipts = []
    for run in runs:
        if run.replicate_index == 0 and run.arm_id == "treatment":
            receipts.append(_success_receipt(root, run, manifest, 0.0, quality="missing"))
        elif run.replicate_index == 0 and run.arm_id == "control":
            receipts.append(_success_receipt(root, run, manifest, 10.0))
        else:
            value = 10.0 if run.arm_id == "control" else 12.0 + run.replicate_index
            receipts.append(_success_receipt(root, run, manifest, value))
    report = analyze_evidence(plan, manifest, receipts, config, root)
    assert report.audit_counts["unmeasured_metric"] == 1
    assert report.audit_counts["excluded_unpaired"] == 1
    assert report.pair_count == 2
    assert report.decision == "insufficient_pairs"


def test_result_artifact_tampering_fails_hash_verification(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation" and r.arm_id == "control")
    receipt = _success_receipt(root, run, manifest, 10.0)
    path = root / receipt.result_location
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"][run.target_metric]["value"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = analyze_evidence(plan, manifest, [receipt], config, root)

    assert report.audit_counts["invalid_result"] == 1
    assert report.pair_count == 0


def test_receipt_request_hash_mismatch_is_fatal(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation")
    receipt = _failed_receipt(run)
    bad = receipt.model_copy(update={"request_sha256": "f" * 64})
    with pytest.raises(EvidenceAnalysisError, match="receipt_request_hash_mismatch"):
        analyze_evidence(plan, manifest, [bad], config, root)


def test_result_run_provenance_mismatch_is_audited_and_excluded(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation" and r.arm_id == "control")
    artifact = _make_result(run, manifest, 10.0).model_copy(update={"seed": run.seed + 1})
    location = f"results/{run.run_id}.json"
    raw = (artifact.model_dump_json(indent=2) + "\n").encode()
    path = root / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    suffix = hashlib.sha256(run.run_id.encode()).hexdigest()[:24]
    started = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    receipt = ExecutionReceipt(
        receipt_id=f"rcpt-{suffix}",
        run_id=run.run_id,
        plan_id=run.plan_id,
        request_sha256=request_hash(run),
        executor_kind="local",
        status="succeeded",
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=1),
        result_location=location,
        result_sha256=hashlib.sha256(raw).hexdigest(),
    )
    report = analyze_evidence(plan, manifest, [receipt], config, root)
    assert report.audit_counts["invalid_result"] == 1
    assert report.pair_count == 0


def test_out_of_range_metric_is_not_analyzed(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation" and r.arm_id == "control")
    receipt = _success_receipt(root, run, manifest, 99999.0)
    report = analyze_evidence(plan, manifest, [receipt], config, root)
    assert report.audit_counts["out_of_range"] == 1
    assert report.pair_count == 0


def test_wrong_unit_is_not_analyzed(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation" and r.arm_id == "control")
    receipt = _success_receipt(root, run, manifest, 10.0, unit="tasks")
    report = analyze_evidence(plan, manifest, [receipt], config, root)
    assert report.audit_counts["wrong_unit"] == 1
    assert report.pair_count == 0


def test_primary_decision_uses_validation_only(context):
    root, manifest, plan, config = context
    validation = _full_validation_receipts(root, manifest, plan)
    discovery_runs = _run_context(plan, "discovery")
    discovery_receipts = [
        _success_receipt(root, run, manifest, 10.0 if run.arm_id == "control" else 100.0)
        for run in discovery_runs
    ]
    report = analyze_evidence(plan, manifest, validation + discovery_receipts, config, root)
    assert report.pair_count == 3
    assert report.audit_counts["excluded_non_validation"] == len(discovery_runs)
    assert report.mean_paired_effect == pytest.approx(3.0)


def test_duplicate_receipt_is_rejected(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation")
    receipt = _failed_receipt(run)
    with pytest.raises(EvidenceAnalysisError, match="duplicate_receipt"):
        analyze_evidence(plan, manifest, [receipt, receipt], config, root)


def test_receipt_for_unknown_run_is_rejected(context):
    root, manifest, plan, config = context
    run = next(r for r in plan.runs if r.split == "validation")
    receipt = _failed_receipt(run).model_copy(update={"run_id": "run-" + "f" * 24})
    with pytest.raises(EvidenceAnalysisError, match="receipt_for_unknown_run"):
        analyze_evidence(plan, manifest, [receipt], config, root)


def test_manifest_provenance_mismatch_is_rejected(context):
    root, manifest, plan, config = context
    bad = manifest.model_copy(update={"scenario_id": "different-scenario"})
    with pytest.raises(EvidenceAnalysisError, match="manifest_hash_mismatch"):
        analyze_evidence(plan, bad, [], config, root)


def test_report_id_is_deterministic_and_report_write_refuses_conflict(context):
    root, manifest, plan, config = context
    receipts = _full_validation_receipts(root, manifest, plan)
    first = analyze_evidence(plan, manifest, receipts, config, root)
    second = analyze_evidence(plan, manifest, receipts, config, root)
    assert first.report_id == second.report_id
    output = root / "evidence-report.json"
    write_report_atomic(output, first)
    write_report_atomic(output, first)
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report_atomic(output, first)


def test_zero_variance_effect_size_is_null_not_infinite(context):
    root, manifest, plan, config = context
    receipts = _full_validation_receipts(
        root, manifest, plan, values={0: (10.0, 12.0), 1: (10.0, 12.0), 2: (10.0, 12.0)}
    )
    report = analyze_evidence(plan, manifest, receipts, config, root)
    assert report.mean_paired_effect == pytest.approx(2.0)
    assert report.sample_sd_paired_effect == 0.0
    assert report.effect_size_cohens_dz is None
    assert report.decision == "supports_predicted_direction"


def test_measured_observation_accepts_zero_but_rejects_unmeasured_zero():
    measured_zero = MetricObservation(value=0.0, unit="seconds", quality="measured")
    assert measured_zero.value == 0.0
    with pytest.raises(ValidationError, match="unmeasured metric values must be null"):
        MetricObservation(value=0.0, unit="seconds", quality="missing", reason="not available")
