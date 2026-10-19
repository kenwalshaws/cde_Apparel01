# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Amazon Bedrock wrapper for summarization.

Client layer: knows how to invoke a Bedrock model and parse its response via
`invoke_model`. Supports two model families, selected by model id:
Anthropic Claude (Messages API shape) and Amazon Nova text models (messages +
inferenceConfig). Knows nothing about the pipeline or quality scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import boto3


@dataclass
class SummarizationResult:
    summary: str
    # Token usage, when the model reports it. Useful telemetry for the handoff.
    input_tokens: int | None = None
    output_tokens: int | None = None


_SYSTEM_PROMPT = (
    "You summarize apparel product reviews for shoppers. Produce a single "
    "tight summary of one to two sentences that captures fit, material, and "
    "overall sentiment. Do not add information that is not in the review. Do "
    "not include a preamble, quotes, or bullet points. Respond with the "
    "summary text only."
)


def _is_nova(model_id: str) -> bool:
    """True for Amazon Nova text models (different invoke_model schema)."""
    # Handles bare ids and inference-profile ids (e.g. "us.amazon.nova-...").
    return "amazon.nova" in model_id


class BedrockClient:
    """Thin wrapper over Bedrock `invoke_model` for summarization.

    Supports two request/response schemas, chosen by model family:
      - Anthropic Claude: the Messages API shape (anthropic_version/system/
        messages; response under `content`).
      - Amazon Nova text models: `messages` + `system` + `inferenceConfig`;
        response under `output.message.content`.
    """

    def __init__(self, region: str, model_id: str, client: Any | None = None) -> None:
        self._model_id = model_id
        self._client = client or boto3.client("bedrock-runtime", region_name=region)

    def summarize(self, english_text: str, max_tokens: int = 160) -> SummarizationResult:
        """Summarize already-English review text into 1-2 sentences."""
        user_text = f"Review:\n{english_text}\n\nSummary:"
        if _is_nova(self._model_id):
            body = _nova_request(user_text, max_tokens)
        else:
            body = _anthropic_request(user_text, max_tokens)

        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())

        if _is_nova(self._model_id):
            summary, usage = _nova_parse(payload)
        else:
            summary, usage = _anthropic_parse(payload)

        return SummarizationResult(
            summary=summary.strip(),
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
        )


# --------------------------------------------------------------------------- #
# Anthropic Claude (Messages API)
# --------------------------------------------------------------------------- #
def _anthropic_request(user_text: str, max_tokens: int) -> dict[str, Any]:
    # Note: `temperature` is intentionally omitted. Claude Haiku 5.5 rejects it
    # ("temperature is deprecated for this model"). The model default is fine
    # for short, deterministic-enough summaries.
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": user_text}]}
        ],
    }


def _anthropic_parse(payload: dict[str, Any]) -> tuple[str, dict[str, int | None]]:
    content = payload.get("content", [])
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    usage = payload.get("usage", {})
    return text, {"input": usage.get("input_tokens"), "output": usage.get("output_tokens")}


# --------------------------------------------------------------------------- #
# Amazon Nova text models
# --------------------------------------------------------------------------- #
def _nova_request(user_text: str, max_tokens: int) -> dict[str, Any]:
    return {
        "system": [{"text": _SYSTEM_PROMPT}],
        "messages": [
            {"role": "user", "content": [{"text": user_text}]}
        ],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
    }


def _nova_parse(payload: dict[str, Any]) -> tuple[str, dict[str, int | None]]:
    message = payload.get("output", {}).get("message", {})
    content = message.get("content", [])
    text = "".join(b.get("text", "") for b in content if "text" in b)
    usage = payload.get("usage", {})
    return text, {"input": usage.get("inputTokens"), "output": usage.get("outputTokens")}
