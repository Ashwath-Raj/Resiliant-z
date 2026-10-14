# Local discrete-event fleet model

## Purpose

`resiliant fleet-demo` offers a more behavior-driven CPU-only intermediate backend while Isaac Sim access is being arranged. It is meant for testing the experiment orchestration, evidence analysis, provenance, and policy-replay workflow on a laptop.

**It is not Isaac Sim, a physics-based digital twin, robot-control software, or evidence about real robots.** Never relabel its outputs as Isaac Sim results.

## Model assumptions

- Ten logical robots.
- A 900-second simulated horizon.
- Poisson task arrivals at `0.20 * traffic_demand` tasks per simulated second. `traffic_demand` is a scenario multiplier, not a real-world calibrated arrival rate.
- Tasks are assigned to an available robot; robots remain occupied through approach, route service and delivery/return.
- Through-tasks share one junction service queue; the `bypass_ratio` selects a separate route/server.
- Priority tasks are scheduled ahead of normal tasks and have longer service windows. This is an explicit scenario assumption intended to expose workload/capacity interactions, not a universal physical fact.
- Random events derive from the experiment manifest's seed. Metrics should be deterministic for the same code, manifest and Python runtime.
- Geometry, collisions, kinematics, sensors, battery, blocked paths and true deadlocks are not modeled. `deadlock_events=0` is structurally imposed, not a safety metric.

## Run it

```bash
.venv/bin/resiliant fleet-demo
```

Optional smaller smoke run (less statistical power):

```bash
.venv/bin/resiliant fleet-demo --output-dir artifacts/fleet-smoke --seeds-per-cell 3 --replay-seeds 3
```

The normal run uses 20 discovery runs, 20 held-out validation runs, and 24 paired policy-replay runs. The smoke run may be marked inconclusive; that is a valid scientific outcome.

## Decision rule

The analyzer compares a main-effects regression with a main-effects-plus-interaction regression. It also estimates a held-out difference-in-differences contrast:

`mean(high demand, high priority) - mean(high demand, low priority) - mean(low demand, high priority) + mean(low demand, low priority)`

A discovery is marked validated only when the discovery interaction estimate is negative, the conservative approximate 95% interval for the held-out contrast lies below zero, and the interaction model has lower held-out RMSE than the main-effects model. The interval uses a conservative cell-wise t approximation; report cell sizes and distributions and avoid universal causal claims.

Factor levels are configured experiment settings. This test does not discover continuous thresholds or establish generalization to new layouts.

## Output

`artifacts/fleet-demo/` contains `summary.json`, `discovery.json`, `hypotheses.json`, `manifests.jsonl`, `runs.jsonl`, and `report.md`. Each row keeps the experiment manifest and seed for traceability. Inspect `report.md` for the backend limitations.

## Relationship to Isaac Sim

Both simulator backends are intended to return the shared `SimulationRun` contract. The discrete-event backend is for local software development. The approved university Isaac Sim host must later run a documented scene and export measured telemetry that passes the CSV contract. The Isaac Sim integration is not implemented by this local model.

## Policy-selection protocol

A policy intervention is considered only after the held-out discovery gate returns `validated`. The runner then evaluates the predeclared bypass candidates `(0.00, 0.15, 0.30, 0.45)` on shared policy-selection seeds. It selects the candidate maximizing mean completed tasks within the fixed horizon; ties are broken by lower end-window queue-growth slope and then by the lower bypass ratio. Candidate-selection seeds are separate from the final paired replay seeds. If discovery is `inconclusive` or `rejected`, the intervention is blocked and the selected bypass ratio remains zero.

This is an explicit experimental policy-selection rule, not a learned continuous controller. The candidate list, high-stress operating condition, objective and tie-breaking order are fixed in advance and are recorded in the report. Final replay estimates the selected intervention's effect on new paired seeds.
