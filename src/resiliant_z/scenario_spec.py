"""Backend-independent, versioned warehouse scenario specification.

This is an experimental scene *description*, not a physics simulator or a
calibrated digital twin. The current discrete-event backend does not consume
spatial geometry; it remains a queueing model with explicit limitations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceLabel = Literal["LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM"]
CalibrationStatus = Literal["synthetic_uncalibrated", "measured_unverified", "calibrated"]


class ScenarioModel(BaseModel):
    """Reject undeclared fields so typos do not silently change a scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MapNode(ScenarioModel):
    node_id: str = Field(min_length=1)
    role: Literal["aisle", "intersection", "station", "charger", "spawn", "other"]
    x_m: float
    y_m: float
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class AisleSegment(ScenarioModel):
    aisle_id: str = Field(min_length=1)
    start_node_id: str = Field(min_length=1)
    end_node_id: str = Field(min_length=1)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    one_way: bool = False
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class ShelfRow(ScenarioModel):
    shelf_id: str = Field(min_length=1)
    aisle_id: str = Field(min_length=1)
    side: Literal["left", "right", "both"]
    length_m: float = Field(gt=0)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class Intersection(ScenarioModel):
    intersection_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    conflict_zone_id: str = Field(min_length=1)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class TaskStation(ScenarioModel):
    station_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    role: Literal["pickup", "dropoff", "combined"]
    service_time_s: float = Field(gt=0)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class ChargingArea(ScenarioModel):
    charging_area_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    charger_bays: int = Field(ge=1)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class RobotSpawn(ScenarioModel):
    spawn_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    x_m: float
    y_m: float
    yaw_rad: float
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"


class ScenarioFactor(ScenarioModel):
    """An experimental input, kept separate from policy configuration."""

    factor_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    min_value: float
    max_value: float
    test_levels: list[float] = Field(min_length=1)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"

    @model_validator(mode="after")
    def validate_range_and_levels(self) -> ScenarioFactor:
        if self.min_value >= self.max_value:
            raise ValueError("min_value must be strictly less than max_value")
        if any(level < self.min_value or level > self.max_value for level in self.test_levels):
            raise ValueError("all test_levels must lie within [min_value, max_value]")
        if len(set(self.test_levels)) != len(self.test_levels):
            raise ValueError("test_levels must be unique")
        return self


class PolicyParameter(ScenarioModel):
    """A controllable parameter, intentionally not a scenario factor."""

    parameter_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    min_value: float
    max_value: float
    default_value: float
    candidate_values: list[float] = Field(min_length=1)
    calibration_status: CalibrationStatus = "synthetic_uncalibrated"

    @model_validator(mode="after")
    def validate_range_and_candidates(self) -> PolicyParameter:
        if self.min_value > self.max_value:
            raise ValueError("min_value must be <= max_value")
        if not self.min_value <= self.default_value <= self.max_value:
            raise ValueError("default_value must lie within [min_value, max_value]")
        if any(value < self.min_value or value > self.max_value for value in self.candidate_values):
            raise ValueError("candidate_values must lie within [min_value, max_value]")
        if len(set(self.candidate_values)) != len(self.candidate_values):
            raise ValueError("candidate_values must be unique")
        return self


class WarehouseLayout(ScenarioModel):
    coordinate_unit: Literal["m"] = "m"
    angle_unit: Literal["rad"] = "rad"
    nodes: list[MapNode] = Field(min_length=2)
    aisles: list[AisleSegment] = Field(min_length=1)
    shelves: list[ShelfRow] = Field(default_factory=list)
    intersections: list[Intersection] = Field(min_length=1)
    task_stations: list[TaskStation] = Field(min_length=1)
    charging_areas: list[ChargingArea] = Field(min_length=1)
    robot_spawns: list[RobotSpawn] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_layout_references(self) -> WarehouseLayout:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node_id values must be unique")
        node_set = set(node_ids)

        aisle_ids = [aisle.aisle_id for aisle in self.aisles]
        if len(aisle_ids) != len(set(aisle_ids)):
            raise ValueError("aisle_id values must be unique")
        aisle_set = set(aisle_ids)
        for aisle in self.aisles:
            if aisle.start_node_id not in node_set or aisle.end_node_id not in node_set:
                raise ValueError(f"aisle {aisle.aisle_id!r} references an unknown node")
            if aisle.start_node_id == aisle.end_node_id:
                raise ValueError(f"aisle {aisle.aisle_id!r} must connect two different nodes")

        for shelf in self.shelves:
            if shelf.aisle_id not in aisle_set:
                raise ValueError(f"shelf {shelf.shelf_id!r} references an unknown aisle")

        def require_node(node_id: str, owner: str) -> None:
            if node_id not in node_set:
                raise ValueError(f"{owner} references unknown node {node_id!r}")

        for item in self.intersections:
            require_node(item.node_id, f"intersection {item.intersection_id!r}")
        for item in self.task_stations:
            require_node(item.node_id, f"task station {item.station_id!r}")
        for item in self.charging_areas:
            require_node(item.node_id, f"charging area {item.charging_area_id!r}")
        for item in self.robot_spawns:
            require_node(item.node_id, f"robot spawn {item.spawn_id!r}")

        for collection, field_name in (
            (self.intersections, "intersection_id"),
            (self.task_stations, "station_id"),
            (self.charging_areas, "charging_area_id"),
            (self.robot_spawns, "spawn_id"),
            (self.shelves, "shelf_id"),
        ):
            values = [getattr(item, field_name) for item in collection]
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} values must be unique")
        return self


class WarehouseScenario(ScenarioModel):
    schema_version: Literal["1.0.0"]
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    evidence_label: EvidenceLabel
    layout: WarehouseLayout
    scenario_factors: list[ScenarioFactor] = Field(min_length=1)
    policy_parameters: list[PolicyParameter] = Field(min_length=1)
    policy_mode_choices: list[str] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_factor_policy_separation(self) -> WarehouseScenario:
        factor_ids = [item.factor_id for item in self.scenario_factors]
        parameter_ids = [item.parameter_id for item in self.policy_parameters]
        if len(factor_ids) != len(set(factor_ids)):
            raise ValueError("scenario factor IDs must be unique")
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("policy parameter IDs must be unique")
        overlap = set(factor_ids) & set(parameter_ids)
        if overlap:
            raise ValueError(
                f"scenario factors and policy parameters must be separate: {sorted(overlap)}"
            )
        if len(set(self.policy_mode_choices)) != len(self.policy_mode_choices):
            raise ValueError("policy_mode_choices must be unique")
        return self


def load_warehouse_scenario(path: str | Path) -> WarehouseScenario:
    """Load and validate a scenario JSON file without importing Isaac packages."""
    return WarehouseScenario.model_validate_json(Path(path).read_text(encoding="utf-8"))


def parse_warehouse_scenario_json(raw_json: str) -> WarehouseScenario:
    """Parse and validate an in-memory scenario JSON document."""
    # Keep JSON errors and Pydantic validation errors explicit to callers.
    json.loads(raw_json)
    return WarehouseScenario.model_validate_json(raw_json)
