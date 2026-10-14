# RESILIANT — Technical Implementation Plan

## 15-Session Build Roadmap

**Project:** RESILIANT  
**Track:** NVIDIA × Nebius Global AI Hackathon — Physical AI  
**Implementation target:** Pure-software multi-robot fleet discovery prototype  
**Primary stack:** NVIDIA Nemotron + NVIDIA Isaac Sim + Nebius AI Cloud / Token Factory + Nebius Serverless Jobs / Endpoints  
**Architecture principle:** LLM proposes; deterministic software validates; simulation experiments; evidence decides.

---

# 0. Implementation Objective

The implementation must prove one complete loop:

```text
LIVE / SIMULATED FLEET
        ↓
TELEMETRY
        ↓
MODEL / REALITY GAP
        ↓
NEMOTRON HYPOTHESES
        ↓
EXPERIMENT COMPILER
        ↓
EXPERIMENT SELECTION
        ↓
NEBIUS SERVERLESS JOBS
        ↓
ISAAC SIM COUNTERFACTUALS
        ↓
DETERMINISTIC EVIDENCE ANALYSIS
        ↓
DISCOVERY VALIDATION
        ↓
FLEET KNOWLEDGE UPDATE
        ↓
POLICY UPDATE
        ↓
REPLAY
```

The prototype does **not** need to build a commercial warehouse fleet manager.

It needs to demonstrate that the fleet can acquire and operationalize a previously absent fleet-specific relationship.

---

# 1. Non-Negotiable Engineering Principles

## 1.1 Nemotron is not the controller

Nemotron must never directly:

- command robot velocity;
- generate arbitrary executable simulation code;
- bypass safety bounds;
- directly modify the fleet controller;
- declare a discovery valid.

Nemotron is responsible for semantic reasoning and hypothesis generation.

---

## 1.2 All LLM output is untrusted

The pipeline is:

```text
Nemotron
   ↓
JSON schema
   ↓
Schema validation
   ↓
Parameter whitelist
   ↓
Range checks
   ↓
Experiment validation
   ↓
Simulation
```

Invalid output is rejected.

---

## 1.3 Simulation results, not LLM text, determine discoveries

Nemotron can say:

```text
"Hypothesis H3 appears plausible."
```

That is not evidence.

The evidence pipeline must independently evaluate:

```text
simulation → measurements → statistics → validation
```

---

## 1.4 Discovery requires independent validation

A rule cannot be promoted merely because it fits the experiments that generated it.

The discovery pipeline must separate:

```text
Discovery dataset
```

from:

```text
Validation dataset
```

---

# 2. Prototype Target

## Fleet

Target:

```text
20–35 AMRs
```

Recommended initial demonstration:

```text
35 simulated robots
```

The exact number is less important than demonstrating meaningful multi-agent interaction.

---

## Environment

Warehouse environment containing:

- storage zones;
- task pickup/drop zones;
- multiple junctions;
- narrow aisles;
- charging area;
- priority task region;
- traffic bottlenecks.

---

## Target phenomenon

Recommended first phenomenon:

> **Nonlinear congestion caused by the interaction between junction occupancy and priority-task concentration.**

Initial model intentionally does not encode the interaction.

---

# 3. System Architecture

```text
                       ┌───────────────────┐
                       │   Isaac Sim Fleet │
                       └─────────┬─────────┘
                                 │
                              telemetry
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Telemetry Adapter │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ State Aggregator  │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Gap Detector      │
                       └─────────┬─────────┘
                                 │
                         investigation trigger
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Nemotron Reasoner │
                       └─────────┬─────────┘
                                 │
                          hypothesis JSON
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Semantic Compiler │
                       └─────────┬─────────┘
                                 │
                         valid experiments
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Experiment Planner│
                       └─────────┬─────────┘
                                 │
                           job manifests
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Nebius Jobs       │
                       └─────────┬─────────┘
                                 │
                         parallel simulations
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Isaac Sim         │
                       └─────────┬─────────┘
                                 │
                           raw results
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Evidence Analyzer │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Discovery Engine  │
                       └─────────┬─────────┘
                                 │
                            validation
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Knowledge Model   │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Policy Generator  │
                       └─────────┬─────────┘
                                 │
                                 ▼
                       ┌───────────────────┐
                       │ Fleet Replay      │
                       └───────────────────┘
```

