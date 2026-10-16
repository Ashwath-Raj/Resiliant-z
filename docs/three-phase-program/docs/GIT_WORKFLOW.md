# Git Workflow for the Three-Phase Program

## First action is inventory, not editing

The existing local branch is `feat/local-discrete-event`. Treat the user worktree as authoritative. Before starting, record `git status -sb`, `git log --oneline --decorate -10`, tracked diff and untracked files. Create a local backup patch or bundle of current uncommitted work. Do not reset or clean untracked files to get a clean tree.

## Branching model

Keep one source tree; phases are delivered as reviewable milestones, **not as duplicated source directories**.

1. `phase/1-local-engine-contracts` — canonical decision function, schema/metric audit, local tests.
2. `phase/2-discovery-evidence` — telemetry, provider boundary, experiment compiler, evidence validation, knowledge and replay.
3. `phase/3-isaac-readiness` — simulator protocol implementation, scenario configs, fake backend and host readiness docs; no Isaac launch.

Create each branch from the accepted previous phase only after its gate passes. If the current `feat/local-discrete-event` work is still uncommitted, do not create a branch or modify it until a backup is complete and changes are understood.

## Commit standards

Use small, scoped commits with clear messages, for example:

- `refactor(policy): isolate canonical route decision`
- `test(sim): enforce paired-seed and missing-metric invariants`
- `feat(discovery): validate bounded experiment proposals`
- `feat(evidence): add held-out discovery validation gate`
- `feat(sim): add Isaac backend contract and fake adapter tests`
- `docs(isaac): record host compatibility and run gate`

Before each commit:

- review `git diff --stat` and each substantive hunk;
- run tests and `git diff --check`;
- verify `.env`, API keys, caches, downloaded assets, and generated run data are not staged;
- stage explicit paths rather than `git add -A` during uncertain work;
- keep previous artifacts and manifests recoverable.

Do not push, force-push, merge or tag a release automatically. Those are explicit review gates.

## Ignore policy

Keep these outside version control unless there is an explicit reason to include them:

- `.venv/`, `.venv-isaac/`, `env_isaacsim/`, `__pycache__/`, caches and shader caches;
- `.env`, credential files, access tokens, SSH material;
- downloaded robot USD/asset bundles and Isaac installation directories;
- raw high-volume traces and generated results (archive separately if necessary);
- host-specific absolute paths.

Version-control small configs, schemas, deterministic fixtures, test results summaries and documentation. Record checksums of large assets instead of committing them by default.
