from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from resiliant_z.release_readiness import (
    CORE_REQUIRED_PATHS,
    HostReadinessAttestation,
    HostReadinessRequirements,
    IsaacAdapterContract,
    ReleaseAuditConfig,
    ReleaseReadinessError,
    assess_host_readiness,
    audit_project,
    build_handoff_manifest,
)


def make_project(root: Path) -> Path:
    for relative in CORE_REQUIRED_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            path.write_text('{"fixture": true}\n', encoding="utf-8")
        elif path.suffix == ".jsonl":
            path.write_text('{"fixture": true}\n', encoding="utf-8")
        else:
            path.write_text(f"# fixture: {relative}\n", encoding="utf-8")
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    return root


def make_requirements() -> HostReadinessRequirements:
    return HostReadinessRequirements(
        target_simulator_release="6.2.0",
        minimum_system_ram_gb=32,
        minimum_gpu_vram_gb=16,
        minimum_free_disk_gb=50,
    )


def make_attestation(**overrides: object) -> HostReadinessAttestation:
    values: dict[str, object] = {
        "host_label": "test-host",
        "checked_at_utc": datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
        "checked_by": "test-operator",
        "os_release": "Example Linux x86_64",
        "os_compatibility_confirmed": True,
        "gpu_model": "Example GPU",
        "gpu_vram_gb": 24,
        "driver_version": "example-driver",
        "driver_compatibility_confirmed": True,
        "system_ram_gb": 64,
        "free_disk_gb": 200,
        "simulator_release": "6.2.0",
        "official_requirements_reviewed": True,
        "asset_manifest_sha256": "a" * 64,
        "assets_checksums_confirmed": True,
    }
    values.update(overrides)
    return HostReadinessAttestation.model_validate(values)