---

# Session 1 — Repository, Infrastructure & Contract Setup

## Objective

Create the project skeleton and establish all interface contracts before implementing intelligence.

## Deliverables

```text
resiliant/
├── agent/
├── telemetry/
├── experiments/
├── simulation/
├── evidence/
├── discovery/
├── knowledge/
├── policy/
├── api/
├── configs/
├── tests/
├── scripts/
└── docs/
```

Define:

- Python environment;
- container strategy;
- configuration format;
- logging;
- experiment IDs;
- simulation run IDs;
- result schema;
- error handling;
- local development mode.

## Critical contract

Every simulation must have:

```text
experiment_id
run_id
seed
scenario_id
parameters
software_version
timestamp
```

This makes experiments reproducible.

## Acceptance criterion

A dummy experiment can move through:

```text
manifest → execution → result JSON
```

without any LLM dependency.

---

# Session 2 — Warehouse Simulation Environment

## Objective

Build the minimum deterministic warehouse world.

## Components

- floor;
- shelves;
- aisles;
- junctions;
- task stations;
- charging zone;
- robot spawn points.

## Robot state

Each robot should expose at least:

```text
position
velocity
heading
current_task
task_priority
battery
navigation_state
waiting_time
```

## Environment state

```text
junction occupancy
queue length
task arrival rate
priority ratio
throughput
collision/near-collision events
deadlocks
```

## Acceptance criterion

At least 20 robots can execute tasks repeatedly in simulation.

---

# Session 3 — Fleet Telemetry Pipeline

## Objective

Convert simulation state into a stable telemetry stream.

## Raw telemetry

The simulator may generate high-frequency data.

Do not send that directly to Nemotron.

Create:

```text
Raw state
   ↓
Windowing
   ↓
Aggregation
   ↓
Semantic state
```

## Example

```json
{
  "time_window": 30,
  "fleet": {
    "robots": 35,
    "active": 32
  },
  "junctions": {
    "C": {
      "occupancy_mean": 0.78,
      "occupancy_p95": 0.84,
      "queue_mean": 11.2,
      "queue_growth": 3.4
    }
  },
  "demand": {
    "arrival_rate": 17.8,
    "priority_ratio": 0.42
  },
  "performance": {
    "throughput": 0.61,
    "baseline_expected": 0.83
  }
}
```

## Acceptance criterion

Telemetry can be persisted and replayed independently of the simulator.

---

# Session 4 — Baseline Fleet Model

## Objective

Create the model against which unexplained behavior will be measured.

The model should encode normal operational expectations.

Possible baseline:

```text
expected throughput = f(
    demand,
    fleet size,
    robot availability,
    nominal occupancy
)
```

It can initially be simple.

The objective is not to build a perfect predictor.

The objective is to establish a measurable expectation.

## Output

For each observation:

```json
{
  "expected": 0.83,
  "observed": 0.61,
  "residual": -0.22
}
```

## Acceptance criterion

The system can quantify the difference between expected and observed behavior.

---

# Session 5 — Model/Reality Gap Detector

## Objective

Prevent unnecessary investigations.

A trigger should require more than one noisy observation.

Possible trigger logic:

```text
residual > threshold
AND
persistent for N windows
AND
confidence > threshold
```

Example:

```python
if abs(z_score) > 2.5 and persistence >= 3:
    trigger_investigation()
```

The exact threshold must be empirically tuned.

## Additional checks

Reject triggers caused by:

- simulator startup;
- missing telemetry;
- invalid data;
- known scenario transitions;
- job failures.

## Acceptance criterion

Normal variance does not continuously trigger investigations.

