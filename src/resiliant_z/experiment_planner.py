"""Deterministic planning and run-registry primitives for RESILIANT-Z Session 8.

This module creates reproducible run manifests and records lifecycle transitions.
It deliberately does not execute a simulator, submit cloud jobs, or call a network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from resiliant_z.experiment_compiler import (
    CompiledExperimentManifest,
    ExperimentArm,
)

SchemaVersion = Literal["1.0.0"]
SeedSplit = Literal["discovery", "selection", "validation", "replay"]
RunStatus = Literal[
    "planned",
    "validated",
    "queued",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "incomplete",
    "invalidated",
]
ArmId = Literal["control", "treatment"]

REQUIRED_SPLITS: tuple[SeedSplit, ...] = (
    "discovery",
    "selection",
    "validation",
    "replay",
)

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    "planned": frozenset({"validated", "invalidated"}),
    "validated": frozenset({"queued", "invalidated"}),
    "queued": frozenset({"running", "failed", "timed_out", "incomplete", "invalidated"}),
    "running": frozenset({"succeeded", "failed", "timed_out", "incomplete", "invalidated"}),
    "succeeded": frozenset({"invalidated"}),
    "failed": frozenset({"invalidated"}),
    "timed_out": frozenset({"invalidated"}),
    "incomplete": frozenset({"invalidated"}),
    "invalidated": frozenset(),
}


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


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class PlannerConfig(StrictModel):
    """Trusted bounds for a deterministic, predeclared paired design."""

    schema_version: SchemaVersion = "1.0.0"
    config_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    root_seed: int = Field(ge=0, le=4_294_967_295)
    replicates_per_split: int = Field(default=3, ge=1, le=100)
    max_total_runs: int = Field(default=48, ge=2, le=200)
    max_manifest_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    seed_derivation_version: Literal["sha256-v1"] = "sha256-v1"
    selection_strategy: Literal["predeclared_paired_single_factor"] = (
        "predeclared_paired_single_factor"
    )
    seed_splits: list[SeedSplit] = Field(
        default_factory=lambda: list(REQUIRED_SPLITS),
        min_length=4,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_seed_split_contract(self) -> PlannerConfig:
        if tuple(self.seed_splits) != REQUIRED_SPLITS:
            raise ValueError(
                "seed_splits must be exactly discovery, selection, validation, replay in that order"
            )
        if len(set(self.seed_splits)) != len(self.seed_splits):
            raise ValueError("seed_splits must be unique")
        return self


def load_planner_config(path: str | Path) -> PlannerConfig:
    return PlannerConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _parse_manifest(
    manifest: CompiledExperimentManifest | Mapping[str, object] | str | Path,
    max_bytes: int,
) -> CompiledExperimentManifest:
    try:
        if isinstance(manifest, CompiledExperimentManifest):
            raw = _canonical_bytes(manifest)
            parsed = manifest.model_dump(mode="python")
        elif isinstance(manifest, Path):
            raw = manifest.read_bytes()
            parsed = json.loads(raw)
        elif isinstance(manifest, str):
            raw = manifest.encode("utf-8")
            parsed = json.loads(manifest)
        else:
            parsed = dict(manifest)
            raw = _canonical_bytes(parsed)
        if len(raw) > max_bytes:
            raise PlannerError("manifest_too_large", f"compiled manifest exceeds {max_bytes} bytes")
        if not isinstance(parsed, dict):
            raise PlannerError("invalid_manifest_shape", "compiled manifest must be a JSON object")
        result = CompiledExperimentManifest.model_validate(parsed)
    except PlannerError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PlannerError(
            "manifest_read_error", f"could not read compiled manifest: {exc}"
        ) from None
    except json.JSONDecodeError as exc:
        raise PlannerError(
            "malformed_manifest_json",
            f"compiled manifest JSON invalid at line {exc.lineno}, column {exc.colno}",
        ) from None
    except (ValidationError, TypeError, ValueError) as exc:
        raise PlannerError("invalid_compiled_manifest", str(exc)) from None
    return result


class PlannerError(ValueError):
    """Actionable error raised when a plan or registry update is rejected."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class SeedAllocation(StrictModel):
    split: SeedSplit
    seeds: list[int] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_seeds(self) -> SeedAllocation:
        if any(seed < 0 or seed > 2_147_483_647 for seed in self.seeds):
            raise ValueError("allocated seeds must fit in signed 31-bit non-negative range")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds within a split must be unique")
        return self


