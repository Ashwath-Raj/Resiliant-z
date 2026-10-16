# RESILIANT-Z — Session-by-Session Engineering Execution Matrix

This document expands the supplied 15-session plan into implementation tasks that can be reviewed against the current repository. It does **not** authorize Isaac Sim, asset downloads, GPU simulation, Nebius job submission, or paid API calls. Complete and sign off one session at a time; do not mark a session complete just because its module or file exists.

## Program rules

1. Inspect existing code, APIs, tests, branches and artifacts before changing anything. Extend the current repository; do not replace it with a scaffold or duplicate an existing subsystem.
2. Preserve the current CPU discrete-event backend as a regression baseline and keep its evidence label `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`.
3. Never claim collisions, deadlocks, contact events or physics metrics are zero unless the backend measured them with an implemented detector. Use `null`/`unmeasured` where appropriate.
4. Keep LLM output untrusted. LLMs cannot execute code, change safety bounds, issue robot velocities, or promote their own hypotheses.
5. Keep cloud/model-provider work opt-in. Unit tests and default commands must not need internet, secrets, paid API calls or remote jobs.
6. Use separate discovery, selection and validation/replay seed sets. No leakage from candidate selection into final validation.
7. Run relevant tests after each session and full regression tests at the phase gate. Update this matrix with commit/file/test references; never fake completion.
8. Stop before running Isaac Sim. Phase III prepares the adapter and run bundle for a later explicitly authorized host session.

---

## Phase I — Local engine and contracts

### Session 1 — Repository and contract baseline
**Implement:**
- Record branch, `HEAD`, working-tree state, test/lint baseline and the paths/hashes of important existing experiment artifacts.
- Inspect existing Pydantic models, CLI routes, backend protocol, `fleet_pipeline`, sensitivity/stress tests, metrics and report-writing paths before designing edits.
- Define a backward-compatible run manifest/result contract with experiment/run IDs, seed, scenario/config version, backend, code SHA, status, timestamps, parameters, metrics and failure details.
- Establish a safe backup procedure for dirty changes; never reset, force-push, silently discard or overwrite user's work.

**Tests/acceptance:** contract round-trip tests; invalid fields rejected; baseline test results captured; current artifacts unchanged. No simulator or cloud command runs.

### Session 2 — Local scenario/backend boundary
**Implement:**
- Keep the current discrete-event model as the reference backend and formalize the interface that a later physics backend must satisfy.
- Specify the future warehouse scenario (aisles, shelves, multiple intersections, task stations, charging area, pickup/drop-off, robot spawn poses) independently from backend code.
- Separate scenario factors from policy parameters and record units/ranges. Do not invent calibrated real-world parameters.
- Document which phenomena the local model omits: geometry, kinematics, sensing, collisions, contacts and physical deadlocks.

**Tests/acceptance:** local backend satisfies the contract; scenario configs parse without importing Isaac packages; evidence labels remain distinct.

### Session 3 — Telemetry and semantic state
**Implement:**
- Add a versioned telemetry schema and a pure aggregation layer for time-windowed fleet state: active/idle robots, task arrivals/starts/completions, queue state, priority ratio, junction occupancy/pressure when actually measured, missing/stale values and sampling interval.
- Persist/replay telemetry independently of the backend. Never feed high-frequency raw state to the LLM by default.
- Explicitly distinguish missing, stale, not applicable, not measured and measured zero.

**Tests/acceptance:** valid fixtures load; missing/stale fields propagate as quality flags; aggregate values have units and deterministic window boundaries.

### Session 4 — Baseline performance model
**Implement:**
- Formalize the current baseline estimator using existing observable factors and documented assumptions. Keep predicted and observed metrics separate.
- Emit prediction residuals with baseline-model version, feature window and data-quality flags.
- Fit/calibrate only from allowed training data; do not use final validation/replay seeds to tune the baseline.

**Tests/acceptance:** deterministic fixture predictions; residual arithmetic tests; invalid measurements do not become valid prediction rows; baseline model explicitly marked as prototype if not calibrated.