def test_complete_fixture_passes_software_gate(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    report = audit_project(root)
    assert report.software_gate == "pass_for_handoff_review"
    assert report.blockers == ()
    assert report.scanned_json_files >= 1
    assert len(report.report_sha256) == 64
    assert report.execution_authorized is False


def test_missing_core_file_blocks_gate(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    (root / "src/resiliant_z/gap_detector.py").unlink()
    report = audit_project(root)
    assert report.software_gate == "blocked"
    assert any(
        check.evidence_path == "src/resiliant_z/gap_detector.py" for check in report.blockers
    )


def test_malformed_json_blocks_gate(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    (root / "configs/broken.json").write_text("{broken", encoding="utf-8")
    report = audit_project(root)
    assert report.software_gate == "blocked"
    assert any(check.evidence_path == "configs/broken.json" for check in report.blockers)


def test_malformed_jsonl_line_blocks_gate(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    (root / "configs/broken.jsonl").write_text('{"ok": 1}\nnope\n', encoding="utf-8")
    report = audit_project(root)
    failed = [check for check in report.blockers if check.evidence_path == "configs/broken.jsonl"]
    assert len(failed) == 1
    assert "line 2" in failed[0].message


def test_oversized_json_blocks_gate(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    (root / "configs/big.json").write_text('{"x":"' + "x" * 2_000 + '"}', encoding="utf-8")
    report = audit_project(root, ReleaseAuditConfig(max_json_file_bytes=1_024))
    assert any("scan limit" in check.message for check in report.blockers)


def test_configuration_cannot_remove_core_checks(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    config = ReleaseAuditConfig(additional_required_paths=())
    report = audit_project(root, config)
    assert any(
        check.check_id == "required:src/resiliant_z/knowledge_model.py" for check in report.checks
    )


def test_unsafe_relative_path_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReleaseAuditConfig(additional_required_paths=("../outside.txt",))


def test_missing_project_root_raises(tmp_path: Path) -> None:
    with pytest.raises(ReleaseReadinessError):
        audit_project(tmp_path / "does-not-exist")


def test_handoff_is_contract_only_and_never_authorizes_execution(tmp_path: Path) -> None:
    report = audit_project(make_project(tmp_path / "project"))
    handoff = build_handoff_manifest(report, IsaacAdapterContract(adapter_contract_version="1.2.0"))
    assert handoff.handoff_status == "software_contracts_prepared_host_not_assessed"
    assert handoff.adapter_contract.implementation_status == "contract_only_not_implemented"
    assert handoff.adapter_contract.adapter_runtime_status == "not_started"
    assert handoff.adapter_contract.automatic_execution_allowed is False
    assert handoff.host_launch_authorized is False
    assert handoff.isaac_sim_launched is False


def test_blocked_software_audit_blocks_handoff_status(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    (root / "src/resiliant_z/knowledge_model.py").unlink()
    report = audit_project(root)
    handoff = build_handoff_manifest(report)
    assert handoff.handoff_status == "blocked"
    assert handoff.host_launch_authorized is False


def test_host_attestation_meets_configured_thresholds() -> None:
    result = assess_host_readiness(make_attestation(), make_requirements())
    assert result.status == "attested_meets_configured_thresholds"
    assert not any(check.status == "blocked" for check in result.checks)
    assert result.actual_hardware_measurement_performed is False
    assert result.simulator_launched is False
    assert result.execution_authorized is False


@pytest.mark.parametrize(
    ("field", "value", "expected_check"),
    [
        ("system_ram_gb", 16, "system-ram"),
        ("gpu_vram_gb", 6, "gpu-vram"),
        ("free_disk_gb", 10, "free-disk"),
        ("simulator_release", "other-release", "target-release"),
        ("official_requirements_reviewed", False, "requirements-reviewed"),
        ("os_compatibility_confirmed", False, "os-compatibility"),
        ("driver_compatibility_confirmed", False, "driver-compatibility"),
        ("assets_checksums_confirmed", False, "asset-checksums"),
        ("asset_manifest_sha256", None, "asset-checksums"),
    ],
)
def test_host_readiness_fails_closed(field: str, value: object, expected_check: str) -> None:
    attestation = make_attestation(**{field: value})
    result = assess_host_readiness(attestation, make_requirements())
    assert result.status == "blocked"
    assert any(
        check.check_id == expected_check and check.status == "blocked" for check in result.checks
    )


def test_placeholder_simulator_release_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HostReadinessRequirements(
            target_simulator_release="VERIFY_FOR_TARGET_RELEASE",
            minimum_system_ram_gb=32,
            minimum_gpu_vram_gb=16,
            minimum_free_disk_gb=50,
        )


def test_host_requirements_template_cannot_be_used_unedited() -> None:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "release-readiness"
        / "session15_host_requirements.template.json"
    )
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError, match="target_simulator_release"):
        HostReadinessRequirements.model_validate(payload)


def test_report_contains_no_true_execution_flags(tmp_path: Path) -> None:
    report = audit_project(make_project(tmp_path / "project"))
    payload = report.model_dump(mode="json")
    assert payload["isaac_sim_launched"] is False
    assert payload["cloud_job_launched"] is False
    assert payload["live_policy_modified"] is False
    assert payload["execution_authorized"] is False


def test_all_checks_have_unique_ids(tmp_path: Path) -> None:
    report = audit_project(make_project(tmp_path / "project"))
    ids = [check.check_id for check in report.checks]
    assert len(ids) == len(set(ids))


def test_all_successful_required_file_checks_have_hashes(tmp_path: Path) -> None:
    report = audit_project(make_project(tmp_path / "project"))
    required_checks = [check for check in report.checks if check.category == "required_file"]
    assert required_checks
    assert all(check.sha256 is not None for check in required_checks if check.status == "passed")


def test_scan_blocks_symlinked_json_file(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    outside = tmp_path / "outside.json"
    outside.write_text("invalid", encoding="utf-8")
    (root / "configs/link.json").symlink_to(outside)
    report = audit_project(root)
    assert report.software_gate == "blocked"
    assert any(
        check.evidence_path == "configs/link.json" and check.status == "blocked"
        for check in report.checks
    )


def test_host_requirements_do_not_infer_live_measurements() -> None:
    result = assess_host_readiness(make_attestation(), make_requirements())
    assert result.actual_hardware_measurement_performed is False
    assert "attested" in result.status


def test_adapter_contract_rejects_execution_enabled() -> None:
    with pytest.raises(ValidationError):
        IsaacAdapterContract(adapter_contract_version="1.0.0", automatic_execution_allowed=True)  # type: ignore[arg-type]


def test_cli_audit_artifacts_are_json_serializable(tmp_path: Path) -> None:
    root = make_project(tmp_path / "project")
    report = audit_project(root)
    handoff = build_handoff_manifest(report)
    encoded_report = json.dumps(report.model_dump(mode="json"))
    encoded_handoff = json.dumps(handoff.model_dump(mode="json"))
    assert json.loads(encoded_report)["software_gate"] == "pass_for_handoff_review"
    assert json.loads(encoded_handoff)["host_launch_authorized"] is False