class PlannedRun(StrictModel):
    run_id: str = Field(pattern=r"^run-[0-9a-f]{24}$")
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{24}$")
    manifest_id: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_id: Literal["discrete_event", "surrogate"]
    target_metric: str
    horizon_seconds: float = Field(gt=0, allow_inf_nan=False)
    split: SeedSplit
    arm_id: ArmId
    replicate_index: int = Field(ge=0, le=99)
    seed: int = Field(ge=0, le=2_147_483_647)
    scenario_factors: dict[str, float] = Field(min_length=1, max_length=100)
    policy_parameters: dict[str, float] = Field(min_length=1, max_length=100)
    selection_strategy: Literal["predeclared_paired_single_factor"]
    selection_reason: str = Field(min_length=1, max_length=512)
    status: Literal["planned"] = "planned"
    automatic_execution: Literal[False] = False


class ExperimentPlan(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{24}$")
    planner_version: Literal["session8.experiment-planner.v1"] = "session8.experiment-planner.v1"
    status: Literal["planned"] = "planned"
    source_manifest_id: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_id: Literal["discrete_event", "surrogate"]
    target_metric: str
    root_seed: int = Field(ge=0, le=4_294_967_295)
    planner_config_id: str
    planner_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_derivation_version: Literal["sha256-v1"]
    seed_allocations: list[SeedAllocation] = Field(min_length=4, max_length=4)
    selection_strategy: Literal["predeclared_paired_single_factor"]
    selection_reason: str = Field(min_length=1, max_length=512)
    common_random_numbers: Literal[True] = True
    run_count: int = Field(ge=8, le=200)
    max_run_count_at_compile: int = Field(ge=2, le=200)
    automatic_execution: Literal[False] = False
    evidence_status: Literal["not_executed_not_evidence"] = "not_executed_not_evidence"
    runs: list[PlannedRun] = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def validate_plan_invariants(self) -> ExperimentPlan:
        if self.run_count != len(self.runs):
            raise ValueError("run_count must equal the number of run records")
        if self.run_count > self.max_run_count_at_compile:
            raise ValueError("planned run count exceeds the source manifest's compile-time limit")
        if len({run.run_id for run in self.runs}) != len(self.runs):
            raise ValueError("run_id values must be unique")
        if any(run.plan_id != self.plan_id for run in self.runs):
            raise ValueError("every run must reference this plan_id")
        if any(run.manifest_id != self.source_manifest_id for run in self.runs):
            raise ValueError("every run must reference the source manifest")
        allocation_by_split = {item.split: item.seeds for item in self.seed_allocations}
        if set(allocation_by_split) != set(REQUIRED_SPLITS):
            raise ValueError("plan must include all four required seed splits")
        all_split_seeds: list[int] = []
        for split in REQUIRED_SPLITS:
            seeds = allocation_by_split[split]
            if len(seeds) != len(set(seeds)):
                raise ValueError(f"seeds must be unique within {split}")
            all_split_seeds.extend(seeds)
        if len(all_split_seeds) != len(set(all_split_seeds)):
            raise ValueError("discovery, selection, validation and replay seeds must be disjoint")
        by_pair: dict[tuple[str, int], list[PlannedRun]] = {}
        for run in self.runs:
            by_pair.setdefault((run.split, run.replicate_index), []).append(run)
        expected_pairs = sum(len(allocation_by_split[split]) for split in REQUIRED_SPLITS)
        if len(by_pair) != expected_pairs:
            raise ValueError("each allocated seed must define exactly one paired run group")
        for (split, replicate), pair in by_pair.items():
            if len(pair) != 2 or {run.arm_id for run in pair} != {"control", "treatment"}:
                raise ValueError(
                    f"{split} replicate {replicate} must contain one control and one treatment"
                )
            if pair[0].seed != pair[1].seed:
                raise ValueError("paired arms must share the same random seed")
            if replicate >= len(allocation_by_split[split]):
                raise ValueError("replicate index exceeds its declared seed allocation")
            if pair[0].seed != allocation_by_split[split][replicate]:
                raise ValueError(
                    "run seed must match the seed allocated to its split/replicate index"
                )
        return self


def _seed_for(root_seed: int, manifest_id: str, split: str, replicate_index: int, salt: int) -> int:
    payload = (
        f"resiliant-z:session8:sha256-v1:{root_seed}:{manifest_id}:{split}:{replicate_index}:{salt}"
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF


def plan_experiment(
    manifest: CompiledExperimentManifest | Mapping[str, object] | str | Path,
    config: PlannerConfig,
) -> ExperimentPlan:
    """Create a deterministic four-split paired plan without running any backend."""
    compiled = _parse_manifest(manifest, config.max_manifest_bytes)
    if (
        compiled.status != "compiled_provisional"
        or compiled.promotion_status != "provisional_not_validated"
    ):
        raise PlannerError(
            "manifest_not_provisional",
            "planner accepts only compiler output still marked provisional",
        )
    if compiled.design_kind != "paired_single_factor":
        raise PlannerError(
            "unsupported_design", "Session 8 currently supports paired_single_factor only"
        )
    if compiled.automatic_execution is not False:
        raise PlannerError(
            "automatic_execution_forbidden", "planner never enables automatic execution"
        )

    control_scenario = compiled.control.scenario_factors
    treatment_scenario = compiled.treatment.scenario_factors
    control_policy = compiled.control.policy_parameters
    treatment_policy = compiled.treatment.policy_parameters
    if set(control_scenario) != set(treatment_scenario) or set(control_policy) != set(
        treatment_policy
    ):
        raise PlannerError(
            "arm_parameter_mismatch", "control and treatment must contain identical parameter keys"
        )
    differences: list[tuple[str, str]] = []
    for parameter_id in sorted(control_scenario):
        left, right = control_scenario[parameter_id], treatment_scenario[parameter_id]
        if not math.isfinite(left) or not math.isfinite(right):
            raise PlannerError(
                "non_finite_arm_value", f"scenario factor {parameter_id!r} is not finite"
            )
        if not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9):
            differences.append(("scenario_factor", parameter_id))
    for parameter_id in sorted(control_policy):
        left, right = control_policy[parameter_id], treatment_policy[parameter_id]
        if not math.isfinite(left) or not math.isfinite(right):
            raise PlannerError(
                "non_finite_arm_value", f"policy parameter {parameter_id!r} is not finite"
            )
        if not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9):
            differences.append(("policy_parameter", parameter_id))
    expected_focus = [(compiled.focus.kind, compiled.focus.parameter_id)]
    if differences != expected_focus:
        raise PlannerError(
            "not_single_factor_pair",
            f"control and treatment must differ only on focus {expected_focus}; differences={differences}",
        )

    total_runs = len(REQUIRED_SPLITS) * config.replicates_per_split * 2
    allowed_total = min(config.max_total_runs, compiled.max_run_count_at_compile)
    if total_runs > allowed_total:
        raise PlannerError(
            "run_limit_exceeded",
            f"plan needs {total_runs} runs but the effective limit is {allowed_total}",
        )
    if config.replicates_per_split > compiled.replicates_per_arm:
        raise PlannerError(
            "replicate_limit_exceeded",
            "replicates_per_split cannot exceed the compiler-accepted replicates_per_arm",
        )

    seed_allocations: list[SeedAllocation] = []
    used_seeds: set[int] = set()
    for split in REQUIRED_SPLITS:
        seeds: list[int] = []
        for replicate_index in range(config.replicates_per_split):
            salt = 0
            seed = _seed_for(config.root_seed, compiled.manifest_id, split, replicate_index, salt)
            while seed in used_seeds:
                salt += 1
                seed = _seed_for(
                    config.root_seed, compiled.manifest_id, split, replicate_index, salt
                )
                if salt > 1000:
                    raise PlannerError(
                        "seed_collision_exhausted", "unable to allocate a distinct seed"
                    )
            used_seeds.add(seed)
            seeds.append(seed)
        seed_allocations.append(SeedAllocation(split=split, seeds=seeds))

    reason = (
        "Predeclared paired single-factor design from the validated compiler manifest; "
        "control and treatment share common random numbers within each split/replicate. "
        "The planner adds no new parameter values or interactions."
    )
    source_manifest_hash = _sha256(compiled)
    config_hash = _sha256(config)
    plan_identity = {
        "planner_version": "session8.experiment-planner.v1",
        "source_manifest_sha256": source_manifest_hash,
        "planner_config_sha256": config_hash,
        "root_seed": config.root_seed,
        "seed_allocations": [item.model_dump(mode="json") for item in seed_allocations],
        "selection_strategy": config.selection_strategy,
    }
    plan_id = f"plan-{_sha256(plan_identity)[:24]}"

    runs: list[PlannedRun] = []
    arms: tuple[ExperimentArm, ...] = (compiled.control, compiled.treatment)
    for allocation in seed_allocations:
        for replicate_index, seed in enumerate(allocation.seeds):
            for arm in arms:
                run_identity = f"{plan_id}:{allocation.split}:{replicate_index}:{arm.arm_id}"
                run_id = f"run-{hashlib.sha256(run_identity.encode('utf-8')).hexdigest()[:24]}"
                runs.append(
                    PlannedRun(
                        run_id=run_id,
                        plan_id=plan_id,
                        manifest_id=compiled.manifest_id,
                        source_manifest_sha256=source_manifest_hash,
                        scenario_id=compiled.scenario_id,
                        scenario_sha256=compiled.scenario_sha256,
                        backend_id=compiled.backend_id,
                        target_metric=compiled.target_metric,
                        horizon_seconds=compiled.horizon_seconds,
                        split=allocation.split,
                        arm_id=arm.arm_id,
                        replicate_index=replicate_index,
                        seed=seed,
                        scenario_factors=arm.scenario_factors,
                        policy_parameters=arm.policy_parameters,
                        selection_strategy=config.selection_strategy,
                        selection_reason=reason,
                    )
                )

    try:
        return ExperimentPlan(
            plan_id=plan_id,
            source_manifest_id=compiled.manifest_id,
            source_manifest_sha256=source_manifest_hash,
            scenario_id=compiled.scenario_id,
            scenario_sha256=compiled.scenario_sha256,
            backend_id=compiled.backend_id,
            target_metric=compiled.target_metric,
            root_seed=config.root_seed,
            planner_config_id=config.config_id,
            planner_config_sha256=config_hash,
            seed_derivation_version=config.seed_derivation_version,
            seed_allocations=seed_allocations,
            selection_strategy=config.selection_strategy,
            selection_reason=reason,
            run_count=len(runs),
            max_run_count_at_compile=compiled.max_run_count_at_compile,
            runs=runs,
        )
    except ValidationError as exc:
        raise PlannerError("invalid_plan", str(exc)) from None


