# RESILIANT — Product & Research Proposal

## Autonomous Discovery of Hidden Operating Rules in Multi-Robot Fleets

**Project:** RESILIANT  
**Track:** NVIDIA × Nebius Global AI Hackathon — Physical AI  
**Category:** Pure-software Physical AI  
**Document:** Product & Research Proposal / Master Concept Document  
**Status:** Proposed prototype

---

# 1. Executive Summary

Modern autonomous robot fleets are increasingly capable of executing complex warehouse operations. They can assign tasks, plan routes, avoid obstacles, coordinate traffic, manage priorities, and recover from individual failures.

Yet these systems remain fundamentally dependent on an **operational model defined in advance**.

That creates a difficult class of failures: situations in which individual robots behave correctly, the fleet manager behaves correctly according to its programmed objectives, and the physical environment remains within nominal operating conditions, but the **collective fleet exhibits a behavior that the current model does not explain well**.

RESILIANT addresses this problem by introducing an **autonomous discovery layer** above the fleet controller.

The central question is:

> **Can an autonomous robot fleet discover a fleet-specific operational relationship that was not explicitly encoded in its initial knowledge model?**

RESILIANT does not attempt to replace the low-level robot controller with an LLM. It does not ask an LLM to directly drive robots. Instead, it creates a controlled investigation loop:

> **Observe → Detect Model/Reality Gap → Hypothesize → Design Experiment → Simulate → Analyze Evidence → Falsify → Validate → Update Knowledge → Operationalize**

NVIDIA Nemotron serves as the semantic reasoning component. NVIDIA Isaac Sim provides the embodied experimental environment. Nebius provides the cloud infrastructure for model serving and scalable simulation workloads.

The result is a system that treats simulation not merely as a development environment, but as an **experimental instrument for acquiring operational knowledge about the fleet**.

A successful demonstration will begin with an initial fleet model that intentionally lacks a particular fleet-level relationship. The fleet will then be exposed to a scenario that produces unexpected degradation. RESILIANT will identify the model/reality gap, generate competing hypotheses, formulate controlled experiments, execute counterfactual simulations, extract a candidate relationship using deterministic analysis, validate it under unseen conditions, and store the surviving relationship as new fleet knowledge.

The same scenario will then be replayed using the updated knowledge.

The objective is not to claim that RESILIANT invents new mathematics. The underlying technologies—LLM reasoning, multi-robot coordination, simulation-based experimentation, statistical analysis, and digital twins—are established fields. The proposed contribution is the **integration of these capabilities into a closed-loop fleet discovery architecture in which unexplained embodied behavior becomes an autonomous experimental question and validated knowledge becomes part of the fleet's future operating model**.

---

# 2. The Problem

## 2.1 Autonomous fleets are optimized around known knowledge

A conventional autonomous warehouse fleet typically contains several layers:

```text
Human-defined operational knowledge
            ↓
Fleet management
            ↓
Task allocation
            ↓
Path planning
            ↓
Robot control
            ↓
Physical environment
```

Each layer can be highly sophisticated.

The weakness is that the system's behavior is still constrained by assumptions made during design, deployment, calibration, or optimization.

Examples include assumptions about:

- expected traffic density;
- task arrival rates;
- robot capabilities;
- warehouse topology;
- priority distributions;
- charging behavior;
- congestion;
- robot interaction;
- fleet composition.

These assumptions do not have to be "wrong" to become insufficient.

A relationship can simply be absent from the model.

---

# 3. The Failure Mode RESILIANT Targets

Consider a warehouse containing 35 autonomous mobile robots.

Every robot is healthy.

The task allocator is functioning.

The navigation stack is functioning.

No robot has crashed.

Yet throughput suddenly collapses.

A possible chain is:

```text
Priority orders increase
        ↓
More robots converge on a region
        ↓
Junction occupancy increases
        ↓
Waiting time increases
        ↓
Effective fleet capacity decreases
        ↓
More tasks accumulate
        ↓
More robots are redirected
        ↓
Congestion becomes self-reinforcing
```

The individual robot decisions may all be locally reasonable.

The failure emerges from the **interaction of the fleet as a system**.

A conventional fleet manager can detect the congestion and react.

The deeper question is:

> **Why did this operating regime emerge, and was there a relationship in the fleet that the original model did not represent?**

RESILIANT is designed to investigate that question.

---

# 4. The Core Research Question

## Primary question

> **Can a software-defined autonomous fleet use embodied simulation and AI reasoning to discover, experimentally validate, and operationalize fleet-specific relationships that were not explicitly encoded in its initial operating model?**

This question deliberately avoids claiming universal scientific discovery.

The target is **fleet-specific operational knowledge**.

For example:

```text
IF
    Junction C occupancy > θ1
AND
    priority-task concentration > θ2
THEN
    queue growth enters a high-risk regime
```

The values of `θ1` and `θ2` are not assumed to be known.

