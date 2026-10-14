# RESILIANT

## Autonomous Fleet Operational Discovery Through Simulation

> **Today's fleets optimize the rules they were given. RESILIANT investigates where those rules fail, experimentally discovers fleet-specific operational relationships, and turns validated discoveries into new policy.**

---

# 1. Project Overview

RESILIANT is a software-defined Physical AI system for autonomous multi-robot fleets.

It is designed around a simple observation:

**A fleet can be highly autonomous without being capable of discovering that its own operating model is incomplete.**

Existing fleet systems can already:

- assign tasks;
- route robots;
- avoid collisions;
- balance workloads;
- react to failures;
- optimize known objectives;
- operate using predefined traffic and scheduling policies.

RESILIANT targets a different capability.

When the fleet behaves differently from what its current model predicts, RESILIANT treats the deviation as an **investigation problem** rather than simply another runtime error.

It asks:

```text
What happened?
      ↓
Why might it have happened?
      ↓
Which explanations can be experimentally distinguished?
      ↓
What does simulation say?
      ↓
Does the evidence support a new relationship?
      ↓
Does that relationship survive independent validation?
      ↓
Can the fleet use that knowledge?
```

The result is a closed loop between:

```text
Physical AI reasoning
        +
multi-robot simulation
        +
cloud-scale experimentation
        +
deterministic evidence
        +
machine-readable fleet knowledge
```

---

# 2. The Problem

## Autonomous fleets are good at executing known intelligence.

A modern warehouse can contain dozens or hundreds of autonomous mobile robots.

The system may already know:

```text
Robot capabilities
Warehouse map
Task priorities
Traffic rules
Battery constraints
Routing policies
Task allocation logic
```

But these inputs do not completely describe the behavior of the resulting multi-agent system.

Fleet-level behavior is emergent.

Small changes can interact:

```text
robot density
+
junction occupancy
+
priority demand
+
route concentration
+
fleet composition
+
task arrival rate
```

and create effects that are not obvious from any individual component.

For example:

```text
Moderate occupancy       → acceptable
High priority demand     → acceptable

Moderate occupancy
+
high priority demand
→ severe nonlinear congestion
```

The individual rules may all be reasonable.

Their interaction may not be.

This creates a gap between:

> **what the fleet's model says should happen**

and:

> **what the fleet actually does.**

RESILIANT is designed to investigate that gap.

---

# 3. The Core Question

The project asks:

> **Can an autonomous multi-robot fleet discover and validate a fleet-level operational relationship that was not explicitly encoded in its initial knowledge model?**

This is deliberately narrower than claiming general-purpose self-learning robotics.

The prototype targets one experimentally measurable capability:

```text
unknown operational relationship
        ↓
autonomous investigation
        ↓
validated discovery
        ↓
policy adaptation
```

---

# 4. What RESILIANT Is Not

RESILIANT is not:

- a replacement for a robot controller;
- a new path-planning algorithm;
- a new reinforcement-learning algorithm;
- a general-purpose LLM robotics controller;
- a chatbot controlling robots;
- a claim that LLMs can safely control robots directly;
- a claim of universal causal discovery;
- a commercial warehouse fleet-management system.

The LLM does not directly control robot motors or low-level navigation.

The simulator does not automatically determine what a discovery means.

The project intentionally separates these responsibilities.

---

# 5. What RESILIANT Does

The system consists of an autonomous investigation pipeline.

```text
1. Observe fleet
        ↓
2. Detect persistent model/reality gap
        ↓
3. Generate competing hypotheses
        ↓
4. Compile hypotheses into bounded experiments
        ↓
5. Select informative experiments
        ↓
6. Execute parallel counterfactual simulations
        ↓
7. Analyze experimental evidence
        ↓
8. Extract candidate relationship
        ↓
9. Validate on unseen experiments
        ↓
10. Store validated discovery
        ↓
11. Generate bounded policy change
        ↓
12. Replay the original problem
```

The critical property is that the final discovery is **not supplied to the system beforehand**.

---

# 6. Example Discovery Scenario

Consider a simulated warehouse with:

```text
35 autonomous mobile robots
multiple junctions
dynamic task arrivals
priority orders
narrow aisles
central task allocation
```

