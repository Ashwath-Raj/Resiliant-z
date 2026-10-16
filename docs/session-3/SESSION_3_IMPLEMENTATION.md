# RESILIANT-Z Phase I — Session 3: Telemetry and Semantic State

## Scope implemented

Session 3 adds a versioned telemetry contract, deterministic time-window aggregation, and JSON Lines persistence/replay independent of a simulator. It does not change the discrete-event backend or start Session 4.

### Files

- `src/resiliant_z/telemetry.py` — Pydantic v2 models and a pure `aggregate_telemetry(...)` function.
- `src/resiliant_z/telemetry_io.py` — strict `write_telemetry_jsonl(...)` and `load_telemetry_jsonl(...)` functions.
- `configs/telemetry/session3_fixture.v1.jsonl` — three synthetic 10-second windows demonstrating measured, missing, stale, not-applicable, and not-measured values.
- `docs/session-3/schemas/telemetry-window.v1.schema.json` — JSON Schema for one window.
- `docs/session-3/schemas/fleet-window-aggregate.v1.schema.json` — JSON Schema for aggregate output.
- `tests/test_session3_telemetry.py` — deterministic schema, aggregation, coverage and replay tests.

## Contract semantics

Every record declares `schema_version: "1.0"`, run/scenario/backend identity, timezone-aware window start/end, and a sampling interval that must match the window duration. Windows represent half-open intervals `[window_start, window_end)`.

Each metric is a `NumericObservation` with a fixed unit, a value or `null`, and an explicit quality status:

- `measured`: numeric values are permitted, including a genuine measured zero.
- `missing`: the source did not provide the field.
- `stale`: the value was too old for the consumer's freshness requirement.
- `not_applicable`: the metric does not apply to this backend/scenario.
- `not_measured`: no implemented detector or measurement source provides the metric.

Every unavailable state requires a non-empty reason and must have `value: null`. Unavailable observations cannot be encoded as zero. For example, the local discrete-event model has no implemented junction occupancy/contact detector, so those values should remain `not_measured` (or `not_applicable` where appropriate), not reported as zero.

### Metric meaning and aggregation

| Metric | Unit | Window meaning | Aggregation |
|---|---|---|---|
| `active_robots`, `idle_robots` | `robots` | Mean count during the interval | Duration-weighted mean |
| `tasks_arrived`, `tasks_started`, `tasks_completed` | `tasks` | Event count within the interval | Sum |
| `queue_length` | `tasks` | Mean queue length during the interval | Duration-weighted mean |
| `priority_ratio` | `ratio` (0–1) | Mean fraction for the interval | Duration-weighted mean |
| `junction_occupancy` | `ratio` (0–1) | Mean measured occupancy fraction | Duration-weighted mean |
| `junction_pressure` | `robots` | Mean number of robots represented by the backend's pressure metric | Duration-weighted mean |

The priority ratio is treated as a time-window mean. This contract does not claim it is a task-weighted overall share; that would require retaining high-priority and total-task denominators.

## Boundary, gap and quality behavior

Aggregation only includes records wholly contained in the requested target window. A record crossing a target boundary is excluded; values are not clipped or interpolated. Inputs must describe one run/scenario/backend and overlapping telemetry records are rejected. The target interval may include gaps.

An aggregate metric's numeric `value` is emitted only when that metric is measured over the full requested interval and the interval has complete telemetry coverage. When any part is missing, stale, inapplicable, unmeasured, or absent, the numeric aggregate remains `null`; quality flags and coverage fields identify the limitation. `coverage_ratio` is measured duration divided by the requested duration, not merely the ratio of records present.

The `aggregate_telemetry(...)` function is pure: it performs no file I/O and imports no simulator, LLM, network or cloud code. `telemetry_io.py` persists and replays JSONL separately. JSONL replay is all-or-error, reports malformed line numbers, rejects overlapping windows, and does not silently accept blank lines. Writing refuses to overwrite an existing path by default; `overwrite=True` is explicit and uses atomic replacement.

## Synthetic fixture

`configs/telemetry/session3_fixture.v1.jsonl` is synthetic test data only. It is not extracted from a live fleet, calibrated to a real warehouse, or produced by Isaac Sim. The backend label is `local_discrete_event`; no physical/geometry, sensing, collision, contact or deadlock claim is implied.

## Validation commands

From the repository root, the installer runs:

```bash
.venv/bin/python -m pytest -q tests/test_session3_telemetry.py
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m compileall -q src tests
git diff --check
```

It also checks the two JSON Schema documents. Ruff auto-fixes and formats **only the newly installed Session 3 Python files** before the checks, if Ruff is available. No dependencies are installed by the installer.

## Acceptance and remaining work

Session 3 passes only if its tests, full regression suite, lint, format, compile, schema and whitespace checks pass. The implementation does **not** yet connect the discrete-event backend's internal states to this telemetry contract, and it does not implement a live sampling loop. The fixture and replay path establish a backend-independent contract; backend instrumentation/adapter wiring must be explicit and reviewed separately. Session 4's baseline estimator/residuals and Session 5's persistent gap detector remain out of scope.
