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
- Each bypass route that completes route service adds `bypass_detour_seconds` to the robot's return/availability time (default `2.5` simulated seconds; allowed range `0–30`). This represents an explicit detour cost. The default is a scenario-design value, not a measured or calibrated travel cost. The reported cumulative cost counts applied detour seconds in route completions observed within the horizon.
- Priority tasks are scheduled ahead of normal tasks and have longer service windows. This is an explicit scenario assumption intended to expose workload/capacity interactions, not a universal physical fact.
- Random events derive from the experiment manifest's seed. Metrics should be deterministic for the same code, manifest and Python runtime.
- Geometry, collisions, kinematics, sensors, battery, blocked paths and true deadlocks are not modeled. `deadlock_events` is null/unmeasured, not a safety metric.

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

A policy intervention is considered only after the held-out discovery gate returns `validated`. The runner then evaluates the predeclared bypass candidates `(0.00, 0.15, 0.30, 0.45)` on shared policy-selection seeds. It selects the candidate with the lowest predeclared weighted normalized operational penalty; exact score ties are broken by the lower bypass ratio. Candidate-selection seeds are separate from the final paired replay seeds. If discovery is `inconclusive` or `rejected`, the intervention is blocked and the selected bypass ratio remains zero.

The objective weights are fixed in code and emitted in `summary.json`: completion shortfall `0.40`, tasks not started by the horizon `0.20`, started-task wait normalized by 60 s `0.20`, queue growth normalized by arrival rate `0.10`, bypass detour capacity fraction `0.05`, and bypass intervention fraction `0.05`. Each component is normalized/capped to `[0, 1]`; lower scores are preferred. Completion shortfall and not-started fraction intentionally put extra weight on work that remains unfinished at the horizon. The weight choices are design judgments, not learned parameters or validated business costs.

This is an explicit experimental policy-selection rule, not a learned continuous controller. The candidate list, high-stress operating condition, objective weights and tie-breaking order are fixed in advance and recorded in the report. Final replay estimates the selected intervention's effect on new paired seeds; the score does not replace the underlying raw metrics.


## Three-arm conditional-policy comparison

The benchmark compares baseline (zero bypass), a static control using the selected bypass ratio, and a discovery-conditioned policy. It evaluates two fixed workload contexts: nominal (`traffic_demand=0.55`, `priority_ratio=0.15`) and high-risk (`1.05`, `0.50`). Each policy arm shares a seed within a condition, with per-task random variates pre-sampled so policy-dependent event ordering does not change the exogenous workload or service-time draws. Selection seeds are disjoint from the final paired replay seeds.

The conditioned arm only diverts when (1) discovery was independently validated and a nonzero ratio was selected by the pipeline, (2) the workload is in the predeclared high-demand/high-priority envelope (midpoints of the experimental factor levels), and (3) observed junction pressure is at least two tasks (one in service plus at least one queued). These thresholds are configured assumptions, not values discovered by the system. The report provides arm-level measures and paired treatment-minus-baseline differences with 95% Student-t intervals. Results remain evidence from this simplified queueing model, not Isaac Sim or physical robotics.


## Detour-cost sensitivity experiment

Use `resiliant fleet-sensitivity` to vary the configured robot-occupancy penalty after bypass-route service across `0, 2.5, 5, 10, 20, 30` simulated seconds. It runs the baseline, static and conditioned policy arms with paired seeds in both nominal and high-risk conditions. The selected bypass ratio remains fixed at `0.45` by default so the sweep tests the detour assumption without re-selecting the policy at each level. Override it with `--bypass-ratio` only when intentionally testing a different fixed ratio.

```bash
.venv/bin/resiliant fleet-sensitivity
# Small smoke run: fewer paired seeds and two cost levels
.venv/bin/resiliant fleet-sensitivity --output-dir artifacts/fleet-sensitivity-smoke --replay-seeds 3 --detour-costs 0 2.5
```

Artifacts include a human-readable `report.md`, structured `summary.json` with paired treatment-minus-control intervals, a long-form `sensitivity.csv`, and per-run `runs.jsonl` plus `manifests.jsonl`. The default run contains 432 simulations (6 detour levels × 2 operating conditions × 3 policy arms × 12 seeds). The confidence intervals are exploratory, unadjusted 95% Student-t intervals across multiple levels and metrics. The score weights are design judgments and the default 2.5-second detour is not calibrated from real-world route data. All outputs remain CPU discrete-event model evidence—not Isaac Sim or physical-robot evidence.