The initial fleet model knows that congestion increases with occupancy.

It does **not** know a particular interaction between:

```text
junction occupancy
```

and:

```text
priority-task concentration
```

A workload shift occurs.

The fleet experiences:

```text
throughput ↓
queue growth ↑
waiting time ↑
```

while the initial model predicts considerably better performance.

RESILIANT detects a persistent deviation.

---

# 7. Hypothesis Generation

NVIDIA Nemotron receives a compressed semantic representation of the fleet state.

It does not receive raw high-frequency robot logs.

Example:

```json
{
  "robots": 35,
  "junction_C_occupancy": 0.78,
  "priority_ratio": 0.42,
  "queue_growth": 3.4,
  "throughput": 0.61,
  "expected_throughput": 0.82
}
```

Nemotron generates competing hypotheses.

For example:

```text
H1:
Junction occupancy independently explains the degradation.

H2:
Priority-task concentration independently explains the degradation.

H3:
The interaction between occupancy and priority concentration
creates the degradation.
```

Nemotron is a **hypothesis generator**, not a scientific oracle.

---

# 8. Experiment Compilation

The generated hypotheses are translated into structured experiment specifications.

Nemotron cannot execute arbitrary code.

A deterministic compiler verifies:

```text
JSON schema
      ↓
allowed variables
      ↓
types
      ↓
parameter ranges
      ↓
cross-parameter constraints
      ↓
experiment manifest
```

Example:

```json
{
  "experiment_id": "EXP-017",
  "variables": {
    "junction_C_occupancy": 0.75,
    "priority_ratio": 0.40
  },
  "duration": 300,
  "seed": 103
}
```

Unsupported requests are rejected.

This creates a hard boundary between:

```text
probabilistic language reasoning
```

and:

```text
deterministic physical experimentation
```

---

# 9. Counterfactual Simulation

The experiment manifests are submitted as independent simulation jobs.

Nebius provides the cloud execution layer.

NVIDIA Isaac Sim provides the simulated physical environment.

Conceptually:

```text
                Experiment Planner
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Job A          Job B        Job C
          │            │            │
       Isaac Sim    Isaac Sim    Isaac Sim
          │            │            │
          ▼            ▼            ▼
       metrics      metrics      metrics
          └────────────┼────────────┘
                       ▼
                 Evidence Store
```

The experiments vary controlled conditions.

This allows the system to distinguish:

```text
occupancy effect
```

from:

```text
priority effect
```

from:

```text
interaction effect
```

---

# 10. Evidence Is Independent of Nemotron

This is a critical architectural property.

Nemotron can propose:

```text
"H3 is plausible."
```

But that statement is not evidence.

The evidence pipeline computes metrics such as:

```text
throughput
queue length
queue growth
waiting time
task completion time
deadlocks
near-collisions
robot utilization
```

Repeated experiments can use different seeds and conditions.

The system then evaluates whether the observed relationship is stable.

---

# 11. Discovery

Suppose the experiments produce:

```text
Occupancy alone
→ manageable degradation

Priority concentration alone
→ manageable degradation

Occupancy + priority concentration
→ nonlinear queue growth
```

The deterministic discovery layer can extract a candidate relationship.

For example:

```yaml
conditions:
  occupancy:
    operator: ">"
    threshold: 0.73

  priority_ratio:
    operator: ">"
    threshold: 0.35

effect:
  queue_growth: nonlinear
```

The threshold is derived from experimental data.

It is not generated by the LLM.

Nemotron can subsequently explain the result in natural language, but the numerical evidence comes from the experiments.

---

# 12. Independent Validation

A discovery is not accepted immediately.

The candidate relationship is evaluated on data that was not used to discover it.

Validation varies:

- random seed;
- initial robot positions;
- task distribution;
- demand pattern;
- robot availability;
- operating conditions.

The system asks:

> Does the relationship reproduce?

If not:

```text
Candidate rejected.
```

If yes:

```text
Candidate promoted to validated fleet knowledge.
```

This prevents the demonstration from being reduced to:

```text
fit a rule → declare victory.
```

---

# 13. Fleet Knowledge

