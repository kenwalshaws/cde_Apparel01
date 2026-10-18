# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Amazon Translate wrapper.

Client layer: knows how to call Amazon Translate and nothing about the
pipeline. One public method, plus a confidence signal the service layer can
feed into quality scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import boto3


@dataclass
class TranslationResult:
    text: str
    source_language: str
    target_language: str
    # Translate does not return a numeric confidence, but it does report the
    # detected source language when asked to auto-detect. We expose whether the
    # detected language matched the expectation so the scorer can use it.
    detected_source_language: Optional[str] = None


class TranslateClient:
    """Thin wrapper over the Amazon Translate `translate_text` API."""

    def __init__(self, region: str, client: Any | None = None) -> None:
        self._client = client or boto3.client("translate", region_name=region)

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto",
    ) -> TranslationResult:
        """Translate `text` into `target_language`.

        `source_language` defaults to "auto" so Translate detects it. When a
        source is given explicitly, it is passed through unchanged.
        """
        response = self._client.translate_text(
            Text=text,
            SourceLanguageCode=source_language,
            TargetLanguageCode=target_language,
        )
        return TranslationResult(
            text=response["TranslatedText"],
            source_language=source_language,
            target_language=target_language,
            detected_source_language=response.get("SourceLanguageCode"),
        )