Injected abnormal behavior does.

---

# Session 6 — Nemotron Reasoning Layer

## Objective

Connect Nemotron through Nebius model serving.

## Input

Semantic telemetry + historical context.

## Output

Strictly structured hypotheses.

Example:

```json
{
  "investigation": "INV-003",
  "hypotheses": [
    {
      "id": "H1",
      "claim": "junction occupancy is the primary driver",
      "variables": [
        "junction_C_occupancy"
      ]
    },
    {
      "id": "H2",
      "claim": "priority concentration is the primary driver",
      "variables": [
        "priority_ratio"
      ]
    },
    {
      "id": "H3",
      "claim": "occupancy and priority concentration interact",
      "variables": [
        "junction_C_occupancy",
        "priority_ratio"
      ]
    }
  ]
}
```

## Prompt requirements

The system prompt must instruct Nemotron to:

- generate multiple hypotheses;
- avoid declaring any hypothesis true;
- use only registered variables;
- provide testable claims;
- output schema-conforming JSON.

## Acceptance criterion

A malformed or unsupported hypothesis is rejected automatically.

---

# Session 7 — Semantic Experiment Compiler

## Objective

Convert semantic hypotheses into executable experiment specifications.

## Allowed parameters

Create a strict registry:

```yaml
junction_C_occupancy:
  type: float
  min: 0.0
  max: 1.0

priority_ratio:
  type: float
  min: 0.0
  max: 1.0

robot_count:
  type: integer
  min: 1
  max: 50
```

The LLM cannot invent:

```text
"warp_factor"
"gravity_override"
"disable_collision"
```

unless those parameters are explicitly registered.

## Compiler stages

```text
Parse
 ↓
Schema validate
 ↓
Whitelist validate
 ↓
Type validate
 ↓
Range validate
 ↓
Cross-parameter validate
 ↓
Generate manifest
```

## Acceptance criterion

Every accepted Nemotron experiment can be executed without manual editing.

---

# Session 8 — Experiment Planner

## Objective

Select useful experiments rather than blindly sweeping the entire state space.

For the initial MVP, use a simple and defensible strategy.

### Option A — hypothesis discrimination

For each candidate experiment, estimate how differently each hypothesis predicts the outcome.

Prefer experiments that maximize expected separation.

### Option B — uncertainty sampling

Run experiments near regions where the current evidence is uncertain.

### Option C — staged search

```text
coarse sweep
    ↓
identify transition region
    ↓
fine sweep
    ↓
validation
```

The MVP should favor the third option because it is easier to explain and verify.

## Example

```text
0.50
0.60
0.70
0.80
0.90
```

If the transition appears around:

```text
0.70–0.80
```

run:

```text
0.70
0.72
0.74
0.76
0.78
0.80
```

## Acceptance criterion

The planner produces reproducible experiment manifests.

---

# Session 9 — Nebius Serverless Simulation Orchestration

## Objective

Execute simulation experiments as independent jobs.

Conceptually:

```text
Experiment Manifest
       ↓
Nebius Job
       ↓
Container
       ↓
Isaac Sim
       ↓
metrics.json
```

Parallelize independent experiments.

Example:

```text
                    Experiment batch
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
        Job A          Job B          Job C
          │              │              │
       Isaac          Isaac          Isaac
        Sim             Sim            Sim
          │              │              │
       result          result         result
          └──────────────┼──────────────┘
                         ▼
                  Evidence store
```

## Requirements

Each job must return:

```json
{
  "experiment_id": "EXP-17",
  "run_id": "RUN-17-03",
  "seed": 103,
  "parameters": {},
  "metrics": {},
  "status": "success"
}
```

## Failure handling

Jobs can:

- fail;
- timeout;
- return incomplete results.

These must be marked invalid rather than silently treated as evidence.

---

# Session 10 — Evidence Analyzer

## Objective

Turn simulation output into numerical evidence.

Metrics:

```text
throughput
mean waiting time
queue growth
task completion time
deadlocks
near-collisions
robot utilization
```