Validated discoveries become persistent machine-readable knowledge.

Example:

```yaml
discovery_id: DISC-007

phenomenon: nonlinear_junction_congestion

conditions:
  junction_C_occupancy: "> 0.73"
  priority_ratio: "> 0.35"

effect:
  queue_growth: nonlinear

evidence:
  discovery_runs: 120
  validation_runs: 40

confidence:
  replication: 0.87

status: validated
```

The knowledge has provenance.

It can be:

- inspected;
- versioned;
- reproduced;
- rolled back;
- invalidated.

The objective is not simply to store a text explanation.

The objective is to create operational knowledge that software can use.

---

# 14. Policy Adaptation

Once validated, the discovery can influence fleet policy.

For example:

```text
IF
junction_C_occupancy > 0.73
AND
priority_ratio > 0.35

THEN
reduce assignment concentration through Junction C
within predefined limits.
```

The exact action is deterministic.

RESILIANT does not let Nemotron invent arbitrary robot commands.

The policy layer translates validated knowledge into an authorized fleet-level policy adjustment.

---

# 15. The Proof

The strongest demonstration is a controlled replay.

## Before discovery

```text
35 robots
+
problematic workload
+
original knowledge
=
high congestion
```

## Investigation

```text
model/reality gap
→ hypotheses
→ experiments
→ evidence
→ validation
```

## After discovery

```text
35 robots
+
same warehouse
+
same workload
+
new validated knowledge
=
improved operation
```

Compare:

```text
throughput
queue growth
waiting time
task completion time
deadlocks
```

The project should demonstrate measurable improvement rather than merely displaying a generated explanation.

---

# 16. Architecture

```text
┌───────────────────────────────────────────────┐
│              SIMULATED FLEET                  │
│          NVIDIA Isaac Sim / AMRs              │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             TELEMETRY ADAPTER                 │
│ raw state → temporal/spatial aggregation      │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│            MODEL / GAP DETECTOR               │
│ expected behavior vs observed behavior        │
└──────────────────────┬────────────────────────┘
                       │
                investigation trigger
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             NEMOTRON REASONER                 │
│ semantic context → competing hypotheses       │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│            SEMANTIC COMPILER                  │
│ schema → whitelist → bounds → manifest        │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│            EXPERIMENT PLANNER                 │
│ choose informative counterfactuals             │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│            NEBIUS SERVERLESS JOBS             │
│ parallel simulation workloads                 │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│               ISAAC SIM                       │
│ counterfactual multi-robot experiments        │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             EVIDENCE ANALYZER                 │
│ metrics → statistics → candidate relationships│
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│           INDEPENDENT VALIDATION              │
│ held-out seeds / scenarios / demand           │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             FLEET KNOWLEDGE                  │
│ validated machine-readable discoveries        │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────┐
│             POLICY ENGINE                     │
│ bounded deterministic adaptation              │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
                  FLEET REPLAY
```

---

# 17. Why the Architecture Is Deliberately Hybrid

RESILIANT does not try to make every component AI-driven.

Instead:

| Component | Responsibility |
|---|---|
| Isaac Sim | Physical simulation |
| Telemetry layer | State representation |
| Gap detector | Detect unexplained deviation |
| Nemotron | Generate hypotheses |
| Semantic compiler | Constrain experiments |
| Experiment planner | Select tests |
| Nebius | Scale experiment execution |
| Evidence analyzer | Measure outcomes |
| Discovery engine | Extract relationships |
| Validation engine | Test generalization |
| Knowledge model | Persist discoveries |
| Policy engine | Apply deterministic adaptation |

This division makes the system easier to audit and defend.

---

# 18. Why Nemotron Matters

Nemotron is not included as decorative AI.

Its role is specifically suited to semantic reasoning.

The system needs to transform:

```text
"What unusual combination of fleet variables
could explain this behavior?"
```

into:

```text
testable competing hypotheses.
```

This is different from asking an LLM to:

```text
drive robot #17.
```

The latter is an inappropriate use of a language model for a latency- and safety-critical control loop.

RESILIANT uses Nemotron at a higher abstraction level.

---

# 19. Why Nebius Matters

