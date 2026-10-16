# RESILIANT-Z — Three-Phase Implementation Plan

**Purpose:** refactor the existing project into a reproducible discovery system that is fully prepared for Isaac Sim integration, then stop before running Isaac Sim.

**Target phenomenon:** non-linear fleet congestion associated with the interaction between junction pressure/occupancy and priority-task concentration.
**Repository baseline:** existing `feat/local-discrete-event` work and current local CPU model, subject to a clean-worktree backup and baseline verification before edits.

## Engineering definition of done at the end of Phase III

The project must be able to complete all non-Isaac steps locally and reproducibly: validate telemetry and hypotheses; compile constrained experiments; generate manifests; execute and analyze CPU tests; preserve held-out validation; manage a candidate fleet-knowledge record; compare baseline and candidate policies; and export a fully specified Isaac run bundle. The Isaac adapter, scenario configuration, telemetry interface, artifact schema, host checklist and acceptance tests are in place. The project has **not** launched Isaac Sim, downloaded large assets, invoked cloud jobs, or claimed physics-based results.

The remaining action after Phase III is a clearly gated, human-authorized host session to verify the actual Isaac installation and then execute one small test. This later runtime stage is outside the three phases here.

## Mapping from the supplied 15-session plan

| New phase | Original technical-plan sessions | Gate focus |
|---|---|---|
| Phase I — local engine and contracts | Sessions 1–5 | Repository/contracts, local scene/model, telemetry, baseline, gap detection |
| Phase II — hypothesis-to-evidence | Sessions 6–10 | Nemotron, semantic compiler, experiment planner, optional Nebius orchestration, evidence analyzer |
| Phase III — discovery operationalization and Isaac readiness | Sessions 11–15 plus offline adapter preparation | Deterministic discovery, independent validation, knowledge model, bounded policy/replay, end-to-end hardening, Isaac adapter/host package (not run) |

The original sessions are preserved as work packages; grouping them into phases changes milestone management, not the research objective or trust boundaries.

---

# Phase I — Reliable Local Engine and Contracts

## Objective

Make the existing local discrete-event engine the stable reference implementation. Consolidate policy decisions and contracts before building more intelligence or simulator integration. Keep this phase offline and CPU-only.

## Work packages

### I.1 Baseline and source control hygiene

- Record branch, HEAD SHA, `git status`, tracked/untracked changes, current test result and hashes of existing experiment artifacts.
- Back up uncommitted work before restructuring. Do not reset, force-push, squash, or overwrite evidence artifacts during cleanup.
- Separate source, configuration, test fixtures, logs, metrics and generated simulation artifacts. Ensure virtual environments, caches, credentials, downloaded assets and large generated files remain ignored by Git.
- Establish a single source of truth for factor levels, thresholds, policy names and scenario version. Experimental factor values are design settings until evidence supports otherwise.

### I.2 Canonical policy function

- Extract route/policy selection into a pure, deterministic function callable from both the CPU simulator and, later, the Isaac adapter.
- Inputs must be typed state and validated scenario parameters; output must be a small enum/decision object, not source code or arbitrary commands.
- Keep the baseline policy, static-bypass control and conditioned candidate as separate named policy arms.
- Conditioned routing must fail closed: outside a validated operating envelope, with missing telemetry, invalid pressure, stale observations or unknown state, it must use the declared safe fallback and record why.
- Do not infer collision safety from queueing metrics. Do not give an LLM control authority.

### I.3 Contract and metric audit

- Version the manifest, run result, telemetry snapshot and discovery evidence contracts.
- Define each metric's unit, observation window, denominator, handling of incomplete episodes and backend provenance.
- Distinguish `not measured`, `not applicable`, `failed run`, and measured zero. In particular, do not hard-code zero deadlocks for a model that has no collision/deadlock detector.
- Preserve the existing right-censoring rule: a task that has not started by the horizon is not included in the mean wait and must be separately counted.
- Preserve common random numbers / paired seeds across policy arms and test the pairing invariant.

### I.4 Local benchmark and tests