### Session 5 — Persistent model/reality-gap detector
**Implement:**
- Add an explicit detector with persistent-window logic, threshold configuration, cooldown/deduplication and an audit record for each trigger/rejection.
- Reject startup transients, missing/stale telemetry, invalid states and known scenario transitions.
- Keep detector thresholds configurable and labelled as uncalibrated until tested with normal and injected-degradation fixtures.

**Tests/acceptance:** no-trigger normal fixture, trigger sustained-degradation fixture, no trigger for malformed/stale data, and deterministic trigger IDs. Phase I gate review required before Phase II.

---

## Phase II — Hypothesis-to-evidence pipeline

### Session 6 — Nemotron/provider abstraction
**Implement:**
- Define a provider interface, deterministic fixture provider and a separate optional Nebius/Nemotron implementation using the provider currently supported by the project.
- Require schema-conforming hypotheses with IDs, falsifiable claims, registered variables, predicted direction/response, factor values, assumptions and rationale.
- Bound response bytes, hypothesis count, retries and timeouts; redact keys and response secrets from logs.
- Default to fixture/offline mode. Do not call the real endpoint during tests or default CLI operation.

**Tests/acceptance:** valid provider fixture, malformed JSON, timeout, refusal/empty answer, out-of-schema factors and retry exhaustion are tested without network access.

### Session 7 — Semantic experiment compiler
**Implement:**
- Compile accepted hypotheses into a constrained experiment DSL/manifest using a registry of parameter names, types, ranges, units, supported interactions and scenario IDs.
- Enforce type, range, cross-parameter, maximum run count, maximum horizon and allowed-backend validation.
- Never execute generated code or accept free-form shell commands from model output.

**Tests/acceptance:** allowlisted hypothesis compiles; unknown factor, unsafe range, unsupported scenario, oversized request and malformed output are rejected with actionable errors.

### Session 8 — Experiment planner and run registry
**Implement:**
- Plan a deterministic coarse-to-fine or predeclared factorial experiment with paired policy arms and common random numbers where supported.
- Allocate disjoint discovery, selection, validation and replay seeds; persist the allocation in manifests.
- Track run states: `planned`, `validated`, `queued`, `running`, `succeeded`, `failed`, `timed_out`, `incomplete`, `invalidated`.
- Keep selection strategy interpretable and record why each experiment was selected.

**Tests/acceptance:** deterministic manifest generation; no seed overlap; exact paired arms; state transitions valid; failed jobs never become successful evidence.

### Session 9 — Optional Nebius orchestration boundary
**Implement:**
- Create an orchestration interface with a local executor and a separately configured Nebius Jobs adapter only if it is supported by the current dependencies and documentation.
- Do not add a provider credential or call a remote API automatically. Require an explicit environment/config opt-in and preflight for permissions, credits/quota, image, resources and spending.
- Persist job ID, request hash, container/image digest, start/end times, logs location and failure status.

**Tests/acceptance:** local fake executor and mocked remote failure/status tests; default path proves no network calls; no real job is submitted.

### Session 10 — Deterministic evidence analyzer
**Implement:**
- Validate result completeness/ranges/provenance before analysis. Preserve failed and incomplete rows in the audit trail; define when rows are excluded from estimates.
- Implement paired treatment deltas, sample counts, effect sizes and confidence intervals with documented assumptions/methods.
- Report exploratory/multiple-comparison caveats. The LLM must not compute or approve evidence.

**Tests/acceptance:** hand-calculated fixtures for paired effects/intervals; invalid/missing metrics rejected or marked unmeasured; deterministic report; failure rows retained.

**Phase II gate:** end-to-end offline run from telemetry fixture to gap → fixture hypothesis → compiler → local planned runs → evidence report, with no API/network/cloud calls. Candidate output remains provisional until Phase III's validation gate.

---

## Phase III — Validation, knowledge, replay and Isaac readiness