Nebius is used as an experimental compute fabric.

A discovery may require many counterfactual worlds:

```text
different demand
different seeds
different robot density
different fleet composition
different priority concentration
different initial states
```

Independent experiments can run concurrently.

This makes the cloud infrastructure part of the discovery mechanism rather than merely application hosting.

---

# 20. Why Isaac Sim Matters

The project needs more than tabular synthetic data.

The phenomenon being investigated arises from interacting agents in a spatial environment.

Isaac Sim provides the environment in which:

```text
robot movement
+
traffic
+
task allocation
+
spatial constraints
+
multi-agent interactions
```

can produce fleet-level behavior.

RESILIANT operates above that environment.

---

# 21. Why This Fits Physical AI

The project is software-only, but its subject is explicitly physical:

```text
robots
+
motion
+
spatial constraints
+
traffic
+
task execution
+
multi-agent interaction
```

The simulation represents an embodied fleet.

The system reasons about the consequences of physical interaction rather than merely processing abstract business records.

For the hackathon's software-only Physical AI path, the demonstration focuses on the **key application modules in action**.

---

# 22. Why the Lack of Physical Hardware Is Not the Core Limitation

The physical robot is replaced by a physics-based simulation.

This changes the demonstration medium, not the architecture.

Instead of:

```text
physical fleet
→ telemetry
→ investigation
```

the prototype uses:

```text
simulated fleet
→ telemetry
→ investigation
```

This has one major advantage for the hackathon:

The team can deliberately reproduce rare conditions.

For example:

```text
high robot density
+
priority surge
+
junction congestion
```

can be triggered repeatedly without risking hardware.

---

# 23. What Is Different From Conventional Fleet Optimization?

Conventional optimization asks:

> What is the best decision given the current model?

RESILIANT asks:

> Does the current model still explain what the fleet is doing?

This creates a second loop around the operational system:

```text
Operational loop:

observe
→ optimize
→ execute


Investigation loop:

observe
→ detect unexplained behavior
→ hypothesize
→ experiment
→ discover
→ update knowledge
```

The investigation loop is the central product capability.

---

# 24. What Is Different From Standard Anomaly Detection?

Anomaly detection:

```text
detect abnormal behavior
→ alert
```

RESILIANT:

```text
detect abnormal behavior
→ generate explanations
→ experimentally distinguish explanations
→ extract relationship
→ validate relationship
→ update fleet knowledge
```

The distinction is the transition from:

```text
detection
```

to:

```text
investigation.
```

---

# 25. What Is Different From Reinforcement Learning?

RL generally optimizes a policy against a reward.

RESILIANT instead seeks interpretable operational relationships.

For example:

```text
RL:
policy parameters changed.

RESILIANT:
"Under this combination of conditions,
the fleet enters a nonlinear congestion regime."
```

The two approaches can coexist.

RESILIANT is not positioned as a replacement for RL.

---

# 26. What Is Different From an LLM Robotics Agent?

A conventional LLM robotics agent may follow:

```text
language
→ plan
→ tool call
→ action
```

RESILIANT follows:

```text
fleet observation
→ epistemic gap
→ hypothesis
→ experiment
→ evidence
→ validated knowledge
→ policy
```

The key output is not an action.

It is **new operational knowledge**.

---

# 27. What Is Different From a Digital Twin?

A digital twin can already support:

- monitoring;
- prediction;
- simulation;
- optimization.

RESILIANT does not claim that those capabilities are new.

Its contribution is to place the digital simulation environment inside an autonomous investigation loop:

```text
Digital environment
+
hypothesis generation
+
experiment selection
+
evidence analysis
+
knowledge update
```

The simulator becomes an experimental laboratory for the fleet's operational model.

---

# 28. The Most Important Design Decision

The initial knowledge model must intentionally be incomplete.

Suppose the final discovery is:

```text
occupancy × priority concentration
→ nonlinear congestion
```

The system must begin without that interaction encoded.

Otherwise:

```text
known rule
→ simulated confirmation
```

is not discovery.

The demonstration must therefore distinguish:

```text
prior knowledge
```

from:

```text
post-investigation knowledge.
```

---

