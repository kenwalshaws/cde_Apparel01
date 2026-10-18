# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Service layer: orchestration and quality scoring.

The only layer that knows the full translate -> summarize -> translate flow.
"""

from .pipeline_service import PipelineService
from .synthetic import generate_reviews
from . import quality_scorer

__all__ = ["PipelineService", "generate_reviews", "quality_scorer"]