- Maintain the seeded discrete-event benchmark with documented queueing, service-time, approach, return, priority and bypass assumptions.
- Run the current stress and detour sensitivity experiments only after their outputs are backed up and their source code version is recorded.
- Test the objective components, metric bounds, policy fallbacks, seed pairing, task lifecycle totals, scenario parameter bounds, output schema and repeatability.
- Keep the model evidence label explicit: `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`.

## Phase I deliverables

- Canonical pure policy decision module used by the local simulator.
- Versioned contracts and explicit metric definitions.
- Baseline/stress/sensitivity runs with manifests and provenance.
- Tests for safety-relevant invariants, paired seeds and missing/unmeasured metrics.
- README and local-model limitations updated to match the implementation.

## Phase I exit gate

- Existing and new unit tests pass.
- Lint/format checks pass without broad unrelated formatting churn.
- Re-running a manifest with the same code/config/seed produces the same numeric results apart from wall-clock provenance fields.
- Paired policy arms share equivalent arrivals and pre-sampled randomness.
- Every generated artifact identifies the model as a local discrete-event model, not Isaac Sim.
- No Isaac Sim imports are needed by the local engine.

---

# Phase II — Discovery, Experiment Design and Evidence Gate

## Objective

Turn the local engine into a defensible hypothesis-to-evidence workflow. Reasoning generates hypotheses; deterministic contracts compile hypotheses into bounded experiments; experiment runs create evidence; statistical analysis produces provisional candidates. Independent validation and promotion into trusted knowledge are completed in Phase III.

## Work packages

### II.1 Telemetry and gap detection

- Define a versioned semantic fleet snapshot with timestamp, robot count/density, junction occupancy/pressure, task arrivals, priority mix, completed/queued/not-started tasks and baseline predictions.
- Separate raw observations, aggregated state and the model prediction. Track sampling interval, missing data and stale telemetry.
- Detect persistent model/reality residuals using explicit thresholds and a documented false-alert policy. Treat the initial detector as a prototype and report its calibration limits.
- Make “no gap” a valid state; the reasoner should not run on every ordinary telemetry sample.

### II.2 Nemotron / provider boundary

- Keep the existing Nebius Token Factory integration behind a provider interface; add a deterministic fixture provider for tests and offline development.
- The default test path must not require an API key, internet access, cloud job, or spend.
- Treat model responses as untrusted. Require strict JSON/schema validation, allowed factor names, known scenario IDs, parameter ranges, bounded hypothesis count and bounded output size.
- Retry only a bounded number of times. Invalid output must be rejected; repeated failures use documented deterministic fallback hypotheses or terminate the investigation. Never execute generated Python or arbitrary simulator commands.
- Log provider/model identifier, prompt/schema version and response hash; redact credentials and private data.

### II.3 Semantic compiler and experiment planner

- Map a valid hypothesis into a predeclared experiment grammar; never accept free-form control code.
- Support the existing controlled factor design and paired replay protocol first. Keep discovery seeds and validation/replay seeds disjoint.
- Use a registry for manifests and statuses: `planned`, `validated`, `queued`, `running`, `succeeded`, `failed`, `invalidated`.
- Validate all manifests locally before dispatch. Use deterministic CPU mode as the default backend.
- Add a Nebius Jobs execution adapter only as an optional, explicitly enabled path after a no-cost/credit and permission check. It must not be called by tests or default commands.

### II.4 Evidence analyzer and candidate extraction

- Keep evidence calculations deterministic and independent of the LLM.
- Analyze paired differences and interaction contrasts with sample counts and uncertainty intervals. Report interval method and preregistered metrics; flag the intervals as exploratory when multiple comparisons are unadjusted.
- Preserve failed/incomplete runs in audit output; exclude them from statistical estimates only under a written rule, never silently.
- Mark outputs as provisional candidates, not validated discoveries. Maintain the separate validation seed allocation and leave promotion to Phase III.
- Include comparator baselines: reactive/current policy, fixed policy and a blind/predeclared grid where appropriate.

### II.5 Candidate discovery output (pre-promotion only)

- Assemble candidate records from measured effects, exact conditions, uncertainty, sample count and source manifest IDs.
- At the end of Phase II, candidate records remain provisional. Do not mark them validated, persist them as trusted knowledge or operationalize a policy until Phase III's independent-validation gate is implemented.
- Prepare before/after comparison interfaces, but defer policy promotion and final replay acceptance to Phase III.