# 29. Scientific Integrity

RESILIANT must not overclaim.

The system can establish:

> A relationship was experimentally observed and independently reproduced under the simulated fleet conditions.

It cannot automatically establish:

> This is a universal law of all warehouses.

Similarly, it should not claim:

> Nemotron discovered the truth.

The accurate chain is:

```text
Nemotron
→ proposes

Simulation
→ tests

Statistics
→ extracts

Validation
→ verifies

Knowledge engine
→ accepts
```

---

# 30. Evaluation

The project should be evaluated against meaningful baselines.

## Baseline A — Fixed policy

No autonomous investigation.

## Baseline B — Reactive policy

Respond to congestion using predefined rules.

## Baseline C — Blind simulation sweep

Run predefined parameter combinations without hypothesis-driven investigation.

## RESILIANT

```text
gap detection
→ hypotheses
→ targeted experiments
→ discovery
→ validation
→ policy update
```

---

# 31. Evaluation Metrics

## Operational

```text
Throughput
Waiting time
Queue length
Task completion time
Deadlocks
Recovery time
```

## Discovery

```text
Discovery validity
Validation success
False discovery rate
Relationship reproducibility
```

## Compute

```text
Experiments required per validated discovery
Wall-clock investigation time
Parallel job utilization
```

The project should report both:

```text
operational improvement
```

and:

```text
discovery efficiency.
```

---

# 32. What Success Looks Like

A successful run should produce a trace such as:

```text
INV-003

Observed:
throughput = 0.61

Expected:
throughput = 0.82

Gap:
-0.21

Hypotheses:
H1 occupancy
H2 priority
H3 interaction

Experiments:
24 selected

Simulation runs:
120

Candidate:
occupancy > 0.73
AND priority > 0.35

Validation:
40 unseen runs

Result:
VALIDATED

Policy:
reduce assignment concentration at Junction C

Replay:
queue growth ↓
waiting time ↓
throughput ↑
```

This trace is much more valuable than a screenshot of an LLM answer.

---

# 33. Hackathon Demo

The three-minute demonstration should show the actual modules operating.

Recommended sequence:

### 0:00–0:30 — Fleet

Show:

```text
35 robots
warehouse
task execution
```

### 0:30–0:50 — Disruption

Introduce:

```text
priority demand surge
```

Show:

```text
queue growth
throughput degradation
```

### 0:50–1:15 — Investigation

Show:

```text
model/reality gap
→ Nemotron
→ H1/H2/H3
```

### 1:15–1:45 — Experiment

Show:

```text
compiled experiment manifests
→ Nebius jobs
→ parallel Isaac Sim runs
```

### 1:45–2:15 — Discovery

Show:

```text
metrics
→ relationship extraction
→ validation
→ fleet knowledge
```

### 2:15–2:45 — Adaptation

Show:

```text
policy update
→ same scenario replay
```

### 2:45–3:00 — Result

Show:

```text
BEFORE vs AFTER
```

with actual metrics.

---

# 34. Repository Requirements

The public repository should include:

```text
README.md
LICENSE
Dockerfile
requirements/environment files
simulation
agent
experiments
evidence
discovery
knowledge
policy
tests
```

The README should clearly explain:

```text
How to run locally
How to run the simulator
How Nemotron is connected
How Nebius is used
How experiments are launched
How discoveries are validated
How to reproduce the demo
```

---

# 35. Reproducibility

Every experiment should record:

```text
experiment ID
run ID
random seed
scenario version
configuration
model identifier
software version
timestamp
```

A discovery should be traceable back to:

```text
hypothesis
→ experiment
→ simulation run
→ metrics
→ analysis
→ validation
```

This is essential because the project is explicitly making an evidence-based discovery claim.

---

# 36. Safety Boundary

The project uses a layered authority model.

```text
Nemotron
    ↓
semantic suggestion

Compiler
    ↓
authorized experiment

Simulator
    ↓
physical consequence

Evidence analyzer
    ↓
measurement

Validation
    ↓
accept/reject

Policy engine
    ↓
bounded adaptation
```

No single probabilistic component has unrestricted control.

This is especially important when demonstrating Physical AI.

---

