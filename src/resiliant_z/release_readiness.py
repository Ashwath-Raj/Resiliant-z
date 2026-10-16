"""Offline release audit and Isaac Sim handoff contracts for RESILIANT-Z.

This module does not import Isaac Sim, inspect hardware automatically, contact a
network endpoint, launch a simulator, submit cloud work, or modify policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0.0"

# Mandatory files are embedded in code so a user-supplied config cannot weaken
# the software gate by deleting checks. Config may only add more required files.
CORE_REQUIRED_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    "README.md",
    "src/resiliant_z/models.py",
    "src/resiliant_z/scenario_spec.py",
    "src/resiliant_z/simulation/base.py",
    "src/resiliant_z/simulation/backend_contract.py",
    "src/resiliant_z/simulation/discrete_event.py",
    "src/resiliant_z/simulation/isaac_csv.py",
    "src/resiliant_z/telemetry.py",
    "src/resiliant_z/telemetry_io.py",
    "src/resiliant_z/baseline.py",
    "src/resiliant_z/gap_detector.py",
    "src/resiliant_z/hypothesis_provider.py",
    "src/resiliant_z/experiment_compiler.py",
    "src/resiliant_z/experiment_planner.py",
    "src/resiliant_z/orchestration.py",
    "src/resiliant_z/evidence/session10.py",
    "src/resiliant_z/candidate_discovery.py",
    "src/resiliant_z/independent_validation.py",
    "src/resiliant_z/knowledge_model.py",
    "src/resiliant_z/policy_replay.py",
    "src/resiliant_z/stress_test.py",
    "src/resiliant_z/release_readiness.py",
    "tests/test_contracts.py",
    "tests/test_stress_test.py",
    "tests/test_session2_scenario_contract.py",
    "tests/test_session3_telemetry.py",
    "tests/test_session4_baseline.py",
    "tests/test_session5_gap_detector.py",
    "tests/test_session6_hypothesis_provider.py",
    "tests/test_session7_experiment_compiler.py",
    "tests/test_session8_experiment_planner.py",
    "tests/test_session9_orchestration.py",
    "tests/test_session10_evidence.py",
    "tests/test_session11_candidate_discovery.py",
    "tests/test_session12_independent_validation.py",
    "tests/test_session13_knowledge_model.py",
    "tests/test_session14_policy_replay.py",
    "tests/test_session15_release_readiness.py",
    "configs/warehouse_scenario.example.v1.json",
    "docs/session-2/SESSION_2_IMPLEMENTATION.md",
    "docs/session-3/SESSION_3_IMPLEMENTATION.md",
    "docs/session-4/SESSION_4_IMPLEMENTATION.md",
    "docs/session-5/SESSION_5_IMPLEMENTATION.md",
    "docs/session-6/SESSION_6_IMPLEMENTATION.md",
    "docs/session-7/SESSION_7_IMPLEMENTATION.md",
    "docs/session-8/SESSION_8_IMPLEMENTATION.md",
    "docs/session-9/SESSION_9_IMPLEMENTATION.md",
    "docs/session-10/SESSION_10_IMPLEMENTATION.md",
    "docs/session-11/SESSION_11_IMPLEMENTATION.md",
    "docs/session-12/SESSION_12_IMPLEMENTATION.md",
    "docs/session-13/SESSION_13_IMPLEMENTATION.md",
    "docs/session-14/SESSION_14_IMPLEMENTATION.md",
    "docs/session-15/SESSION_15_IMPLEMENTATION.md",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _is_safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


class ReleaseReadinessError(ValueError):
    """Raised when audit inputs or handoff artifacts violate the contract."""


class ReleaseAuditConfig(BaseModel):
    """Conservative software-audit configuration; core checks cannot be removed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    additional_required_paths: tuple[str, ...] = ()
    scan_json_directories: tuple[str, ...] = ("configs", "docs")
    max_json_file_bytes: int = Field(default=5_000_000, ge=1_024, le=25_000_000)
    require_clean_tracked_diff: bool = False

    @model_validator(mode="after")
    def validate_paths(self) -> ReleaseAuditConfig:
        for value in (*self.additional_required_paths, *self.scan_json_directories):
            if not _is_safe_relative_path(value):
                raise ValueError(f"path must be a safe repository-relative path: {value!r}")
        if len(set(self.additional_required_paths)) != len(self.additional_required_paths):
            raise ValueError("additional_required_paths must be unique")
        return self


class AuditCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1, max_length=100)
    category: Literal["required_file", "json_syntax", "git_state", "safety_boundary"]
    status: Literal["passed", "warning", "blocked", "not_assessed"]
    message: str = Field(min_length=1, max_length=1_000)
    evidence_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ReleaseAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    audit_id: str = Field(pattern=r"^audit-[0-9a-f]{20}$")
    generated_at_utc: datetime
    project_root_label: str = Field(min_length=1, max_length=256)
    git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    software_gate: Literal["pass_for_handoff_review", "blocked"]
    host_gate: Literal["not_assessed", "blocked", "attested_meets_configured_thresholds"] = (
        "not_assessed"
    )
    checks: tuple[AuditCheck, ...]
    scanned_json_files: int = Field(ge=0)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    isaac_sim_launched: Literal[False] = False
    cloud_job_launched: Literal[False] = False
    live_policy_modified: Literal[False] = False
    execution_authorized: Literal[False] = False

    @property
    def blockers(self) -> tuple[AuditCheck, ...]:
        return tuple(check for check in self.checks if check.status == "blocked")


class IsaacAdapterContract(BaseModel):
    """Versioned contract only; this is not a working Isaac Sim adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    adapter_id: Literal["resiliant-z.isaac-adapter-contract"] = "resiliant-z.isaac-adapter-contract"
    adapter_contract_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scenario_schema_versions: tuple[str, ...] = ("1.0.0",)
    telemetry_schema_versions: tuple[str, ...] = ("1.0.0",)
    required_capabilities: tuple[str, ...] = (
        "deterministic_seed_control",
        "scenario_reset",
        "timestamped_metrics",
        "run_metadata_export",
        "clean_shutdown",
    )
    implementation_status: Literal["contract_only_not_implemented"] = (
        "contract_only_not_implemented"
    )
    adapter_runtime_status: Literal["not_started"] = "not_started"
    automatic_execution_allowed: Literal[False] = False
    host_launch_authorized: Literal[False] = False


class HostReadinessRequirements(BaseModel):
    """Configurable minimums. Verify these against the chosen official release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    target_simulator_release: str = Field(min_length=1, max_length=80)
    minimum_system_ram_gb: float = Field(gt=0, le=2_048)
    minimum_gpu_vram_gb: float = Field(gt=0, le=512)
    minimum_free_disk_gb: float = Field(gt=0, le=100_000)
    require_driver_compatibility_confirmation: bool = True
    require_os_compatibility_confirmation: bool = True
    require_assets_checksum_confirmation: bool = True

    @model_validator(mode="after")
    def reject_placeholder_release(self) -> HostReadinessRequirements:
        if self.target_simulator_release.strip().upper() in {
            "VERIFY",
            "TBD",
            "VERIFY_FOR_TARGET_RELEASE",
            "REPLACE_WITH_EXACT_RELEASE_AFTER_OFFICIAL_REQUIREMENTS_REVIEW",
        }:
            raise ValueError(
                "target_simulator_release must be the exact release selected for evaluation"
            )
        return self


