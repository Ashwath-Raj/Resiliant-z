"""Shared, validated contracts for experiments and simulator outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model: reject undeclared fields at system boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExperimentParameters(StrictModel):
    """Inputs exposed by the controlled benchmark scenario."""

    traffic_demand: float = Field(
        ge=0.4, le=1.2, description="Normalized workload multiplier used by the controlled scenario"
    )
    priority_ratio: float = Field(ge=0.1, le=0.6, description="Fraction of priority tasks")
    bypass_ratio: float = Field(
        ge=0.0,
        le=0.5,
        description="Maximum/probabilistic fraction diverted when routing policy permits",
    )
    bypass_detour_seconds: float = Field(
        default=2.5,
        ge=0.0,
        le=30.0,
        description="Extra simulated robot-occupancy seconds charged to each bypass route completion",
    )
    routing_policy: Literal["static", "conditioned"] = Field(
        default="static",
        description="Static diversion or diversion gated by the validated operating envelope and live junction pressure",
    )


class ExperimentManifest(StrictModel):
    """Versioned, immutable-in-practice contract for one simulation run."""

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    scenario_id: str = Field(default="priority_junction_v1", min_length=3, max_length=80)
    scenario_version: str | None = Field(default=None, min_length=1, max_length=80)
    scenario_config_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    stage: Literal["discovery", "validation", "policy_selection", "replay"]
    seed: int = Field(ge=0, le=2**31 - 1)
    parameters: ExperimentParameters
    git_sha: str = "unknown"

    @model_validator(mode="before")
    @classmethod
    def infer_scenario_version(cls, values: object) -> object:
        if not isinstance(values, dict) or values.get("scenario_version") is not None:
            return values

        scenario_id = values.get("scenario_id", "priority_junction_v1")
        if not isinstance(scenario_id, str):
            return values
        _, separator, version = scenario_id.rpartition("_v")
        if not separator or not version or not all(part.isdigit() for part in version.split(".")):
            return values

        result = values.copy()
        result["scenario_version"] = version
        return result

    @field_validator("git_sha")
    @classmethod
    def normalize_sha(cls, value: str) -> str:
        return value.strip() or "unknown"


class ScenarioMetrics(StrictModel):
    """Outputs measured by a backend; unavailable values remain ``None``.

    ``average_wait_seconds`` in the discrete-event backend is the mean delay from
    task arrival until route-service start among tasks that actually started
    route service before the observation horizon. Unstarted tasks are right-censored
    and must be reported separately; they must not be silently counted as completed
    waits.
    """

    throughput_tasks_per_min: float | None = Field(default=None, ge=0)
    average_wait_seconds: float | None = Field(default=None, ge=0)
    queue_growth_per_min: float | None = Field(default=None, ge=0)
    junction_occupancy: float | None = Field(default=None, ge=0, le=1)
    deadlock_events: int | None = Field(default=None, ge=0)
    task_arrivals: int | None = Field(default=None, ge=0)
    task_completions: int | None = Field(default=None, ge=0)
    route_service_started_count: int | None = Field(default=None, ge=0)
    tasks_not_started_by_horizon: int | None = Field(default=None, ge=0)
    route_service_wait_total_seconds: float | None = Field(default=None, ge=0)
    censored_wait_observation_seconds: float | None = Field(default=None, ge=0)
    bypass_task_count: int | None = Field(default=None, ge=0)
    bypass_detour_total_seconds: float | None = Field(default=None, ge=0)
    high_risk_context_arrival_count: int | None = Field(default=None, ge=0)
    conditional_policy_trigger_count: int | None = Field(default=None, ge=0)


class RunProvenance(StrictModel):
    """Code, scenario configuration, and backend version associated with a run."""

    code_sha: str = Field(min_length=1)
    scenario_config_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    simulator_version: str | None = None


class SimulationRun(StrictModel):
    """Provenance-linked output from one backend execution."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    experiment: ExperimentManifest
    backend: Literal["surrogate", "discrete_event", "isaac_sim_import"]
    backend_version: str | None = None
    metrics: ScenarioMetrics
    started_at: datetime | None = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: Literal["completed", "failed", "timeout", "incomplete", "invalidated"] = "completed"
    notes: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    log_artifact: str | None = None
    provenance: RunProvenance | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_provenance(cls, values: object) -> object:
        if not isinstance(values, dict) or values.get("provenance") is not None:
            return values

        experiment = values.get("experiment")
        if isinstance(experiment, ExperimentManifest):
            code_sha = experiment.git_sha
            scenario_config_sha256 = experiment.scenario_config_sha256
        elif isinstance(experiment, dict):
            code_sha = (experiment.get("git_sha") or "unknown").strip() or "unknown"
            scenario_config_sha256 = experiment.get("scenario_config_sha256")
        else:
            return values

        result = values.copy()
        result["provenance"] = {
            "code_sha": code_sha,
            "scenario_config_sha256": scenario_config_sha256,
            "simulator_version": values.get("backend_version"),
        }
        return result

    @model_validator(mode="after")
    def validate_provenance(self) -> SimulationRun:
        if self.status == "completed":
            required_metrics = (
                self.metrics.throughput_tasks_per_min,
                self.metrics.average_wait_seconds,
                self.metrics.queue_growth_per_min,
                self.metrics.junction_occupancy,
            )
            if any(value is None for value in required_metrics):
                raise ValueError("completed runs require all core operational metrics")

        provenance = self.provenance
        if provenance is None:
            raise ValueError("run provenance is required")
        if self.experiment.git_sha != "unknown" and provenance.code_sha != self.experiment.git_sha:
            raise ValueError("provenance code_sha must match the experiment git_sha")
        if (
            self.experiment.scenario_config_sha256 is not None
            and provenance.scenario_config_sha256 != self.experiment.scenario_config_sha256
        ):
            raise ValueError("provenance scenario_config_sha256 must match the experiment manifest")
        if (
            self.backend_version is not None
            and provenance.simulator_version is not None
            and provenance.simulator_version != self.backend_version
        ):
            raise ValueError("provenance simulator_version must match backend_version")
        return self


class Hypothesis(StrictModel):
    """A proposed explanation; never accepted as evidence by itself."""

    hypothesis_id: str = Field(pattern=r"^H[0-9]+$")
    kind: Literal["main_effect", "interaction", "other"]
    factors: list[Literal["traffic_demand", "priority_ratio", "bypass_ratio"]] = Field(
        min_length=1, max_length=3
    )
    claim: str = Field(min_length=8, max_length=500)
    falsification_test: str = Field(min_length=8, max_length=500)


class HypothesisSet(StrictModel):
    hypotheses: list[Hypothesis] = Field(min_length=2, max_length=8)
    recommended_experiment: str = Field(min_length=8, max_length=500)


class DiscoveryDecision(StrictModel):
    status: Literal["validated", "rejected", "inconclusive"]
    claim: str
    interaction_effect: float
    discovery_main_effect_rmse: float
    discovery_interaction_rmse: float
    validation_main_effect_rmse: float
    validation_interaction_rmse: float
    validation_improvement_fraction: float
    sample_count_discovery: int
    sample_count_validation: int
    validation_interaction_effect: float | None = None
    validation_interaction_ci_lower: float | None = None
    validation_interaction_ci_upper: float | None = None
    limitations: list[str] = Field(default_factory=list)