# 37. Known Limitations

RESILIANT is a prototype.

Its main limitations include:

### Simulation-to-real gap

A simulated relationship may not reproduce identically in physical hardware.

### Model dependence

The initial model determines what counts as unexpected.

### Computational cost

Large-scale counterfactual experimentation can be expensive.

### Hypothesis quality

Poor hypotheses can produce poor investigations.

### Simulator artifacts

Simulation failures must be separated from genuine fleet dynamics.

### Limited discovery vocabulary

The MVP will only investigate variables exposed by the experiment registry.

These are engineering constraints, not problems to hide.

---

# 38. Future Extension

A mature deployment could extend the same architecture to:

```text
physical fleet telemetry
        ↓
shadow investigation
        ↓
cloud simulation
        ↓
validated discovery
        ↓
human approval
        ↓
production policy
```

Additional future capabilities could include:

- heterogeneous robot fleets;
- multi-warehouse knowledge transfer;
- richer causal experiment design;
- uncertainty-aware discovery;
- automated policy rollback;
- human approval workflows;
- physical fleet validation;
- continuous fleet health monitoring.

These are future directions, not required claims for the hackathon prototype.

---

# 39. The Core Research Hypothesis

The project ultimately tests:

> **Can simulation-in-the-loop Physical AI transform persistent fleet-model failures into experimentally validated operational knowledge that improves subsequent fleet behavior?**

The hypothesis is falsifiable.

RESILIANT is successful only if the system can demonstrate:

```text
initially unknown relationship
        ↓
experimentally discovered
        ↓
independently validated
        ↓
used by policy
        ↓
measurable operational improvement
```

---

# 40. Why This Matters

Autonomy has traditionally focused on making machines better at acting.

The next problem is making autonomous systems better at **understanding the limits of their own operating assumptions**.

A fleet may know how to:

```text
move
route
assign
avoid
optimize
recover
```

But when a previously unseen interaction appears, the important question becomes:

> **Can the system investigate the failure instead of waiting for a human engineer to explain it?**

RESILIANT explores that capability.

---

# 41. Final Position

RESILIANT does not claim to invent the individual technologies it uses.

Its value is the closed-loop composition:

```text
        OBSERVE
           ↓
   FIND MODEL GAP
           ↓
     HYPOTHESIZE
           ↓
      EXPERIMENT
           ↓
       MEASURE
           ↓
      DISCOVER
           ↓
       VALIDATE
           ↓
    UPDATE KNOWLEDGE
           ↓
      CHANGE POLICY
           ↓
        REPLAY
           ↓
        OBSERVE
```

The defining transition is:

```text
Today's fleet:

"What should I do?"


RESILIANT:

"What am I failing to understand,
and can I experimentally find out?"
```

That is the capability this project is built to demonstrate.

---

# 42. Hackathon Alignment

## Physical AI Track

RESILIANT fits the Physical AI track because the system operates over:

- autonomous robots;
- spatial environments;
- multi-agent interactions;
- physical simulation;
- embodied task execution;
- NVIDIA Physical AI tooling.

## NVIDIA Technology

The project uses NVIDIA technology for:

```text
Nemotron
→ reasoning / hypothesis generation

Isaac Sim
→ embodied multi-robot simulation
```

## Nebius Technology

Nebius provides:

```text
model-serving infrastructure
+
parallel simulation workloads
+
cloud-scale experimental execution
```

## Software-only Demonstration

The project does not require physical hardware for the prototype demonstration.

The key application modules are shown operating inside the simulated physical environment:

```text
fleet
→ telemetry
→ investigation
→ hypothesis
→ experiment
→ simulation
→ discovery
→ validation
→ policy
→ replay
```

---

# 43. Final One-Line Description

> **RESILIANT is an autonomous fleet investigation layer that uses NVIDIA Nemotron to hypothesize, Isaac Sim to experiment, Nebius to scale counterfactual worlds, and deterministic evidence to discover and validate operational knowledge that changes how a robot fleet behaves.**

---

# 44. Final Principle

**Do not sell RESILIANT as an AI that controls robots.**

Sell it as:

> **AI that investigates robots.**

That distinction is the entire project.
