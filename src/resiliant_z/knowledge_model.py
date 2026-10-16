"""Versioned, append-only RESILIANT-Z knowledge and policy-proposal ledger.

The ledger records independently validated findings within an explicit scope. Local
synthetic/surrogate evidence is never marked operationally eligible. Policy proposals
are declarative and require human approval; this module never applies a policy.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Literal["1.0.0"]
ValidationStatus = Literal["validated", "rejected", "inconclusive", "invalidated"]
LifecycleStatus = Literal[
    "validated_scoped", "rejected", "inconclusive", "invalidated", "rolled_back"
]
OperationalGate = Literal["blocked", "eligible_for_policy_review"]
PolicyProposalStatus = Literal[
    "approval_required",
    "blocked_lifecycle",
    "blocked_operational_provenance",
    "blocked_no_policy_rule",
    "blocked_effect_gate",
    "blocked_out_of_bounds",
]
NonBlank = Annotated[str, Field(min_length=1, max_length=512)]
MAX_CANDIDATE_REPORT_BYTES = 8_388_608
MAX_VALIDATION_REPORT_BYTES = 16_777_216
MAX_LEDGER_BYTES = 33_554_432
MAX_LEDGER_LINE_BYTES = 1_048_576
MAX_PROPOSAL_BYTES = 2_097_152


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_bounded(path: str | Path, limit: int, label: str) -> bytes:
    source = Path(path)
    if source.is_symlink():
        raise KnowledgeError(f"{label}_symlink", f"refusing to read symlink: {source}")
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise KnowledgeError(
            f"{label}_read_error", f"could not read {label}: {type(exc).__name__}"
        ) from None
    if len(payload) > limit:
        raise KnowledgeError(f"{label}_too_large", f"{label} exceeds the configured byte limit")
    return payload


class KnowledgeError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class FactorRange(StrictModel):
    minimum_observed: float = Field(allow_inf_nan=False)
    maximum_observed: float = Field(allow_inf_nan=False)
    unit: NonBlank
    calibration_status: Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]

    @model_validator(mode="after")
    def ordered(self) -> FactorRange:
        if self.minimum_observed >= self.maximum_observed:
            raise ValueError("factor minimum_observed must be less than maximum_observed")
        return self


class CandidateProjection(BaseModel):
    """Fields consumed from a Session 11 report; unknown future fields are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    candidate_id: str = Field(pattern=r"^cand-[0-9a-f]{24}$")
    spec_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    candidate_kind: Literal["main_effect", "interaction"]
    variable_ids: list[str] = Field(min_length=1, max_length=2)
    target_metric: str = Field(min_length=1, max_length=128)
    target_unit: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: str = Field(min_length=1, max_length=128)
    evidence_label: str = Field(min_length=1, max_length=256)
    model_version: str = Field(min_length=1, max_length=128)
    estimated_effect: float | None = Field(default=None, allow_inf_nan=False)
    effect_direction: Literal[
        "increase", "decrease", "positive_interaction", "negative_interaction", "unclear"
    ]
    factor_ranges: dict[str, FactorRange]
    evidence_ids: list[str] = Field(max_length=500)
    selection_outcome: Literal["shortlisted", "not_shortlisted", "insufficient_evidence"]
    lifecycle_status: Literal["provisional"] = "provisional"


class CandidateReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: SchemaVersion = "1.0.0"
    batch_id: str = Field(pattern=r"^candbatch-[0-9a-f]{24}$")
    status: Literal["provisional_candidates_only"]
    config_id: str = Field(min_length=1, max_length=128)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str = Field(min_length=1, max_length=128)
    backend_id: str = Field(min_length=1, max_length=128)
    evidence_label: str = Field(min_length=1, max_length=256)
    target_metric: str = Field(min_length=1, max_length=128)
    target_unit: str = Field(min_length=1, max_length=128)
    candidates: list[CandidateProjection] = Field(max_length=25)

    @model_validator(mode="after")
    def unique_candidates(self) -> CandidateReport:
        candidate_ids = [item.candidate_id for item in self.candidates]
        spec_ids = [item.spec_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate report contains duplicate candidate_id values")
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("candidate report contains duplicate spec_id values")
        for candidate in self.candidates:
            if len(candidate.variable_ids) != len(set(candidate.variable_ids)):
                raise ValueError("candidate variable_ids must be unique")
            if set(candidate.factor_ranges) != set(candidate.variable_ids):
                raise ValueError("candidate factor_ranges must match variable_ids exactly")
        return self


class ValidationResultProjection(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    candidate_id: str | None
    spec_id: str = Field(min_length=1, max_length=128)
    status: ValidationStatus
    reason: str = Field(min_length=1, max_length=512)
    candidate_kind: Literal["main_effect", "interaction"] | None = None
    target_metric: str | None = None
    target_unit: str | None = None
    pair_count: int = Field(ge=0)
    mean_effect: float | None = Field(default=None, allow_inf_nan=False)
    sample_sd_effect: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    confidence_interval_95_low: float | None = Field(default=None, allow_inf_nan=False)
    confidence_interval_95_high: float | None = Field(default=None, allow_inf_nan=False)
    concordant_fraction: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    effect_retention_fraction: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    validated_scenarios: list[str] = Field(max_length=20)
    distinct_initial_states: int = Field(ge=0)
    distinct_task_patterns: int = Field(ge=0)
    distinct_workload_patterns: int = Field(ge=0)
    replicate_effects: list[float] = Field(max_length=100)
    criteria_snapshot: dict[str, object]
    evidence_ids: list[str] = Field(max_length=1000)

    @model_validator(mode="after")
    def finite_effects(self) -> ValidationResultProjection:
        if any(not math.isfinite(value) for value in self.replicate_effects):
            raise ValueError("replicate effects must be finite")
        return self


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: SchemaVersion = "1.0.0"
    report_id: str = Field(pattern=r"^valreport-[0-9a-f]{24}$")
    status: Literal["independent_validation_report"]
    validation_config_id: str = Field(min_length=1, max_length=128)
    validation_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: list[ValidationResultProjection] = Field(max_length=25)
    overall_limitations: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_result_ids(self) -> ValidationReport:
        result_ids = [result.candidate_id for result in self.results]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("validation report contains duplicate candidate_id values")
        return self


class Condition(StrictModel):
    variable_id: NonBlank
    minimum_observed: float = Field(allow_inf_nan=False)
    maximum_observed: float = Field(allow_inf_nan=False)
    unit: NonBlank
    calibration_status: Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]


class RecordProvenance(StrictModel):
    discovery_batch_id: str
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_id: str
    validation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_config_id: str
    validation_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_id: str
    evidence_label: str
    model_version: str
    evidence_ids: list[str] = Field(max_length=1500)


class KnowledgeRecord(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    knowledge_id: str = Field(pattern=r"^know-[0-9a-f]{24}$")
    spec_id: str
    candidate_id: str = Field(pattern=r"^cand-[0-9a-f]{24}$")
    phenomenon: str
    candidate_kind: Literal["main_effect", "interaction"]
    lifecycle_status: LifecycleStatus
    validation_status: ValidationStatus
    validation_reason: str
    target_metric: str
    target_unit: str
    effect_direction: str
    mean_effect: float | None = Field(default=None, allow_inf_nan=False)
    sample_sd_effect: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    confidence_interval_95_low: float | None = Field(default=None, allow_inf_nan=False)
    confidence_interval_95_high: float | None = Field(default=None, allow_inf_nan=False)
    concordant_fraction: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    effect_retention_fraction: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    pair_count: int = Field(ge=0)
    conditions: list[Condition] = Field(min_length=1, max_length=2)
    validated_scenarios: list[str] = Field(max_length=20)
    distinct_initial_states: int = Field(ge=0)
    distinct_task_patterns: int = Field(ge=0)
    distinct_workload_patterns: int = Field(ge=0)
    operational_gate_status: OperationalGate
    operational_gate_reasons: list[str] = Field(max_length=20)
    provenance: RecordProvenance
    limitations: list[str] = Field(max_length=100)
    created_at_utc: str


class PolicyRule(StrictModel):
    spec_id: str = Field(min_length=1, max_length=128)
    target_metric: str = Field(min_length=1, max_length=128)
    expected_effect_sign: Literal["positive", "negative"]
    policy_parameter_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,95}$")
    update_direction: Literal["increase", "decrease"]
    step_size: float = Field(gt=0.0, le=1.0, allow_inf_nan=False)
    current_value: float = Field(allow_inf_nan=False)
    minimum_value: float = Field(allow_inf_nan=False)
    maximum_value: float = Field(allow_inf_nan=False)
    minimum_absolute_effect: float = Field(ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_bounds(self) -> PolicyRule:
        if self.minimum_value >= self.maximum_value:
            raise ValueError("minimum_value must be less than maximum_value")
        if not self.minimum_value <= self.current_value <= self.maximum_value:
            raise ValueError("current_value must lie inside parameter bounds")
        return self


class PolicyUpdateConfig(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    config_id: str = Field(min_length=1, max_length=128)
    allowed_operational_backends: list[str] = Field(min_length=1, max_length=20)
    allowed_operational_evidence_labels: list[str] = Field(min_length=1, max_length=20)
    minimum_validated_scenarios: int = Field(default=2, ge=1, le=20)
    require_calibrated_factors: Literal[True] = True
    require_human_approval: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    rules: list[PolicyRule] = Field(min_length=1, max_length=25)
    max_config_bytes: int = Field(default=1_048_576, ge=1024, le=8_388_608)

    @model_validator(mode="after")
    def unique_rules(self) -> PolicyUpdateConfig:
        ids = [rule.spec_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule spec_id values must be unique")
        for values, label in (
            (self.allowed_operational_backends, "allowed_operational_backends"),
            (self.allowed_operational_evidence_labels, "allowed_operational_evidence_labels"),
        ):
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"{label} must contain unique, non-blank values")
        return self


class PolicyProposal(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    proposal_id: str = Field(pattern=r"^polprop-[0-9a-f]{24}$")
    status: PolicyProposalStatus
    knowledge_id: str = Field(pattern=r"^know-[0-9a-f]{24}$")
    spec_id: str
    policy_parameter_id: str | None = None
    current_value: float | None = Field(default=None, allow_inf_nan=False)
    proposed_value: float | None = Field(default=None, allow_inf_nan=False)
    update_direction: Literal["increase", "decrease"] | None = None
    mean_effect: float | None = Field(default=None, allow_inf_nan=False)
    target_metric: str
    target_unit: str
    reason_codes: list[str] = Field(min_length=1, max_length=20)
    source_candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_validation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_config_id: str
    policy_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_approval_required: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    applied: Literal[False] = False
    created_at_utc: str


class LifecycleEvent(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    event_id: str = Field(pattern=r"^kwevent-[0-9a-f]{24}$")
    event_type: Literal["invalidate", "rollback"]
    knowledge_id: str = Field(pattern=r"^know-[0-9a-f]{24}$")
    reason: str = Field(min_length=1, max_length=512)
    restores_knowledge_id: str | None = Field(default=None, pattern=r"^know-[0-9a-f]{24}$")
    created_at_utc: str


class LedgerEntryView(StrictModel):
    entry_type: Literal["knowledge_record", "lifecycle_event"]
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record: KnowledgeRecord | None = None
    event: LifecycleEvent | None = None

    @model_validator(mode="after")
    def valid_variant(self) -> LedgerEntryView:
        if (self.entry_type == "knowledge_record") != (self.record is not None):
            raise ValueError("ledger knowledge_record entry must contain only record")
        if (self.entry_type == "lifecycle_event") != (self.event is not None):
            raise ValueError("ledger lifecycle_event entry must contain only event")
        return self


def _ledger_payload(entry_type: str, value: KnowledgeRecord | LifecycleEvent) -> dict[str, object]:
    key = "record" if entry_type == "knowledge_record" else "event"
    return {"entry_type": entry_type, key: value.model_dump(mode="json")}


def _line_for(entry_type: str, value: KnowledgeRecord | LifecycleEvent) -> bytes:
    payload = _ledger_payload(entry_type, value)
    envelope = {**payload, "entry_sha256": _sha256_value(payload)}
    return _canonical_bytes(envelope) + b"\n"


def _parse_ledger_bytes(data: bytes) -> list[LedgerEntryView]:
    if len(data) > MAX_LEDGER_BYTES:
        raise KnowledgeError(
            "ledger_too_large", "knowledge ledger exceeds the configured byte limit"
        )
    entries: list[LedgerEntryView] = []
    records: dict[str, KnowledgeRecord] = {}
    event_ids: set[str] = set()
    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line) > MAX_LEDGER_LINE_BYTES:
            raise KnowledgeError(
                "ledger_line_too_large", f"ledger line {line_number} exceeds the byte limit"
            )
        try:
            raw = json.loads(line)
            claimed_hash = raw.get("entry_sha256")
            payload = {key: value for key, value in raw.items() if key != "entry_sha256"}
            if not isinstance(claimed_hash, str) or claimed_hash != _sha256_value(payload):
                raise KnowledgeError(
                    "ledger_integrity_error",
                    f"ledger line {line_number} failed SHA-256 verification",
                )
            entry = LedgerEntryView.model_validate(raw)
        except KnowledgeError:
            raise
        except Exception as exc:
            raise KnowledgeError(
                "ledger_parse_error", f"invalid ledger line {line_number}: {type(exc).__name__}"
            ) from None
        if entry.entry_type == "knowledge_record":
            assert entry.record is not None
            key = entry.record.knowledge_id
            if key in records:
                raise KnowledgeError(
                    "ledger_duplicate_record",
                    f"duplicate knowledge record id at line {line_number}",
                )
            records[key] = entry.record
        else:
            assert entry.event is not None
            if entry.event.event_id in event_ids:
                raise KnowledgeError(
                    "ledger_duplicate_event", f"duplicate lifecycle event id at line {line_number}"
                )
            if entry.event.knowledge_id not in records:
                raise KnowledgeError(
                    "ledger_event_orphan",
                    f"event at line {line_number} references an unknown record",
                )
            if (
                entry.event.restores_knowledge_id is not None
                and entry.event.restores_knowledge_id not in records
            ):
                raise KnowledgeError(
                    "ledger_restore_orphan",
                    f"event at line {line_number} restores an unknown record",
                )
            event_ids.add(entry.event.event_id)
        entries.append(entry)
    return entries


def load_ledger(path: str | Path) -> list[LedgerEntryView]:
    ledger_path = Path(path)
    if ledger_path.is_symlink():
        raise KnowledgeError("ledger_symlink", f"refusing to read symlink ledger: {ledger_path}")
    if not ledger_path.exists():
        return []
    try:
        fd = os.open(ledger_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise KnowledgeError(
            "ledger_read_error", f"could not open ledger: {type(exc).__name__}"
        ) from None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        chunks = bytearray()
        while True:
            chunk = os.read(fd, 1_048_576)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_LEDGER_BYTES:
                raise KnowledgeError(
                    "ledger_too_large", "knowledge ledger exceeds the configured byte limit"
                )
        return _parse_ledger_bytes(bytes(chunks))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _stable_record_payload(record: KnowledgeRecord) -> dict[str, object]:
    return record.model_dump(mode="json", exclude={"created_at_utc"})


def append_record(path: str | Path, record: KnowledgeRecord) -> Literal["added", "already_present"]:
    return _append_line(path, "knowledge_record", record)


def append_lifecycle_event(
    path: str | Path, event: LifecycleEvent
) -> Literal["added", "already_present"]:
    return _append_line(path, "lifecycle_event", event)


def _append_line(
    path: str | Path, entry_type: str, value: KnowledgeRecord | LifecycleEvent
) -> Literal["added", "already_present"]:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.is_symlink():
        raise KnowledgeError("ledger_symlink", f"refusing to write symlink ledger: {ledger_path}")
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(ledger_path, flags, 0o600)
    except OSError as exc:
        raise KnowledgeError(
            "ledger_open_error", f"could not safely open ledger: {type(exc).__name__}"
        ) from None
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.lseek(fd, 0, os.SEEK_SET)
        existing = bytearray()
        while True:
            chunk = os.read(fd, 1_048_576)
            if not chunk:
                break
            existing.extend(chunk)
            if len(existing) > MAX_LEDGER_BYTES:
                raise KnowledgeError(
                    "ledger_too_large", "knowledge ledger exceeds the configured byte limit"
                )
        entries = _parse_ledger_bytes(bytes(existing))
        if entry_type == "knowledge_record":
            assert isinstance(value, KnowledgeRecord)
            for entry in entries:
                if entry.record and entry.record.knowledge_id == value.knowledge_id:
                    if _stable_record_payload(entry.record) == _stable_record_payload(value):
                        return "already_present"
                    raise KnowledgeError(
                        "knowledge_id_conflict",
                        "knowledge id exists with different immutable content",
                    )
        else:
            assert isinstance(value, LifecycleEvent)
            for entry in entries:
                if entry.event and entry.event.event_id == value.event_id:
                    stable_old = entry.event.model_dump(mode="json", exclude={"created_at_utc"})
                    stable_new = value.model_dump(mode="json", exclude={"created_at_utc"})
                    if stable_old == stable_new:
                        return "already_present"
                    raise KnowledgeError(
                        "event_id_conflict", "lifecycle event id exists with different content"
                    )
            records = {e.record.knowledge_id: e.record for e in entries if e.record}
            if value.knowledge_id not in records:
                raise KnowledgeError(
                    "unknown_knowledge_id", "lifecycle event references a record not in this ledger"
                )
            if value.restores_knowledge_id is not None:
                if value.restores_knowledge_id not in records:
                    raise KnowledgeError(
                        "unknown_restore_id", "rollback restore target is not present in the ledger"
                    )
                if (
                    records[value.restores_knowledge_id].spec_id
                    != records[value.knowledge_id].spec_id
                ):
                    raise KnowledgeError(
                        "rollback_scope_mismatch",
                        "rollback restore target must have the same spec_id",
                    )
        line = _line_for(entry_type, value)
        if len(existing) + len(line) > MAX_LEDGER_BYTES:
            raise KnowledgeError("ledger_too_large", "append would exceed the ledger byte limit")
        os.lseek(fd, 0, os.SEEK_END)
        view = memoryview(line)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        return "added"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _parse_inputs(
    candidate_report_path: str | Path, validation_report_path: str | Path
) -> tuple[CandidateReport, ValidationReport, bytes, bytes]:
    candidate_bytes = _read_bounded(
        candidate_report_path, MAX_CANDIDATE_REPORT_BYTES, "candidate_report"
    )
    validation_bytes = _read_bounded(
        validation_report_path, MAX_VALIDATION_REPORT_BYTES, "validation_report"
    )
    try:
        candidate_raw = json.loads(candidate_bytes)
        validation_raw = json.loads(validation_bytes)
        candidates = CandidateReport.model_validate(candidate_raw)
        validation = ValidationReport.model_validate(validation_raw)
    except Exception as exc:
        raise KnowledgeError(
            "input_contract_error",
            f"candidate/validation report failed contract checks: {type(exc).__name__}",
        ) from None
    report_identity_payload = dict(validation_raw)
    report_identity_payload.pop("report_id", None)
    report_identity_payload.pop("status", None)
    expected_report_id = "valreport-" + _sha256_value(report_identity_payload)[:24]
    if validation.report_id != expected_report_id:
        raise KnowledgeError(
            "validation_report_integrity_error",
            "validation report ID does not match its canonical contents",
        )
    if validation.candidate_report_sha256 != _sha256_bytes(candidate_bytes):
        raise KnowledgeError(
            "candidate_report_hash_mismatch",
            "validation report does not reference these exact candidate-report bytes",
        )
    candidate_ids = {candidate.candidate_id for candidate in candidates.candidates}
    for result in validation.results:
        if result.candidate_id is None or result.candidate_id not in candidate_ids:
            raise KnowledgeError(
                "candidate_link_missing",
                f"validation result {result.spec_id!r} does not link to an input candidate",
            )
        candidate = next(
            item for item in candidates.candidates if item.candidate_id == result.candidate_id
        )
        if candidate.spec_id != result.spec_id:
            raise KnowledgeError(
                "candidate_spec_mismatch",
                f"candidate {candidate.candidate_id} is linked to a different spec_id",
            )
        if result.candidate_kind is not None and result.candidate_kind != candidate.candidate_kind:
            raise KnowledgeError(
                "candidate_kind_mismatch",
                f"candidate {candidate.candidate_id} has a different candidate_kind",
            )
        if result.target_metric is not None and result.target_metric != candidate.target_metric:
            raise KnowledgeError(
                "candidate_metric_mismatch",
                f"candidate {candidate.candidate_id} has a different target metric",
            )
        if result.target_unit is not None and result.target_unit != candidate.target_unit:
            raise KnowledgeError(
                "candidate_unit_mismatch",
                f"candidate {candidate.candidate_id} has a different target unit",
            )
        if result.status == "validated" and not result.validated_scenarios:
            raise KnowledgeError(
                "validated_context_missing", "validated result must include validation scenarios"
            )
        if result.status == "validated" and candidate.selection_outcome != "shortlisted":
            raise KnowledgeError(
                "invalid_promotion_path",
                "a candidate not shortlisted in discovery cannot be validated for knowledge ingestion",
            )
    return candidates, validation, candidate_bytes, validation_bytes


def load_policy_config(path: str | Path) -> tuple[PolicyUpdateConfig, bytes]:
    raw = _read_bounded(path, 8_388_608, "policy_config")
    try:
        config = PolicyUpdateConfig.model_validate_json(raw)
    except Exception as exc:
        raise KnowledgeError(
            "policy_config_invalid",
            f"policy-update config failed contract checks: {type(exc).__name__}",
        ) from None
    if len(raw) > config.max_config_bytes:
        raise KnowledgeError(
            "policy_config_too_large", "policy-update config exceeds its declared max_config_bytes"
        )
    return config, raw


def _operational_gate_reasons(
    candidate: CandidateProjection, result: ValidationResultProjection, config: PolicyUpdateConfig
) -> list[str]:
    reasons: list[str] = []
    if result.status != "validated":
        reasons.append("independent_validation_not_passed")
    if candidate.backend_id not in config.allowed_operational_backends:
        reasons.append("backend_not_in_operational_allowlist")
    if candidate.evidence_label not in config.allowed_operational_evidence_labels:
        reasons.append("evidence_label_not_in_operational_allowlist")
    if config.require_calibrated_factors and any(
        item.calibration_status != "calibrated" for item in candidate.factor_ranges.values()
    ):
        reasons.append("one_or_more_factors_not_calibrated")
    if len(set(result.validated_scenarios)) < config.minimum_validated_scenarios:
        reasons.append("insufficient_validated_scenario_diversity")
    if not result.evidence_ids:
        reasons.append("validated_evidence_links_missing")
    return reasons


def build_knowledge_records(
    candidate_report_path: str | Path,
    validation_report_path: str | Path,
    policy_config_path: str | Path,
    *,
    created_at_utc: str | None = None,
) -> list[KnowledgeRecord]:
    candidates_report, validation_report, candidate_bytes, validation_bytes = _parse_inputs(
        candidate_report_path, validation_report_path
    )
    policy_config, _policy_bytes = load_policy_config(policy_config_path)
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in candidates_report.candidates
    }
    created_at = created_at_utc or _now_utc()
    output: list[KnowledgeRecord] = []
    for result in validation_report.results:
        assert result.candidate_id is not None
        candidate = candidate_by_id[result.candidate_id]
        lifecycle_status: LifecycleStatus = (
            "validated_scoped" if result.status == "validated" else result.status
        )
        gate_reasons = _operational_gate_reasons(candidate, result, policy_config)
        gate_status: OperationalGate = (
            "eligible_for_policy_review"
            if lifecycle_status == "validated_scoped" and not gate_reasons
            else "blocked"
        )
        conditions = [
            Condition(
                variable_id=variable_id,
                minimum_observed=factor.minimum_observed,
                maximum_observed=factor.maximum_observed,
                unit=factor.unit,
                calibration_status=factor.calibration_status,
            )
            for variable_id, factor in sorted(candidate.factor_ranges.items())
        ]
        evidence_ids = sorted(set(candidate.evidence_ids) | set(result.evidence_ids))
        identity_payload = {
            "candidate_id": candidate.candidate_id,
            "spec_id": candidate.spec_id,
            "validation_report_id": validation_report.report_id,
            "candidate_report_sha256": _sha256_bytes(candidate_bytes),
            "validation_report_sha256": _sha256_bytes(validation_bytes),
            "validation_status": result.status,
        }
        knowledge_id = "know-" + _sha256_value(identity_payload)[:24]
        record = KnowledgeRecord(
            knowledge_id=knowledge_id,
            spec_id=candidate.spec_id,
            candidate_id=candidate.candidate_id,
            phenomenon=candidate.label,
            candidate_kind=candidate.candidate_kind,
            lifecycle_status=lifecycle_status,
            validation_status=result.status,
            validation_reason=result.reason,
            target_metric=result.target_metric or candidate.target_metric,
            target_unit=result.target_unit or candidate.target_unit,
            effect_direction=candidate.effect_direction,
            mean_effect=result.mean_effect,
            sample_sd_effect=result.sample_sd_effect,
            confidence_interval_95_low=result.confidence_interval_95_low,
            confidence_interval_95_high=result.confidence_interval_95_high,
            concordant_fraction=result.concordant_fraction,
            effect_retention_fraction=result.effect_retention_fraction,
            pair_count=result.pair_count,
            conditions=conditions,
            validated_scenarios=sorted(set(result.validated_scenarios)),
            distinct_initial_states=result.distinct_initial_states,
            distinct_task_patterns=result.distinct_task_patterns,
            distinct_workload_patterns=result.distinct_workload_patterns,
            operational_gate_status=gate_status,
            operational_gate_reasons=gate_reasons,
            provenance=RecordProvenance(
                discovery_batch_id=candidates_report.batch_id,
                candidate_report_sha256=_sha256_bytes(candidate_bytes),
                validation_report_id=validation_report.report_id,
                validation_report_sha256=_sha256_bytes(validation_bytes),
                validation_config_id=validation_report.validation_config_id,
                validation_config_sha256=validation_report.validation_config_sha256,
                observation_input_sha256=validation_report.observation_input_sha256,
                backend_id=candidate.backend_id,
                evidence_label=candidate.evidence_label,
                model_version=candidate.model_version,
                evidence_ids=evidence_ids,
            ),
            limitations=sorted(
                set(validation_report.overall_limitations)
                | {
                    "Knowledge status is scoped to the supplied backend, metric, context and validation design.",
                    "This ledger never makes a finding universally true or calibrated by implication.",
                    "Policy proposals are review artifacts only; no live policy is changed or executed.",
                }
            ),
            created_at_utc=created_at,
        )
        output.append(record)
    return output


def effective_status(record: KnowledgeRecord, entries: list[LedgerEntryView]) -> str:
    status: str = record.lifecycle_status
    own_events = [
        (index, entry.event)
        for index, entry in enumerate(entries)
        if entry.event and entry.event.knowledge_id == record.knowledge_id
    ]
    last_own_index = -1
    if own_events:
        last_own_index, latest = own_events[-1]
        assert latest is not None
        status = "invalidated" if latest.event_type == "invalidate" else "rolled_back"
    restore_events = [
        (index, entry.event)
        for index, entry in enumerate(entries)
        if entry.event
        and entry.event.event_type == "rollback"
        and entry.event.restores_knowledge_id == record.knowledge_id
    ]
    if restore_events:
        last_restore_index, _ = restore_events[-1]
        if last_restore_index > last_own_index and status != "invalidated":
            status = "restored"
    return status


def records_from_ledger(entries: list[LedgerEntryView]) -> list[tuple[KnowledgeRecord, str]]:
    records = [entry.record for entry in entries if entry.record is not None]
    return [(record, effective_status(record, entries)) for record in records if record is not None]


def create_lifecycle_event(
    entries: list[LedgerEntryView],
    knowledge_id: str,
    event_type: Literal["invalidate", "rollback"],
    reason: str,
    restores_knowledge_id: str | None = None,
    *,
    created_at_utc: str | None = None,
) -> LifecycleEvent:
    records = {entry.record.knowledge_id: entry.record for entry in entries if entry.record}
    if not reason.strip():
        raise KnowledgeError(
            "lifecycle_reason_required", "invalidation/rollback requires a non-empty reason"
        )
    if knowledge_id not in records:
        raise KnowledgeError(
            "unknown_knowledge_id", "knowledge record does not exist in this ledger"
        )
    current_statuses = {
        record.knowledge_id: status for record, status in records_from_ledger(entries)
    }
    if event_type == "rollback" and current_statuses.get(knowledge_id) == "invalidated":
        raise KnowledgeError(
            "invalidated_record_terminal", "an invalidated knowledge record cannot be rolled back"
        )
    if event_type == "rollback" and restores_knowledge_id:
        if restores_knowledge_id not in records:
            raise KnowledgeError(
                "unknown_restore_id", "rollback target record does not exist in this ledger"
            )
        if records[restores_knowledge_id].spec_id != records[knowledge_id].spec_id:
            raise KnowledgeError(
                "rollback_scope_mismatch", "rollback target must have the same spec_id"
            )
        if current_statuses.get(restores_knowledge_id) == "invalidated":
            raise KnowledgeError(
                "invalidated_restore_target", "an invalidated record cannot be restored"
            )
    if event_type == "invalidate" and restores_knowledge_id is not None:
        raise KnowledgeError(
            "unexpected_restore_id", "invalidation cannot carry restores_knowledge_id"
        )
    stable = {
        "event_type": event_type,
        "knowledge_id": knowledge_id,
        "reason": reason,
        "restores_knowledge_id": restores_knowledge_id,
    }
    event_id = "kwevent-" + _sha256_value(stable)[:24]
    return LifecycleEvent(
        event_id=event_id,
        event_type=event_type,
        knowledge_id=knowledge_id,
        reason=reason,
        restores_knowledge_id=restores_knowledge_id,
        created_at_utc=created_at_utc or _now_utc(),
    )


def _record_operational_gate_reasons(
    record: KnowledgeRecord, config: PolicyUpdateConfig
) -> list[str]:
    reasons: list[str] = []
    if record.validation_status != "validated" or record.lifecycle_status != "validated_scoped":
        reasons.append("knowledge_not_independently_validated")
    if record.provenance.backend_id not in config.allowed_operational_backends:
        reasons.append("backend_not_in_operational_allowlist")
    if record.provenance.evidence_label not in config.allowed_operational_evidence_labels:
        reasons.append("evidence_label_not_in_operational_allowlist")
    if config.require_calibrated_factors and any(
        condition.calibration_status != "calibrated" for condition in record.conditions
    ):
        reasons.append("one_or_more_factors_not_calibrated")
    if len(set(record.validated_scenarios)) < config.minimum_validated_scenarios:
        reasons.append("insufficient_validated_scenario_diversity")
    if not record.provenance.evidence_ids:
        reasons.append("validated_evidence_links_missing")
    return reasons


def build_policy_proposal(
    record: KnowledgeRecord,
    current_lifecycle_status: str,
    config: PolicyUpdateConfig,
    policy_config_bytes: bytes,
    *,
    created_at_utc: str | None = None,
) -> PolicyProposal:
    reason_codes: list[str] = []
    status: PolicyProposalStatus
    rule = next((item for item in config.rules if item.spec_id == record.spec_id), None)
    policy_parameter_id: str | None = None
    current_value: float | None = None
    proposed_value: float | None = None
    update_direction: Literal["increase", "decrease"] | None = None
    if (
        current_lifecycle_status not in {"validated_scoped", "restored"}
        or record.lifecycle_status != "validated_scoped"
        or record.validation_status != "validated"
    ):
        status = "blocked_lifecycle"
        reason_codes.append("knowledge_not_currently_validated")
    elif (
        record.operational_gate_status != "eligible_for_policy_review"
        or _record_operational_gate_reasons(record, config)
    ):
        status = "blocked_operational_provenance"
        reason_codes.extend(
            sorted(
                set(record.operational_gate_reasons)
                | set(_record_operational_gate_reasons(record, config))
                | {"operational_provenance_not_eligible"}
            )
        )
    elif rule is None:
        status = "blocked_no_policy_rule"
        reason_codes.append("no_predeclared_rule_for_spec_id")
    elif rule.target_metric != record.target_metric:
        status = "blocked_no_policy_rule"
        reason_codes.append("policy_rule_metric_mismatch")
    elif (
        record.mean_effect is None
        or abs(record.mean_effect) < rule.minimum_absolute_effect
        or (record.mean_effect == 0.0)
        or ((record.mean_effect > 0.0) != (rule.expected_effect_sign == "positive"))
    ):
        status = "blocked_effect_gate"
        reason_codes.append("validated_effect_does_not_meet_predeclared_policy_gate")
    else:
        delta = rule.step_size if rule.update_direction == "increase" else -rule.step_size
        proposed = rule.current_value + delta
        policy_parameter_id = rule.policy_parameter_id
        current_value = rule.current_value
        update_direction = rule.update_direction
        if proposed < rule.minimum_value or proposed > rule.maximum_value:
            status = "blocked_out_of_bounds"
            reason_codes.append("proposed_step_exceeds_predeclared_parameter_bounds")
        else:
            status = "approval_required"
            proposed_value = proposed
            reason_codes.append("human_review_and_approval_required")
    proposal_body = {
        "knowledge_id": record.knowledge_id,
        "spec_id": record.spec_id,
        "policy_config_sha256": _sha256_bytes(policy_config_bytes),
        "status": status,
        "policy_parameter_id": policy_parameter_id,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "update_direction": update_direction,
        "reasons": reason_codes,
    }
    return PolicyProposal(
        proposal_id="polprop-" + _sha256_value(proposal_body)[:24],
        status=status,
        knowledge_id=record.knowledge_id,
        spec_id=record.spec_id,
        policy_parameter_id=policy_parameter_id,
        current_value=current_value,
        proposed_value=proposed_value,
        update_direction=update_direction,
        mean_effect=record.mean_effect,
        target_metric=record.target_metric,
        target_unit=record.target_unit,
        reason_codes=reason_codes,
        source_candidate_report_sha256=record.provenance.candidate_report_sha256,
        source_validation_report_sha256=record.provenance.validation_report_sha256,
        policy_config_id=config.config_id,
        policy_config_sha256=_sha256_bytes(policy_config_bytes),
        created_at_utc=created_at_utc or _now_utc(),
    )


def write_json_no_clobber(
    value: BaseModel, path: str | Path, max_bytes: int = MAX_PROPOSAL_BYTES
) -> str:
    destination = Path(path)
    if destination.is_symlink():
        raise KnowledgeError("output_symlink", f"refusing to write through symlink: {destination}")
    payload = (
        json.dumps(
            value.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > max_bytes:
        raise KnowledgeError("output_too_large", "output exceeds the configured byte limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            try:
                existing = destination.read_bytes()
            except OSError:
                raise KnowledgeError(
                    "output_conflict", "existing output could not be read safely"
                ) from None
            if existing != payload:
                raise KnowledgeError(
                    "output_conflict",
                    f"refusing to overwrite existing output with different bytes: {destination}",
                ) from None
        os.chmod(destination, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return _sha256_bytes(payload)


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist scoped knowledge and emit approval-gated policy proposals; never applies policy."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="ingest Session 12 independent-validation results")
    ingest.add_argument("--candidate-report", required=True)
    ingest.add_argument("--validation-report", required=True)
    ingest.add_argument("--policy-config", required=True)
    ingest.add_argument("--ledger", required=True)
    listing = sub.add_parser(
        "list", help="list immutable knowledge records and effective lifecycle states"
    )
    listing.add_argument("--ledger", required=True)
    compare = sub.add_parser("compare", help="compare the effects recorded for two knowledge IDs")
    compare.add_argument("--ledger", required=True)
    compare.add_argument("--knowledge-ids", nargs=2, required=True)
    invalidate = sub.add_parser(
        "invalidate", help="append an invalidation event without mutating records"
    )
    invalidate.add_argument("--ledger", required=True)
    invalidate.add_argument("--knowledge-id", required=True)
    invalidate.add_argument("--reason", required=True)
    rollback = sub.add_parser(
        "rollback", help="append a rollback lifecycle event (does not modify live policy)"
    )
    rollback.add_argument("--ledger", required=True)
    rollback.add_argument("--knowledge-id", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--restores-knowledge-id")
    propose = sub.add_parser(
        "propose-policy", help="write a bounded, approval-required policy proposal"
    )
    propose.add_argument("--ledger", required=True)
    propose.add_argument("--knowledge-id", required=True)
    propose.add_argument("--policy-config", required=True)
    propose.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            records = build_knowledge_records(
                args.candidate_report, args.validation_report, args.policy_config
            )
            for record in records:
                outcome = append_record(args.ledger, record)
                print(
                    f"{outcome}: {record.knowledge_id} spec={record.spec_id} lifecycle={record.lifecycle_status} operational_gate={record.operational_gate_status}"
                )
            print(
                f"Knowledge records processed: {len(records)}. This does not apply a fleet policy."
            )
            return 0
        if args.command == "list":
            entries = load_ledger(args.ledger)
            rows = [
                {
                    "knowledge_id": record.knowledge_id,
                    "spec_id": record.spec_id,
                    "lifecycle_status": record.lifecycle_status,
                    "effective_status": status,
                    "operational_gate_status": record.operational_gate_status,
                    "mean_effect": record.mean_effect,
                    "metric": record.target_metric,
                    "unit": record.target_unit,
                }
                for record, status in records_from_ledger(entries)
            ]
            print(json.dumps(rows, indent=2, sort_keys=True))
            return 0
        if args.command == "compare":
            entries = load_ledger(args.ledger)
            records = {
                record.knowledge_id: (record, status)
                for record, status in records_from_ledger(entries)
            }
            left_id, right_id = args.knowledge_ids
            if left_id not in records or right_id not in records:
                raise KnowledgeError(
                    "unknown_knowledge_id", "both comparison IDs must exist in ledger"
                )
            left, left_status = records[left_id]
            right, right_status = records[right_id]
            if (left.target_metric, left.target_unit) != (right.target_metric, right.target_unit):
                raise KnowledgeError(
                    "incomparable_effects", "records use different metrics or units"
                )
            print(
                json.dumps(
                    {
                        "metric": left.target_metric,
                        "unit": left.target_unit,
                        "left": {
                            "knowledge_id": left_id,
                            "mean_effect": left.mean_effect,
                            "status": left_status,
                        },
                        "right": {
                            "knowledge_id": right_id,
                            "mean_effect": right.mean_effect,
                            "status": right_status,
                        },
                        "difference_left_minus_right": None
                        if left.mean_effect is None or right.mean_effect is None
                        else left.mean_effect - right.mean_effect,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command in {"invalidate", "rollback"}:
            entries = load_ledger(args.ledger)
            event = create_lifecycle_event(
                entries,
                args.knowledge_id,
                args.command,
                args.reason,
                getattr(args, "restores_knowledge_id", None),
            )
            print(
                f"{append_lifecycle_event(args.ledger, event)} lifecycle event {event.event_id}; records remain immutable."
            )
            return 0
        if args.command == "propose-policy":
            entries = load_ledger(args.ledger)
            lookup = {
                record.knowledge_id: (record, status)
                for record, status in records_from_ledger(entries)
            }
            if args.knowledge_id not in lookup:
                raise KnowledgeError(
                    "unknown_knowledge_id", "knowledge ID does not exist in ledger"
                )
            record, current_status = lookup[args.knowledge_id]
            config, config_bytes = load_policy_config(args.policy_config)
            proposal = build_policy_proposal(record, current_status, config, config_bytes)
            digest = write_json_no_clobber(proposal, args.output)
            print(f"Policy proposal: {proposal.proposal_id}")
            print(f"Status: {proposal.status}")
            print(f"SHA-256: {digest}")
            print("automatic_application_allowed=false; applied=false; no live policy was changed.")
            return 0
    except KnowledgeError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2
    except Exception as exc:
        print(f"ERROR: operation failed safely ({type(exc).__name__})", flush=True)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
