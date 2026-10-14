"""Minimal OpenAI-compatible Nebius Token Factory client.

A model ID must be copied from the user's own Token Factory catalogue. This module
never starts a paid GPU VM and never silently claims that a local fallback was Nemotron.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from resiliant_z.models import HypothesisSet

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"


class NebiusConfigurationError(RuntimeError):
    pass


class NebiusRequestError(RuntimeError):
    pass


def nebius_is_configured() -> bool:
    return bool(os.getenv("NEBIUS_API_KEY", "").strip() and os.getenv("NEBIUS_MODEL", "").strip())


def _extract_json(content: str) -> dict:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise NebiusRequestError("Model response did not contain a JSON object")
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise NebiusRequestError(f"Model returned invalid JSON: {exc.msg}") from exc
    if not isinstance(result, dict):
        raise NebiusRequestError("Model response must be a JSON object")
    return result


def generate_hypotheses_with_nebius(summary: dict) -> tuple[HypothesisSet, str]:
    """Return schema-validated hypotheses plus the configured model ID."""
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    model = os.getenv("NEBIUS_MODEL", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    timeout_seconds = float(os.getenv("NEBIUS_TIMEOUT_SECONDS", "45"))
    if not api_key or not model:
        raise NebiusConfigurationError(
            "Set NEBIUS_API_KEY and NEBIUS_MODEL. Get the exact model ID from your Token Factory catalogue."
        )

    system_prompt = (
        "You are the hypothesis-generation module in RESILIANT-Z, a research prototype for fleet "
        "operations. Return a single JSON object only. You propose explanations; you do not claim "
        "they are proven. Use only these factor names: traffic_demand, priority_ratio, bypass_ratio. "
        "Include at least two competing hypotheses and a falsification test for every hypothesis. "
        "Your output must match this schema: {hypotheses:[{hypothesis_id:'H1',kind:'main_effect' "
        "|'interaction'|'other',factors:[allowed factor names],claim:string,falsification_test:string}], "
        "recommended_experiment:string}. Do not include code or arbitrary executable instructions."
    )
    user_prompt = (
        "Propose competing, falsifiable hypotheses for this observed scenario summary. Do not assume "
        "any one explanation is true. The experiment compiler will enforce allowed variables and bounds.\n"
        + json.dumps(summary, sort_keys=True)
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise NebiusRequestError("Model response content was not text")
        hypotheses = HypothesisSet.model_validate(_extract_json(content))
    except NebiusRequestError:
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise NebiusRequestError(f"Nebius Token Factory request failed: {exc}") from exc
    return hypotheses, model


def local_hypotheses() -> HypothesisSet:
    """Deterministic baseline hypotheses when no API call is requested."""
    return HypothesisSet(
        hypotheses=[
            {
                "hypothesis_id": "H1",
                "kind": "main_effect",
                "factors": ["traffic_demand"],
                "claim": "Increasing traffic demand independently reduces observed throughput.",
                "falsification_test": "Compare low and high demand at both priority-ratio levels across independent seeds.",
            },
            {
                "hypothesis_id": "H2",
                "kind": "main_effect",
                "factors": ["priority_ratio"],
                "claim": "Priority-task fraction independently changes throughput or queue growth.",
                "falsification_test": "Compare low and high priority ratios at both demand levels across independent seeds.",
            },
            {
                "hypothesis_id": "H3",
                "kind": "interaction",
                "factors": ["traffic_demand", "priority_ratio"],
                "claim": "The combined high-demand/high-priority condition adds a throughput penalty beyond individual effects.",
                "falsification_test": "Fit main-effects and interaction models on discovery seeds and compare errors on held-out seeds.",
            },
        ],
        recommended_experiment=(
            "Run a replicated 2x2 factorial experiment varying traffic demand and priority ratio; "
            "hold out independent random seeds for validation."
        ),
    )
