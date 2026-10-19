# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline configuration.

Centralizes every tunable so the service and client layers never hardcode
values. Static settings come from environment variables; the Bedrock model is
resolved at runtime from a `config.json` object in the input bucket so it can
be changed without a redeploy (see `resolve_model_id`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Any


# Final fallback if config.json is missing/unreadable and no env override is
# set. This is the Claude Haiku 5.5 US inference profile.
_FALLBACK_MODEL_ID = "us.anthropic.claude-haiku-5-5"

# Key of the runtime model-config object in the input bucket.
MODEL_CONFIG_KEY = "config.json"


@dataclass(frozen=True)
class Config:
    # AWS region for Translate and Bedrock.
    region: str = os.environ.get("AWS_REGION", "us-east-1")

    # Bedrock model used for summarization. Defaults to the env override if
    # present, else the fallback; `resolve_model_id` may replace this at
    # runtime from config.json in the input bucket.
    bedrock_model_id: str = os.environ.get("BEDROCK_MODEL_ID", _FALLBACK_MODEL_ID)

    # Target languages: the English summary is translated into German and French.
    target_languages: tuple[str, ...] = ("de", "fr")

    # A result is surfaced only if every step scores at or above this.
    quality_threshold: float = float(os.environ.get("QUALITY_THRESHOLD", "0.7"))

    # Summary length guardrails (characters), used by the quality scorer.
    summary_min_chars: int = 40
    summary_max_chars: int = 320


def load_config() -> Config:
    """Return the active configuration (static settings only)."""
    return Config()


def parse_model_config(raw: dict[str, Any]) -> str:
    """Return the chosen model id from a parsed config.json mapping.

    Picks `default_model` when present and listed under `models`; otherwise
    the first entry in `models`; otherwise the fallback.
    """
    models = raw.get("models") or []
    valid_ids = {m.get("id") for m in models if isinstance(m, dict)}

    default_model = raw.get("default_model")
    if default_model and default_model in valid_ids:
        return default_model
    if valid_ids:
        # Fall back to the first listed model id.
        for m in models:
            if isinstance(m, dict) and m.get("id"):
                return m["id"]
    return _FALLBACK_MODEL_ID


def resolve_model_id(s3_client: Any, bucket: str) -> str:
    """Resolve the Bedrock model id from config.json in the input bucket.

    Any failure (missing file, bad JSON, no models) falls back to the env
    override or the hardcoded default so a run never breaks on config.
    """
    env_override = os.environ.get("BEDROCK_MODEL_ID")
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=MODEL_CONFIG_KEY)
        raw = json.loads(obj["Body"].read())
        return parse_model_config(raw)
    except Exception:
        return env_override or _FALLBACK_MODEL_ID


def load_runtime_config(s3_client: Any, bucket: str) -> tuple[str, bool]:
    """Read config.json once; return (model_id, debug_enabled).

    debug defaults to True (on) when absent or on any read/parse failure, so a
    missing config.json still gives verbose logs rather than silent failure.
    """
    env_override = os.environ.get("BEDROCK_MODEL_ID")
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=MODEL_CONFIG_KEY)
        raw = json.loads(obj["Body"].read())
        model_id = parse_model_config(raw)
        debug = bool(raw.get("debug", True))
        return model_id, debug
    except Exception:
        return (env_override or _FALLBACK_MODEL_ID), True


def with_model_id(config: Config, model_id: str) -> Config:
    """Return a copy of `config` with the resolved Bedrock model id."""
    return replace(config, bedrock_model_id=model_id)