The system attempts to discover them from experiments.

---

# 5. What RESILIANT Means by "Discovery"

A major design requirement is to avoid calling every model-generated explanation a discovery.

RESILIANT distinguishes several stages.

### Observation

The system observes an operational phenomenon.

Example:

```text
Throughput ↓ 31%
Queue length ↑ 240%
```

### Hypothesis

Nemotron proposes possible explanations.

Example:

```text
H1: robot density
H2: priority concentration
H3: density × priority interaction
```

### Experiment

The system deliberately changes controllable variables in simulation.

### Evidence

The simulation produces measurable outcomes.

### Candidate relationship

A deterministic analysis layer identifies a relationship supported by the evidence.

### Validation

The relationship is tested under conditions not used to discover it.

### Discovery

Only a relationship that survives the validation process becomes persistent fleet knowledge.

Therefore:

> **Nemotron cannot declare a discovery.**

The evidence pipeline must do that.

---

# 6. Product Concept

RESILIANT is an **out-of-band fleet discovery layer**.

It sits above an existing fleet manager and observes fleet behavior without participating in latency-critical low-level control.

Conceptually:

```text
                 ┌──────────────────────┐
                 │     ROBOT FLEET      │
                 └──────────┬───────────┘
                            │
                         Telemetry
                            │
                            ▼
                 ┌──────────────────────┐
                 │  RESILIANT           │
                 │  Discovery Layer     │
                 └──────────┬───────────┘
                            │
                   Knowledge / Policy
                            │
                            ▼
                 ┌──────────────────────┐
                 │ Existing Fleet       │
                 │ Manager / Controller │
                 └──────────────────────┘
```

The underlying fleet controller remains responsible for:

- navigation;
- collision avoidance;
- motion;
- task execution;
- safety constraints.

RESILIANT is responsible for:

- detecting unexplained behavior;
- generating hypotheses;
- designing investigations;
- evaluating counterfactuals;
- discovering relationships;
- validating knowledge;
- updating the strategic operating model.

---

# 7. Why an Out-of-Band Architecture?

An LLM should not be placed directly inside a 10–100 Hz physical control loop simply because it can generate natural-language instructions.

That creates unnecessary latency, unpredictability, and verification problems.

RESILIANT instead uses a hierarchy:

```text
Strategic discovery
        │
        ▼
Fleet policy
        │
        ▼
Task allocation
        │
        ▼
Path planning
        │
        ▼
Robot control
```

The LLM operates at the strategic discovery level.

Deterministic systems remain responsible for physical execution.

This makes the prototype easier to audit and gives the system a clear safety boundary.

---

# 8. High-Level System Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         RESILIANT RUNTIME                            │
│                                                                      │
│  ┌──────────────────┐                                                │
│  │ Fleet Telemetry  │                                                │
│  └────────┬─────────┘                                                │
│           │                                                          │
│           ▼                                                          │
│  ┌────────────────────────┐                                          │
│  │ Model/Reality Monitor  │                                          │
│  └────────────┬───────────┘                                          │
│               │ unexplained deviation                               │
│               ▼                                                      │
│  ┌────────────────────────┐       Nebius Endpoint                  │
│  │ NVIDIA Nemotron         │──────────────────────────┐              │
│  │ Hypothesis Generator   │                           │              │
│  └────────────┬───────────┘                           │              │
│               │ typed experiment specification        │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ Semantic Compiler      │                           │              │
│  │ Validation + Bounds    │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ Experiment Planner     │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ Nebius Serverless Jobs │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ NVIDIA Isaac Sim       │                           │              │
│  │ Counterfactual Worlds  │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ Deterministic Evidence │                           │              │
│  │ Analyzer               │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│               ▼                                       │              │
│  ┌────────────────────────┐                           │              │
│  │ Discovery Validator    │                           │              │
│  └────────────┬───────────┘                           │              │
│               │                                       │              │
│          ┌────┴─────┐                                 │              │
│          │          │                                 │              │
│        FAIL        PASS                               │              │
│          │          │                                 │              │
│          ▼          ▼                                 │              │
│       Reject   Fleet Knowledge                        │              │
│                       │                                │              │
│                       ▼                                │              │
│                 Policy Update                         │              │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 9. Model/Reality Gap Detection

The investigation begins only when the system has evidence that the current model is insufficient.

A naïve trigger would be:

```text
throughput changed
→ investigate
```

That would generate too many false alarms.

Instead, the prototype should establish a baseline distribution of expected fleet behavior.

For a measured metric `y`:

```text
expected = μ(x)
observed = y
residual = y - μ(x)
```

The system can monitor:

- normalized residual;
- confidence interval;
- rolling variance;
- persistence over time;
- cross-metric consistency.

A candidate anomaly can be triggered when the observed behavior exceeds an established tolerance over multiple observations.

The precise statistical trigger is an implementation decision and should be validated experimentally.