## Data quality checks

Reject runs with:

- missing metrics;
- invalid robot states;
- physics instability;
- simulation timeout;
- impossible values.

## Aggregation

For repeated seeds:

```text
mean
median
standard deviation
confidence interval
```

The goal is to estimate whether the observed relationship is stable.

## Acceptance criterion

The system can produce an experiment report without asking Nemotron to calculate the numbers.

---

# Session 11 — Deterministic Discovery Engine

## Objective

Extract candidate fleet relationships.

A first implementation can use interpretable statistical models.

For example:

```text
queue_growth ~
    occupancy
    + priority_ratio
    + occupancy × priority_ratio
```

The interaction term is important.

If:

```text
occupancy × priority_ratio
```

substantially improves explanatory power, that becomes a candidate relationship.

Alternative implementation:

- decision tree;
- change-point detection;
- piecewise regression;
- generalized additive model.

## Output

Example:

```json
{
  "candidate": "DISC-007",
  "relationship": {
    "conditions": [
      {
        "variable": "junction_C_occupancy",
        "operator": ">",
        "value": 0.73
      },
      {
        "variable": "priority_ratio",
        "operator": ">",
        "value": 0.35
      }
    ],
    "effect": "rapid_queue_growth"
  }
}
```

## Important

The output is a:

> **candidate operational relationship**

not automatically a causal law.

---

# Session 12 — Independent Discovery Validation

## Objective

Determine whether the candidate relationship generalizes.

Split:

```text
Discovery data
──────────────
used to find relationship

Validation data
───────────────
never used to discover threshold
```

Vary:

- random seed;
- demand pattern;
- initial robot positions;
- task distribution;
- robot availability.

## Acceptance criterion

A candidate is promoted only if it satisfies predefined validation criteria.

Example:

```text
replication ≥ 80%
effect direction consistent
confidence interval excludes baseline
unseen scenarios confirm trend
```

These numbers are provisional and must be tuned from experiments.

---

# Session 13 — Fleet Knowledge Model

## Objective

Persist validated discoveries in a machine-readable form.

Example:

```yaml
discovery_id: DISC-007

phenomenon: junction_congestion

conditions:
  - variable: junction_C_occupancy
    operator: ">"
    threshold: 0.73

  - variable: priority_ratio
    operator: ">"
    threshold: 0.35

effect:
  metric: queue_growth
  regime: nonlinear

evidence:
  runs: 120
  validation_runs: 40
  seeds: 20

confidence:
  replication: 0.87

status: validated
```

The knowledge model should support:

- versioning;
- provenance;
- confidence;
- evidence links;
- rollback;
- invalidation.

## Acceptance criterion

A discovery can be loaded into a fresh runtime without conversational context.

---

# Session 14 — Policy Generation & Fleet Replay

## Objective

Demonstrate that discovered knowledge changes future fleet behavior.

Example:

```text
IF
junction_C_occupancy > 0.73
AND
priority_ratio > 0.35

THEN
reduce task concentration at Junction C
```

The policy layer must translate this into a deterministic fleet-management action.

Possible MVP action:

```text
reduce assignment weight
to tasks routing through Junction C
```

or:

```text
increase alternate-route preference
```

## Safety

The policy must remain inside predefined operational limits.

## Replay experiment

Run:

```text
Scenario A — baseline knowledge
Scenario B — updated knowledge
```

Compare:

```text
throughput
queue growth
waiting time
deadlocks
recovery time
```

## Acceptance criterion

The same problematic scenario demonstrates measurable improvement after the knowledge update.

---

# Session 15 — End-to-End Demo, Evaluation & Hardening

## Objective

Integrate everything and create a reproducible demonstration.

## Required sequence

