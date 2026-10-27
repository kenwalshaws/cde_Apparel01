# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Composition root.

Wires the client and service layers together from a Config. Keeping this in
one place means the CLI, the Lambda handler, and the API all build the
pipeline the same way.
"""

from __future__ import annotations

from typing import Any

from .config import Config, load_config, load_runtime_settings
from .client import TranslateClient, BedrockClient, JobStore
from .service import JobService, PipelineService


def build_pipeline(config: Config | None = None) -> PipelineService:
    cfg = config or load_config()
    translate_client = TranslateClient(region=cfg.region)
    bedrock_client = BedrockClient(region=cfg.region, model_id=cfg.bedrock_model_id)
    return PipelineService(translate_client, bedrock_client, cfg)


def build_job_service(
    s3_client: Any, input_bucket: str, output_bucket: str, config: Config | None = None
) -> JobService:
    """Wire the job service: S3 store + runtime settings from config.json.

    The settings loader re-reads config.json on every call, so edits in the
    input bucket apply to the next job without a redeploy.
    """
    base = config or load_config()
    store = JobStore(s3_client, input_bucket, output_bucket)
    return JobService(
        store=store,
        settings_loader=lambda: load_runtime_settings(s3_client, input_bucket, base),
        pipeline_factory=build_pipeline,
        base_config=base,
    )