The principle is:

> **Do not spend expensive simulation compute on ordinary noise.**

---

# 10. Semantic Telemetry Representation

Sending raw robot telemetry directly to an LLM is inefficient.

A fleet can generate enormous quantities of:

```text
x
y
velocity
orientation
timestamp
battery
task ID
path state
```

RESILIANT therefore aggregates raw telemetry into semantic state representations.

For example:

```json
{
  "fleet": {
    "robot_count": 35,
    "active": 32,
    "charging": 3
  },
  "junctions": {
    "A": {
      "occupancy": 0.41,
      "queue": 2
    },
    "B": {
      "occupancy": 0.57,
      "queue": 4
    },
    "C": {
      "occupancy": 0.79,
      "queue": 17
    }
  },
  "demand": {
    "priority_ratio": 0.42,
    "arrival_rate": 18.2
  },
  "performance": {
    "throughput": 0.61,
    "expected_throughput": 0.84
  }
}
```

The LLM sees the **semantic structure** of the fleet rather than millions of raw coordinate updates.

Raw telemetry remains available for deterministic analysis.

---

# 11. Nemotron's Role

Nemotron is used for reasoning tasks where semantic generation is valuable.

### Nemotron can:

- interpret a model/reality gap;
- generate competing hypotheses;
- propose controllable variables;
- propose experiment structures;
- explain validated relationships;
- summarize evidence.

### Nemotron cannot:

- directly control robot motors;
- directly mutate arbitrary simulation code;
- declare numerical results true;
- bypass parameter validation;
- promote its own hypothesis to fleet knowledge.

This distinction is fundamental to the architecture.

---

# 12. Hypothesis Generation

Given:

```text
Observed:
throughput = 0.61

Expected:
throughput = 0.84

Junction C occupancy = 0.79

Priority ratio = 0.42
```

Nemotron might produce:

```json
{
  "hypotheses": [
    {
      "id": "H1",
      "claim": "Junction occupancy is the dominant driver",
      "variables": ["junction_C_occupancy"]
    },
    {
      "id": "H2",
      "claim": "Priority traffic concentration is the dominant driver",
      "variables": ["priority_ratio"]
    },
    {
      "id": "H3",
      "claim": "Occupancy and priority traffic interact",
      "variables": [
        "junction_C_occupancy",
        "priority_ratio"
      ]
    }
  ]
}
```

The hypotheses are machine-readable.

This allows the experiment planner to work with them deterministically.

---

# 13. Semantic Experiment Compiler

The compiler converts the model-generated experiment description into an approved simulation configuration.

A conceptual pipeline:

```text
Nemotron output
      ↓
Schema validation
      ↓
Parameter authorization
      ↓
Range validation
      ↓
Scene/entity validation
      ↓
Experiment consistency checks
      ↓
Executable configuration
```

For example:

```json
{
  "parameter": "priority_ratio",
  "value": 0.50,
  "allowed_range": [0.0, 1.0]
}
```

A request such as:

```text
priority_ratio = 1.8
```

must be rejected.

Similarly, a request to mutate a nonexistent simulation entity must fail before the simulation is launched.

This creates the deterministic boundary:

```text
Probabilistic model
       ↓
Typed specification
       ↓
Deterministic compiler
       ↓
Physical simulation
```

---

# 14. Counterfactual Experimentation

Suppose the competing hypotheses are:

```text
H1 = occupancy
H2 = priority
H3 = interaction
```

The experiment planner should choose interventions capable of distinguishing them.

For example:

| Experiment | Occupancy | Priority |
|---|---:|---:|
| A | 0.60 | 0.20 |
| B | 0.60 | 0.50 |
| C | 0.80 | 0.20 |
| D | 0.80 | 0.50 |

The resulting response surface can reveal whether:

```text
occupancy alone
```

or:

```text
priority alone
```

or:

```text
occupancy × priority
```

better explains the observed phenomenon.

The important idea is that the system is **intervening on controllable variables**, not merely collecting more observational logs.

---

# 15. Nebius as the Experimental Compute Fabric

Nebius Serverless AI Jobs are designed for finite containerized workloads including batch processing and scientific simulations. This makes them suitable for the distributed simulation stage of RESILIANT. citeturn0search2turn0search8

The runtime can fan out:

```text
Experiment manifest
       │
       ├── Job 1 → Seed 1
       ├── Job 2 → Seed 2
       ├── Job 3 → Seed 3
       ├── Job 4 → Scenario B
       └── Job N → Scenario N
```

Each job returns structured evidence.

The system then aggregates the results.

Nebius therefore provides the computational scale required to turn one hypothesis into many controlled experiments.

---

# 16. NVIDIA Isaac Sim as the Embodied Laboratory

NVIDIA describes Isaac Sim as a physically based robotics simulation framework for simulation, testing, validation, and synthetic data generation. It supports fleet-level testing and software-in-the-loop workflows. citeturn0search0turn0search3

