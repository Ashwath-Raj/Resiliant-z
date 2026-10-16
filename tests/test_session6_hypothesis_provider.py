from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError

from resiliant_z.hypothesis_provider import (
    FixtureHypothesisProvider,
    HypothesisGenerationConfig,
    HypothesisGenerationError,
    HypothesisRequest,
    HypothesisService,
    NebiusNemotronHTTPProvider,
    ProviderCallError,
    load_generation_config,
    make_offline_service,
    save_batch_atomic,
)
from resiliant_z.scenario_spec import load_warehouse_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_warehouse_scenario(ROOT / "configs" / "warehouse_scenario.example.v1.json")
FIXTURE = ROOT / "configs" / "hypotheses" / "session6_fixture.v1.json"
CONFIG_PATH = ROOT / "configs" / "hypotheses" / "session6_config.v1.json"


def make_request(**overrides: object) -> HypothesisRequest:
    values: dict[str, object] = {
        "request_id": "req-session6-test-001",
        "gap_event_id": "gap-event-test-001",
        "scenario_id": SCENARIO.scenario_id,
        "baseline_id": "baseline-test-v1",
        "backend_id": "discrete-event-test-v1",
        "target_metric": "queue_length",
        "registered_metrics": ["queue_length", "mean_wait_s", "throughput"],
        "observed_residual": 4.0,
        "standardized_residual": 1.8,
        "evidence_label": "local_discrete_event_unvalidated",
    }
    values.update(overrides)
    return HypothesisRequest.model_validate(values)


class StaticProvider:
    provider_id = "test.static-provider"

    def __init__(self, results: list[object]):
        self.results = list(results)
        self.calls = 0

    def generate(
        self, request, scenario, *, timeout_seconds, max_response_bytes, max_request_bytes
    ):
        del request, scenario, timeout_seconds, max_response_bytes, max_request_bytes
        self.calls += 1
        item = self.results.pop(0) if self.results else self.results[-1] if self.results else "{}"
        if isinstance(item, BaseException):
            raise item
        return item


def fixture_raw(request: HypothesisRequest | None = None) -> str:
    request = request or make_request()
    provider = FixtureHypothesisProvider(FIXTURE)
    return provider.generate(
        request,
        SCENARIO,
        timeout_seconds=1,
        max_response_bytes=65536,
        max_request_bytes=65536,
    )


def mutate_raw(mutator) -> str:
    payload = json.loads(fixture_raw())
    mutator(payload)
    return json.dumps(payload)


def make_service(provider: object, **config_overrides: object) -> HypothesisService:
    values: dict[str, object] = {
        "max_hypotheses": 3,
        "max_attempts": 2,
        "timeout_seconds": 1.0,
        "max_response_bytes": 32768,
        "max_request_bytes": 32768,
    }
    values.update(config_overrides)
    return HypothesisService(provider, HypothesisGenerationConfig.model_validate(values))


def test_local_fixture_generates_a_validated_provisional_batch() -> None:
    config = load_generation_config(CONFIG_PATH)
    service = HypothesisService(FixtureHypothesisProvider(FIXTURE), config)
    batch = service.generate(make_request(), SCENARIO)
    assert batch.provider_id == "fixture.offline.v1"
    assert batch.status == "provisional_unvalidated"
    assert len(batch.hypotheses) == 2
    assert batch.attempts[-1].outcome == "accepted"
    assert all(item.gap_event_id == "gap-event-test-001" for item in batch.hypotheses)
    assert all(item.target_metric == "queue_length" for item in batch.hypotheses)


def test_fixture_ids_are_deterministic_for_same_request() -> None:
    service = make_service(FixtureHypothesisProvider(FIXTURE))
    first = service.generate(make_request(), SCENARIO)
    second = service.generate(make_request(), SCENARIO)
    assert [item.hypothesis_id for item in first.hypotheses] == [
        item.hypothesis_id for item in second.hypotheses
    ]
    assert first.response_sha256 == second.response_sha256


def test_fixture_ids_change_for_a_different_request() -> None:
    provider = FixtureHypothesisProvider(FIXTURE)
    one = provider.generate(
        make_request(),
        SCENARIO,
        timeout_seconds=1,
        max_response_bytes=32768,
        max_request_bytes=32768,
    )
    two = provider.generate(
        make_request(request_id="req-session6-test-002"),
        SCENARIO,
        timeout_seconds=1,
        max_response_bytes=32768,
        max_request_bytes=32768,
    )
    ids_one = [item["hypothesis_id"] for item in json.loads(one)["hypotheses"]]
    ids_two = [item["hypothesis_id"] for item in json.loads(two)["hypotheses"]]
    assert ids_one != ids_two


