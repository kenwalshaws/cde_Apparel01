# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Amazon Bedrock wrapper for summarization.

Client layer: knows how to invoke a Bedrock model and parse its response.
Uses the Anthropic Messages API shape (Claude 3 family) via `invoke_model`.
Knows nothing about the pipeline or quality scoring.
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


class BedrockClient:
    """Thin wrapper over Bedrock `invoke_model` for Claude 3 summarization."""

    def __init__(self, region: str, model_id: str, client: Any | None = None) -> None:
        self._model_id = model_id
        self._client = client or boto3.client("bedrock-runtime", region_name=region)

    def summarize(self, english_text: str, max_tokens: int = 160) -> SummarizationResult:
        """Summarize already-English review text into 1-2 sentences."""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Review:\n{english_text}\n\nSummary:",
                        }
                    ],
                }
            ],
        }

        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        payload = json.loads(response["body"].read())
        summary = _extract_text(payload).strip()
        usage = payload.get("usage", {})
        return SummarizationResult(
            summary=summary,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the text out of an Anthropic Messages API response body."""
    content = payload.get("content", [])
    parts = [block.get("text", "") for block in content if block.get("type") == "text"]
    return "".join(parts)
