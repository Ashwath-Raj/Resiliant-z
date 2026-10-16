# RESILIANT-Z — Three-Phase Engineering Program

This is a **repository overlay and implementation plan** for the existing private `Ashwath-Raj/Resiliant-z` project. It does not replace the source repository and it does not contain a one-click Isaac Sim installer or simulator launcher.

## Intent

Develop the project in three phases and stop at the boundary immediately before an authorized Isaac Sim run:

1. **Phase I — Reliable local engine and contracts.**
2. **Phase II — Discovery, experiments, evidence, validation and knowledge pipeline.**
3. **Phase III — Isaac Sim integration readiness.** Build/test the adapter interfaces offline, prepare a separate environment specification, and verify that the integration is gated. **Do not install, download assets, launch Isaac Sim, or execute a simulation until explicitly authorized.**

## Read first

- `README.md` — program scope and safety guardrails.
- `docs/SESSION_BY_SESSION_EXECUTION.md` — concrete implementation tasks and acceptance tests for all 15 original sessions.
- `docs/CODE_AGENT_EXECUTION_PROMPT.md` — instructions for a coding agent working inside the actual local repository, with per-session tests and no-Isaac restrictions.

- `docs/THREE_PHASE_IMPLEMENTATION_PLAN.md` — authoritative plan and acceptance gates.
- `docs/ARCHITECTURE_AND_TRUST_BOUNDARIES.md` — component ownership and control safety.
- `docs/PHASE_ACCEPTANCE_MATRIX.md` — phase exit criteria.
- `docs/ISAAC_SIM_READINESS.md` — host/runtime/asset preparation, no launch steps executed.
- `docs/GIT_WORKFLOW.md` — branch, backup, commit and artifact rules.
- `docs/SOURCE_ALIGNMENT.md` — how this plan maps to the supplied product and technical documents.

Quality-check commands are listed in `docs/CODE_AGENT_EXECUTION_PROMPT.md`. This documentation bundle does not include an installer or a separate verification script.

## Important status

The three-phase program documentation is present in this repository. Session 1 has been implemented and recorded in `docs/IMPLEMENTATION_LEDGER.md`; the pre-existing dirty worktree was preserved, not committed or pushed. A pre-edit patch, untracked-file archive, and checksums for existing artifacts were saved in session state. Session 2 has not started and awaits review. No Isaac Sim installation, asset download, launch, cloud job, or GPU simulation was performed.

## Guardrails

- No Isaac Sim launch, installer, asset download, or GPU execution is included or run here.
- No cloud API request is required to test the local pipeline.
- No LLM can issue velocity commands, generate executable simulator code, set policy limits, or approve a discovery.
- No simulation failure may be converted into a successful result row.
- A `deadlock_events` value of `0` may only be used if the backend actually measured it and the event definition is implemented. Otherwise use `null` / `unmeasured`.
- Keep the existing canonical local discrete-event model and its reports as the reference; do not replace it with a shadow model from the earlier fast-track scaffold.
- Preserve provenance on all evidence: code SHA, scenario/config version, manifest, seed, backend/runtime version, metrics and logs.

## Official simulator references

See `docs/ISAAC_SIM_READINESS.md` for NVIDIA's current versioned requirements, Python environment warning, controller and ROS 2 references.
