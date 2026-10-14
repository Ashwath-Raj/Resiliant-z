"""Simulator adapter contract. Backends must return the same validated metrics schema."""

from typing import Protocol

from resiliant_z.models import ExperimentManifest, SimulationRun


class SimulatorAdapter(Protocol):
    name: str

    def run(self, manifest: ExperimentManifest) -> SimulationRun:
        """Execute one manifest and return measured metrics plus provenance."""
        ...