## Phase II deliverables

- Telemetry snapshot schema and model/reality-gap detector.
- Provider abstraction with offline deterministic fixtures.
- Strict hypothesis schema and experiment compiler.
- Deterministic planner, local execution registry and optional cloud adapter behind a hard opt-in.
- Evidence report and provisional candidate records, not yet trusted knowledge.
- Failure-path tests for malformed JSON, unknown fields, out-of-range values, missing metrics, corrupt results, timeouts and failed simulator jobs.

## Phase II exit gate

- Entire discovery/evidence pipeline can be tested offline.
- No invalid hypothesis can reach the simulator backend.
- LLM wording never sets evidence status or declares a discovery valid.
- Discovery and validation seeds are disjoint and documented.
- Cloud/API use is opt-in, has explicit time/cost bounds and is absent from CI.
- Candidate outputs are reproducible and traceable, but not promoted into trusted operational knowledge.
- Before/after replay is specified and the comparison path is contract-tested with fixtures.

---

# Phase III — Deterministic Discovery, Operationalization and Isaac Readiness (STOP BEFORE EXECUTION)

## Objective

Complete the validation/knowledge/policy loop, then prepare NVIDIA Isaac Sim as the future embodied backend. This phase builds and tests its software contracts offline. It does not install, download assets or launch Isaac Sim.

## Work packages

### III.1 Deterministic discovery and independent validation

- Turn Phase II candidate estimates into explicit discovery decisions using predeclared acceptance criteria and separate validation data.
- Require disjoint discovery and validation seeds. Record replication rate, uncertainty, validation sample count and whether the result is validated, rejected or inconclusive.
- If a candidate does not generalize, preserve the audit record and reject or mark it inconclusive. Never change thresholds after seeing holdout data without versioning the protocol.

### III.2 Persistent knowledge, bounded policy and replay

- Store candidate/discovery records with exact conditions, metric definitions, effect estimate, uncertainty, sample size, validation state, source run IDs, configuration hash and code SHA.
- Use lifecycle states such as `candidate`, `validated`, `rejected` and `superseded`. Promotion must be explicit, reversible and auditable.
- Select among allowlisted parameter updates only. No generated source code, direct velocity commands or unbounded controller changes.
- Replay baseline and candidate policy on matched workloads/seeds where scientifically valid. Report throughput, wait, queue growth, completion, intervention rate and any instrumented physical safety metrics separately.
- Do not apply policy changes to physical robots or a live fleet in this project.

### III.3 Backend contract and dependency isolation

- Extend the existing `SimulatorAdapter` protocol rather than introducing a parallel metrics format.
- Implement an Isaac adapter module with lazy simulator imports; the local engine and normal CI must import without `isaacsim`, `omni` or GPU libraries installed.
- The adapter must receive a validated `ExperimentManifest`, create a run context, execute one bounded episode when explicitly enabled, emit the same `SimulationRun` contract, and preserve failures separately.
- Provide a fake backend for adapter contract tests. Do not use the earlier shadow simulation to claim canonical-policy parity.
- Reuse the pure canonical route-decision function from Phase I. A second, copied policy implementation is not acceptable.

### III.4 Scenario and robot definition

- Define a versioned warehouse scenario: connected aisles, multiple junctions, pickup/drop zones, priority-task region, charging region and fixed traffic bottlenecks.
- Target the proposal's 20–35 AMRs, but stage validation at 1 robot, 2 robots, 10 robots, then 20–35. Each scale is gated by the prior scale's results.
- Select a locally available, supported wheeled mobile robot asset only after reviewing the target host's Isaac release and available licensed assets. Do not assume the lab workstation has a particular robot USD cached.
- Use articulated physics and a documented wheel/differential-drive controller. Directly changing an actor's world pose each frame is not a physical robot controller and cannot satisfy this gate.
- Keep geometry, robot parameters, navigation/task logic and policy settings separate, versioned and hashed.

### III.5 Evidence instrumentation

Record per simulated tick or event as appropriate:

- sim timestamp and wall-clock timestamp;
- robot ID, commanded velocity, measured linear/angular velocity, pose and route state;
- task ID, arrival/start/completion/cancel state and timestamps;
- junction entry/exit and occupancy;
- policy arm, policy decision, trigger state and fallback reason;
- contact/collision/contact-pair events and robot-stop events where implemented;
- simulation reset, exception, timeout, dropped data and incomplete episode status;
- asset/scenario/config hashes, backend release, host metadata and Git SHA.

Metrics such as collision count, blocked-route duration and deadlock events stay `unmeasured` until the instrumentation and event definitions actually support them.

### III.6 Host/runtime preparation

- Keep the current project environment for CPU development. Do **not** install Isaac Sim into the existing `.venv`.
- Once the actual provided host is known, select one supported route: the binary installation and its own launcher, a dedicated Isaac Python environment, or the institution's approved container/cloud setup. Do not mix their dependency models.
- Target documented Isaac Sim 6.2 interfaces provisionally; lock the actual version only after reading the workstation's installed version and confirming compatibility.
- Keep ROS 2 optional. Only add it if the architecture needs a separate ROS process and the host's exact Isaac/ROS pair is officially supported. Do not create a ROS workspace by guesswork.
- Store host-specific paths in a local ignored environment file. Never commit tokens, browser cookies, SSH keys, credentials or downloaded asset caches.
- Put run artifacts in an output directory that survives a short lab session and can be copied back via the approved transfer method.

### III.7 Validation scaffolding — offline only

- Add fake-backend tests for input validation, result provenance, failure-state mapping, metric schema and no-result-on-failure behaviour.
- Add static checks that the normal CPU package does not eagerly import Isaac Sim and that Isaac execution is disabled by default in configuration.
- Validate example manifest/result files without accessing Isaac or Nebius.
- Prepare a host acceptance checklist: exact release; OS; GPU/VRAM; driver; RAM; free disk; launcher; asset access; permissions; persistent output path; license/access terms.
- Write the eventual manual run procedure, but leave it explicitly **not executed**.

## Phase III deliverables

- Isaac adapter design using the existing simulator contract.
- Versioned warehouse and robot configuration schema, without downloaded assets.
- Articulation/controller and telemetry requirements documented.
- Artifact importer/validator contract, runtime provenance contract and failure report.
- Separate-environment policy, compatibility checklist and explicit Isaac execution gate.
- Fake-backend tests and offline checks.

## Phase III exit gate — final state requested in this task

- Unit, contract and fake-backend tests pass on the current non-Isaac environment.
- Existing local benchmark still runs and the original output remains available.
- Independent validation, durable knowledge records and bounded policy replay are complete and tested.
- Isaac modules are lazy-loaded and non-Isaac tests work with no Isaac package installed.
- Configuration defaults to `execution_enabled: false`; no script downloads, installs or launches Isaac Sim.
- No robot-physics, collision-safety or Isaac result is claimed.
- A ready-to-review Git diff, manifest bundle, scenario specification, compatibility sheet and manual host runbook exist.

**Stop here. Wait for explicit user authorization before any Isaac Sim installation, asset download, simulator startup or GPU experiment.**

---

# Cross-phase scientific and safety rules

1. **Reasoning is not evidence.** Only measured runs and deterministic analysis can support a discovery.
2. **Simulation is not reality.** Results apply to the model/scenario/version under test; transfer requires separate validation.
3. **Fail closed.** Unknown/missing/stale state, invalid manifests and corrupt results are rejected or use the declared safe fallback.
4. **No arbitrary code generation.** The LLM can propose structured hypotheses, never executable experiments or velocity commands.
5. **No hidden result rewriting.** Crashed or incomplete runs are labelled and preserved.
6. **Reproducibility.** Version, seed, configuration, scenario, model/provider, metrics definition and code SHA are mandatory provenance.
7. **No surprise cost.** Local CPU mode remains default. Nebius API/job execution requires explicit environment enablement and budget/permission confirmation.
8. **One policy source.** The CPU engine and Isaac backend call the same tested decision function.
9. **Evidence semantics.** Unmeasured metrics are `null`/`unmeasured`, not zero.
10. **No unauthorized runtime actions.** Phase III here is a preparation phase and ends before Isaac is launched.
