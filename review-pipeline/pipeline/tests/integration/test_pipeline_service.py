# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Integration test for the pipeline orchestration using fake clients.

Exercises the English-source flow (summarize once -> translate the summary
into each target -> combined row) without touching AWS.
"""

from src.config import load_config
from src.client import TranslationResult, SummarizationResult
from src.service import PipelineService
from src.model import Review


class FakeTranslate:
    def __init__(self):
        self.calls = []

    def translate(self, text, target_language, source_language="auto"):
        self.calls.append((text, source_language, target_language))
        return TranslationResult(
            text=f"[{target_language}] {text}",
            source_language=source_language,
            target_language=target_language,
            # Real Amazon Translate echoes the SOURCE language here, not the
            # target. Mirroring that keeps this fake honest.
            detected_source_language=source_language,
        )


class FakeBedrock:
    def __init__(self):
        self.calls = 0

    def summarize(self, english_text, max_tokens=160):
        self.calls += 1
        return SummarizationResult(
            summary="The item fits well and feels good. The buyer was satisfied.",
            input_tokens=20,
            output_tokens=15,
        )


def _english_review():
    return Review(
        review_id="rev-0001",
        product="jacket",
        product_id="PRD-0001-abc123",
        product_name="Heritage Wool Jacket",
        source_language="en",
        rating=4,
        text="The fit is spot on. The fabric feels soft. I would buy it again.",
        date="2026-10-01",
    )


def test_summarize_and_translate_produces_combined_row():
    bedrock = FakeBedrock()
    translate = FakeTranslate()
    svc = PipelineService(translate, bedrock, load_config())

    row = svc.summarize_and_translate(_english_review(), ["de", "fr"])

    # Exactly one summarize call for both target languages.
    assert bedrock.calls == 1
    # One translate call per target.
    assert len(translate.calls) == 2

    assert row["english_review"].startswith("The fit is spot on")
    assert row["english_summary"].startswith("The item fits well")
    assert row["de_summary"].startswith("[de] ")
    assert row["fr_summary"].startswith("[fr] ")
    assert row["surfaced"] is True


def test_process_review_single_target_still_works():
    svc = PipelineService(FakeTranslate(), FakeBedrock(), load_config())
    result = svc.process_review(_english_review(), "de")
    assert [s.name for s in result.steps] == ["summarize", "translate_summary"]
    assert result.summary_translated.startswith("[de] ")
    assert result.surfaced is True


def test_process_batch_covers_de_and_fr():
    results = PipelineService(FakeTranslate(), FakeBedrock(), load_config()).process_batch(
        [_english_review(), _english_review()], ["de", "fr"]
    )
    assert len(results) == 4
    assert {r.target_language for r in results} == {"de", "fr"}


def test_process_batch_summarizes_each_review_once_for_all_targets():
    bedrock = FakeBedrock()
    svc = PipelineService(FakeTranslate(), bedrock, load_config())
    results = svc.process_batch([_english_review(), _english_review()], ["de", "fr", "es"])

    assert len(results) == 6  # 2 reviews x 3 targets
    assert bedrock.calls == 2  # one summary per review, not per (review, target)
