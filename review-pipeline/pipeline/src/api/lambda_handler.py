# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""AWS Lambda entry point.

api layer: a thin adapter. It routes an incoming event to one of three
actions and delegates the real work to the service layer via the factory.
No business logic lives here.

Actions (chosen by the event's `action` field; defaults to "process"):

  "generate"  — generate a synthetic review corpus inside the Lambda and
                upload it to the input bucket.
                event: {"action": "generate", "count": 100, "seed": 42,
                        "key": "sample/reviews.json"}

  "process"   — read a reviews JSON from the input bucket, run the pipeline
                for each target language, write surfaced results and a run
                summary to the output bucket.
                event: {"action": "process", "input_key": "sample/reviews.json",
                        "targets": ["fr", "de"]}

  S3 trigger  — when the input bucket is configured to notify this function on
                object creation, the event arrives with a `Records` array.
                Treated as a "process" of each uploaded key. This trigger is
                OFF by default and gated behind a CloudFormation parameter; the
                GUI-driven flow uses the explicit "process" action instead.

Environment variables (set by the CloudFormation template):
    INPUT_BUCKET, OUTPUT_BUCKET, AWS_REGION, BEDROCK_MODEL_ID, QUALITY_THRESHOLD
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import unquote_plus

import boto3

from ..config import load_config
from ..factory import build_pipeline
from ..model import Review, PipelineResult
from ..service.synthetic import generate_reviews


_s3 = boto3.client("s3")


# --------------------------------------------------------------------------- #
# S3 helpers
# --------------------------------------------------------------------------- #
def _read_reviews_from_s3(bucket: str, key: str) -> list[Review]:
    obj = _s3.get_object(Bucket=bucket, Key=key)
    raw = json.loads(obj["Body"].read())
    return [Review.from_dict(item) for item in raw]


def _write_json_to_s3(bucket: str, key: str, payload: Any) -> None:
    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _write_result_to_s3(bucket: str, result: PipelineResult) -> None:
    key = f"translated_summaries/{result.target_language}/{result.review_id}.json"
    _write_json_to_s3(bucket, key, result.to_dict())


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def _action_generate(event: dict[str, Any]) -> dict[str, Any]:
    """Generate a synthetic corpus in-Lambda and upload it to the input bucket."""
    input_bucket = os.environ["INPUT_BUCKET"]
    count = int(event.get("count", 100))
    seed = int(event.get("seed", 42))
    key = event.get("key", "sample/reviews.json")

    reviews = generate_reviews(count, seed)
    _write_json_to_s3(input_bucket, key, [r.to_dict() for r in reviews])

    by_lang: dict[str, int] = {}
    for r in reviews:
        by_lang[r.source_language] = by_lang.get(r.source_language, 0) + 1

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "action": "generate",
                "bucket": input_bucket,
                "key": key,
                "count": len(reviews),
                "by_source_language": by_lang,
            }
        ),
    }


def _process_keys(pairs: list[tuple[str, str]], targets: list[str]) -> dict[str, Any]:
    config = load_config()
    pipeline = build_pipeline(config)
    output_bucket = os.environ["OUTPUT_BUCKET"]
    effective_targets = targets or list(config.target_languages)

    all_results: list[PipelineResult] = []
    start = time.time()
    for bucket, key in pairs:
        reviews = _read_reviews_from_s3(bucket, key)
        for review in reviews:
            for target in effective_targets:
                result = pipeline.process_review(review, target)
                all_results.append(result)
                if result.surfaced:
                    _write_result_to_s3(output_bucket, result)
    elapsed = time.time() - start

    surfaced = sum(1 for r in all_results if r.surfaced)
    summary = {
        "total_results": len(all_results),
        "surfaced": surfaced,
        "surfaced_pct": round(100 * surfaced / len(all_results), 1) if all_results else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "mean_seconds_per_result": round(elapsed / len(all_results), 3) if all_results else 0.0,
        "targets": effective_targets,
    }
    _write_json_to_s3(output_bucket, "run_summary.json", summary)
    return {"statusCode": 200, "body": json.dumps(summary)}


def _action_process(event: dict[str, Any]) -> dict[str, Any]:
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    key = event.get("input_key", "sample/reviews.json")
    targets = event.get("targets") or []
    return _process_keys([(input_bucket, key)], targets)


def _action_s3_trigger(event: dict[str, Any]) -> dict[str, Any]:
    """Handle an S3 object-created notification (OFF by default)."""
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    pairs: list[tuple[str, str]] = []
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name", input_bucket)
        key = unquote_plus(s3.get("object", {}).get("key", ""))
        if key:
            pairs.append((bucket, key))
    if not pairs:
        return {"statusCode": 400, "body": json.dumps({"error": "no S3 records in event"})}
    return _process_keys(pairs, [])


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # S3 notifications arrive with a Records array and no action field.
    if "Records" in event:
        return _action_s3_trigger(event)

    action = (event.get("action") or "process").lower()
    if action == "generate":
        return _action_generate(event)
    if action == "process":
        return _action_process(event)

    return {
        "statusCode": 400,
        "body": json.dumps({"error": f"unknown action: {action}"}),
    }
