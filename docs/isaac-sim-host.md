# Isaac Sim host integration: operator checklist and CSV contract

## Important status

This repository does not yet launch Isaac Sim or construct a warehouse scene. It includes the shared run contract and a validator for actual host-produced metrics so the rest of the application can be developed without continuous GPU access. Do not describe the current surrogate as Isaac Sim output.

## Before using a campus workstation

1. Obtain explicit permission to use the machine, run containers, reserve GPU time and access it remotely.
2. Run `nvidia-smi`; identify the exact GPU(s), driver version and available memory.
3. Confirm OS, system RAM, free SSD space, Docker/container permissions, outbound asset access, and the institution's scheduler or job-submission policy.
4. Check the exact Isaac Sim release's official requirements. Current requirements are release-specific; don't infer compatibility from the word “DGX” alone.
5. Clone/pull a known Git SHA and pin the simulator release/image. Store all persistent outputs somewhere that survives a session reset.
6. Test one robot and one junction before increasing fleet size or enabling sensors.

## Remote workflow

- Prepare and validate manifests locally.
- Transfer the selected manifests to the approved host using Git/SSH or the institution's sanctioned file transfer method.
- Execute only prevalidated manifests; do not execute arbitrary code emitted by the LLM.
- Save host logs, scene/config hashes and per-run seeds.
- Export one CSV row per completed run using the schema below.
- Copy the CSV and associated logs back to the repository's ignored `artifacts/` directory.
- Run `resiliant validate-isaac-csv <csv>` before analysis.

## Required CSV columns

```text
run_id,experiment_id,scenario_id,stage,seed,traffic_demand,priority_ratio,bypass_ratio,throughput_tasks_per_min,average_wait_seconds,queue_growth_per_min,junction_occupancy,deadlock_events,git_sha
```

Allowed stages are `discovery`, `validation`, `replay`. Parameter bounds must match `ExperimentParameters` or be revised with tests and a versioned schema change. Occupancy must be a fraction in [0,1]. The exporter should not invent a successful row for a crashed/timeout simulation; record failures separately and include them in reporting.

## Streaming and security

If using Isaac Sim livestream/WebRTC, keep streaming ports private and restrict access to authorized clients. Do not expose a viewer service without authentication and transport security. Follow the institution's remote-access policy; this document does not authorize a tunnel, firewall change or installation.

## When access is short

Batch runs headlessly, cap concurrency, use a finite manifest queue and keep logs/resumable outputs outside temporary directories. Use the browser/desktop viewer to inspect or record the selected demonstration, not as a requirement for every simulation run.