```text
START
  │
  ▼
35-robot fleet operating normally
  │
  ▼
Priority-demand disruption
  │
  ▼
Performance degradation
  │
  ▼
Model/Reality Gap detected
  │
  ▼
Nemotron generates hypotheses
  │
  ▼
Experiment compiler validates them
  │
  ▼
Experiment planner selects tests
  │
  ▼
Nebius launches parallel jobs
  │
  ▼
Isaac Sim executes counterfactuals
  │
  ▼
Evidence analyzer processes results
  │
  ▼
Candidate relationship extracted
  │
  ▼
Independent validation
  │
  ├──────── FAIL ────────► Reject
  │
  ▼ PASS
Fleet knowledge updated
  │
  ▼
Policy generated
  │
  ▼
Same disruption replayed
  │
  ▼
Improved fleet behavior
  │
  ▼
DONE
```

## Demo requirements

Show actual modules operating:

1. fleet simulation;
2. telemetry;
3. anomaly/model-gap detection;
4. Nemotron hypothesis generation;
5. experiment manifest;
6. Nebius jobs;
7. simulation outputs;
8. discovery;
9. validation;
10. knowledge update;
11. policy change;
12. replay comparison.

A static architecture diagram is insufficient.

---

# 16. Recommended Repository Architecture

```text
resiliant/
│
├── agent/
│   ├── reasoner.py
│   ├── prompts/
│   └── schemas.py
│
├── telemetry/
│   ├── collector.py
│   ├── aggregator.py
│   └── semantic_state.py
│
├── monitoring/
│   ├── baseline.py
│   ├── residuals.py
│   └── gap_detector.py
│
├── experiments/
│   ├── compiler.py
│   ├── planner.py
│   ├── registry.py
│   └── manifest.py
│
├── simulation/
│   ├── isaac/
│   ├── scenario.py
│   ├── runner.py
│   └── metrics.py
│
├── cloud/
│   ├── nebius_jobs.py
│   └── endpoint_client.py
│
├── evidence/
│   ├── validator.py
│   ├── analyzer.py
│   └── statistics.py
│
├── discovery/
│   ├── extractor.py
│   ├── relationships.py
│   └── validation.py
│
├── knowledge/
│   ├── store.py
│   ├── schema.py
│   └── versioning.py
│
├── policy/
│   ├── generator.py
│   ├── validator.py
│   └── executor.py
│
├── dashboard/
│
├── configs/
│
├── tests/
│
├── scripts/
│
├── Dockerfile
├── LICENSE
└── README.md
```

---

# 17. Core Data Contracts

## Telemetry

```json
{
  "timestamp": "...",
  "fleet": {},
  "spatial": {},
  "demand": {},
  "performance": {}
}
```

## Hypothesis

```json
{
  "id": "H3",
  "claim": "...",
  "variables": [],
  "expected_effect": {}
}
```

## Experiment

```json
{
  "experiment_id": "EXP-001",
  "hypothesis_ids": ["H1", "H2", "H3"],
  "parameters": {},
  "seeds": [],
  "scenario": {}
}
```

## Result

```json
{
  "experiment_id": "EXP-001",
  "run_id": "RUN-001",
  "seed": 42,
  "status": "success",
  "metrics": {}
}
```

## Discovery

```json
{
  "discovery_id": "DISC-001",
  "conditions": [],
  "effect": {},
  "evidence": {},
  "validation": {},
  "status": "validated"
}
```

---

# 18. State Machine

The runtime should be implemented as an explicit state machine.

```text
OBSERVE
   ↓
GAP_DETECTED
   ↓
HYPOTHESIZE
   ↓
COMPILE
   ↓
PLAN
   ↓
SIMULATE
   ↓
ANALYZE
   ↓
VALIDATE
   │
   ├── REJECT → HYPOTHESIZE
   │
   ▼
DISCOVER
   ↓
UPDATE_KNOWLEDGE
   ↓
GENERATE_POLICY
   ↓
REPLAY
   ↓
OBSERVE
```

This makes the agent runtime auditable and prevents uncontrolled LLM loops.

---

# 19. Failure-State Handling

Every stage needs explicit failure behavior.

## Nemotron failure

```text
retry
→ fallback hypothesis template
→ terminate investigation if repeated
```

