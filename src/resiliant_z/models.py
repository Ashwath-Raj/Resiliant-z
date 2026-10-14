"""Shared, validated contracts for experiments and simulator outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model: reject undeclared fields at system boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExperimentParameters(StrictModel):
    """Inputs exposed by the controlled benchmark scenario."""

    traffic_demand: float = Field(ge=0.4, le=1.2, description="Normalized workload multiplier used by the controlled scenario")
    priority_ratio: float = Field(ge=0.1, le=0.6, description="Fraction of priority tasks")
    bypass_ratio: float = Field(ge=0.0, le=0.5, description="Fraction of traffic diverted from the junction")


class ExperimentManifest(StrictModel):
    """Immutable-in-practice contract for one simulation run."""

    experiment_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    scenario_id: str = Field(default="priority_junction_v1", min_length=3, max_length=80)
    stage: Literal["discovery", "validation", "policy_selection", "replay"]
    seed: int = Field(ge=0, le=2**31 - 1)
    parameters: ExperimentParameters
    git_sha: str = "unknown"

    @field_validator("git_sha")
    @classmethod
    def normalize_sha(cls, value: str) -> str:
        return value.strip() or "unknown"


class ScenarioMetrics(StrictModel):
    """Measured outputs. They are metrics, not claims about real hardware.

    ``average_wait_seconds`` in the discrete-event backend is the mean delay from
    task arrival until route-service start among tasks that actually started
    route service before the observation horizon. Unstarted tasks are right-censored
    and must be reported separately; they must not be silently counted as completed
    waits.
    """

    throughput_tasks_per_min: float = Field(ge=0)
    average_wait_seconds: float = Field(ge=0)
    queue_growth_per_min: float = Field(ge=0)
    junction_occupancy: float = Field(ge=0, le=1)
    deadlock_events: int = Field(ge=0)
    task_arrivals: int | None = Field(default=None, ge=0)
    task_completions: int | None = Field(default=None, ge=0)
    route_service_started_count: int | None = Field(default=None, ge=0)
    tasks_not_started_by_horizon: int | None = Field(default=None, ge=0)
    route_service_wait_total_seconds: float | None = Field(default=None, ge=0)
    censored_wait_observation_seconds: float | None = Field(default=None, ge=0)


class SimulationRun(StrictModel):
    """Provenance-linked output from one backend execution."""

    run_id: str
    experiment: ExperimentManifest
    backend: Literal["surrogate", "discrete_event", "isaac_sim_import"]
    metrics: ScenarioMetrics
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["completed", "failed"] = "completed"
    notes: list[str] = Field(default_factory=list)


class Hypothesis(StrictModel):
    """A proposed explanation; never accepted as evidence by itself."""

    hypothesis_id: str = Field(pattern=r"^H[0-9]+$")
    kind: Literal["main_effect", "interaction", "other"]
    factors: list[Literal["traffic_demand", "priority_ratio", "bypass_ratio"]] = Field(min_length=1, max_length=3)
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
