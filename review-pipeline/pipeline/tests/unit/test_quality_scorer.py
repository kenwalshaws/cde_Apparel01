# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the quality scorer. No AWS calls."""

from src.config import load_config
from src.service import quality_scorer


CONFIG = load_config()


def test_real_shaped_translation_scores_high():
    # Real Translate response for an English->French call reports source "en".
    score = quality_scorer.score_translation("Bonjour le monde", "Hello world", "en", "en")
    assert score == 1.0


def test_empty_translation_scores_zero():
    score = quality_scorer.score_translation("", "Hello world", "en", "en")
    assert score == 0.0


def test_unexpected_source_language_lowers_score():
    matched = quality_scorer.score_translation("Hallo Welt", "Hello world", "en", "en")
    mismatched = quality_scorer.score_translation("Hallo Welt", "Hello world", "en", "es")
    assert matched > mismatched


def test_untranslated_echo_lowers_score():
    echoed = quality_scorer.score_translation("Hello world", "Hello world", "en", "en")
    assert echoed < 0.7


def test_missing_detection_is_neutral_not_zero():
    score = quality_scorer.score_translation("Bonjour", "Hello", "en", None)
    assert 0.0 < score < 1.0


def test_good_summary_scores_above_threshold():
    summary = "The jacket fits well and the fabric feels soft. The buyer was very satisfied."
    source = (
        "The fit is spot on. The fabric feels soft and well made. "
        "Very satisfied with this purchase overall and would buy again."
    )
    score = quality_scorer.score_summary(summary, source, CONFIG)
    assert score >= CONFIG.quality_threshold


def test_echoed_summary_scores_low():
    source = "The fit is spot on. The fabric feels soft. Very satisfied."
    # Summary identical to source -> no_echo = 0.
    score = quality_scorer.score_summary(source, source, CONFIG)
    assert score < CONFIG.quality_threshold


def test_empty_summary_scores_zero():
    score = quality_scorer.score_summary("", "some source text here", CONFIG)
    assert score == 0.0


def test_runaway_summary_penalized():
    source = "Short source."
    runaway = "This summary runs on and on. " * 40  # far over the max band
    score = quality_scorer.score_summary(runaway, source, CONFIG)
    assert score < CONFIG.quality_threshold
