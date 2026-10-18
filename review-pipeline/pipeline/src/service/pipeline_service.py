# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pipeline orchestration.

Service layer: the only place that knows the full flow. Depends on the client
layer (Translate, Bedrock), the quality scorer, and the model. Does not know
how it is invoked (CLI, Lambda, API) — callers hand it reviews and config.

Flow per (review, target_language):
    1. Translate source review -> English      (skip if already English)
    2. Summarize English review -> 1-2 sentences
    3. Translate summary -> target language
    4. Score each step; surface only if all steps pass the threshold
"""

from __future__ import annotations

from ..config import Config
from ..client import TranslateClient, BedrockClient
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

        # Step 1: source -> English (skip the call when already English).
        if review.source_language.lower().startswith("en"):
            english_text = review.text
            steps.append(
                StepResult(
                    name="translate_source",
                    output=english_text,
                    score=1.0,
                    passed=True,
                    detail={"skipped": True, "reason": "source already English"},
                )
            )
        else:
            translated = self._translate.translate(
                text=review.text,
                target_language="en",
                source_language=review.source_language,
            )
            english_text = translated.text
            score = quality_scorer.score_translation(
                english_text, "en", translated.detected_source_language
            )
            steps.append(
                StepResult(
                    name="translate_source",
                    output=english_text,
                    score=score,
                    passed=score >= self._config.quality_threshold,
                    detail={"detected": translated.detected_source_language},
                )
            )

        # Step 2: summarize the English review.
        summarized = self._bedrock.summarize(english_text)
        summary_en = summarized.summary
        summary_score = quality_scorer.score_summary(summary_en, english_text, self._config)
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

        # Step 3: translate the summary into the target shopper language.
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
