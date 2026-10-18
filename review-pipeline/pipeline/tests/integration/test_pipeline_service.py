# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Integration test for the pipeline orchestration using fake clients.

Exercises the full translate -> summarize -> translate -> score flow without
touching AWS. Fakes stand in for the client layer.
"""

from src.config import load_config
from src.client import TranslationResult, SummarizationResult
from src.service import PipelineService
from src.model import Review


class FakeTranslate:
    """Returns deterministic translations and records calls."""

    def __init__(self):
        self.calls = []

    def translate(self, text, target_language, source_language="auto"):
        self.calls.append((text, source_language, target_language))
        prefix = f"[{target_language}] "
        return TranslationResult(
            text=prefix + text,
            source_language=source_language,
            target_language=target_language,
            detected_source_language=target_language,
        )


class FakeBedrock:
    def summarize(self, english_text, max_tokens=160):
        return SummarizationResult(
            summary="The item fits well and feels good. The buyer was satisfied.",
            input_tokens=20,
            output_tokens=15,
        )


def _service():
    return PipelineService(FakeTranslate(), FakeBedrock(), load_config())


def test_french_review_runs_end_to_end_and_surfaces():
    review = Review(
        review_id="rev-0003",
        product="jacket",
        source_language="fr",
        rating=4,
        text="Il taille très bien. Le tissu est doux. Je le rachèterais.",
        date="2026-10-01",
    )
    result = _service().process_review(review, "de")

    assert [s.name for s in result.steps] == [
        "translate_source",
        "summarize",
        "translate_summary",
    ]
    assert result.target_language == "de"
    assert result.surfaced is True
    assert result.summary_translated.startswith("[de] ")


def test_english_source_skips_first_translation():
    svc = _service()
    review = Review(
        review_id="rev-0002",
        product="dress",
        source_language="en",
        rating=5,
        text="The fit is spot on. The fabric feels soft. Very satisfied.",
        date="2026-10-01",
    )
    result = svc.process_review(review, "fr")

    first_step = result.steps[0]
    assert first_step.name == "translate_source"
    assert first_step.detail.get("skipped") is True


def test_process_batch_covers_every_target():
    reviews = [
        Review("rev-1", "hat", "fr", 4, "Bon produit.", "2026-10-01"),
        Review("rev-2", "shoes", "de", 2, "Zu klein.", "2026-10-01"),
    ]
    results = _service().process_batch(reviews, ["fr", "de"])
    assert len(results) == 4
    langs = {r.target_language for r in results}
    assert langs == {"fr", "de"}
