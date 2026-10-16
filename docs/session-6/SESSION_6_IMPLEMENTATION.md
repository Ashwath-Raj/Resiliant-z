# RESILIANT-Z Session 6 — Provider Boundary and Hypothesis Contracts

## Scope

Session 6 introduces an untrusted-output boundary for hypothesis generation. It does not compile experiments, run a simulator, change routing policy, infer causal truth, or promote hypotheses into validated knowledge. Candidate output remains `provisional_unvalidated`.

## Providers and default behavior

- `FixtureHypothesisProvider` reads the checked-in local fixture and makes no network calls.
- `make_offline_service()` is the recommended default path and selects the fixture provider.
- `NebiusNemotronHTTPProvider` is optional, must be explicitly constructed with an HTTPS Chat Completions endpoint and an API-key environment variable, and is never auto-selected.
- Unit tests use fixture/fake providers only. They do not contact Nebius, NVIDIA, or any external host.

## Contract

Each accepted hypothesis includes a unique ID, request/gap/scenario correlation, target metric, a falsifiable claim and falsification criterion, a registered focus variable, predicted direction and response, complete registered factor values and policy values, assumptions, rationale, and a bounded confidence score.

The validator checks:

1. Strict JSON and Pydantic schema with unknown fields forbidden.
2. Request, gap event, scenario and metric correlation.
3. Unique hypothesis IDs and configured maximum hypothesis count.
4. Focus variable membership in the scenario registry.
5. Exact factor and policy key sets, legal ranges, and membership in declared test/candidate levels.
6. Maximum request/response bytes, bounded attempts, and provider timeout.
7. Empty response, malformed JSON, provider refusal, timeout, HTTP failure and retry exhaustion without exposing raw response text or credentials in errors.

No provider string is executed as code, shell text, a query, a policy, or a simulator command. A JSON-schema-valid response can still be scientifically wrong; schema compliance is not evidence of truth.

## Optional Nemotron adapter

Provide an explicit HTTPS `endpoint_url`, model name, and API-key environment variable when constructing `NebiusNemotronHTTPProvider`. The provider reads credentials only from that environment variable and never includes the key, response body or raw exception text in diagnostic errors. The adapter expects an OpenAI-compatible Chat Completions response envelope with `choices[0].message.content`; endpoint/provider compatibility must be confirmed before use. Do not test it against a live endpoint as part of this session.

`make_offline_service()` remains the required default for development and tests. Do not add automatic network fallback.

## Limitations and evidence labeling

All bundled hypothesis examples are synthetic, illustrative candidates for the local discrete-event model. They are not calibrated warehouse settings, causal findings, physics validation, or authorization to change a policy. The optional provider outputs are also provisional until compiled into registered experiments and checked against independent evidence.

## Example

```python
from pathlib import Path

from resiliant_z.hypothesis_provider import HypothesisRequest, make_offline_service, save_batch_atomic
from resiliant_z.scenario_spec import load_warehouse_scenario

root = Path.cwd()
scenario = load_warehouse_scenario(root / "configs/warehouse_scenario.example.v1.json")
request = HypothesisRequest(
    request_id="demo-request-001",
    gap_event_id="demo-gap-event-001",
    scenario_id=scenario.scenario_id,
    baseline_id="baseline-demo-v1",
    backend_id="local-discrete-event-v1",
    target_metric="queue_length",
    registered_metrics=["queue_length", "mean_wait_s", "throughput"],
    observed_residual=4.0,
    standardized_residual=1.8,
)
batch = make_offline_service().generate(request, scenario)
save_batch_atomic(root / "artifacts/hypotheses/session6-batch.v1.json", batch)
```

The actual default function runs only the local fixture. Selecting the optional Nemotron adapter requires explicit construction and is not part of the example above.

## Acceptance gate

Focused tests, complete regression tests, Ruff lint, Ruff format check, Python compilation, fixture/config/schema JSON parsing, `git diff --check`, and unchanged hashes for pre-existing artifacts must pass on the target repository. Phase I's gate review remains a separate project decision even after all Session 1–5 checks are green.
