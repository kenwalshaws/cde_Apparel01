# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Client layer: thin AWS SDK wrappers with no pipeline knowledge."""

from .translate_client import TranslateClient, TranslationResult
from .bedrock_client import BedrockClient, SummarizationResult

__all__ = [
    "TranslateClient",
    "TranslationResult",
    "BedrockClient",
    "SummarizationResult",
]
