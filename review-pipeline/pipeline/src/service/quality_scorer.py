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
  - source match:    Translate saw the input language we declared ("en")
  - translated:      output is not identical to the input
  - no-echo:         summary did not simply copy the input verbatim
  - sentence shape:  summary reads as 1-2 sentences, not a fragment or a wall

Each dimension returns 0.0-1.0; the step score is their mean. The pipeline
compares the score to the configured threshold to decide `passed`.
"""

from __future__ import annotations

import re

from ..config import Config


_SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s|$)")

# --- Tunable score values ---------------------------------------------------
# These are judgment calls for a proof of concept, not measured constants.
# Raise or lower them (or replace the heuristic) once real review data shows
# what "good" looks like. The pass threshold is QUALITY_THRESHOLD (default 0.7).

# Summary shape: 1-2 sentences scores 1.0. Three is a mild miss (still readable,
# but not tight); four or more reads as a paragraph or a fragment run.
THREE_SENTENCE_SCORE = 0.6
LONG_OR_FRAGMENT_SCORE = 0.3

# Summary that is nearly as long as the review barely summarized it. Not zero,
# because it may still be a legitimate short review.
NEAR_ECHO_SCORE = 0.4
NEAR_ECHO_LENGTH_RATIO = 0.9

# Translation: Translate saw a different input language than we declared.
# Low enough to fail the pass threshold when combined with a good echo score.
SOURCE_MISMATCH_SCORE = 0.2
# No source reported: neutral, because we do not have the signal.
SOURCE_UNREPORTED_SCORE = 0.8
# Output identical to the input means nothing was translated.
UNTRANSLATED_ECHO_SCORE = 0.2


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
        return THREE_SENTENCE_SCORE
    return LONG_OR_FRAGMENT_SCORE


def _no_echo(summary: str, source_english: str) -> float:
    """Penalize a 'summary' that is just the input copied back."""
    s = summary.strip().lower()
    src = source_english.strip().lower()
    if not s:
        return 0.0
    if s == src:
        return 0.0
    # If the summary is nearly as long as the source, it did not summarize.
    if len(s) >= NEAR_ECHO_LENGTH_RATIO * len(src):
        return NEAR_ECHO_SCORE
    return 1.0


def _source_match(reported_source: str | None, expected_source: str) -> float:
    """Reward translations whose reported SOURCE language is the expected one.

    Amazon Translate reports the language of the input (SourceLanguageCode),
    not of the output. So the valid check is: did Translate see the language
    we said the input was? When no source is reported, stay neutral (SOURCE_UNREPORTED_SCORE)
    rather than punishing a signal we do not have.
    """
    if reported_source is None:
        return SOURCE_UNREPORTED_SCORE
    matches = reported_source.lower().startswith(expected_source.lower())
    return 1.0 if matches else SOURCE_MISMATCH_SCORE


def _translated(output: str, source_text: str) -> float:
    """Penalize output identical to the input (nothing was translated)."""
    same = output.strip().lower() == source_text.strip().lower()
    return UNTRANSLATED_ECHO_SCORE if same else 1.0


def score_translation(
    text: str,
    source_text: str,
    expected_source: str,
    reported_source: str | None,
) -> float:
    """Score a translation step output. Returns 0.0-1.0.

    `text` is the translated output, `source_text` the input that was
    translated, `expected_source` the language we declared for the input, and
    `reported_source` what Translate reported back.

    Empty output is a hard failure (0.0): there is nothing to surface, so no
    other dimension can rescue it.
    """
    if _non_empty(text) == 0.0:
        return 0.0
    dims = [
        _source_match(reported_source, expected_source),
        _translated(text, source_text),
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
