# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline orchestration.

Service layer: the only place that knows the full flow. Depends on the client
layer (Translate, Bedrock), the quality scorer, and the model. Does not know
how it is invoked (CLI, Lambda, API) — callers hand it reviews and config.

Reviews are English. Flow per review:
    1. Summarize the review -> 1-2 sentences        (Bedrock, ONCE per review)
    2. Translate the summary into each target       (Amazon Translate)
    3. Score each step; surface only if all steps pass the threshold

Every public method follows this order, so the summary is computed once per
review no matter how many target languages there are.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..client import TranslateClient, BedrockClient
from ..debug import debug_print
from ..model import Review, StepResult, PipelineResult
from . import quality_scorer


class PipelineService:
    def __init__(
        self,
        translate_client: TranslateClient,
        bedrock_client: BedrockClient,
        config: Config,
    ) -> None:
        self._translate = translate_client
        self._bedrock = bedrock_client
        self._config = config

    # ------------------------------------------------------------------ #
    # Steps (private): each returns its output together with its StepResult
    # ------------------------------------------------------------------ #
    def _summarize(self, review: Review) -> tuple[str, StepResult]:
        """Summarize the English review once (Bedrock) and score the summary."""
        summarized = self._bedrock.summarize(review.text)
        summary_en = summarized.summary
        score = quality_scorer.score_summary(summary_en, review.text, self._config)
        debug_print(
            f"  summarized -> {summary_en!r} (score={score}, tokens in/out="
            f"{summarized.input_tokens}/{summarized.output_tokens})"
        )
        step = StepResult(
            name="summarize",
            output=summary_en,
            score=score,
            passed=score >= self._config.quality_threshold,
            detail={
                "input_tokens": summarized.input_tokens,
                "output_tokens": summarized.output_tokens,
            },
        )
        return summary_en, step

    def _translate_summary(self, summary_en: str, target: str) -> tuple[str, StepResult]:
        """Translate the English summary into one target language and score it."""
        translated = self._translate.translate(
            text=summary_en, target_language=target, source_language="en"
        )
        score = quality_scorer.score_translation(
            translated.text, summary_en, "en", translated.detected_source_language
        )
        debug_print(f"  translate_summary -> [{target}] {translated.text!r} (score={score})")
        step = StepResult(
            name="translate_summary",
            output=translated.text,
            score=score,
            passed=score >= self._config.quality_threshold,
            detail={"target": target},
        )
        return translated.text, step

    @staticmethod
    def _result(
        review: Review,
        target: str,
        summary_en: str,
        translated: str,
        steps: list[StepResult],
    ) -> PipelineResult:
        return PipelineResult(
            review_id=review.review_id,
            product=review.product,
            source_language=review.source_language,
            target_language=target,
            original_text=review.text,
            english_text=review.text,
            summary_en=summary_en,
            summary_translated=translated,
            steps=steps,
            surfaced=all(step.passed for step in steps),
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def process_review(self, review: Review, target_language: str) -> PipelineResult:
        """Run one review through the pipeline for one target language."""
        debug_print(f"process_review: {review.review_id} target={target_language}")
        summary_en, summary_step = self._summarize(review)
        translated, translate_step = self._translate_summary(summary_en, target_language)
        return self._result(
            review, target_language, summary_en, translated, [summary_step, translate_step]
        )

    def process_batch(
        self, reviews: list[Review], target_languages: list[str] | None = None
    ) -> list[PipelineResult]:
        """Run every review against every target language.

        Each review is summarized once and the summary is reused for every
        target, so Bedrock calls scale with the number of reviews, not with
        reviews x targets.
        """
        targets = target_languages or list(self._config.target_languages)
        results: list[PipelineResult] = []
        for review in reviews:
            summary_en, summary_step = self._summarize(review)
            for target in targets:
                translated, translate_step = self._translate_summary(summary_en, target)
                results.append(
                    self._result(
                        review, target, summary_en, translated, [summary_step, translate_step]
                    )
                )
        return results

    def summarize_and_translate(
        self, review: Review, target_languages: list[str]
    ) -> dict[str, Any]:
        """Summarize an English review once, then translate into each target.

        Returns one combined row:
            {review_id, product, english_review, english_summary,
             <lang>_summary..., surfaced}
        Summarizing once (vs. per target) avoids duplicate Bedrock calls and
        guarantees an identical English summary across all target languages.
        """
        debug_print(f"summarize_and_translate: {review.review_id} targets={target_languages}")
        summary_en, summary_step = self._summarize(review)

        row: dict[str, Any] = {
            "review_id": review.review_id,
            "product": review.product,
            "product_id": review.product_id,
            "product_name": review.product_name,
            "english_review": review.text,
            "english_summary": summary_en,
        }
        all_ok = summary_step.passed
        for target in target_languages:
            translated, translate_step = self._translate_summary(summary_en, target)
            row[f"{target}_summary"] = translated
            all_ok = all_ok and translate_step.passed

        row["surfaced"] = all_ok
        return row
