# RESILIANT-Z — Session 2 implementation

## What this installs

This change set is an **additive local implementation** of Phase I, Session 2. It adds:

- `src/resiliant_z/scenario_spec.py`: a versioned Pydantic model for a backend-independent warehouse description, including aisle graph, shelves, intersections, pickup/drop-off stations, charging areas, robot spawn poses, factor ranges, and policy parameter ranges.
- `src/resiliant_z/simulation/backend_contract.py`: a runtime-checkable `SimulationBackend` protocol and one-run guard that verifies the shared `SimulationRun` result and experiment identity.
- `configs/warehouse_scenario.example.v1.json`: a sample synthetic scenario with three intersections, aisle segments, shelves, pickup/drop-off, charging capacity, and robot spawn poses.
- `tests/test_session2_scenario_contract.py`: parser, reference validation, factor/policy separation, and a single local backend smoke test.

## Important semantic boundary

The scenario JSON is deliberately **not wired into the current queueing model as physical geometry**. It records the spatial design intended for a future scene backend. The local discrete-event simulator remains the reference CPU backend and must continue to be reported as `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`.

The sample dimensions, shelf positions, service-time values, coordinates, factor levels, and candidate policy settings are synthetic/uncalibrated. They are not real-world measurements. This session does not validate geometry, kinematics, sensing, collisions, contacts, battery behavior, or physical deadlocks.

## Run and verify

From the repository root:

```bash
.venv/bin/python -m pytest -q tests/test_session2_scenario_contract.py
.venv/bin/ruff check src/resiliant_z/scenario_spec.py src/resiliant_z/simulation/backend_contract.py tests/test_session2_scenario_contract.py
.venv/bin/ruff format --check src/resiliant_z/scenario_spec.py src/resiliant_z/simulation/backend_contract.py tests/test_session2_scenario_contract.py
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pytest -q
```

The installation script runs available checks automatically and prints their real exit statuses. A failed check is not silently converted into success.

## Non-goals for Session 2

- No Session 3 telemetry implementation.
- No baseline residual model or persistent gap detector.
- No Isaac Sim import, install, download, launch, or asset access.
- No GPU/cloud job, Nebius API call, paid service, commit, or push.
- No overwrite of existing project files. The installer aborts if a target path already contains different content.