## Invalid LLM output

```text
schema rejection
→ regenerate
```

## Compiler failure

```text
reject experiment
→ return error
```

## Nebius job failure

```text
mark run invalid
→ retry if appropriate
→ never count failed run as evidence
```

## Isaac Sim failure

```text
discard result
→ record simulator failure
```

## Discovery validation failure

```text
reject candidate
→ retain investigation history
```

---

# 20. Testing Strategy

## Unit tests

Test:

- schemas;
- compiler;
- bounds;
- state aggregation;
- anomaly detector;
- statistics;
- knowledge persistence.

## Integration tests

Test:

```text
Nemotron → compiler
compiler → simulation
simulation → evidence
evidence → discovery
discovery → knowledge
knowledge → policy
```

## Failure tests

Intentionally send:

```text
invalid JSON
unknown parameter
out-of-range value
missing metric
failed job
corrupt simulation result
```

The system must fail closed.

---

# 21. Reproducibility

Every result must be traceable.

Use:

```text
experiment ID
+
simulation seed
+
scenario version
+
configuration version
+
code commit
+
model identifier
```

This is particularly important because the project claims experimental discovery.

A discovery that cannot be reproduced is weak evidence.

---

# 22. Experimental Evaluation Matrix

## Baseline 1 — Reactive

```text
Detect congestion
→ react
```

## Baseline 2 — Fixed policy

```text
Use existing policy
```

## Baseline 3 — Blind sweep

```text
Run predefined parameter grid
```

## RESILIANT

```text
Detect
→ hypothesize
→ select experiment
→ simulate
→ discover
→ validate
→ update
```

Compare all four.

---

# 23. Primary Metrics

## Fleet performance

```text
throughput ↑
waiting time ↓
queue length ↓
task completion time ↓
deadlocks ↓
```

## Discovery performance

```text
valid discovery rate ↑
false discovery rate ↓
validation success ↑
```

## Compute efficiency

```text
simulation runs / validated discovery ↓
```

## Adaptation value

```text
baseline degradation
vs
post-discovery degradation
```

---

# 24. What the Team Must Actually Build

The minimum credible implementation is:

```text
✓ Multi-robot Isaac Sim environment
✓ Telemetry pipeline
✓ Baseline model
✓ Model/reality gap detector
✓ Nemotron hypothesis generator
✓ Strict JSON schemas
✓ Semantic experiment compiler
✓ Experiment planner
✓ Nebius Serverless simulation execution
✓ Deterministic evidence analyzer
✓ Candidate relationship extractor
✓ Independent validation
✓ Persistent knowledge model
✓ Deterministic policy update
✓ Before/after replay
```

The following are optional and should not consume MVP time:

```text
✗ Full commercial fleet manager
✗ Physical robots
✗ Full reinforcement-learning stack
✗ General-purpose autonomous coding agent
✗ Multi-warehouse support
✗ Perfect causal inference
✗ Universal fleet ontology
```

---

# 25. Critical Scope Control

The team should resist the temptation to make the system "more AI."

More AI does not automatically make the project stronger.

The strongest architecture is:

```text
LLM
 ↓
Hypothesis

Deterministic system
 ↓
Experiment

Physics simulator
 ↓
Evidence

Statistics
 ↓
Validation

Knowledge model
 ↓
Policy
```

Each component has one job.

---

# 26. Final Engineering Definition

RESILIANT is complete when the following statement can be demonstrated truthfully:

> **A simulated autonomous fleet began with an incomplete operational model. After encountering unexplained fleet-level behavior, RESILIANT used NVIDIA Nemotron to generate competing hypotheses, converted those hypotheses into constrained experiments, executed counterfactual fleet simulations through NVIDIA Isaac Sim on Nebius infrastructure, extracted and independently validated a fleet-specific operational relationship, stored that relationship as machine-readable knowledge, and used the new knowledge to produce measurably different behavior when the problematic condition was replayed.**

That is the implementation target.

Everything else is secondary.
