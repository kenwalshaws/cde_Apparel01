# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the model layer. No AWS calls."""

from src.model import Review, StepResult, PipelineResult


def test_review_roundtrip():
    data = {
        "review_id": "rev-0001",
        "product": "shirt",
        "product_id": "PRD-0001-abc123",
        "product_name": "Classic Cotton Shirt",
        "source_language": "en",
        "rating": 4,
        "text": "The fit is spot on.",
        "date": "2026-10-01",
    }
    review = Review.from_dict(data)
    assert review.to_dict() == data


def test_review_defaults_optional_fields_when_missing():
    # Older inputs without product_id/product_name still load (empty strings).
    review = Review.from_dict(
        {
            "review_id": "rev-1",
            "product": "hat",
            "source_language": "en",
            "rating": 3,
            "text": "Fine.",
            "date": "2026-10-01",
        }
    )
    assert review.product_id == ""
    assert review.product_name == ""


def test_review_coerces_rating_to_int():
    review = Review.from_dict(
        {
            "review_id": 1,
            "product": "hat",
            "source_language": "en",
            "rating": "5",
            "text": "Great.",
            "date": "2026-10-01",
        }
    )
    assert review.rating == 5
    assert review.review_id == "1"


def test_overall_score_is_mean_of_steps():
    result = PipelineResult(
        review_id="rev-1",
        product="shirt",
        source_language="fr",
        target_language="de",
        original_text="x",
        english_text="x",
        summary_en="x",
        summary_translated="x",
        steps=[
            StepResult(name="a", output="", score=1.0, passed=True),
            StepResult(name="b", output="", score=0.5, passed=False),
        ],
    )
    assert result.overall_score == 0.75


def test_overall_score_zero_with_no_steps():
    result = PipelineResult(
        review_id="rev-1",
        product="shirt",
        source_language="fr",
        target_language="de",
        original_text="x",
        english_text="x",
        summary_en="x",
        summary_translated="x",
    )
    assert result.overall_score == 0.0