class HostReadinessAttestation(BaseModel):
    """Operator-supplied host facts; the auditor does not autodetect or verify hardware."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    host_label: str = Field(min_length=1, max_length=120)
    checked_at_utc: datetime
    checked_by: str = Field(min_length=1, max_length=120)
    os_release: str = Field(min_length=1, max_length=200)
    os_compatibility_confirmed: bool
    gpu_model: str = Field(min_length=1, max_length=200)
    gpu_vram_gb: float = Field(gt=0, le=512)
    driver_version: str = Field(min_length=1, max_length=120)
    driver_compatibility_confirmed: bool
    system_ram_gb: float = Field(gt=0, le=2_048)
    free_disk_gb: float = Field(gt=0, le=100_000)
    simulator_release: str = Field(min_length=1, max_length=80)
    official_requirements_reviewed: bool
    asset_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    assets_checksums_confirmed: bool
    confirmation_is_operator_attestation: Literal[True] = True

    @model_validator(mode="after")
    def require_timezone(self) -> HostReadinessAttestation:
        if self.checked_at_utc.tzinfo is None or self.checked_at_utc.utcoffset() is None:
            raise ValueError("checked_at_utc must include a timezone")
        return self


class HostReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    status: Literal["attested_meets_configured_thresholds", "blocked"]
    checks: tuple[AuditCheck, ...]
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_hardware_measurement_performed: Literal[False] = False
    simulator_launched: Literal[False] = False
    execution_authorized: Literal[False] = False


class HandoffManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    handoff_id: str = Field(pattern=r"^handoff-[0-9a-f]{20}$")
    generated_at_utc: datetime
    software_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    adapter_contract: IsaacAdapterContract
    handoff_status: Literal["software_contracts_prepared_host_not_assessed", "blocked"]
    required_operator_actions: tuple[str, ...]
    isaac_sim_launched: Literal[False] = False
    cloud_job_launched: Literal[False] = False
    live_policy_modified: Literal[False] = False
    host_launch_authorized: Literal[False] = False


def _git_commit(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if len(value) == 40 and all(ch in "0123456789abcdef" for ch in value) else None


def _audit_digest_payload(
    checks: tuple[AuditCheck, ...],
    generated_at_utc: datetime,
    git_commit: str | None,
    scanned_json_files: int,
    software_gate: str,
) -> bytes:
    return _canonical_json_bytes(
        {
            "checks": [check.model_dump(mode="json") for check in checks],
            "generated_at_utc": generated_at_utc.isoformat(),
            "git_commit": git_commit,
            "scanned_json_files": scanned_json_files,
            "software_gate": software_gate,
            "schema_version": SCHEMA_VERSION,
        }
    )


def audit_project(
    project_root: str | Path,
    config: ReleaseAuditConfig | None = None,
) -> ReleaseAuditReport:
    """Audit repository structure and JSON/JSONL syntax without executing project code."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ReleaseReadinessError(f"project root is not a directory: {root}")
    cfg = config or ReleaseAuditConfig()
    checks: list[AuditCheck] = []

    for relative in (*CORE_REQUIRED_PATHS, *cfg.additional_required_paths):
        target = root / relative
        safe = _is_safe_relative_path(relative)
        exists = safe and target.is_file() and not target.is_symlink()
        data_hash: str | None = None
        if exists:
            try:
                data_hash = _sha256_bytes(target.read_bytes())
            except OSError:
                exists = False
        checks.append(
            AuditCheck(
                check_id=f"required:{relative}",
                category="required_file",
                status="passed" if exists else "blocked",
                message="required file exists and is readable"
                if exists
                else "required file is missing, unreadable, symlinked, or unsafe",
                evidence_path=relative,
                sha256=data_hash,
            )
        )

    json_count = 0
    for directory in cfg.scan_json_directories:
        base = root / directory
        if not base.exists():
            checks.append(
                AuditCheck(
                    check_id=f"json-scan-directory:{directory}",
                    category="json_syntax",
                    status="blocked",
                    message="configured JSON scan directory is missing",
                    evidence_path=directory,
                )
            )
            continue
        if not base.is_dir() or base.is_symlink():
            checks.append(
                AuditCheck(
                    check_id=f"json-scan-directory:{directory}",
                    category="json_syntax",
                    status="blocked",
                    message="configured JSON scan target is not a regular directory",
                    evidence_path=directory,
                )
            )
            continue
        for candidate in sorted(base.rglob("*")):
            if any(
                part
                in {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
                for part in candidate.parts
            ):
                continue
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                checks.append(
                    AuditCheck(
                        check_id=f"scan-symlink:{relative}",
                        category="json_syntax",
                        status="blocked",
                        message="symbolic links inside scanned configs/docs paths are not followed; review and replace with regular paths",
                        evidence_path=relative,
                    )
                )
                continue
            if not candidate.is_file() or candidate.suffix.lower() not in {".json", ".jsonl"}:
                continue
            json_count += 1
            try:
                payload = candidate.read_bytes()
                if len(payload) > cfg.max_json_file_bytes:
                    raise ValueError(
                        f"file exceeds configured scan limit ({cfg.max_json_file_bytes} bytes)"
                    )
                text = payload.decode("utf-8")
                if candidate.suffix.lower() == ".json":
                    json.loads(text)
                else:
                    for line_number, line in enumerate(text.splitlines(), 1):
                        if line.strip():
                            try:
                                json.loads(line)
                            except json.JSONDecodeError as exc:
                                raise ValueError(
                                    f"invalid JSONL at line {line_number}: {exc.msg}"
                                ) from None
                status = "passed"
                message = "JSON/JSONL syntax valid"
                digest = _sha256_bytes(payload)
            except (OSError, ValueError) as exc:
                status = "blocked"
                message = f"JSON/JSONL syntax check failed: {exc}"[:1_000]
                digest = None
            checks.append(
                AuditCheck(
                    check_id=f"json:{relative}",
                    category="json_syntax",
                    status=status,
                    message=message,
                    evidence_path=relative,
                    sha256=digest,
                )
            )

    if cfg.require_clean_tracked_diff:
        try:
            status_result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            is_clean = not status_result.stdout.strip()
            checks.append(
                AuditCheck(
                    check_id="git:tracked-working-tree-clean",
                    category="git_state",
                    status="passed" if is_clean else "blocked",
                    message="tracked working tree is clean"
                    if is_clean
                    else "tracked working tree has modifications",
                )
            )
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append(
                AuditCheck(
                    check_id="git:tracked-working-tree-clean",
                    category="git_state",
                    status="blocked",
                    message=f"could not establish tracked working-tree status: {exc}"[:1_000],
                )
            )

    checks.append(
        AuditCheck(
            check_id="safety:no-execution",
            category="safety_boundary",
            status="passed",
            message="audit performs no simulator launch, cloud job, policy change, or network request",
        )
    )
    final_checks = tuple(checks)
    software_gate: Literal["pass_for_handoff_review", "blocked"] = (
        "blocked"
        if any(item.status == "blocked" for item in final_checks)
        else "pass_for_handoff_review"
    )
    generated_at = _utc_now()
    git_sha = _git_commit(root)
    digest = _sha256_bytes(
        _audit_digest_payload(final_checks, generated_at, git_sha, json_count, software_gate)
    )
    audit_id = f"audit-{digest[:20]}"
    return ReleaseAuditReport(
        audit_id=audit_id,
        generated_at_utc=generated_at,
        project_root_label=root.name,
        git_commit=git_sha,
        software_gate=software_gate,
        checks=final_checks,
        scanned_json_files=json_count,
        report_sha256=digest,
    )


def build_handoff_manifest(
    audit_report: ReleaseAuditReport,
    adapter_contract: IsaacAdapterContract | None = None,
) -> HandoffManifest:
    """Build a handoff package; a passing software audit is not host authorization."""
    is_blocked = audit_report.software_gate != "pass_for_handoff_review"
    required = (
        "Select the exact Isaac Sim release and review its official platform requirements.",
        "Collect operator-attested OS, driver, RAM, GPU VRAM, disk and simulator-version evidence.",
        "Verify scenario/telemetry mappings against the selected Isaac Sim release.",
        "Review assets, licenses, checksums and safe reset/shutdown behavior.",
        "Run a separate explicitly authorized host smoke test only after review.",
    )
    payload = {
        "audit_sha256": audit_report.report_sha256,
        "git_commit": audit_report.git_commit,
        "adapter_contract_version": (
            adapter_contract or IsaacAdapterContract(adapter_contract_version="1.0.0")
        ).adapter_contract_version,
        "created_at": _utc_now().isoformat(),
    }
    digest = _sha256_bytes(_canonical_json_bytes(payload))
    return HandoffManifest(
        handoff_id=f"handoff-{digest[:20]}",
        generated_at_utc=_utc_now(),
        software_audit_sha256=audit_report.report_sha256,
        git_commit=audit_report.git_commit,
        adapter_contract=adapter_contract or IsaacAdapterContract(adapter_contract_version="1.0.0"),
        handoff_status="blocked" if is_blocked else "software_contracts_prepared_host_not_assessed",
        required_operator_actions=required,
    )


def assess_host_readiness(
    attestation: HostReadinessAttestation,
    requirements: HostReadinessRequirements,
) -> HostReadinessResult:
    """Evaluate an operator attestation against configured requirements, not actual hardware."""
    checks: list[AuditCheck] = []

    def add(check_id: str, ok: bool, message: str) -> None:
        checks.append(
            AuditCheck(
                check_id=check_id,
                category="safety_boundary",
                status="passed" if ok else "blocked",
                message=message,
            )
        )

    add(
        "target-release",
        attestation.simulator_release == requirements.target_simulator_release,
        "attested simulator release matches target"
        if attestation.simulator_release == requirements.target_simulator_release
        else "attested simulator release does not match configured target",
    )
    add(
        "system-ram",
        attestation.system_ram_gb >= requirements.minimum_system_ram_gb,
        "attested system RAM meets configured minimum"
        if attestation.system_ram_gb >= requirements.minimum_system_ram_gb
        else "attested system RAM is below configured minimum",
    )
    add(
        "gpu-vram",
        attestation.gpu_vram_gb >= requirements.minimum_gpu_vram_gb,
        "attested GPU VRAM meets configured minimum"
        if attestation.gpu_vram_gb >= requirements.minimum_gpu_vram_gb
        else "attested GPU VRAM is below configured minimum",
    )
    add(
        "free-disk",
        attestation.free_disk_gb >= requirements.minimum_free_disk_gb,
        "attested free disk meets configured minimum"
        if attestation.free_disk_gb >= requirements.minimum_free_disk_gb
        else "attested free disk is below configured minimum",
    )
    add(
        "requirements-reviewed",
        attestation.official_requirements_reviewed,
        "operator attests official requirements were reviewed"
        if attestation.official_requirements_reviewed
        else "official requirements review is not confirmed",
    )
    add(
        "os-compatibility",
        (
            attestation.os_compatibility_confirmed
            or not requirements.require_os_compatibility_confirmation
        ),
        "OS compatibility confirmation satisfied"
        if (
            attestation.os_compatibility_confirmed
            or not requirements.require_os_compatibility_confirmation
        )
        else "OS compatibility has not been confirmed",
    )
    add(
        "driver-compatibility",
        (
            attestation.driver_compatibility_confirmed
            or not requirements.require_driver_compatibility_confirmation
        ),
        "driver compatibility confirmation satisfied"
        if (
            attestation.driver_compatibility_confirmed
            or not requirements.require_driver_compatibility_confirmation
        )
        else "driver compatibility has not been confirmed",
    )
    add(
        "asset-checksums",
        (attestation.assets_checksums_confirmed and attestation.asset_manifest_sha256 is not None)
        or not requirements.require_assets_checksum_confirmation,
        "asset checksum confirmation satisfied"
        if (
            (
                attestation.assets_checksums_confirmed
                and attestation.asset_manifest_sha256 is not None
            )
            or not requirements.require_assets_checksum_confirmation
        )
        else "asset manifest SHA-256/checksum confirmation is missing",
    )
    canonical = _canonical_json_bytes(attestation.model_dump(mode="json"))
    return HostReadinessResult(
        status="blocked"
        if any(check.status == "blocked" for check in checks)
        else "attested_meets_configured_thresholds",
        checks=tuple(checks),
        attestation_sha256=_sha256_bytes(canonical),
    )


def _write_json_atomic(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json_bytes(value.model_dump(mode="json"))
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit RESILIANT-Z release readiness; never launches Isaac Sim."
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config_payload = json.loads(args.config.read_text(encoding="utf-8"))
        config = ReleaseAuditConfig.model_validate(config_payload)
        report = audit_project(args.project_root, config)
        handoff = build_handoff_manifest(report)
        _write_json_atomic(args.output_dir / "release-audit.v1.json", report)
        _write_json_atomic(args.output_dir / "isaac-handoff-manifest.v1.json", handoff)
    except (OSError, ValueError) as exc:
        print(f"ERROR: release audit failed: {exc}")
        return 2
    print(f"Audit: {report.audit_id}")
    print(f"Software gate: {report.software_gate}")
    print(
        f"Checks: {len(report.checks)}; blockers: {len(report.blockers)}; JSON/JSONL files scanned: {report.scanned_json_files}"
    )
    print(f"Handoff: {handoff.handoff_status}")
    print(
        "Isaac Sim launched: false; cloud job launched: false; live policy modified: false; execution authorized: false"
    )
    print(f"Audit report SHA-256: {report.report_sha256}")
    print(f"Output directory: {args.output_dir}")
    return 0 if report.software_gate == "pass_for_handoff_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
