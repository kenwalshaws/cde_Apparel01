# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""AWS Lambda entry point.

api layer: a thin adapter. It normalizes the incoming event (direct invoke,
API Gateway proxy, or S3 notification), routes to an action, and delegates the
real work to the service layer via the factory. No business logic lives here.

Actions:

  "generate"  — generate a synthetic review corpus in-Lambda and upload it to
                the input bucket.
                { "action": "generate", "count": 100, "seed": 42,
                  "key": "sample/reviews.json" }

  "process"   — run one job: snapshot the input into jobs/<jobnum>/inputs/,
                summarize each English review, translate the summary into every
                target language (de, fr), and write one combined row per review
                to jobs/<jobnum>/results/results.json. Returns the job summary
                (including jobnum). The Bedrock model + debug flag are resolved
                at runtime from config.json (no redeploy to switch).
                { "action": "process", "input_key": "sample/reviews.json" }

  "jobs"      — list job ids, newest first.
                { "action": "jobs" }  ->  { "jobs": ["job-..."] }

  "job"       — return one job's inputs, results, and summary.
                { "action": "job", "jobnum": "job-..." }

  S3 trigger  — object-created notification (event has a `Records` array).
                Treated as a job run of the uploaded key. OFF by default,
                gated behind a CloudFormation parameter.

Event shapes handled:
  - Direct Lambda invoke:  {"action": "...", ...}
  - API Gateway proxy:     {"httpMethod": "...", "path": "...", "body": "..."}
  - S3 notification:       {"Records": [...]}

Environment variables (set by the CloudFormation template):
    INPUT_BUCKET, OUTPUT_BUCKET, AWS_REGION, BEDROCK_MODEL_ID (fallback),
    QUALITY_THRESHOLD
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import unquote_plus

import boto3

from ..config import load_config, load_runtime_config, with_model_id
from ..debug import set_debug, debug_print
from ..factory import build_pipeline_with_config
from ..model import Review, PipelineResult
from ..service.synthetic import generate_reviews


_s3 = boto3.client("s3")
_lambda = boto3.client("lambda")

# CORS headers so a browser (GUI) can call API Gateway cross-origin. Permissive
# for the plumbing/PoC phase; tighten the origin when auth is turned on.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


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


def _new_jobnum() -> str:
    """Unique, sortable job id: job-YYYYMMDD-HHMMSS-<rand>, UTC."""
    import datetime
    import uuid

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"job-{ts}-{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------- #
# Actions (each returns a plain dict payload; the router wraps the response)
# --------------------------------------------------------------------------- #
def _action_generate(req: dict[str, Any]) -> dict[str, Any]:
    input_bucket = os.environ["INPUT_BUCKET"]
    # Pick up the debug flag from config.json if it already exists; defaults on.
    _, debug = load_runtime_config(_s3, input_bucket)
    set_debug(debug)

    count = int(req.get("count", 100))
    seed = int(req.get("seed", 42))
    key = req.get("key", "sample/reviews.json")
    debug_print(f"generate: count={count} seed={seed} key={key} bucket={input_bucket}")

    reviews = generate_reviews(count, seed)
    _write_json_to_s3(input_bucket, key, [r.to_dict() for r in reviews])

    by_lang: dict[str, int] = {}
    for r in reviews:
        by_lang[r.source_language] = by_lang.get(r.source_language, 0) + 1

    return {
        "action": "generate",
        "bucket": input_bucket,
        "key": key,
        "count": len(reviews),
        "by_source_language": by_lang,
    }


def _write_status(output_bucket: str, jobnum: str, status: str, **extra: Any) -> None:
    """Write jobs/<jobnum>/status.json so the GUI can poll running/complete/error."""
    payload = {"jobnum": jobnum, "status": status, **extra}
    _write_json_to_s3(output_bucket, f"jobs/{jobnum}/status.json", payload)