RESILIANT uses this capability differently from a conventional robot-training pipeline.

The simulation is not only used to:

- train a policy;
- generate synthetic data;
- visualize robots.

It is used to execute **controlled counterfactual experiments**.

For each experiment:

```text
Initial state
+
Controlled intervention
+
Random seed
+
Fleet configuration
+
Demand pattern
        ↓
Isaac Sim
        ↓
Trajectory + performance evidence
```

The simulator becomes the experimental environment in which candidate explanations can be tested.

---

# 17. Deterministic Evidence Extraction

Simulation outputs should be processed without asking the LLM to invent numerical boundaries.

A candidate implementation can use:

- regression;
- decision trees;
- change-point detection;
- interaction terms;
- threshold analysis;
- confidence intervals;
- repeated-seed evaluation.

For example:

```text
Input:

occupancy
priority_ratio
queue_growth
throughput
deadlocks
waiting_time
```

The analysis layer might identify:

```text
occupancy ≈ 0.73
```

as a candidate transition boundary.

Nemotron can then turn that result into an explanation:

> Under elevated priority demand, Junction C begins exhibiting a sharp increase in queue growth once occupancy approaches the validated operating boundary.

The exact numerical boundary comes from the evidence pipeline.

---

# 18. Discovery Validation

A candidate relationship must be tested outside its discovery dataset.

Example:

### Discovery

```text
Seeds: 1–10
Demand patterns: A–D
Fleet states: A–C
```

### Validation

```text
Seeds: 11–20
Demand patterns: E–H
Fleet states: D–F
```

A relationship that performs well only on the discovery dataset is rejected.

This is essential because simulation can generate apparent relationships that are artifacts of:

- random seeds;
- geometry;
- controller behavior;
- parameter interactions;
- implementation assumptions.

---

# 19. Statistical and Simulation Robustness

A valid prototype must distinguish genuine fleet behavior from simulator artifacts.

Candidate discoveries should therefore be tested across:

- independent random seeds;
- initial robot positions;
- demand profiles;
- fleet composition;
- task distributions;
- scenario variations.

A rule such as:

```text
occupancy > 0.73
```

should not become fleet knowledge merely because one simulation run happened to cross that number.

The system should measure replication and stability.

---

# 20. Fleet Knowledge Model

Validated discoveries become structured records.

Example:

```yaml
id: RD-014

phenomenon:
  nonlinear_junction_congestion

variables:
  junction_occupancy:
    threshold: 0.73
  priority_ratio:
    threshold: 0.35

effect:
  queue_growth:
    regime: nonlinear

evidence:
  experiments: 120
  independent_seeds: 20

validation:
  unseen_scenarios: true
  replicated: true

status:
  validated: true
```

The knowledge model becomes a persistent memory of experimentally established fleet behavior.

This is different from storing conversational text.

The result is machine-readable operational knowledge.

---

# 21. Operationalization

A discovery becomes useful only when it affects future operation.

Suppose RESILIANT establishes:

```text
Junction C instability:
occupancy > 0.73
AND
priority ratio > 0.35
```

An operational policy can be generated:

```text
IF
    Junction C occupancy approaches 0.73
AND
    priority ratio exceeds 0.35

THEN
    reduce concentration of priority tasks
    OR
    activate alternate routing
```

The exact intervention belongs to the fleet-management layer.

RESILIANT provides the discovered condition and recommended strategic response.

Low-level controllers continue enforcing physical constraints.

---

# 22. Before vs After

This is the central experimental demonstration.

## Before discovery

```text
Disruption
    ↓
Unexpected congestion
    ↓
Existing model fails to explain severity
    ↓
Throughput collapse
```

## Investigation

```text
Model/Reality Gap
    ↓
Nemotron hypotheses
    ↓
Controlled experiments
    ↓
Parallel Isaac Sim runs
    ↓
Evidence extraction
    ↓
Validation
    ↓
New fleet knowledge
```

## After discovery

```text
Same disruption
    ↓
Known operating regime
    ↓
Policy response
    ↓
Lower degradation
```

The system demonstrates a measurable change in behavior caused by **newly acquired operational knowledge**.

---

# 23. What Is Actually New?

RESILIANT does not claim that any individual building block is novel.

Established technologies include:

- LLM reasoning;
- multi-robot task allocation;
- simulation-based optimization;
- digital twins;
- active learning;
- statistical rule extraction;
- physics simulation;
- cloud batch computation.

The project contribution is the architecture that combines these into:

```text
Unexpected fleet behavior
        ↓
Autonomous question formation
        ↓
Competing explanations
        ↓
Experiment design
        ↓
Embodied counterfactual evaluation
        ↓
Deterministic evidence extraction
        ↓
Falsification
        ↓
Persistent fleet knowledge
        ↓
Operational adaptation
```

This distinction is important.