def _write_atomic_no_overwrite(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise FileExistsError(f"refusing to overwrite existing file with different content: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_name, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise FileExistsError(
                    f"refusing to overwrite existing file with different content: {path}"
                ) from None
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def save_plan_atomic(path: str | Path, plan: ExperimentPlan) -> None:
    """Persist immutable plan output, refusing conflicting overwrites."""
    target = Path(path)
    payload = (plan.model_dump_json(indent=2) + "\n").encode("utf-8")
    _write_atomic_no_overwrite(target, payload)


class RunRegistryEntry(StrictModel):
    run_id: str = Field(pattern=r"^run-[0-9a-f]{24}$")
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{24}$")
    manifest_id: str
    split: SeedSplit
    arm_id: ArmId
    replicate_index: int = Field(ge=0, le=99)
    seed: int = Field(ge=0, le=2_147_483_647)
    status: RunStatus
    reason: str | None = Field(default=None, max_length=512)
    updated_at_utc: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> RunRegistryEntry:
        if self.updated_at_utc.tzinfo is None or self.updated_at_utc.utcoffset() is None:
            raise ValueError("updated_at_utc must be timezone-aware")
        return self


class RunStateEvent(StrictModel):
    event_id: str = Field(pattern=r"^evt-[0-9a-f]{24}$")
    run_id: str = Field(pattern=r"^run-[0-9a-f]{24}$")
    from_status: RunStatus | None = None
    to_status: RunStatus
    reason: str = Field(min_length=1, max_length=512)
    occurred_at_utc: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> RunStateEvent:
        if self.occurred_at_utc.tzinfo is None or self.occurred_at_utc.utcoffset() is None:
            raise ValueError("occurred_at_utc must be timezone-aware")
        return self


class RunRegistrySnapshot(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    registry_version: Literal[1] = 1
    runs: dict[str, RunRegistryEntry] = Field(default_factory=dict)
    events: list[RunStateEvent] = Field(default_factory=list, max_length=100_000)

    @model_validator(mode="after")
    def validate_registry_keys(self) -> RunRegistrySnapshot:
        if any(run_id != entry.run_id for run_id, entry in self.runs.items()):
            raise ValueError("registry map keys must equal each entry's run_id")
        known_ids = set(self.runs)
        if any(event.run_id not in known_ids for event in self.events):
            raise ValueError("all registry events must reference a registered run")
        return self


class RunRegistry:
    """Atomic JSON run registry with a validated transition state machine."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            try:
                self._snapshot = RunRegistrySnapshot.model_validate_json(
                    self.path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError, ValueError) as exc:
                raise PlannerError(
                    "invalid_registry", f"existing registry cannot be loaded: {exc}"
                ) from None
        else:
            self._snapshot = RunRegistrySnapshot()

    @property
    def snapshot(self) -> RunRegistrySnapshot:
        return self._snapshot

    def _persist(self) -> None:
        payload = (self._snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _append_event(
        self,
        run_id: str,
        from_status: RunStatus | None,
        to_status: RunStatus,
        reason: str,
    ) -> RunStateEvent:
        timestamp = datetime.now(UTC)
        event_material = {
            "sequence": len(self._snapshot.events),
            "run_id": run_id,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
            "occurred_at_utc": timestamp.isoformat(),
        }
        event = RunStateEvent(
            event_id=f"evt-{_sha256(event_material)[:24]}",
            run_id=run_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            occurred_at_utc=timestamp,
        )
        self._snapshot = self._snapshot.model_copy(
            update={"events": [*self._snapshot.events, event]}
        )
        return event

    def register_plan(self, plan: ExperimentPlan) -> int:
        """Register planned runs. Repeating the exact registration is idempotent."""
        if plan.automatic_execution is not False or plan.status != "planned":
            raise PlannerError(
                "unsafe_plan_status", "only non-executing plans in planned status can be registered"
            )
        runs = dict(self._snapshot.runs)
        events = list(self._snapshot.events)
        now = datetime.now(UTC)
        added = 0
        for planned in plan.runs:
            existing = runs.get(planned.run_id)
            if existing is not None:
                immutable_existing = (
                    existing.plan_id,
                    existing.manifest_id,
                    existing.split,
                    existing.arm_id,
                    existing.replicate_index,
                    existing.seed,
                )
                immutable_incoming = (
                    planned.plan_id,
                    planned.manifest_id,
                    planned.split,
                    planned.arm_id,
                    planned.replicate_index,
                    planned.seed,
                )
                if immutable_existing != immutable_incoming:
                    raise PlannerError(
                        "run_id_conflict",
                        f"existing run {planned.run_id} conflicts with incoming plan",
                    )
                continue
            entry = RunRegistryEntry(
                run_id=planned.run_id,
                plan_id=planned.plan_id,
                manifest_id=planned.manifest_id,
                split=planned.split,
                arm_id=planned.arm_id,
                replicate_index=planned.replicate_index,
                seed=planned.seed,
                status="planned",
                reason="registered from deterministic experiment plan",
                updated_at_utc=now,
            )
            runs[planned.run_id] = entry
            event_material = {
                "sequence": len(events),
                "run_id": planned.run_id,
                "from_status": None,
                "to_status": "planned",
                "reason": "registered from deterministic experiment plan",
                "occurred_at_utc": now.isoformat(),
            }
            events.append(
                RunStateEvent(
                    event_id=f"evt-{_sha256(event_material)[:24]}",
                    run_id=planned.run_id,
                    from_status=None,
                    to_status="planned",
                    reason="registered from deterministic experiment plan",
                    occurred_at_utc=now,
                )
            )
            added += 1
        if added:
            self._snapshot = RunRegistrySnapshot(runs=runs, events=events)
            self._persist()
        return added

    def transition(
        self,
        run_id: str,
        to_status: RunStatus,
        reason: str | None = None,
    ) -> RunRegistryEntry:
        """Advance a run according to the allowlisted state machine."""
        current = self._snapshot.runs.get(run_id)
        if current is None:
            raise PlannerError("unknown_run", f"run_id {run_id!r} is not registered")
        if to_status not in ALLOWED_TRANSITIONS[current.status]:
            raise PlannerError(
                "invalid_state_transition",
                f"transition {current.status!r} -> {to_status!r} is not permitted for {run_id}",
            )
        detail = (reason or "").strip()
        if to_status in {"failed", "timed_out", "incomplete", "invalidated"} and not detail:
            raise PlannerError(
                "transition_reason_required",
                f"a non-empty reason is required for status {to_status!r}",
            )
        if not detail:
            detail = f"state transitioned to {to_status}"
        if len(detail) > 512:
            raise PlannerError(
                "transition_reason_too_long", "transition reason must be at most 512 characters"
            )

        now = datetime.now(UTC)
        entry = current.model_copy(
            update={"status": to_status, "reason": detail, "updated_at_utc": now}
        )
        runs = dict(self._snapshot.runs)
        runs[run_id] = entry
        previous_snapshot = self._snapshot
        self._snapshot = RunRegistrySnapshot(runs=runs, events=list(previous_snapshot.events))
        self._append_event(run_id, current.status, to_status, detail)
        try:
            self._persist()
        except OSError:
            self._snapshot = previous_snapshot
            raise
        return entry


def _write_registry_cli(registry: RunRegistry, plan: ExperimentPlan) -> int:
    return registry.register_plan(plan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan reproducible RESILIANT-Z runs; does not execute them."
    )
    parser.add_argument(
        "--manifest",
        default="configs/experiment-planner/session8_manifest_fixture.v1.json",
        help="Session 7 compiled manifest JSON (default: offline example fixture)",
    )
    parser.add_argument(
        "--config",
        default="configs/experiment-planner/session8_config.v1.json",
        help="trusted Session 8 planner config JSON",
    )
    parser.add_argument("--output", default="artifacts/session8/experiment-plan.json")
    parser.add_argument("--registry", default="artifacts/session8/run-registry.json")
    args = parser.parse_args(argv)
    try:
        config = load_planner_config(args.config)
        plan = plan_experiment(Path(args.manifest), config)
        save_plan_atomic(args.output, plan)
        registry = RunRegistry(args.registry)
        added = _write_registry_cli(registry, plan)
    except (PlannerError, FileExistsError, OSError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Plan: {plan.plan_id}")
    print(f"Runs planned: {plan.run_count}; registered: {added}")
    print(f"Plan output: {args.output}")
    print(f"Registry: {args.registry}")
    print("No simulator, API, network endpoint or cloud job was invoked.")
    print(
        "Run status is 'planned'; no result is evidence until execution and analysis validate it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