def test_factor_and_policy_values_are_registered_choices() -> None:
    batch = make_service(FixtureHypothesisProvider(FIXTURE)).generate(make_request(), SCENARIO)
    factor_levels = {item.factor_id: item.test_levels for item in SCENARIO.scenario_factors}
    policy_levels = {
        item.parameter_id: set(item.candidate_values + [item.default_value])
        for item in SCENARIO.policy_parameters
    }
    for hypothesis in batch.hypotheses:
        assert set(hypothesis.factor_values) == set(factor_levels)
        assert set(hypothesis.policy_values) == set(policy_levels)
        assert all(value in factor_levels[key] for key, value in hypothesis.factor_values.items())
        assert all(value in policy_levels[key] for key, value in hypothesis.policy_values.items())


def test_unknown_focus_variable_is_rejected() -> None:
    raw = mutate_raw(lambda payload: payload["hypotheses"][0].update(focus_variable_id="run_shell"))
    service = make_service(StaticProvider([raw, raw]))
    with pytest.raises(HypothesisGenerationError) as exc:
        service.generate(make_request(), SCENARIO)
    assert [item.error_code for item in exc.value.attempts] == ["unregistered_focus_variable"] * 2


def test_factor_value_outside_registered_levels_is_rejected() -> None:
    raw = mutate_raw(
        lambda payload: payload["hypotheses"][0]["factor_values"].update(traffic_demand=1.19)
    )
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "factor_value_out_of_registry"


def test_policy_value_outside_registered_candidates_is_rejected() -> None:
    raw = mutate_raw(
        lambda payload: payload["hypotheses"][0]["policy_values"].update(bypass_ratio=0.22)
    )
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "policy_value_out_of_registry"


def test_missing_registered_factor_is_rejected() -> None:
    raw = mutate_raw(
        lambda payload: payload["hypotheses"][0]["factor_values"].pop("priority_ratio")
    )
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "factor_registry_mismatch"


def test_unknown_fields_in_model_output_are_rejected() -> None:
    raw = mutate_raw(lambda payload: payload["hypotheses"][0].update(shell_command="rm -rf /"))
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "invalid_schema"


def test_duplicate_hypothesis_ids_are_rejected() -> None:
    def mutate(payload):
        payload["hypotheses"][1]["hypothesis_id"] = payload["hypotheses"][0]["hypothesis_id"]

    raw = mutate_raw(mutate)
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "duplicate_hypothesis_id"


def test_target_metric_must_be_registered_at_request_creation() -> None:
    with pytest.raises(ValidationError, match="target_metric must belong to registered_metrics"):
        make_request(target_metric="unregistered_metric")


def test_scenario_mismatch_is_rejected_before_provider_call() -> None:
    provider = StaticProvider([fixture_raw()])
    request = make_request(scenario_id="other-scenario")
    with pytest.raises(ValueError, match="trusted registered scenario"):
        make_service(provider).generate(request, SCENARIO)
    assert provider.calls == 0


def test_malformed_json_retries_and_exhaustion_is_bounded() -> None:
    provider = StaticProvider(["not-json", "also-not-json", "unused"])
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(provider, max_attempts=2).generate(make_request(), SCENARIO)
    assert provider.calls == 2
    assert [item.error_code for item in exc.value.attempts] == ["invalid_json", "invalid_json"]
    assert "not-json" not in str(exc.value)


def test_timeout_retry_exhaustion_does_not_expose_exception_text() -> None:
    provider = StaticProvider(
        [TimeoutError("secret-token-should-not-leak"), TimeoutError("secret-token-should-not-leak")]
    )
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(provider).generate(make_request(), SCENARIO)
    assert provider.calls == 2
    assert all(item.error_code == "timeout_or_transport_error" for item in exc.value.attempts)
    assert "secret-token" not in str(exc.value)


def test_response_size_is_bounded() -> None:
    provider = FixtureHypothesisProvider(FIXTURE)
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(provider, max_response_bytes=256).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "response_too_large"


def test_request_size_is_bounded_before_provider_call() -> None:
    provider = StaticProvider([fixture_raw()])
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(provider, max_request_bytes=256).generate(make_request(), SCENARIO)
    assert provider.calls == 0
    assert exc.value.attempts[0].error_code == "request_too_large"


def test_hypothesis_count_is_bounded() -> None:
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(FixtureHypothesisProvider(FIXTURE), max_hypotheses=1).generate(
            make_request(), SCENARIO
        )
    assert exc.value.attempts[-1].error_code == "too_many_hypotheses"