def _run_job(jobnum: str, input_bucket: str, input_key: str) -> dict[str, Any]:
    """Do the actual work for a job (runs in the async worker invocation).

    Each review is summarized once, then the English summary is translated into
    every target language. Writes results and updates status to complete/error.
    """
    output_bucket = os.environ["OUTPUT_BUCKET"]
    job_prefix = f"jobs/{jobnum}"

    try:
        # Read config.json once: sets the debug flag and resolves the model.
        model_id, debug = load_runtime_config(_s3, input_bucket)
        set_debug(debug)
        config = with_model_id(load_config(), model_id)
        pipeline = build_pipeline_with_config(config)
        targets = list(config.target_languages)  # ("de", "fr")
        debug_print(f"job {jobnum}: model={model_id} targets={targets} input={input_key}")

        reviews = _read_reviews_from_s3(input_bucket, input_key)

        rows: list[dict[str, Any]] = []
        surfaced_count = 0
        start = time.time()
        for review in reviews:
            row = pipeline.summarize_and_translate(review, targets)
            if row.get("surfaced"):
                surfaced_count += 1
            rows.append(row)
        elapsed = time.time() - start
        debug_print(f"job {jobnum}: {len(rows)} rows in {round(elapsed, 2)}s")

        _write_json_to_s3(output_bucket, f"{job_prefix}/results/results.json", rows)

        summary = {
            "jobnum": jobnum,
            "reviews": len(reviews),
            "rows": len(rows),
            "surfaced": surfaced_count,
            "surfaced_pct": round(100 * surfaced_count / len(rows), 1) if rows else 0.0,
            "elapsed_seconds": round(elapsed, 2),
            "targets": targets,
            "model_id": model_id,
            "created_utc": jobnum.split("job-")[-1],
        }
        _write_json_to_s3(output_bucket, f"{job_prefix}/results/summary.json", summary)
        _write_status(output_bucket, jobnum, "complete", **summary)
        return summary
    except Exception as exc:  # noqa: BLE001 - record failure in the job status
        import traceback

        print(f"job {jobnum} failed:", traceback.format_exc())
        _write_status(output_bucket, jobnum, "error", error=f"{type(exc).__name__}: {exc}")
        raise


def _action_process(req: dict[str, Any]) -> dict[str, Any]:
    """Dispatcher: create the job, kick off async work, return the jobnum now.

    Snapshots the input and writes a 'running' status immediately, then invokes
    this same function asynchronously (Event) to do the heavy lifting. Returns
    without waiting so the API responds fast and the GUI polls for completion.
    """
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    output_bucket = os.environ["OUTPUT_BUCKET"]
    input_key = req.get("input_key", "sample/reviews.json")

    jobnum = _new_jobnum()
    debug_print(f"dispatch job {jobnum} (async) input={input_key}")

    # Snapshot the input into the job folder up front so Inputs is viewable
    # while the job runs.
    reviews = _read_reviews_from_s3(input_bucket, input_key)
    _write_json_to_s3(
        output_bucket, f"jobs/{jobnum}/inputs/samples.json", [r.to_dict() for r in reviews]
    )
    _write_status(output_bucket, jobnum, "running", reviews=len(reviews))

    # Async self-invoke to run the work (InvocationType="Event" returns at once).
    _lambda.invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(
            {"action": "_worker", "jobnum": jobnum, "input_key": input_key}
        ).encode("utf-8"),
    )

    return {"jobnum": jobnum, "status": "running", "reviews": len(reviews)}


def _action_worker(req: dict[str, Any]) -> dict[str, Any]:
    """Async worker entry point: runs the job. Invoked by the dispatcher only."""
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    jobnum = req.get("jobnum") or _new_jobnum()
    input_key = req.get("input_key", "sample/reviews.json")
    return _run_job(jobnum, input_bucket, input_key)


def _action_jobs(_req: dict[str, Any]) -> dict[str, Any]:
    """List job ids (newest first)."""
    output_bucket = os.environ["OUTPUT_BUCKET"]
    jobs: set[str] = set()
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=output_bucket, Prefix="jobs/", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            # cp["Prefix"] == "jobs/<jobnum>/"
            parts = cp["Prefix"].rstrip("/").split("/")
            if len(parts) == 2:
                jobs.add(parts[1])
    return {"jobs": sorted(jobs, reverse=True)}


def _read_json_or_none(bucket: str, key: str) -> Any:
    try:
        body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body)
    except _s3.exceptions.NoSuchKey:
        return None


