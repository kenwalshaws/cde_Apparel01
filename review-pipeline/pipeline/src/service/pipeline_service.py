# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline orchestration.

Service layer: the only place that knows the full flow. Depends on the client
layer (Translate, Bedrock), the quality scorer, and the model. Does not know
how it is invoked (CLI, Lambda, API) — callers hand it reviews and config.

This use case: reviews start in English. Flow per (review, target_language):
    1. (source is English — no source translation needed)
    2. Summarize English review -> 1-2 sentences  (Bedrock)
    3. Render summary into the target language:
         - target "en": pass the English summary through as-is (baseline)
         - other target: translate the summary       (Amazon Translate)
    4. Score each step; surface only if all steps pass the threshold
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

    def process_review(self, review: Review, target_language: str) -> PipelineResult:
        """Run one review through the pipeline for one target language."""
        steps: list[StepResult] = []
        debug_print(f"process_review start: {review.review_id} target={target_language}")

        # Source is English in this use case; no source translation step.
        english_text = review.text
        debug_print(f"  english source: {english_text!r}")

        # Step: summarize the English review (Bedrock).
        summarized = self._bedrock.summarize(english_text)
        summary_en = summarized.summary
        summary_score = quality_scorer.score_summary(summary_en, english_text, self._config)
        debug_print(
            f"  summarized -> {summary_en!r} "
            f"(score={summary_score}, tokens in/out="
            f"{summarized.input_tokens}/{summarized.output_tokens})"
        )
        steps.append(
            StepResult(
                name="summarize",
                output=summary_en,
                score=summary_score,
                passed=summary_score >= self._config.quality_threshold,
                detail={
                    "input_tokens": summarized.input_tokens,
                    "output_tokens": summarized.output_tokens,
                },
            )
        )

        # Step: render the summary into the target language.
        if target_language.lower().startswith("en"):
            # English target: pass the summary through unchanged (baseline).
            summary_translated = summary_en
            translate_summary_score = 1.0
            debug_print("  translate_summary: en pass-through (no Translate call)")
            steps.append(
                StepResult(
                    name="translate_summary",
                    output=summary_translated,
                    score=translate_summary_score,
                    passed=True,
                    detail={"target": target_language, "passthrough": True},
                )
            )
        else:
            summary_translated_result = self._translate.translate(
                text=summary_en,
                target_language=target_language,
                source_language="en",
            )
            summary_translated = summary_translated_result.text
            translate_summary_score = quality_scorer.score_translation(
                summary_translated,
                target_language,
                summary_translated_result.detected_source_language,
            )
            debug_print(
                f"  translate_summary -> [{target_language}] {summary_translated!r} "
                f"(score={translate_summary_score})"
            )
            steps.append(
                StepResult(
                    name="translate_summary",
                    output=summary_translated,
                    score=translate_summary_score,
                    passed=translate_summary_score >= self._config.quality_threshold,
                    detail={"target": target_language},
                )
            )

        surfaced = all(step.passed for step in steps)
        debug_print(f"  surfaced={surfaced}")

        return PipelineResult(
            review_id=review.review_id,
            product=review.product,
            source_language=review.source_language,
            target_language=target_language,
            original_text=review.text,
            english_text=english_text,
            summary_en=summary_en,
            summary_translated=summary_translated,
            steps=steps,
            surfaced=surfaced,
        )

    def process_batch(
        self, reviews: list[Review], target_languages: list[str] | None = None
    ) -> list[PipelineResult]:
        """Run every review against every target language."""
        targets = target_languages or list(self._config.target_languages)
        results: list[PipelineResult] = []
        for review in reviews:
            for target in targets:
                results.append(self.process_review(review, target))
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
        english_text = review.text

        summarized = self._bedrock.summarize(english_text)
        summary_en = summarized.summary
        summary_score = quality_scorer.score_summary(summary_en, english_text, self._config)
        summary_ok = summary_score >= self._config.quality_threshold
        debug_print(f"  english_summary={summary_en!r} (score={summary_score}, ok={summary_ok})")

        row: dict[str, Any] = {
            "review_id": review.review_id,
            "product": review.product,
            "product_id": review.product_id,
            "product_name": review.product_name,
            "english_review": english_text,
            "english_summary": summary_en,
        }
        all_ok = summary_ok
        for target in target_languages:
            translated = self._translate.translate(
                text=summary_en, target_language=target, source_language="en"
            )
            score = quality_scorer.score_translation(
                translated.text, target, translated.detected_source_language
            )
            row[f"{target}_summary"] = translated.text
            ok = score >= self._config.quality_threshold
            all_ok = all_ok and ok
            debug_print(f"  {target}_summary={translated.text!r} (score={score}, ok={ok})")

        row["surfaced"] = all_ok
        return row
