# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline configuration.

Centralizes every tunable so the service and client layers never hardcode
values. Static settings come from environment variables; the Bedrock model is
resolved at runtime from a `config.json` object in the input bucket so it can
be changed without a redeploy (see `load_runtime_settings`, the single
runtime loader).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from typing import Any

from .errors import InvalidConfigError


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
    # present, else the fallback; `load_runtime_settings` replaces this at
    # runtime from config.json in the input bucket.
    bedrock_model_id: str = os.environ.get("BEDROCK_MODEL_ID", _FALLBACK_MODEL_ID)

    # Default target languages (German, French). The deployed Lambda overrides
    # this from `target_languages` in config.json (see load_runtime_settings).
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


@dataclass(frozen=True)
class RuntimeSettings:
    """Settings read from config.json at the start of each job."""

    model_id: str
    debug: bool
    target_languages: tuple[str, ...]
    # Optional display names for the GUI, e.g. {"de": "German"}.
    language_labels: dict[str, str]


# Amazon Translate codes: 2-3 letters, optionally a subtag (zh-TW, fr-CA).
_LANG_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")


def parse_target_languages(raw: dict[str, Any], default: tuple[str, ...]) -> tuple[str, ...]:
    """Return the target language codes from a parsed config.json mapping.

    Absent key -> `default`. A present-but-invalid value raises InvalidConfigError (a ValueError) so
    a bad edit fails the job early with a clear message instead of failing
    partway through on a Translate error. "en" is rejected: the source is
    English, so translating to it is meaningless. Duplicates are dropped.
    """
    if "target_languages" not in raw:
        return default
    value = raw["target_languages"]
    if not isinstance(value, list) or not value:
        raise InvalidConfigError("config.json: target_languages must be a non-empty list of codes")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _LANG_CODE.match(item.strip()):
            raise InvalidConfigError(f"config.json: invalid target language code: {item!r}")
        code = item.strip()
        if code.lower() == "en":
            raise InvalidConfigError("config.json: 'en' is the source language, not a target")
        if code not in codes:
            codes.append(code)
    return tuple(codes)


def parse_language_labels(raw: dict[str, Any]) -> dict[str, str]:
    """Return {code: display name} from config.json; ignores malformed entries."""
    labels = raw.get("language_labels")
    if not isinstance(labels, dict):
        return {}
    return {k: v for k, v in labels.items() if isinstance(k, str) and isinstance(v, str)}


def load_runtime_settings(s3_client: Any, bucket: str, config: Config) -> RuntimeSettings:
    """Read config.json once and return all runtime settings.

    A missing or unreadable file falls back to defaults (never breaks a run).
    A file that is readable but has an invalid `target_languages` raises
    InvalidConfigError so the job is marked as an error with a clear message.
    """
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=MODEL_CONFIG_KEY)
        raw = json.loads(obj["Body"].read())
        if not isinstance(raw, dict):
            raise ValueError("config.json must be a JSON object")
    except Exception:
        env_override = os.environ.get("BEDROCK_MODEL_ID")
        return RuntimeSettings(
            model_id=env_override or _FALLBACK_MODEL_ID,
            debug=True,
            target_languages=config.target_languages,
            language_labels={},
        )
    return RuntimeSettings(
        model_id=parse_model_config(raw),
        debug=bool(raw.get("debug", True)),
        target_languages=parse_target_languages(raw, config.target_languages),
        language_labels=parse_language_labels(raw),
    )


def with_target_languages(config: Config, targets: tuple[str, ...]) -> Config:
    """Return a copy of `config` with the resolved target languages."""
    return replace(config, target_languages=targets)


def with_model_id(config: Config, model_id: str) -> Config:
    """Return a copy of `config` with the resolved Bedrock model id."""
    return replace(config, bedrock_model_id=model_id)
