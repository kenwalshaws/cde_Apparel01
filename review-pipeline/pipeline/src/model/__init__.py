# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Model layer: plain data structures with no outward dependencies."""

from .review import (
    Review,
    StepResult,
    PipelineResult,
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
)

__all__ = [
    "Review",
    "StepResult",
    "PipelineResult",
    "SOURCE_LANGUAGES",
    "TARGET_LANGUAGES",
]
