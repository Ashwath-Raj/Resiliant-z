# RESILIANT-Z

**Evidence-driven operational discovery for simulated multi-robot fleets.**

> The AI proposes. Controlled experiments challenge it. Independent evidence decides.

RESILIANT-Z investigates whether an operational relationship absent from an initial model can be identified through controlled fleet experiments, validated on held-out runs and used to select a bounded policy intervention.

## Current implementation status

This starter repository contains a runnable first vertical slice:

- a deterministic, seeded **synthetic surrogate** for local development and CI;
- a CPU-only **discrete-event fleet model** with robot availability, shared junction/bypass queues, priority service, seeded arrivals and held-out interaction analysis;
- a validated experiment-manifest contract and a bounded 2×2 factorial plan;
- local baseline hypotheses and an optional Nebius Token Factory hypothesis-generation adapter;
- a main-effects versus interaction-model comparison using NumPy least squares;
- held-out-seed validation;
- paired before/after policy replay;
- JSON/JSONL/Markdown provenance artifacts;
- a FastAPI API and browser dashboard;
- a CSV contract validator for metrics exported by a simulator host;
- tests and GitHub Actions CI.

**The current surrogate is not NVIDIA Isaac Sim and is not a physics-based digital twin.** Its dynamics contain a deliberately planted interaction so we can verify the analysis pipeline. The actual Isaac Sim scene/host runner still needs to be implemented and validated on the approved lab workstation. Do not present surrogate metrics as Isaac Sim or real-robot evidence.

## Zero-rupee rule

The code does not provision paid compute or start cloud GPU instances. The local benchmark runs on CPU. Nebius Token Factory calls are opt-in and should only be used while promotional credits remain available. Check the account's credit balance and do not enable pay-as-you-go. Isaac Sim execution is intended for an approved university workstation or other explicitly free compute allocation.

## Requirements

- Ubuntu/Linux or another Python development environment
- Python 3.11 or newer (Python 3.12 recommended)
- Internet only for package installation and optional Token Factory inference
- A compatible GPU host is required for actual Isaac Sim execution, not for the local surrogate

## Install

```bash
bash scripts/bootstrap.sh
```

This creates `.venv`, installs the project and development tools, and copies `.env.example` to `.env` if `.env` does not exist. It does not insert API credentials or provision cloud resources.

Check the environment and run the tests:

```bash
.venv/bin/resiliant doctor
.venv/bin/ruff check src tests
.venv/bin/pytest
```

## Run the end-to-end local benchmark

```bash
.venv/bin/resiliant demo --hypotheses local
```

Generated files are written to `artifacts/demo/`:

- `report.md` — human-readable results and explicit limitations
- `summary.json` — aggregate run summary
- `hypotheses.json` — hypotheses plus source/model provenance
- `discovery.json` — evidence model comparison and decision
- `manifests.jsonl` — experiment configurations and seeds
- `runs.jsonl` — metric records and experiment provenance

The default run contains 20 discovery runs, 20 validation runs and 24 policy-replay runs (12 matched seeds × 2 policy settings). One discovery run is also used as the hypothesis-generation pilot; it is not duplicated in the run records.

This local run is deliberately free and offline. Its output must retain the `SYNTHETIC SURROGATE — NOT ISAAC SIM` label.

## Run the local discrete-event fleet model (still no GPU/API required)

```bash
.venv/bin/resiliant fleet-demo
```

This mode runs a ten-robot queueing model for a 15-minute simulated horizon. Arrivals, robot availability, approach travel, a shared junction server, a separate bypass server, priority scheduling and return-to-availability are represented as deterministic events under a fixed seed. It is more behavior-driven than the formula-based surrogate, but it still omits geometry, collisions, sensors, kinematics and physical robot control. Policy candidates are evaluated only after an independent interaction-validation gate passes; selection seeds are held apart from the final paired replay seeds.

The default experiment uses 20 discovery runs and 20 held-out validation runs. If the discovery gate passes, it evaluates four predeclared static bypass ratios on 20 separate high-risk policy-selection runs, then compares three policies—no-bypass baseline, selected static bypass, and discovery-conditioned bypass—under nominal and high-risk conditions using 12 paired replay seeds per condition (72 replay runs; 132 total runs). The conditioned policy can divert traffic only when the predeclared high-demand/high-priority envelope and a live junction-pressure trigger are both present. Operating-envelope cuts are midpoints between predefined factor levels, not learned thresholds. If discovery is `inconclusive` or `rejected`, nonzero interventions are blocked. The report includes paired effect estimates and 95% Student-t intervals. A result may be `inconclusive`; the tool must not be tuned merely to force a positive decision. All output remains labelled `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`.

