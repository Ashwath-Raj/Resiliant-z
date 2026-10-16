from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.experiment_compiler import CompiledExperimentManifest
from resiliant_z.experiment_planner import (
    RunRegistry,
    load_planner_config,
    plan_experiment,
)
from resiliant_z.orchestration import (
    ExecutionOutcome,
    ExecutionReceipt,
    ExecutionRequest,
    LocalExecutor,
    OrchestrationConfig,
    OrchestrationError,
    ReceiptJournal,
    RunOrchestrator,
    load_orchestration_config,
    preflight_plan,
    request_hash,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN_CONFIG_PATH = ROOT / "configs" / "experiment-planner" / "session8_config.v1.json"
MANIFEST_PATH = ROOT / "configs" / "experiment-planner" / "session8_manifest_fixture.v1.json"
ORCHESTRATION_CONFIG_PATH = ROOT / "configs" / "orchestration" / "session9_config.v1.json"


@pytest.fixture()
def context(tmp_path: Path):
    manifest = CompiledExperimentManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    plan_config = load_planner_config(PLAN_CONFIG_PATH)
    plan = plan_experiment(manifest, plan_config)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    config = load_orchestration_config(ORCHESTRATION_CONFIG_PATH).model_copy(
        update={"allow_execution": True}
    )
    registry = RunRegistry(tmp_path / "registry.json")
    journal = ReceiptJournal(tmp_path / "receipts.jsonl", config.journal_max_bytes)
    orchestrator = RunOrchestrator(registry, journal, config)
    return plan, plan_path, config, registry, journal, orchestrator


def successful_handler(request: ExecutionRequest) -> ExecutionOutcome:
    payload = json.dumps(
        {"run_id": request.run.run_id, "seed": request.run.seed}, sort_keys=True
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return ExecutionOutcome(
        status="succeeded",
        result_location=f"fixture://results/{request.run.run_id}.json",
        result_sha256=digest,
        logs_location=f"fixture://logs/{request.run.run_id}.log",
    )


def test_request_hash_is_deterministic(context):
    plan, *_ = context
    run = plan.runs[0]
    assert request_hash(run) == request_hash(run.model_copy(deep=True))
    request = ExecutionRequest(
        run=run, request_sha256=request_hash(run), created_at_utc=datetime.now(UTC)
    )
    assert request.request_sha256 == request_hash(run)


def test_request_hash_mismatch_is_rejected(context):
    plan, *_ = context
    with pytest.raises(ValidationError, match="does not match"):
        ExecutionRequest(
            run=plan.runs[0],
            request_sha256="0" * 64,
            created_at_utc=datetime.now(UTC),
        )


def test_preflight_reports_zero_execution_network_and_cloud_calls(context):
    plan, plan_path, config, *_ = context
    summary = preflight_plan(plan_path, config.model_copy(update={"allow_execution": False}))
    assert summary["plan_id"] == plan.plan_id
    assert summary["run_count"] == 24
    assert (
        summary["executor_calls"]
        == summary["network_calls"]
        == summary["cloud_jobs_submitted"]
        == 0
    )
    assert summary["evidence_status"] == "not_executed_not_evidence"


def test_preflight_rejects_oversized_plan(context):
    _, plan_path, config, *_ = context
    limited = config.model_copy(update={"max_runs_per_invocation": 8})
    with pytest.raises(OrchestrationError, match="run_limit_exceeded"):
        preflight_plan(plan_path, limited)


def test_execution_requires_two_explicit_opt_ins(context):
    plan, _, _, registry, journal, _ = context
    disabled = RunOrchestrator(
        registry,
        journal,
        load_orchestration_config(ORCHESTRATION_CONFIG_PATH),
    )
    with pytest.raises(OrchestrationError, match="execution_not_opted_in"):
        disabled.execute_plan(
            plan, LocalExecutor(successful_handler), explicit_execution_opt_in=True
        )
    assert not registry.snapshot.runs


def test_successful_fake_local_executor_records_receipts_and_terminal_states(context):
    plan, _, _, registry, journal, orchestrator = context
    calls: list[str] = []

    def handler(request: ExecutionRequest) -> ExecutionOutcome:
        calls.append(request.run.run_id)
        return successful_handler(request)

    receipts = orchestrator.execute_plan(
        plan, LocalExecutor(handler), explicit_execution_opt_in=True
    )
    assert len(receipts) == plan.run_count == 24
    assert len(calls) == 24
    assert all(item.status == "succeeded" for item in receipts)
    assert all(registry.snapshot.runs[item.run_id].status == "succeeded" for item in receipts)
    assert len(journal.read()) == 24


def test_replay_does_not_execute_completed_runs_again(context):
    plan, _, _, _, journal, orchestrator = context
    calls: list[str] = []

    def handler(request: ExecutionRequest) -> ExecutionOutcome:
        calls.append(request.run.run_id)
        return successful_handler(request)

    executor = LocalExecutor(handler)
    first = orchestrator.execute_plan(plan, executor, explicit_execution_opt_in=True)
    second = orchestrator.execute_plan(plan, executor, explicit_execution_opt_in=True)
    assert len(first) == 24
    assert second == []
    assert len(calls) == 24
    assert len(journal.read()) == 24


def test_executor_exception_becomes_failed_receipt_without_exception_text(context):
    plan, _, _, registry, journal, orchestrator = context

    def handler(request: ExecutionRequest) -> ExecutionOutcome:
        if request.run.run_id == plan.runs[0].run_id:
            raise RuntimeError("sensitive token should not appear")
        return successful_handler(request)

    receipts = orchestrator.execute_plan(
        plan, LocalExecutor(handler), explicit_execution_opt_in=True
    )
    failed = next(item for item in receipts if item.run_id == plan.runs[0].run_id)
    assert failed.status == "failed"
    assert failed.failure_reason == "executor error: RuntimeError"
    assert "sensitive token" not in journal.path.read_text(encoding="utf-8")
    assert registry.snapshot.runs[failed.run_id].status == "failed"


def test_timeout_becomes_timed_out_receipt(context):
    plan, _, _, registry, _, orchestrator = context

    def handler(request: ExecutionRequest) -> ExecutionOutcome:
        if request.run.run_id == plan.runs[0].run_id:
            raise TimeoutError("provider-specific diagnostics should not persist")
        return successful_handler(request)

    receipts = orchestrator.execute_plan(
        plan, LocalExecutor(handler), explicit_execution_opt_in=True
    )
    timed_out = next(item for item in receipts if item.run_id == plan.runs[0].run_id)
    assert timed_out.status == "timed_out"
    assert timed_out.failure_reason == "executor timeout"
    assert registry.snapshot.runs[timed_out.run_id].status == "timed_out"


def test_interrupted_running_job_is_marked_incomplete_and_not_rerun(context):
    plan, _, _, registry, journal, orchestrator = context
    registry.register_plan(plan)
    run = plan.runs[0]
    registry.transition(run.run_id, "validated", "test setup")
    registry.transition(run.run_id, "queued", "test setup")
    registry.transition(run.run_id, "running", "test setup")
    calls: list[str] = []

    def handler(request: ExecutionRequest) -> ExecutionOutcome:
        calls.append(request.run.run_id)
        return successful_handler(request)

    receipts = orchestrator.execute_plan(
        plan, LocalExecutor(handler), explicit_execution_opt_in=True
    )
    assert registry.snapshot.runs[run.run_id].status == "incomplete"
    assert run.run_id not in calls
    assert any(item.run_id == run.run_id and item.status == "incomplete" for item in receipts)
    assert len(journal.read()) == plan.run_count


def test_remote_executor_is_rejected_by_default(context):
    plan, _, _, registry, journal, _ = context

    class RemoteExecutor:
        kind = "nebius_jobs"

        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            raise AssertionError("remote executor must not be invoked")

    orchestrator = RunOrchestrator(
        registry,
        journal,
        load_orchestration_config(ORCHESTRATION_CONFIG_PATH),
    )
    with pytest.raises(OrchestrationError, match="executor_not_allowed"):
        orchestrator.execute_plan(plan, RemoteExecutor(), explicit_execution_opt_in=True)
    assert not registry.snapshot.runs


def test_config_cannot_allow_remote_without_both_gates():
    with pytest.raises(ValidationError, match="nebius_jobs"):
        OrchestrationConfig(
            config_id="unsafe",
            allowed_executor_kinds=["local", "nebius_jobs"],
            allow_execution=True,
            allow_remote_execution=False,
        )


def test_receipt_requires_result_hash_for_success():
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="result_location and result_sha256"):
        ExecutionReceipt(
            receipt_id="rcpt-" + "a" * 24,
            run_id="run-" + "b" * 24,
            plan_id="plan-" + "c" * 24,
            request_sha256="d" * 64,
            executor_kind="local",
            status="succeeded",
            started_at_utc=now,
            ended_at_utc=now,
            result_location="fixture://result.json",
        )


def test_malformed_journal_is_rejected(context):
    _, _, _, _, journal, _ = context
    journal.path.write_text('{"status": "broken"}\n', encoding="utf-8")
    with pytest.raises(OrchestrationError, match="journal_invalid_record"):
        journal.read()


def test_planner_and_orchestration_config_fixtures_load(context):
    plan, _, _, *_ = context
    config = load_orchestration_config(ORCHESTRATION_CONFIG_PATH)
    assert config.allow_execution is False
    assert config.allow_remote_execution is False
    assert len(plan.runs) == 24