def test_output_schema_requires_falsifiable_claim_and_criterion() -> None:
    raw = mutate_raw(lambda payload: payload["hypotheses"][0].update(falsification_criterion="x"))
    with pytest.raises(HypothesisGenerationError) as exc:
        make_service(StaticProvider([raw, raw])).generate(make_request(), SCENARIO)
    assert exc.value.attempts[-1].error_code == "invalid_schema"


def test_batch_persistence_is_atomic_and_contains_only_validated_output(tmp_path: Path) -> None:
    batch = make_service(FixtureHypothesisProvider(FIXTURE)).generate(make_request(), SCENARIO)
    output = tmp_path / "nested" / "batch.json"
    save_batch_atomic(output, batch)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["status"] == "provisional_unvalidated"
    assert len(saved["hypotheses"]) == 2
    assert saved["response_sha256"] == batch.response_sha256
    assert not list(output.parent.glob("*.tmp"))


def test_optional_adapter_requires_https_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        NebiusNemotronHTTPProvider("http://example.invalid/v1/chat/completions", "nemotron")


def test_optional_adapter_missing_key_never_invokes_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEBIUS_TEST_KEY", raising=False)
    calls: list[object] = []

    def opener(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("network opener must not run without a key")

    provider = NebiusNemotronHTTPProvider(
        "https://example.invalid/v1/chat/completions",
        "nemotron",
        api_key_env="NEBIUS_TEST_KEY",
        opener=opener,
    )
    with pytest.raises(ProviderCallError) as exc:
        provider.generate(
            make_request(),
            SCENARIO,
            timeout_seconds=1,
            max_response_bytes=4096,
            max_request_bytes=8192,
        )
    assert exc.value.code == "missing_api_key"
    assert calls == []


def test_optional_adapter_detects_refusal_without_logging_refusal_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEBIUS_TEST_KEY", "secret-key-value")
    payload = json.dumps(
        {"choices": [{"message": {"refusal": "I cannot do that secret-key-value", "content": ""}}]}
    ).encode()

    def opener(*args, **kwargs):
        del args, kwargs
        return io.BytesIO(payload)

    provider = NebiusNemotronHTTPProvider(
        "https://example.invalid/v1/chat/completions",
        "nemotron",
        api_key_env="NEBIUS_TEST_KEY",
        opener=opener,
    )
    with pytest.raises(ProviderCallError) as exc:
        provider.generate(
            make_request(),
            SCENARIO,
            timeout_seconds=1,
            max_response_bytes=4096,
            max_request_bytes=8192,
        )
    assert exc.value.code == "provider_refusal"
    assert "secret-key-value" not in str(exc.value)


def test_optional_adapter_detects_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEBIUS_TEST_KEY", "test-only-key")
    payload = json.dumps({"choices": [{"message": {"content": ""}}]}).encode()

    def opener(*args, **kwargs):
        del args, kwargs
        return io.BytesIO(payload)

    provider = NebiusNemotronHTTPProvider(
        "https://example.invalid/v1/chat/completions",
        "nemotron",
        api_key_env="NEBIUS_TEST_KEY",
        opener=opener,
    )
    with pytest.raises(ProviderCallError) as exc:
        provider.generate(
            make_request(),
            SCENARIO,
            timeout_seconds=1,
            max_response_bytes=4096,
            max_request_bytes=8192,
        )
    assert exc.value.code == "empty_response"


def test_http_error_code_is_safe_and_does_not_leak_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEBIUS_TEST_KEY", "sensitive-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise HTTPError(
            "https://example.invalid",
            500,
            "server failed sensitive-key",
            {},
            io.BytesIO(b"sensitive-key"),
        )

    provider = NebiusNemotronHTTPProvider(
        "https://example.invalid/v1/chat/completions",
        "nemotron",
        api_key_env="NEBIUS_TEST_KEY",
        opener=opener,
    )
    with pytest.raises(ProviderCallError) as exc:
        provider.generate(
            make_request(),
            SCENARIO,
            timeout_seconds=1,
            max_response_bytes=4096,
            max_request_bytes=8192,
        )
    assert exc.value.code == "http_500"
    assert "sensitive-key" not in str(exc.value)


def test_default_service_is_explicitly_offline() -> None:
    service = make_offline_service()
    assert service.provider.provider_id == "fixture.offline.v1"
    assert not isinstance(service.provider, NebiusNemotronHTTPProvider)
    batch = service.generate(make_request(), SCENARIO)
    assert batch.provider_id == "fixture.offline.v1"