### Session 11 — Deterministic candidate discovery
**Implement:**
- Extract interpretable candidate relationships from the discovery/selection data only (for example main effects and the predeclared occupancy × priority interaction).
- Record effect direction/magnitude, uncertainty, candidate variables, exact condition range, evidence IDs, model version and selection procedure.
- Mark candidates `provisional`; do not let an LLM assign `validated` status.

**Tests/acceptance:** known synthetic effect recovered; null/noisy relationship not automatically promoted; candidate references existing evidence; discovery data split enforced.

### Session 12 — Independent validation
**Implement:**
- Test candidates against disjoint seeds and changed initial states/task patterns/workload scenarios.
- Define promotion criteria before looking at final validation results; include effect direction, uncertainty, replication and practical-impact criteria.
- Support outcomes `validated`, `rejected`, `inconclusive`, `invalidated`; do not force a binary pass when evidence is insufficient.

**Tests/acceptance:** passing, failing and inconclusive fixtures; validation seed leakage test; criteria and confidence calculations fully deterministic.

### Session 13 — Versioned fleet knowledge model
**Implement:**
- Persist immutable candidate/validated-knowledge records with schema version, provenance, conditions, limits, evidence links, validation result, creation timestamp and lifecycle status.
- Add load/list/compare/rollback/invalidate operations; use safe atomic writes or the existing database choice rather than adding a second datastore unnecessarily.
- Permit operational policy generation only from validated records.

**Tests/acceptance:** serialize/deserialize round-trip; provenance required; older schema migration or explicit rejection; rollback/invalidation tests; no promotion from provisional status.

### Session 14 — Bounded policy generation and paired replay
**Implement:**
- Map validated knowledge to an allowlisted, typed policy action; do not accept arbitrary executable code or LLM-generated controller commands.
- Define a fail-closed fallback for missing/stale telemetry, conditions outside validated ranges, invalid knowledge versions and policy execution failures.
- Run baseline vs candidate on paired replay seeds and report benefit, regressions, operational limits and uncertainty. Keep any safety-related metrics unmeasured until a backend measures them.

**Tests/acceptance:** policy limits enforced; out-of-envelope fallback; deterministic decisions; paired comparison tests; policy does not change baseline behaviour when inactive.

### Session 15 — End-to-end hardening and Isaac handoff package
**Implement:**
- Integrate CLI/API workflow: telemetry fixture → detector → hypotheses → compiler → planner → backend → evidence → candidate → independent validation → knowledge → policy replay.
- Add end-to-end fixture tests for success, rejection, timeout, incomplete evidence, validation failure and rollback.
- Define a versioned Isaac adapter that uses the same validated policy decision function and the existing result contract; lazy-load Isaac-specific code so non-Isaac tests work without Isaac installed.
- Write a versioned warehouse config and articulate mobile-robot controller requirements. Define commanded vs measured velocities, pose, task lifecycle, junction occupancy, contacts/collisions and run-failure telemetry.
- Produce a run bundle (manifest + config + hashes + expected artifact schema + manual host checklist) and document the eventual host procedure.

**Tests/acceptance:** end-to-end fixture pipeline passes; CLI defaults to local offline mode; static test confirms Isaac execution disabled by default; no Isaac asset is downloaded, no simulator launched and no Nebius job/API call made. Isaac handoff must explicitly distinguish visual/demo readiness from physics-validated controller behaviour.

---

## Final gate — deliberately pre-Isaac

Before asking the user to authorize a real Isaac run, attach evidence for:

- [ ] all three phase gates signed off;
- [ ] lint/format/test/compile/whitespace commands passing;
- [ ] current CPU benchmark regression preserved and separately labelled;
- [ ] full offline end-to-end success and failure-path tests passing;
- [ ] independent discovery validation and versioned knowledge promotion tested;
- [ ] reproducible adapter/run bundle and artifact validator;
- [ ] current host's exact OS/GPU/VRAM/driver/RAM/disk/runtime compatibility sheet;
- [ ] documentation showing Isaac Sim has **not** been launched yet.
