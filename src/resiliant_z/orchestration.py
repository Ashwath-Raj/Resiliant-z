"""Bounded orchestration boundary for RESILIANT-Z Session 9.

This module coordinates a preplanned run with an injected, trusted executor.
The default CLI is preflight-only; it never launches a simulator, makes network
requests, or submits cloud jobs. Executor completion is not evidence validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resiliant_z.experiment_planner import (
    ExperimentPlan,
    PlannedRun,
    RunRegistry,
    RunStatus,
)

SCHEMA_VERSION = Literal["1.0.0"]
ExecutionStatus = Literal["succeeded", "failed", "timed_out", "incomplete"]
ExecutorKind = Literal["local", "nebius_jobs"]
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def request_hash(run: PlannedRun) -> str:
    """Return a stable request hash over immutable planned-run data."""
    return hashlib.sha256(_canonical_bytes(run)).hexdigest()


class OrchestrationConfig(StrictModel):
    schema_version: SCHEMA_VERSION = "1.0.0"
    config_id: str = Field(min_length=1, max_length=128)
    max_runs_per_invocation: int = Field(default=24, ge=1, le=200)
    allowed_executor_kinds: list[ExecutorKind] = Field(default_factory=lambda: ["local"])
    allow_execution: bool = False
    allow_remote_execution: bool = False
    journal_max_bytes: int = Field(default=16_777_216, ge=1_024, le=268_435_456)

    @model_validator(mode="after")
    def validate_remote_gate(self) -> OrchestrationConfig:
        if "nebius_jobs" in self.allowed_executor_kinds and not self.allow_remote_execution:
            raise ValueError(
                "nebius_jobs cannot be allowlisted unless allow_remote_execution is true"
            )
        if self.allow_remote_execution and "nebius_jobs" not in self.allowed_executor_kinds:
            raise ValueError(
                "allow_remote_execution requires nebius_jobs in allowed_executor_kinds"
            )
        if "local" not in self.allowed_executor_kinds:
            raise ValueError("the local executor must remain allowlisted")
        return self


class ExecutionRequest(StrictModel):
    schema_version: SCHEMA_VERSION = "1.0.0"
    run: PlannedRun
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    created_at_utc: datetime

    @model_validator(mode="after")
    def validate_request(self) -> ExecutionRequest:
        if self.request_sha256 != request_hash(self.run):
            raise ValueError("request_sha256 does not match the planned run")
        if self.created_at_utc.tzinfo is None or self.created_at_utc.utcoffset() is None:
            raise ValueError("created_at_utc must include a timezone")
        return self


class ExecutionOutcome(StrictModel):
    """Typed outcome returned by a trusted in-process executor adapter."""

    status: ExecutionStatus
    result_location: str | None = Field(default=None, max_length=2_048)
    result_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    logs_location: str | None = Field(default=None, max_length=2_048)
    remote_job_id: str | None = Field(default=None, max_length=256)
    container_image_digest: str | None = Field(default=None, max_length=512)
    failure_reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_outcome(self) -> ExecutionOutcome:
        if self.status == "succeeded":
            if not self.result_location or not self.result_sha256:
                raise ValueError("succeeded outcome requires result_location and result_sha256")
            if self.failure_reason:
                raise ValueError("succeeded outcome cannot include failure_reason")
        elif not self.failure_reason or not self.failure_reason.strip():
            raise ValueError("non-success outcome requires a non-empty failure_reason")
        return self


# Backward-compatible alias for early Session 9 drafts.
ExecutorOutcome = ExecutionOutcome


class ExecutionReceipt(StrictModel):
    schema_version: SCHEMA_VERSION = "1.0.0"
    receipt_id: str = Field(pattern=r"^rcpt-[0-9a-f]{24}$")
    run_id: str = Field(pattern=r"^run-[0-9a-f]{24}$")
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{24}$")
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    executor_kind: ExecutorKind
    status: ExecutionStatus
    started_at_utc: datetime
    ended_at_utc: datetime
    result_location: str | None = Field(default=None, max_length=2_048)
    result_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    logs_location: str | None = Field(default=None, max_length=2_048)
    remote_job_id: str | None = Field(default=None, max_length=256)
    container_image_digest: str | None = Field(default=None, max_length=512)
    failure_reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_receipt(self) -> ExecutionReceipt:
        for field_name in ("started_at_utc", "ended_at_utc"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.ended_at_utc.astimezone(UTC) < self.started_at_utc.astimezone(UTC):
            raise ValueError("ended_at_utc must not precede started_at_utc")
        if self.status == "succeeded":
            if not self.result_location or not self.result_sha256:
                raise ValueError("succeeded receipt requires result_location and result_sha256")
            if self.failure_reason:
                raise ValueError("succeeded receipt cannot include failure_reason")
        elif not self.failure_reason or not self.failure_reason.strip():
            raise ValueError("non-success receipt requires failure_reason")
        if (
            self.executor_kind == "nebius_jobs"
            and self.status == "succeeded"
            and not self.remote_job_id
        ):
            raise ValueError("successful remote receipts require remote_job_id")
        return self


@runtime_checkable
class Executor(Protocol):
    """Trusted executor interface; adapters must not infer permission from an LLM."""

    kind: ExecutorKind

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Execute exactly one planned run and return a typed outcome."""
        ...