RESILIANT is an **engineering and systems research prototype**, not a claim of inventing a new mathematical field.

---

# 24. Relationship to Existing Robotics Simulation

NVIDIA's current robotics stack already supports simulation, fleet testing, software-in-the-loop evaluation, synthetic data generation, and large-scale robot learning. Isaac Lab, for example, is designed for GPU-accelerated robot-learning workflows at scale. citeturn0search0turn0search4

RESILIANT builds on this infrastructure rather than pretending it replaces it.

The proposed difference is the **purpose of simulation**.

Conventional:

```text
Simulation
→ training
→ testing
→ validation
→ optimization
```

RESILIANT:

```text
Fleet behavior
→ unexplained phenomenon
→ question
→ experiment
→ discovery
→ knowledge update
```

Simulation becomes part of an autonomous knowledge-acquisition loop.

---

# 25. Relationship to Automated Scientific Discovery

The overall idea is related to the broader concept of automated scientific experimentation:

```text
Observation
→ Hypothesis
→ Experiment
→ Evidence
→ Updated model
```

RESILIANT does not claim to invent this loop.

Instead, it asks whether the same methodology can be applied to **operational behavior in a multi-robot embodied system**.

The important domain-specific constraints are:

- the system is dynamic;
- multiple agents interact;
- the environment is spatial;
- the variables are coupled;
- experiments can be expensive;
- the resulting knowledge must be operationally useful.

The proposal therefore treats automated experimentation as an architectural pattern rather than claiming ownership of the scientific method itself.

---

# 26. Relationship to LLM-Guided Simulation

Recent work has demonstrated that LLMs can participate in iterative simulation and optimization workflows.

RESILIANT therefore does not claim:

> "LLMs can generate simulation experiments."

That is already established.

Instead, the proposal uses the LLM specifically as a **hypothesis generator inside a controlled evidence pipeline**.

The distinction is:

```text
LLM generates answer
```

versus:

```text
LLM generates hypothesis
        ↓
system designs experiment
        ↓
simulation produces evidence
        ↓
deterministic analysis evaluates evidence
        ↓
validation decides whether knowledge survives
```

The second architecture is the one RESILIANT proposes to demonstrate.

---

# 27. Why Fleet-Specific Knowledge Matters

A relationship that exists in one warehouse may not exist in another.

Differences include:

- aisle geometry;
- junction layout;
- fleet composition;
- robot acceleration;
- payload;
- traffic policies;
- task distribution;
- charging infrastructure;
- order arrival patterns.

Therefore RESILIANT focuses on **local operational knowledge**.

It is not trying to rediscover universal robotics laws.

It is trying to discover:

> **What is true about this fleet operating in this environment under these conditions?**

That makes the knowledge directly useful to the deployment.

---

# 28. Heterogeneous Fleet Scenario

A future extension is mixed robot fleets.

Example:

```text
20 × Robot A
15 × Robot B
```

Robot A:

- faster;
- higher acceleration.

Robot B:

- slower;
- different payload constraints.

Both may be individually correct.

But their interaction may produce:

```text
A follows B
      ↓
traffic compression
      ↓
junction occupancy
      ↓
queue propagation
```

RESILIANT can investigate fleet composition as an experimental variable.

This is particularly relevant to brownfield automation, where organizations may operate multiple generations or types of mobile robots.

---

# 29. Continuous Shadow Investigation

RESILIANT is designed to operate asynchronously.

The fleet continues normal operation.

RESILIANT runs investigations in the background.

```text
                 LIVE FLEET
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
 Normal operation          RESILIANT
                           investigation
                                │
                                ▼
                         Counterfactuals
                                │
                                ▼
                          New knowledge
```

This avoids putting the expensive discovery process directly inside the operational control loop.

It also creates a path toward proactive resilience:

> **investigate potential weaknesses before they become failures.**

---

# 30. Physical AI Interpretation

Although the hackathon prototype is software-only, the system is still centered on an embodied environment.

The simulated robots:

- occupy physical space;
- have motion constraints;
- interact with one another;
- encounter shared bottlenecks;
- execute tasks;
- experience congestion;
- produce collective physical behavior.

NVIDIA explicitly supports simulation and evaluation of single robots and fleets in physically based virtual environments. citeturn0search3

Therefore the physical component of RESILIANT is represented by the embodied simulation environment rather than physical hardware.

The demo should show the **key application modules in action**, rather than presenting a static architecture diagram.

---

# 31. Hackathon Infrastructure Mapping

| Hackathon requirement | RESILIANT implementation |
|---|---|
| NVIDIA open-source model | NVIDIA Nemotron |
| Nebius Token Factory / AI Cloud | Nebius AI infrastructure |
| Physical AI | Multi-robot embodied simulation |
| Simulation | NVIDIA Isaac Sim |
| Scalable simulation | Nebius Serverless Jobs |
| Model serving | Nebius Serverless Endpoint / Token Factory |
| Agent runtime | RESILIANT discovery orchestrator |
| Working project | End-to-end executable prototype |
| Demo | Live investigation + simulation + discovery + replay |
| Public repository | Open-source implementation with setup instructions |

