"""Typed runtime boundary for simulator backends.

The contract deliberately describes the existing experiment-manifest to
SimulationRun boundary; it does not claim to make the discrete-event model a
physics simulator or to execute a warehouse geometry specification.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from resiliant_z.models import ExperimentManifest, SimulationRun


@runtime_checkable
class SimulationBackend(Protocol):
    """Structural contract that local and future physics backends must satisfy."""

    name: str

    def run(self, manifest: ExperimentManifest) -> SimulationRun:
        """Execute one manifest and return a validated run result."""
        ...


def run_with_backend(backend: SimulationBackend, manifest: ExperimentManifest) -> SimulationRun:
    """Execute one run and enforce the shared return contract at runtime."""
    if not isinstance(backend, SimulationBackend):
        raise TypeError("backend must expose a non-empty name and run(manifest) method")
    backend_name = backend.name.strip()
    if not backend_name:
        raise ValueError("backend.name must be a non-empty string")

    result = backend.run(manifest)
    if not isinstance(result, SimulationRun):
        raise TypeError(
            f"backend {backend_name!r} returned {type(result).__name__}; expected SimulationRun"
        )
    if result.backend != backend_name:
        raise ValueError(
            "backend name mismatch: backend declares "
            f"{backend_name!r} but result records {result.backend!r}"
        )
    if result.experiment.experiment_id != manifest.experiment_id:
        raise ValueError("backend result does not preserve the input experiment_id")
    if result.experiment.seed != manifest.seed:
        raise ValueError("backend result does not preserve the input seed")
    return result
