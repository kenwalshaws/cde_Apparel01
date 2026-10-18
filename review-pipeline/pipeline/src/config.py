# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline configuration.

Centralizes every tunable so the service and client layers never hardcode
values. Overridable via environment variables for the deployed path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # AWS region for Translate and Bedrock.
    region: str = os.environ.get("AWS_REGION", "us-east-1")

    # Bedrock model used for summarization.
    bedrock_model_id: str = os.environ.get(
        "BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
    )

    # Target shopper languages the prototype proves out.
    target_languages: tuple[str, ...] = ("fr", "de")

    # A result is surfaced only if every step scores at or above this.
    quality_threshold: float = float(os.environ.get("QUALITY_THRESHOLD", "0.7"))

    # Summary length guardrails (characters), used by the quality scorer.
    summary_min_chars: int = 40
    summary_max_chars: int = 320


def load_config() -> Config:
    """Return the active configuration."""
    return Config()