Nebius explicitly positions Jobs for finite containerized workloads including batch processing and scientific simulations, while Endpoints provide HTTP model-serving environments. citeturn0search2

---

# 32. MVP Scope

The project should deliberately avoid attempting to build an entire commercial warehouse fleet manager.

The MVP needs only one strong discovery scenario.

### MVP fleet

```text
20–35 simulated AMRs
```

### Environment

```text
Warehouse
Multiple junctions
Multiple task zones
Charging region
Priority orders
```

### Initial knowledge

The system knows:

- robot capabilities;
- map;
- normal operating ranges;
- task types;
- baseline performance.

The target relationship is intentionally absent.

### Discovery variables

For example:

```text
junction occupancy
priority ratio
robot density
fleet composition
```

### Outputs

```text
Hypotheses
Experiment plan
Simulation results
Candidate relationship
Validation result
Fleet knowledge update
Policy response
```

---

# 33. The Primary Demonstration Scenario

A practical first scenario is:

## **Priority-Demand / Junction-Congestion Interaction**

Initial condition:

```text
35 robots
Normal demand
Stable throughput
```

Disruption:

```text
Priority order ratio increases
```

Unexpected effect:

```text
Junction congestion becomes nonlinear
```

Investigation:

```text
H1: density
H2: priority
H3: interaction
```

Experiment:

```text
Controlled occupancy × priority matrix
```

Simulation:

```text
Multiple seeds
Multiple scenarios
```

Discovery:

```text
Validated operating boundary
```

Replay:

```text
Same disruption
Adaptive policy
Improved degradation
```

This gives the demo a clean causal narrative without requiring the team to build an entire industrial warehouse stack.

---

# 34. Evaluation Metrics

RESILIANT should be evaluated scientifically rather than only visually.

## Discovery quality

Measure:

- candidate discoveries generated;
- valid discoveries;
- false discoveries;
- rejected discoveries.

## Validation

Measure:

- replication rate;
- unseen-scenario success;
- seed robustness.

## Experiment efficiency

Measure:

```text
simulation runs required
per validated discovery
```

## Operational effect

Compare:

```text
Baseline fleet
vs
Knowledge-updated fleet
```

using:

- throughput;
- mean waiting time;
- queue length;
- task completion time;
- deadlock frequency;
- recovery time.

## Compute efficiency

Measure:

- number of jobs;
- simulation time;
- useful experiments;
- discarded experiments.

---

# 35. Baselines

A serious evaluation should include at least three baselines.

## Baseline A — Reactive fleet

```text
Detect congestion
→ Replan
```

Measures the benefit of discovery versus immediate reaction.

## Baseline B — Fixed optimization

```text
Current model
→ Optimize
```

Measures the value of updating the operating model.

## Baseline C — Blind simulation sweep

```text
Predefined parameter combinations
→ Simulate
```

Measures whether autonomous experiment selection adds value.

## RESILIANT

```text
Unexpected behavior
→ Hypotheses
→ Experiment selection
→ Simulation
→ Evidence
→ Validation
→ Knowledge update
```

This comparison makes the contribution measurable.

---

# 36. What Would Constitute Success?

The project succeeds if it can demonstrate all of the following:

### 1. The initial model does not contain the target relationship.

### 2. The fleet encounters behavior indicating that the model is incomplete.

### 3. Nemotron generates multiple plausible hypotheses.

### 4. The system converts hypotheses into executable experiments.

### 5. Nebius executes simulation workloads.

### 6. Isaac Sim produces embodied evidence.

### 7. Deterministic analysis identifies a candidate relationship.

### 8. The candidate survives independent validation.

### 9. The relationship is stored as machine-readable knowledge.

### 10. The same operational condition produces improved behavior after the knowledge update.

The last point is critical.

If the system discovers a rule but nothing changes afterward, the discovery has little operational value.

---

# 37. What We Are Not Claiming

To keep the project technically credible, RESILIANT explicitly does **not** claim:

- that it invents automated scientific discovery;
- that it invents active learning;
- that it invents digital twins;
- that Nemotron independently proves causality;
- that Isaac Sim perfectly represents every real warehouse;
- that simulation results automatically transfer to physical robots;
- that the LLM is a safe low-level controller;
- that every discovered threshold is universally true;
- that the system replaces commercial fleet-management software.

Instead:

> RESILIANT is a prototype demonstrating a closed-loop architecture for fleet-specific operational discovery using LLM reasoning, deterministic experimentation, and embodied simulation.

---

# 38. Key Technical Risks

## Risk 1 — False discoveries

Mitigation:

- repeated seeds;
- unseen validation;
- statistical thresholds;
- minimum evidence requirements.

