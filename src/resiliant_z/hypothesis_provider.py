"""Bounded hypothesis-provider boundary for RESILIANT-Z Phase II, Session 6.

The default provider is a deterministic local fixture. The optional HTTPS
Nemotron adapter is opt-in and is never selected implicitly. Provider output is
untrusted JSON: it is strictly parsed and checked against a registered scenario
before it can be returned to a caller. Nothing in this module executes output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from resiliant_z.scenario_spec import WarehouseScenario

SchemaVersion = Literal["1.0.0"]
Direction = Literal["increase", "decrease", "no_change", "non_monotonic"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HypothesisGenerationConfig(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    max_hypotheses: int = Field(default=3, ge=1, le=10)
    max_attempts: int = Field(default=2, ge=1, le=3)
    timeout_seconds: float = Field(default=12.0, gt=0, le=60, allow_inf_nan=False)
    max_response_bytes: int = Field(default=32768, ge=256, le=262144)
    max_request_bytes: int = Field(default=32768, ge=256, le=131072)


def load_generation_config(path: str | Path) -> HypothesisGenerationConfig:
    """Load strict limits from a versioned local config file."""
    return HypothesisGenerationConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


class HypothesisRequest(StrictModel):
    """Minimal gap context supplied to a provider; no credentials are accepted."""

    request_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    gap_event_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    baseline_id: str = Field(min_length=1, max_length=128)
    backend_id: str = Field(min_length=1, max_length=128)
    target_metric: str = Field(min_length=1, max_length=128)
    registered_metrics: list[str] = Field(min_length=1, max_length=100)
    observed_residual: float | None = Field(default=None, allow_inf_nan=False)
    standardized_residual: float | None = Field(default=None, allow_inf_nan=False)
    evidence_label: Literal[
        "local_discrete_event_unvalidated", "simulator_unvalidated", "other_unvalidated"
    ] = "local_discrete_event_unvalidated"

    @model_validator(mode="after")
    def validate_metric_registry(self) -> HypothesisRequest:
        if len(set(self.registered_metrics)) != len(self.registered_metrics):
            raise ValueError("registered_metrics must be unique")
        if any(not item.strip() for item in self.registered_metrics):
            raise ValueError("registered metric names must be non-empty")
        if self.target_metric not in self.registered_metrics:
            raise ValueError("target_metric must belong to registered_metrics")
        return self


class HypothesisProposal(StrictModel):
    """One falsifiable, provisional hypothesis; never executable control code."""

    schema_version: SchemaVersion = "1.0.0"
    request_id: str = Field(min_length=1, max_length=128)
    hypothesis_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
    )
    gap_event_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    target_metric: str = Field(min_length=1, max_length=128)
    falsifiable_claim: str = Field(min_length=12, max_length=500)
    falsification_criterion: str = Field(min_length=12, max_length=500)
    focus_variable_id: str = Field(min_length=1, max_length=128)
    predicted_direction: Direction
    predicted_response: str = Field(min_length=8, max_length=300)
    factor_values: dict[str, float] = Field(min_length=1, max_length=50)
    policy_values: dict[str, float] = Field(min_length=1, max_length=50)
    assumptions: list[str] = Field(min_length=1, max_length=8)
    rationale: str = Field(min_length=12, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_numeric_payload(self) -> HypothesisProposal:
        for collection_name, collection in (
            ("factor_values", self.factor_values),
            ("policy_values", self.policy_values),
        ):
            if any(not key.strip() for key in collection):
                raise ValueError(f"{collection_name} keys must be non-empty")
            if any(not math.isfinite(value) for value in collection.values()):
                raise ValueError(f"{collection_name} values must be finite")
        if any(not item.strip() or len(item) > 300 for item in self.assumptions):
            raise ValueError("assumptions must be non-empty strings of at most 300 characters")
        if len(set(self.assumptions)) != len(self.assumptions):
            raise ValueError("assumptions must be unique")
        if not self.falsifiable_claim.strip() or not self.falsification_criterion.strip():
            raise ValueError("claim and falsification criterion must not be blank")
        return self


class HypothesisPayload(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    hypotheses: list[HypothesisProposal] = Field(min_length=1, max_length=10)


class AttemptDiagnostic(StrictModel):
    attempt: int = Field(ge=1, le=3)
    outcome: Literal["accepted", "rejected"]
    error_code: str | None = Field(default=None, max_length=64)


class ValidatedHypothesisBatch(StrictModel):
    schema_version: SchemaVersion = "1.0.0"
    status: Literal["provisional_unvalidated"] = "provisional_unvalidated"
    provider_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    created_at: datetime
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempts: list[AttemptDiagnostic] = Field(min_length=1, max_length=3)
    hypotheses: list[HypothesisProposal] = Field(min_length=1, max_length=10)
    notice: Literal["Hypotheses are provisional, not causal findings or policy authorization."] = (
        "Hypotheses are provisional, not causal findings or policy authorization."
    )

    @model_validator(mode="after")
    def validate_timestamp(self) -> ValidatedHypothesisBatch:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return self


class ProviderCallError(RuntimeError):
    """Safe provider error containing a code only, never raw response/secrets."""

    def __init__(self, code: str, *, retryable: bool = True):
        self.code = re.sub(r"[^a-z0-9_:-]", "_", code.lower())[:64] or "provider_error"
        self.retryable = retryable
        super().__init__(self.code)


class HypothesisGenerationError(RuntimeError):
    """Raised when the bounded generation loop cannot return validated output."""

    def __init__(self, attempts: list[AttemptDiagnostic]):
        self.attempts = tuple(attempts)
        codes = ", ".join(item.error_code or "unknown" for item in attempts)
        super().__init__(f"hypothesis generation failed after {len(attempts)} attempt(s): {codes}")


class HypothesisProvider(Protocol):
    provider_id: str

    def generate(
        self,
        request: HypothesisRequest,
        scenario: WarehouseScenario,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        max_request_bytes: int,
    ) -> str:
        """Return raw JSON text; callers must validate all provider output."""


def _provider_context(request: HypothesisRequest, scenario: WarehouseScenario) -> dict[str, object]:
    return {
        "request": request.model_dump(mode="json"),
        "scenario_registry": {
            "scenario_id": scenario.scenario_id,
            "evidence_label": scenario.evidence_label,
            "scenario_factors": [
                {
                    "factor_id": item.factor_id,
                    "unit": item.unit,
                    "min_value": item.min_value,
                    "max_value": item.max_value,
                    "registered_test_levels": item.test_levels,
                }
                for item in scenario.scenario_factors
            ],
            "policy_parameters": [
                {
                    "parameter_id": item.parameter_id,
                    "unit": item.unit,
                    "min_value": item.min_value,
                    "max_value": item.max_value,
                    "default_value": item.default_value,
                    "registered_candidate_values": item.candidate_values,
                }
                for item in scenario.policy_parameters
            ],
            "policy_mode_choices": scenario.policy_mode_choices,
        },
    }


class FixtureHypothesisProvider:
    """Deterministic local provider. It reads a checked-in fixture and never uses a network."""

    provider_id = "fixture.offline.v1"

    def __init__(self, fixture_path: str | Path | None = None):
        self.fixture_path = (
            Path(fixture_path)
            if fixture_path is not None
            else (
                Path(__file__).resolve().parents[2]
                / "configs"
                / "hypotheses"
                / "session6_fixture.v1.json"
            )
        )
        try:
            self._fixture = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ProviderCallError("fixture_unavailable", retryable=False) from None
        if not isinstance(self._fixture, dict) or not isinstance(
            self._fixture.get("hypotheses"), list
        ):
            raise ProviderCallError("fixture_invalid", retryable=False)

    def generate(
        self,
        request: HypothesisRequest,
        scenario: WarehouseScenario,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        max_request_bytes: int,
    ) -> str:
        del timeout_seconds  # no network timeout is relevant to an in-process fixture
        if request.scenario_id != scenario.scenario_id:
            raise ProviderCallError("scenario_mismatch", retryable=False)
        if (
            len(
                json.dumps(_provider_context(request, scenario), separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            > max_request_bytes
        ):
            raise ProviderCallError("request_too_large", retryable=False)
        digest = hashlib.sha256(
            f"{request.request_id}\0{request.gap_event_id}\0{scenario.scenario_id}".encode()
        ).hexdigest()[:8]
        output: list[dict[str, object]] = []
        for index, template in enumerate(self._fixture["hypotheses"], start=1):
            if not isinstance(template, dict):
                raise ProviderCallError("fixture_invalid", retryable=False)
            item = dict(template)
            item["request_id"] = request.request_id
            item["hypothesis_id"] = (
                f"{str(item.get('hypothesis_id', f'HYP-{index}'))[:54]}-{digest}"
            )
            item["gap_event_id"] = request.gap_event_id
            item["scenario_id"] = scenario.scenario_id
            item["target_metric"] = request.target_metric
            for field in (
                "falsifiable_claim",
                "falsification_criterion",
                "predicted_response",
                "rationale",
            ):
                value = item.get(field)
                if isinstance(value, str):
                    item[field] = value.replace("{{target_metric}}", request.target_metric).replace(
                        "{{scenario_id}}", scenario.scenario_id
                    )
            output.append(item)
        payload = json.dumps(
            {"schema_version": "1.0.0", "hypotheses": output}, separators=(",", ":")
        )
        if len(payload.encode("utf-8")) > max_response_bytes:
            raise ProviderCallError("response_too_large", retryable=False)
        return payload


class NebiusNemotronHTTPProvider:
    """Optional OpenAI-compatible HTTPS adapter; constructing it does not make a call.

    The endpoint must be supplied explicitly and HTTPS is required to protect the
    API key. The adapter makes one bounded request per service attempt. No raw
    response, authorization header or exception text is logged or propagated.
    """

    provider_id = "nebius.nemotron.openai-compatible.v1"

    def __init__(
        self,
        endpoint_url: str,
        model: str,
        *,
        api_key_env: str = "NEBIUS_API_KEY",
        opener: Callable[..., object] | None = None,
    ):
        parsed = urlparse(endpoint_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("endpoint_url must be an explicit HTTPS URL")
        if not model.strip() or not api_key_env.strip():
            raise ValueError("model and api_key_env must be non-empty")
        self.endpoint_url = endpoint_url
        self.model = model
        self.api_key_env = api_key_env
        self._opener = opener

    def generate(
        self,
        request: HypothesisRequest,
        scenario: WarehouseScenario,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        max_request_bytes: int,
    ) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderCallError("missing_api_key", retryable=False)
        context = _provider_context(request, scenario)
        schema = HypothesisPayload.model_json_schema()
        system_prompt = (
            "Propose falsifiable warehouse-fleet hypotheses. Return exactly one JSON object conforming "
            "to this schema, with no Markdown. Use only the registered factor and policy IDs and their "
            "listed levels. Fill all factor_values and policy_values. Do not output code, commands, "
            "credentials, or policy authorization. Claims remain provisional. Schema: "
            + json.dumps(schema, separators=(",", ":"))
        )
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(context, separators=(",", ":"))},
                ],
                "temperature": 0,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > max_request_bytes:
            raise ProviderCallError("request_too_large", retryable=False)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        req = urllib.request.Request(self.endpoint_url, data=body, headers=headers, method="POST")
        try:
            opener = self._opener or urllib.request.urlopen
            with opener(req, timeout=timeout_seconds) as response:  # type: ignore[attr-defined]
                envelope_bytes = response.read(max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raise ProviderCallError(
                f"http_{status}", retryable=(status == 429 or status >= 500)
            ) from None
        except (TimeoutError, OSError, urllib.error.URLError):
            raise ProviderCallError("timeout_or_transport_error", retryable=True) from None
        if len(envelope_bytes) > max_response_bytes:
            raise ProviderCallError("response_too_large", retryable=False)
        try:
            envelope = json.loads(envelope_bytes)
            message = envelope["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise ProviderCallError("invalid_provider_envelope", retryable=True) from None
        refusal = message.get("refusal") if isinstance(message, dict) else None
        if refusal:
            raise ProviderCallError("provider_refusal", retryable=False)
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderCallError("empty_response", retryable=False)
        if len(content.encode("utf-8")) > max_response_bytes:
            raise ProviderCallError("response_too_large", retryable=False)
        return content


def _within_registered_levels(value: float, allowed: list[float]) -> bool:
    return any(math.isclose(value, candidate, rel_tol=0.0, abs_tol=1e-9) for candidate in allowed)


def _validate_against_request(
    payload: HypothesisPayload,
    request: HypothesisRequest,
    scenario: WarehouseScenario,
    config: HypothesisGenerationConfig,
) -> None:
    if request.scenario_id != scenario.scenario_id:
        raise ProviderCallError("scenario_mismatch", retryable=False)
    if len(payload.hypotheses) > min(config.max_hypotheses, 10):
        raise ProviderCallError("too_many_hypotheses", retryable=True)
    factor_registry = {item.factor_id: item for item in scenario.scenario_factors}
    policy_registry = {item.parameter_id: item for item in scenario.policy_parameters}
    seen: set[str] = set()
    expected_factor_ids = set(factor_registry)
    expected_policy_ids = set(policy_registry)
    for hypothesis in payload.hypotheses:
        if hypothesis.hypothesis_id in seen:
            raise ProviderCallError("duplicate_hypothesis_id", retryable=True)
        seen.add(hypothesis.hypothesis_id)
        if hypothesis.request_id != request.request_id:
            raise ProviderCallError("request_id_mismatch", retryable=True)
        if hypothesis.gap_event_id != request.gap_event_id:
            raise ProviderCallError("gap_event_id_mismatch", retryable=True)
        if hypothesis.scenario_id != scenario.scenario_id:
            raise ProviderCallError("scenario_id_mismatch", retryable=True)
        if (
            hypothesis.target_metric != request.target_metric
            or hypothesis.target_metric not in request.registered_metrics
        ):
            raise ProviderCallError("unregistered_metric", retryable=True)
        if hypothesis.focus_variable_id not in expected_factor_ids | expected_policy_ids:
            raise ProviderCallError("unregistered_focus_variable", retryable=True)
        if set(hypothesis.factor_values) != expected_factor_ids:
            raise ProviderCallError("factor_registry_mismatch", retryable=True)
        if set(hypothesis.policy_values) != expected_policy_ids:
            raise ProviderCallError("policy_registry_mismatch", retryable=True)
        for factor_id, value in hypothesis.factor_values.items():
            factor = factor_registry[factor_id]
            if (
                value < factor.min_value
                or value > factor.max_value
                or not _within_registered_levels(value, factor.test_levels)
            ):
                raise ProviderCallError("factor_value_out_of_registry", retryable=True)
        for parameter_id, value in hypothesis.policy_values.items():
            parameter = policy_registry[parameter_id]
            allowed = list(parameter.candidate_values) + [parameter.default_value]
            if (
                value < parameter.min_value
                or value > parameter.max_value
                or not _within_registered_levels(value, allowed)
            ):
                raise ProviderCallError("policy_value_out_of_registry", retryable=True)


def _error_code(error: Exception) -> str:
    if isinstance(error, ProviderCallError):
        return error.code
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, ValidationError):
        return "invalid_schema"
    return "provider_error"


class HypothesisService:
    """Run a provider through strict validation and a bounded retry loop."""

    def __init__(self, provider: HypothesisProvider, config: HypothesisGenerationConfig):
        self.provider = provider
        self.config = config

    def generate(
        self, request: HypothesisRequest, scenario: WarehouseScenario
    ) -> ValidatedHypothesisBatch:
        if request.scenario_id != scenario.scenario_id:
            raise ValueError("request scenario_id must match the trusted registered scenario")
        context_size = len(
            json.dumps(_provider_context(request, scenario), separators=(",", ":")).encode("utf-8")
        )
        if context_size > self.config.max_request_bytes:
            raise HypothesisGenerationError(
                [AttemptDiagnostic(attempt=1, outcome="rejected", error_code="request_too_large")]
            )
        attempts: list[AttemptDiagnostic] = []
        for attempt_number in range(1, self.config.max_attempts + 1):
            retryable = True
            try:
                raw = self.provider.generate(
                    request,
                    scenario,
                    timeout_seconds=self.config.timeout_seconds,
                    max_response_bytes=self.config.max_response_bytes,
                    max_request_bytes=self.config.max_request_bytes,
                )
                if not isinstance(raw, str) or not raw.strip():
                    raise ProviderCallError("empty_response", retryable=True)
                raw_bytes = raw.encode("utf-8")
                if len(raw_bytes) > self.config.max_response_bytes:
                    raise ProviderCallError("response_too_large", retryable=False)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    raise ProviderCallError("invalid_json", retryable=True) from None
                try:
                    payload = HypothesisPayload.model_validate(parsed)
                except ValidationError:
                    raise ProviderCallError("invalid_schema", retryable=True) from None
                _validate_against_request(payload, request, scenario, self.config)
                attempts.append(AttemptDiagnostic(attempt=attempt_number, outcome="accepted"))
                return ValidatedHypothesisBatch(
                    provider_id=self.provider.provider_id,
                    request_id=request.request_id,
                    scenario_id=scenario.scenario_id,
                    created_at=datetime.now(UTC),
                    response_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    attempts=attempts,
                    hypotheses=payload.hypotheses,
                )
            except ProviderCallError as exc:
                code = exc.code
                retryable = exc.retryable
            except (TimeoutError, OSError, urllib.error.URLError):
                code = "timeout_or_transport_error"
                retryable = True
            except (
                Exception
            ) as exc:  # safe boundary: never surface provider response or exception text
                code = _error_code(exc)
                retryable = True
            attempts.append(
                AttemptDiagnostic(attempt=attempt_number, outcome="rejected", error_code=code)
            )
            if not retryable:
                break
        raise HypothesisGenerationError(attempts)


def save_batch_atomic(path: str | Path, batch: ValidatedHypothesisBatch) -> None:
    """Persist only the validated, typed output using an atomic replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = batch.model_dump_json(indent=2).encode("utf-8") + b"\n"
    handle_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            handle_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle_name, destination)
    finally:
        if handle_name is not None and os.path.exists(handle_name):
            os.unlink(handle_name)


def make_offline_service(
    config_path: str | Path | None = None,
    fixture_path: str | Path | None = None,
) -> HypothesisService:
    """Return the default zero-network service using the local checked-in fixture."""
    project_root = Path(__file__).resolve().parents[2]
    chosen_config = (
        Path(config_path)
        if config_path is not None
        else project_root / "configs" / "hypotheses" / "session6_config.v1.json"
    )
    return HypothesisService(
        FixtureHypothesisProvider(fixture_path),
        load_generation_config(chosen_config),
    )