class LocalExecutor:
    """Adapter around a trusted in-process local-run callback.

    The callback must persist its result and return a content hash. No shell or
    free-form command string is accepted by this interface.
    """

    kind: ExecutorKind = "local"

    def __init__(
        self, handler: Callable[[ExecutionRequest], ExecutionOutcome | Mapping[str, object]]
    ):
        if not callable(handler):
            raise TypeError("handler must be a trusted callable")
        self._handler = handler

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        return ExecutionOutcome.model_validate(self._handler(request))


@runtime_checkable
class NebiusJobsClient(Protocol):
    """Optional adapter seam; this project ships no live Nebius client."""

    def submit_job(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        """Submit a job through a separately supplied, documented client."""
        ...

    def get_job(self, job_id: str) -> Mapping[str, object]:
        """Read job status through a separately supplied client."""
        ...


class OrchestrationError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class ReceiptJournal:
    """Append-only JSONL receipt journal with size and shape checks."""

    def __init__(self, path: str | Path, max_bytes: int = 16_777_216):
        self.path = Path(path)
        self.max_bytes = max_bytes

    def read(self) -> list[ExecutionReceipt]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_bytes()
            if len(raw) > self.max_bytes:
                raise OrchestrationError(
                    "journal_too_large", "execution journal exceeds configured size limit"
                )
            text = raw.decode("utf-8")
        except OrchestrationError:
            raise
        except (OSError, UnicodeError) as exc:
            raise OrchestrationError(
                "journal_read_error", f"could not read receipt journal: {type(exc).__name__}"
            ) from None
        receipts: list[ExecutionReceipt] = []
        seen: dict[str, str] = {}
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                receipt = ExecutionReceipt.model_validate_json(line)
            except Exception as exc:
                raise OrchestrationError(
                    "journal_invalid_record",
                    f"invalid receipt on line {line_number}: {type(exc).__name__}",
                ) from None
            previous = seen.get(receipt.run_id)
            if previous is not None and previous != receipt.request_sha256:
                raise OrchestrationError(
                    "journal_identity_conflict", f"conflicting request hashes for {receipt.run_id}"
                )
            seen[receipt.run_id] = receipt.request_sha256
            receipts.append(receipt)
        return receipts

    def append(self, receipt: ExecutionReceipt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (receipt.model_dump_json() + "\n").encode("utf-8")
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size + len(payload) > self.max_bytes:
            raise OrchestrationError(
                "journal_too_large", "append would exceed configured journal size limit"
            )
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(self.path, 0o600)


class RunOrchestrator:
    """Coordinate plan lifecycle, execution receipt persistence and registry state."""

    def __init__(
        self,
        registry: RunRegistry,
        journal: ReceiptJournal,
        config: OrchestrationConfig,
    ):
        self.registry = registry
        self.journal = journal
        self.config = config

    @staticmethod
    def _receipt_id(run_id: str, request_sha256: str, status: str, ended: datetime) -> str:
        material = f"{run_id}|{request_sha256}|{status}|{ended.isoformat()}".encode()
        return "rcpt-" + hashlib.sha256(material).hexdigest()[:24]

    def _make_receipt(
        self,
        run: PlannedRun,
        digest: str,
        executor_kind: ExecutorKind,
        status: ExecutionStatus,
        started: datetime,
        ended: datetime,
        outcome: ExecutionOutcome,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            receipt_id=self._receipt_id(run.run_id, digest, status, ended),
            run_id=run.run_id,
            plan_id=run.plan_id,
            request_sha256=digest,
            executor_kind=executor_kind,
            status=status,
            started_at_utc=started,
            ended_at_utc=ended,
            result_location=outcome.result_location if status == "succeeded" else None,
            result_sha256=outcome.result_sha256 if status == "succeeded" else None,
            logs_location=outcome.logs_location,
            remote_job_id=outcome.remote_job_id,
            container_image_digest=outcome.container_image_digest,
            failure_reason=outcome.failure_reason if status != "succeeded" else None,
        )

    def _to_running(self, run_id: str, status: RunStatus) -> RunStatus:
        current = status
        path: dict[RunStatus, RunStatus] = {
            "planned": "validated",
            "validated": "queued",
            "queued": "running",
        }
        while current in path:
            target = path[current]
            self.registry.transition(run_id, target, f"orchestrator advanced to {target}")
            current = target
        return current

    def execute_plan(
        self,
        plan: ExperimentPlan,
        executor: Executor,
        *,
        explicit_execution_opt_in: bool = False,
    ) -> list[ExecutionReceipt]:
        # Reject an unapproved executor first, independent of execution opt-in flags.
        # This makes policy violations deterministic and guarantees no executor call.
        if executor.kind not in self.config.allowed_executor_kinds:
            raise OrchestrationError(
                "executor_not_allowed",
                f"executor kind {executor.kind!r} is not allowlisted",
            )
        if not explicit_execution_opt_in or not self.config.allow_execution:
            raise OrchestrationError(
                "execution_not_opted_in",
                "execution requires both allow_execution=true in trusted config and explicit_execution_opt_in=True",
            )
        if plan.automatic_execution is not False or plan.status != "planned":
            raise OrchestrationError(
                "unsafe_plan", "only non-automatic, planned experiments are accepted"
            )
        if len(plan.runs) > self.config.max_runs_per_invocation:
            raise OrchestrationError("run_limit_exceeded", "plan exceeds max_runs_per_invocation")
        if executor.kind == "nebius_jobs" and not self.config.allow_remote_execution:
            raise OrchestrationError(
                "remote_execution_disabled", "remote execution is disabled in trusted config"
            )

        self.registry.register_plan(plan)
        existing_receipts = self.journal.read()
        receipt_by_run = {item.run_id: item for item in existing_receipts}
        by_run = {item.run_id: item for item in plan.runs}
        if len(by_run) != len(plan.runs):
            raise OrchestrationError("duplicate_run_ids", "plan contains duplicate run IDs")
        produced: list[ExecutionReceipt] = []

        for run in plan.runs:
            digest = request_hash(run)
            prior_receipt = receipt_by_run.get(run.run_id)
            current = self.registry.snapshot.runs[run.run_id]
            if prior_receipt is not None:
                if prior_receipt.plan_id != plan.plan_id or prior_receipt.request_sha256 != digest:
                    raise OrchestrationError(
                        "receipt_conflict", f"receipt identity differs for {run.run_id}"
                    )
                current_status = self._to_running(run.run_id, current.status)
                if current_status == "running":
                    target = prior_receipt.status
                    self.registry.transition(
                        run.run_id,
                        target,
                        f"recovered from durable receipt {prior_receipt.receipt_id}",
                    )
                elif current_status != prior_receipt.status:
                    raise OrchestrationError(
                        "registry_receipt_mismatch",
                        f"registry status and durable receipt disagree for {run.run_id}",
                    )
                continue

            if current.status in {"succeeded", "failed", "timed_out", "incomplete", "invalidated"}:
                # A terminal state without a receipt is preserved; it is never rerun implicitly.
                continue
            if current.status == "running":
                now = datetime.now(UTC)
                request = ExecutionRequest(run=run, request_sha256=digest, created_at_utc=now)
                outcome = ExecutionOutcome(
                    status="incomplete",
                    failure_reason="process restarted while run was running; no durable receipt exists",
                )
                receipt = self._make_receipt(
                    run, digest, executor.kind, "incomplete", now, now, outcome
                )
                self.journal.append(receipt)
                self.registry.transition(
                    run.run_id,
                    "incomplete",
                    "orchestrator recovered interrupted execution without a durable receipt",
                )
                produced.append(receipt)
                continue

            self._to_running(run.run_id, current.status)
            started = datetime.now(UTC)
            request = ExecutionRequest(run=run, request_sha256=digest, created_at_utc=started)
            try:
                outcome = ExecutionOutcome.model_validate(executor.execute(request))
            except TimeoutError:
                outcome = ExecutionOutcome(status="timed_out", failure_reason="executor timeout")
            except Exception as exc:
                # Do not copy arbitrary exception messages into durable logs; they can contain secrets.
                outcome = ExecutionOutcome(
                    status="failed", failure_reason=f"executor error: {type(exc).__name__}"
                )
            ended = datetime.now(UTC)
            receipt = self._make_receipt(
                run, digest, executor.kind, outcome.status, started, ended, outcome
            )
            self.journal.append(receipt)
            self.registry.transition(
                run.run_id,
                outcome.status,
                outcome.failure_reason or f"executor completed; receipt {receipt.receipt_id}",
            )
            produced.append(receipt)
        return produced


def load_orchestration_config(path: str | Path) -> OrchestrationConfig:
    return OrchestrationConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def preflight_plan(plan_path: str | Path, config: OrchestrationConfig) -> dict[str, object]:
    """Validate an existing plan without registering, executing or networking."""
    try:
        raw = Path(plan_path).read_bytes()
        if len(raw) > 1_048_576:
            raise OrchestrationError("plan_too_large", "plan JSON exceeds 1 MiB limit")
        plan = ExperimentPlan.model_validate_json(raw)
    except OrchestrationError:
        raise
    except Exception as exc:
        raise OrchestrationError(
            "plan_invalid", f"could not validate plan: {type(exc).__name__}"
        ) from None
    if len(plan.runs) > config.max_runs_per_invocation:
        raise OrchestrationError("run_limit_exceeded", "plan exceeds max_runs_per_invocation")
    return {
        "schema_version": "1.0.0",
        "mode": "preflight_only",
        "plan_id": plan.plan_id,
        "run_count": len(plan.runs),
        "executor_calls": 0,
        "network_calls": 0,
        "cloud_jobs_submitted": 0,
        "evidence_status": "not_executed_not_evidence",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight RESILIANT-Z orchestration without executing runs."
    )
    parser.add_argument("--plan", default="artifacts/session8/experiment-plan.json")
    parser.add_argument("--config", default="configs/orchestration/session9_config.v1.json")
    args = parser.parse_args(argv)
    try:
        config = load_orchestration_config(args.config)
        summary = preflight_plan(args.plan, config)
    except (OSError, OrchestrationError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("Preflight only: no executor, simulator, network endpoint or cloud job was invoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