## Risk 2 — LLM hallucination

Mitigation:

- structured outputs;
- schema validation;
- constrained experiment vocabulary;
- deterministic evidence analysis.

## Risk 3 — Simulator artifacts

Mitigation:

- repeated scenarios;
- seed variation;
- physics sanity checks;
- validation outside the discovery dataset.

## Risk 4 — Excessive simulation cost

Mitigation:

- experiment selection;
- early rejection;
- lightweight screening;
- Nebius parallel execution.

## Risk 5 — Overclaiming causality

Mitigation:

Use precise language such as:

> experimentally validated operational relationship

rather than automatically claiming:

> formally proven causal law.

---

# 39. Technical Boundaries

The architecture should maintain explicit boundaries.

```text
Nemotron
───────
Reasoning / hypotheses

Compiler
────────
Validation / translation

Isaac Sim
─────────
Embodied consequences

Evidence Analyzer
──────────────────
Numerical interpretation

Validator
─────────
Generalization test

Knowledge Model
───────────────
Persistent operational knowledge

Fleet Manager
─────────────
Actual execution
```

This makes every component auditable.

---

# 40. Why This Architecture Is Defensible

The strongest defense of RESILIANT is not:

> "Nobody has ever used an LLM with simulation."

That would be false.

It is:

> **"We deliberately combine established components around a capability that conventional fleet software does not normally expose as a first-class operational loop: autonomous investigation of unexplained fleet-level behavior followed by validated knowledge acquisition."**

That is a much more defensible statement.

---

# 41. Research Hypotheses

The prototype can be framed around several experimentally testable hypotheses.

## H1 — Discovery

> An LLM-guided hypothesis generator can produce useful competing explanations for fleet-level model/reality gaps when given semantically compressed telemetry.

## H2 — Experimentation

> Controlled counterfactual simulation can distinguish between competing explanations of fleet-level behavior.

## H3 — Validation

> Deterministic evidence extraction combined with independent validation can reduce false promotion of simulation-derived relationships.

## H4 — Operational value

> Incorporating validated fleet-specific relationships into the operating policy can improve performance under previously problematic conditions.

## H5 — Compute efficiency

> Targeted experiment selection can reduce unnecessary high-fidelity simulation compared with blind parameter sweeps.

These hypotheses are much stronger than simply claiming:

> "AI will make the fleet smarter."

---

# 42. Research Questions

### RQ1 — Detection

When does fleet behavior constitute a meaningful model/reality gap rather than ordinary operational noise?

### RQ2 — Hypothesis generation

Can Nemotron generate diverse, testable explanations rather than repeatedly proposing the same obvious cause?

### RQ3 — Experiment selection

Can the system choose experiments that distinguish hypotheses efficiently?

### RQ4 — Evidence

Can deterministic analysis extract stable fleet-specific relationships from simulation trajectories?

### RQ5 — Validation

How often do candidate relationships survive unseen conditions?

### RQ6 — Operationalization

Does validated knowledge actually improve fleet behavior?

---

# 43. Expected Research Contribution

The expected contribution is not a new optimizer.

It is an architectural demonstration of:

> **Autonomous fleet-level knowledge acquisition through LLM-guided experimental simulation.**

The prototype should establish whether this loop is practically achievable within a software-only embodied environment.

If successful, it provides a foundation for future research into:

- online fleet diagnosis;
- automated policy evolution;
- heterogeneous fleet interaction discovery;
- proactive resilience;
- digital-twin-based operational learning;
- simulation-driven fleet certification.

---

# 44. Future Extension

A later physical deployment could connect RESILIANT to real fleet telemetry.

The architecture would become:

```text
Real Fleet
    ↓
Telemetry
    ↓
Model / Reality Gap
    ↓
RESILIANT
    ↓
Counterfactual Digital Twin
    ↓
Validated Knowledge
    ↓
Fleet Policy
```

The physical system would remain protected because experimental discovery would initially occur in the digital environment.

A mature deployment could also maintain:

```text
Live operational knowledge
+
Simulation knowledge
+
Historical discoveries
+
Validation confidence
```

---

# 45. Product Vision

The long-term product is not another warehouse robot controller.

It is a **fleet intelligence layer** that can sit above heterogeneous automation infrastructure.

Potential deployment:

```text
        Existing Fleet
        Manager A
            │
        Existing Fleet
        Manager B
            │
        Existing Fleet
        Manager C
            │
            ▼
     ┌───────────────┐
     │   RESILIANT   │
     │               │
     │ Fleet         │
     │ Discovery     │
     │ Layer         │
     └───────────────┘
            │
            ▼
      Fleet Knowledge
```

This makes the architecture potentially independent of the vendor-specific low-level controller.

---

# 46. Why the Concept Matters Beyond Warehouses

The same architecture could apply to:

- manufacturing robots;
- airport autonomous vehicles;
- hospital logistics robots;
- agricultural fleets;
- mining vehicles;
- delivery robots;
- inspection robots;
- autonomous traffic systems.

The common pattern is:

```text
Many agents
+
shared environment
+
complex interactions
+
incomplete operational model
```

Whenever these conditions exist, the system may encounter behaviors that were not explicitly encoded.

---

# 47. Final Product Definition

## RESILIANT is:

> **An autonomous fleet discovery layer that observes embodied multi-robot behavior, identifies meaningful deviations from its current operational model, generates competing hypotheses with NVIDIA Nemotron, tests those hypotheses through controlled NVIDIA Isaac Sim counterfactuals executed at scale on Nebius, extracts evidence deterministically, validates candidate relationships under unseen conditions, and stores surviving relationships as operational fleet knowledge.**

## RESILIANT is not:

> an LLM controlling robots.

> a route planner.

> a replacement fleet manager.

> a generic chatbot.

> a visualization dashboard.

> a black-box reinforcement-learning policy.

> a claim that every discovered relationship is universal scientific truth.

---

# 48. The Core Demonstration

The entire project should ultimately be understandable from one sequence:

```text
                     BEFORE

             35 ROBOT FLEET
                    │
                    ▼
            Unexpected behavior
                    │
                    ▼
             Model is wrong
                    │
                    ▼
             RESILIANT starts
             investigation
                    │
                    ▼
              HYPOTHESES
                    │
                    ▼
             EXPERIMENTS
                    │
                    ▼
             ISAAC SIM
                    │
                    ▼
              EVIDENCE
                    │
                    ▼
              VALIDATION
                    │
                    ▼
           NEW FLEET KNOWLEDGE
                    │
                    ▼
             POLICY UPDATE
                    │
                    ▼

                     AFTER

             SAME DISRUPTION
                    │
                    ▼
          KNOWN OPERATING REGIME
                    │
                    ▼
            POLICY ADAPTATION
                    │
                    ▼
          GRACEFUL DEGRADATION
```

The visual result should make one thing obvious:

# **The fleet did not merely react differently.**

# **Its model of the fleet changed.**

---

# 49. Final Thesis

Autonomous systems are usually evaluated by asking:

> **Can they perform the task?**

RESILIANT asks a harder question:

> **Can the system recognize when its understanding of the task environment is incomplete?**

And beyond that:

> **Can it investigate the gap, acquire evidence, reject its own bad explanations, and retain the knowledge that survives?**

That is the capability RESILIANT proposes to demonstrate.

The system starts with a model.

It encounters behavior the model cannot adequately explain.

It asks a question.

It designs an experiment.

It creates counterfactual worlds.

It gathers evidence.

It attempts to falsify its explanation.

It validates what survives.

Then it changes what the fleet knows.

---

# 50. Final Statement

## **Today's autonomous fleets execute the knowledge their designers gave them.**

## **RESILIANT gives a fleet a mechanism for discovering the operational knowledge its designers did not know they needed.**

---

# References & Source Notes

## NVIDIA Robotics Simulation

NVIDIA describes Isaac Sim as a physically based robotics simulation framework supporting simulation, testing, validation, synthetic data generation, software-in-the-loop, and fleet-level workflows.

- NVIDIA Isaac Sim — Robotics Simulation and Synthetic Data Generation  
  https://developer.nvidia.com/isaac/sim/ citeturn0search0
- NVIDIA Robotics Simulation use case  
  https://www.nvidia.com/en-in/use-cases/robotics-simulation/ citeturn0search3
- NVIDIA Isaac Lab — GPU-accelerated robot learning and simulation  
  https://developer.nvidia.com/isaac/lab citeturn0search4

## Nebius Serverless AI

Nebius describes Serverless Jobs as a runtime for finite containerized workloads and explicitly lists batch processing and scientific simulations among relevant workloads. Nebius Endpoints provide model-serving environments behind HTTP endpoints.

- Nebius Serverless AI  
  https://nebius.com/serverless citeturn0search2
- Nebius announcement of DevPods, Jobs and Endpoints  
  https://nebius.com/blog/posts/introducing-serverless citeturn0search8

## Research Foundations

The broader conceptual foundations relevant to RESILIANT include:

- automated scientific discovery;
- hypothesis-driven experimentation;
- multi-agent task allocation;
- simulation-based optimization;
- active learning;
- digital twins;
- LLM-guided experimentation;
- fleet-level robotics simulation.

These foundations should be treated as established research areas rather than claimed as original inventions by RESILIANT.

## Source Discipline

The project should distinguish clearly between:

1. **Established external technology** — supported by external documentation and research.
2. **Our proposed architecture** — the RESILIANT design.
3. **Our experimental hypotheses** — claims that the prototype must test.
4. **Our eventual empirical results** — claims that can only be made after implementation and evaluation.

This separation is essential for technical credibility.