def _action_job(req: dict[str, Any]) -> dict[str, Any]:
    """Return one job's inputs, results, and summary."""
    output_bucket = os.environ["OUTPUT_BUCKET"]
    jobnum = req.get("jobnum", "")
    if not jobnum:
        return {"error": "jobnum is required"}
    prefix = f"jobs/{jobnum}"
    status = _read_json_or_none(output_bucket, f"{prefix}/status.json") or {}
    return {
        "jobnum": jobnum,
        "status": status.get("status", "unknown"),
        "status_detail": status,
        "inputs": _read_json_or_none(output_bucket, f"{prefix}/inputs/samples.json") or [],
        "results": _read_json_or_none(output_bucket, f"{prefix}/results/results.json") or [],
        "summary": _read_json_or_none(output_bucket, f"{prefix}/results/summary.json") or {},
    }


def _action_s3_trigger(event: dict[str, Any]) -> dict[str, Any]:
    # S3 triggers run inside their own (non-API-Gateway) invocation, so there
    # is no 29s limit here — run the job synchronously. Snapshot first.
    input_bucket = os.environ.get("INPUT_BUCKET", "")
    output_bucket = os.environ["OUTPUT_BUCKET"]
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        key = unquote_plus(s3.get("object", {}).get("key", ""))
        if key:
            jobnum = _new_jobnum()
            reviews = _read_reviews_from_s3(input_bucket, key)
            _write_json_to_s3(
                output_bucket,
                f"jobs/{jobnum}/inputs/samples.json",
                [r.to_dict() for r in reviews],
            )
            _write_status(output_bucket, jobnum, "running", reviews=len(reviews))
            return _run_job(jobnum, input_bucket, key)
    return {"error": "no S3 records in event"}


# --------------------------------------------------------------------------- #
# Event normalization
# --------------------------------------------------------------------------- #
def _normalize(event: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """Return (action, request-dict, is_api_gateway).

    Handles API Gateway proxy events (action comes from the path, params from
    the JSON body + query string) and direct invokes (action + params inline).
    """
    # API Gateway REST proxy integration.
    if "httpMethod" in event or "requestContext" in event:
        path = (event.get("path") or "").rstrip("/")
        action = path.rsplit("/", 1)[-1] if path else ""
        req: dict[str, Any] = {}
        body = event.get("body")
        if body:
            try:
                req.update(json.loads(body))
            except (ValueError, TypeError):
                pass
        qs = event.get("queryStringParameters") or {}
        req.update({k: v for k, v in qs.items() if v is not None})
        return action.lower(), req, True

    # Direct invoke.
    return (event.get("action") or "process").lower(), event, False


def _respond(payload: Any, is_api_gateway: bool, status: int = 200) -> dict[str, Any]:
    """Wrap a payload for either an API Gateway proxy response or direct invoke."""
    if is_api_gateway:
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
            "body": json.dumps(payload),
        }
    # Direct invoke keeps the historical {statusCode, body-string} shape so the
    # local control plane's parser continues to work unchanged.
    return {"statusCode": status, "body": json.dumps(payload)}


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # S3 notifications arrive with a Records array and no action field.
    if "Records" in event:
        return _respond(_action_s3_trigger(event), False)

    action, req, is_api_gw = _normalize(event)

    # CORS preflight from the browser.
    if is_api_gw and (event.get("httpMethod") == "OPTIONS"):
        return _respond({"ok": True}, True)

    dispatch = {
        "generate": _action_generate,
        "process": _action_process,
        "_worker": _action_worker,
        "jobs": _action_jobs,
        "job": _action_job,
    }
    fn = dispatch.get(action)
    if fn is None:
        return _respond({"error": f"unknown action: {action or '(none)'}"}, is_api_gw, 400)

    # Catch-all so a failure returns a proper proxy response WITH CORS headers,
    # instead of an opaque 502 the browser reports as a CORS error. The message
    # also carries the exception so the GUI can show the real cause.
    try:
        return _respond(fn(req), is_api_gw)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        import traceback

        print("handler error:", traceback.format_exc())
        return _respond(
            {"error": f"{type(exc).__name__}: {exc}"}, is_api_gw, 500
        )
