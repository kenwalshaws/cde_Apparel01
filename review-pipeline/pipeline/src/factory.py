# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Composition root.

Wires the client and service layers together from a Config. Keeping this in
one place means the CLI, the Lambda handler, and the API all build the
pipeline the same way.
"""

from __future__ import annotations

from .config import Config, load_config
from .client import TranslateClient, BedrockClient
from .service import PipelineService


def build_pipeline(config: Config | None = None) -> PipelineService:
    cfg = config or load_config()
    translate_client = TranslateClient(region=cfg.region)
    bedrock_client = BedrockClient(region=cfg.region, model_id=cfg.bedrock_model_id)
    return PipelineService(translate_client, bedrock_client, cfg)


def build_pipeline_with_config(config: Config) -> PipelineService:
    """Build the pipeline from an already-resolved Config.

    Used by the Lambda handler after it resolves the Bedrock model id from
    config.json in the input bucket. Explicit alias so the call site reads
    clearly; identical wiring to build_pipeline.
    """
    return build_pipeline(config)
