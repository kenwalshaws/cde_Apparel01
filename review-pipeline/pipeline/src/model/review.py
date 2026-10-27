# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Data structures for the review pipeline.

This is the model layer: plain data, no logic, no outward dependencies.
Every other layer may depend on these types; this module depends on nothing
in the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from ..errors import InvalidInputError

# Supported source languages in the synthetic corpus. ISO 639-1 codes.
# This use case: reviews start in English, are summarized, and the English
# summary is translated into the target languages below.
SOURCE_LANGUAGES = ("en",)

# Reference default only. The languages a job actually uses come from
# `target_languages` in config.json (see src/config.py); this constant is the
# built-in fallback and is not read by the deployed pipeline.
TARGET_LANGUAGES = ("de", "fr")

# Fields every input review must carry. `source_language` is required for
# format stability but is not used yet: all text is treated as English.
_REQUIRED_FIELDS = ("review_id", "product", "source_language", "rating", "text", "date")


@dataclass
class Review:
    """A single inbound product review (synthetic, no PII)."""

    review_id: str
    product: str  # category, e.g. "shirt"
    product_id: str  # unique per review
    product_name: str  # marketing-style name, e.g. "Classic Oxford Shirt"
    source_language: str
    rating: int  # 1-5 stars
    text: str
    date: str  # ISO 8601 date string

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Review":
        """Build a Review from one JSON object.

        Raises InvalidInputError (safe to show) naming the missing field or the
        bad value, instead of leaking a bare KeyError.
        """
        if not isinstance(data, dict):
            raise InvalidInputError("each review must be a JSON object")
        missing = [k for k in _REQUIRED_FIELDS if k not in data]
        if missing:
            raise InvalidInputError(
                f"review {data.get('review_id', '?')!r} is missing: {', '.join(missing)}"
            )
        try:
            rating = int(data["rating"])
        except (TypeError, ValueError) as exc:
            raise InvalidInputError(
                f"review {data['review_id']!r}: rating must be an integer"
            ) from exc
        return cls(
            review_id=str(data["review_id"]),
            product=str(data["product"]),
            # Tolerate older inputs that predate these fields.
            product_id=str(data.get("product_id", "")),
            product_name=str(data.get("product_name", "")),
            source_language=str(data["source_language"]),
            rating=rating,
            text=str(data["text"]),
            date=str(data["date"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepResult:
    """Outcome of one pipeline step, carrying its own quality score.

    `passed` reflects whether the step's quality score met the configured
    threshold. A failed step marks the whole review as not surfaceable.
    """

    name: str  # e.g. "translate_source", "summarize", "translate_summary"
    output: str
    score: float  # 0.0 - 1.0
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    """Full result of running one review through the pipeline for one target."""

    review_id: str
    product: str
    source_language: str
    target_language: str
    original_text: str
    english_text: str
    summary_en: str
    summary_translated: str
    steps: list[StepResult] = field(default_factory=list)
    surfaced: bool = False  # True only if every step passed its threshold

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @property
    def overall_score(self) -> float:
        """Mean of step scores; 0.0 if there are no steps."""
        if not self.steps:
            return 0.0
        return sum(s.score for s in self.steps) / len(self.steps)