Artifacts are written to `artifacts/fleet-demo/`. This mode is completely local and does not call Token Factory or provision GPU compute.

## Run the browser dashboard

```bash
.venv/bin/resiliant serve
```

Open <http://127.0.0.1:8000>. The dashboard triggers the local benchmark through the API. Leave **Generate hypotheses with Nebius Token Factory** unchecked for offline execution.

The default server binds to `127.0.0.1`; it is not exposed to the public internet. Do not change the bind address on a shared network without adding authentication and appropriate network controls.

## Optional: connect Nebius Token Factory

1. Create a Token Factory API key in the Token Factory console. This key is separate from a Nebius Cloud IAM token.
2. Edit `.env` and set `NEBIUS_API_KEY`.
3. List the models visible to the key:

   ```bash
   set -a; source .env; set +a
   .venv/bin/resiliant models
   ```

4. Copy an exact available model ID into `NEBIUS_MODEL` in `.env`.
5. Run an explicit API-backed benchmark:

   ```bash
   .venv/bin/resiliant demo --hypotheses nebius
   ```

The configured endpoint is `https://api.tokenfactory.nebius.com/v1`. The application sends a chat-completions request. If the request fails in `auto` mode, the output will disclose that a local fallback was used; explicit `nebius` mode fails rather than mislabelling fallback hypotheses as model output. API calls consume available Token Factory credits. No API key is sent to the browser or committed to Git.

## Remote-first workstation model

Develop and test backend/analysis/UI code locally. When workstation access is granted:

1. Pull a known Git commit on the approved Linux GPU workstation.
2. Verify its NVIDIA driver, GPU, RAM, disk space and permitted container/runtime configuration.
3. Run the pinned Isaac Sim environment and execute the prepared scenario.
4. Export actual per-run metrics using the contract in [`docs/isaac-sim-host.md`](docs/isaac-sim-host.md).
5. Validate the CSV contract on the laptop or workstation:

   ```bash
   .venv/bin/resiliant validate-isaac-csv path/to/isaac_metrics.csv
   ```

The CSV command validates shape and ranges; it cannot independently prove that a row came from Isaac Sim. Preserve the simulator logs, exact commit, scene version, seed, configuration and host details as provenance. The actual Isaac Sim scene-runner is not included in this initial working scaffold.

## Scientific protocol

- Fit the main-effects and interaction models on discovery seeds only.
- Evaluate both fitted models on independent held-out seeds.
- Keep LLM text out of the evidence decision: the model cannot certify its own hypothesis.
- Distinguish the preregistered factor levels from discovered thresholds.
- Compare RESILIANT against a static baseline and a blind experiment sweep before making efficiency claims.
- Treat the current policy replay as a surrogate-only intervention until it is implemented and measured in the Isaac Sim scenario.

The validation rule in this prototype is a transparent engineering criterion, not a universal statistical significance test. Later analysis should add uncertainty intervals, sensitivity checks and validation across a new scenario or layout.

## Git workflow

If `Resiliant z` is not already a repository:

```bash
bash scripts/init_git.sh
git status --short
git add -A
git commit -m "chore: scaffold reproducible RESILIANT-Z benchmark"
```

Then use small feature branches and merge only passing code. Never commit `.env`, API keys, GPU assets, downloaded simulator caches, or bulk run artifacts. The `.gitignore` excludes those by default. Commit compact reproducibility fixtures and selected reports deliberately rather than committing every generated run.

CI runs Ruff and pytest without needing Isaac Sim or Token Factory credentials.

## Core commands

```bash
.venv/bin/resiliant doctor
.venv/bin/resiliant models
.venv/bin/resiliant demo --hypotheses local
.venv/bin/resiliant fleet-demo
.venv/bin/resiliant demo --hypotheses auto
.venv/bin/resiliant demo --hypotheses nebius
.venv/bin/resiliant validate-isaac-csv artifacts/isaac/metrics.csv
.venv/bin/resiliant serve
```

See [`docs/architecture.md`](docs/architecture.md), [`docs/experiment-contract.md`](docs/experiment-contract.md), and [`docs/isaac-sim-host.md`](docs/isaac-sim-host.md).
