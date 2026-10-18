# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Quality scoring for each pipeline step.

Service-layer helper. Produces a 0.0-1.0 score per step from deterministic
heuristics so the proof of concept can filter low-quality output without a
human in the loop. The heuristics are intentionally transparent and documented
so the customer's team can tune or replace them when they take this further.

Scoring dimensions:
  - length fit:      output is neither truncated nor runaway (summary step)
  - non-empty:       output has real content
  - language match:  translation produced the expected target script/language
  - no-echo:         summary did not simply copy the input verbatim
  - sentence shape:  summary reads as 1-2 sentences, not a fragment or a wall

Each dimension returns 0.0-1.0; the step score is their mean. The pipeline
compares the score to the configured threshold to decide `passed`.
"""

from __future__ import annotations

import re

from ..config import Config


_SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s|$)")


def _non_empty(text: str) -> float:
    return 1.0 if text and text.strip() else 0.0


def _length_fit(text: str, min_chars: int, max_chars: int) -> float:
    """1.0 inside the band, decaying linearly outside it, floored at 0.0."""
    n = len(text.strip())
    if n == 0:
        return 0.0
    if min_chars <= n <= max_chars:
        return 1.0
    if n < min_chars:
        return max(0.0, n / min_chars)
    # Too long: penalize overflow relative to the band width.
    overflow = n - max_chars
    return max(0.0, 1.0 - overflow / max_chars)


def _sentence_shape(text: str) -> float:
    """Reward 1-2 sentence summaries; penalize fragments and long runs."""
    stripped = text.strip()
    if not stripped:
        return 0.0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    count = len(sentences)
    if count in (1, 2):
        return 1.0
    if count == 3:
        return 0.6
    return 0.3


def _no_echo(summary: str, source_english: str) -> float:
    """Penalize a 'summary' that is just the input copied back."""
    s = summary.strip().lower()
    src = source_english.strip().lower()
    if not s:
        return 0.0
    if s == src:
        return 0.0
    # If the summary is nearly as long as the source, it did not summarize.
    if len(s) >= 0.9 * len(src):
        return 0.4
    return 1.0


def _language_match(detected: str | None, expected: str) -> float:
    """Reward translations whose detected language matches the target.

    When the client cannot report a detected language, stay neutral (0.8)
    rather than punishing a signal we do not have.
    """
    if detected is None:
        return 0.8
    return 1.0 if detected.lower().startswith(expected.lower()) else 0.2


def score_translation(
    text: str, expected_language: str, detected_language: str | None
) -> float:
    """Score a translation step output. Returns 0.0-1.0.

    Empty output is a hard failure (0.0): there is nothing to surface, so no
    other dimension can rescue it.
    """
    if _non_empty(text) == 0.0:
        return 0.0
    dims = [
        _language_match(detected_language, expected_language),
    ]
    return round(sum(dims) / len(dims), 4)


def score_summary(summary: str, source_english: str, config: Config) -> float:
    """Score a summarization step output. Returns 0.0-1.0.

    Empty output is a hard failure (0.0) for the same reason as translation.
    """
    if _non_empty(summary) == 0.0:
        return 0.0
    dims = [
        _length_fit(summary, config.summary_min_chars, config.summary_max_chars),
        _sentence_shape(summary),
        _no_echo(summary, source_english),
    ]
    return round(sum(dims) / len(dims), 4)
