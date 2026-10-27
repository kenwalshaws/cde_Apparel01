# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""AWS Lambda entry point.

api layer: a thin adapter. It normalizes the incoming event (direct invoke,
API Gateway proxy, or S3 notification), routes to an action, calls the job
service, and wraps the response. Job lifecycle, S3 persistence and scoring
live in the service and client layers (`JobService`, `JobStore`).

Actions:

  "generate"  — generate a synthetic review corpus in-Lambda and upload it to
                the input bucket.
                { "action": "generate", "count": 100, "seed": 42,
                  "key": "sample/reviews.json" }

  "process"   — dispatcher: create a job (snapshot the input, status
                `running`), start the work in a second asynchronous
                invocation of this function, and return the jobnum at once.
                { "action": "process", "input_key": "sample/reviews.json" }

  "_worker"   — internal: run the job (summarize each English review,
                translate into every target language from config.json,
                write results). Invoked only by "process".

  "jobs"      — list job ids, newest first.
                { "action": "jobs" }  ->  { "jobs": ["job-..."] }

  "job"       — return one job's inputs, results, and summary.
                { "action": "job", "jobnum": "job-..." }

  S3 trigger  — object-created notification (event has a `Records` array).
                Runs a job for the uploaded key synchronously (there is no
                29-second API Gateway limit on this path). OFF by default,
                gated behind a CloudFormation parameter.

Event shapes handled:
  - Direct Lambda invoke:  {"action": "...", ...}
  - API Gateway proxy:     {"httpMethod": "...", "path": "...", "body": "..."}
  - S3 notification:       {"Records": [...]}

Errors: a `UserFacingError` (bad request, bad config, bad input review) returns
its message with HTTP 400. Any other exception is logged in full and returns a
generic 500 with the Lambda request id, because raw exception text can contain
bucket names and ARNs.

Environment variables (set by the CloudFormation template):
    INPUT_BUCKET, OUTPUT_BUCKET, AWS_REGION, BEDROCK_MODEL_ID (fallback),
    QUALITY_THRESHOLD, CORS_ALLOW_ORIGIN / CORS_ALLOW_HEADERS / CORS_ALLOW_METHODS
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Any
from urllib.parse import unquote_plus

import boto3

from ..errors import InvalidRequestError, UserFacingError
from ..factory import build_job_service
from ..service import JobService

_s3 = boto3.client("s3")
_lambda = boto3.client("lambda")

# CORS headers so a browser (GUI) can call API Gateway cross-origin. The values
# come from the CloudFormation `Cors` mapping (passed in as environment
# variables), the same source the API Gateway OPTIONS preflight uses, so the two
# cannot drift. The defaults below only apply outside the deployed stack.
# Permissive for the proof of concept; tighten the origin to the CloudFront
# domain if the API is exposed more widely.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("CORS_ALLOW_ORIGIN", "*"),
    "Access-Control-Allow-Headers": os.environ.get(
        "CORS_ALLOW_HEADERS", "Content-Type,X-Api-Key,Authorization"
    ),
    "Access-Control-Allow-Methods": os.environ.get("CORS_ALLOW_METHODS", "GET,POST,OPTIONS"),
}


def _service() -> JobService:
    """Build the job service from the environment (one per invocation)."""
    return build_job_service(
        _s3,
        input_bucket=os.environ.get("INPUT_BUCKET", ""),
        output_bucket=os.environ["OUTPUT_BUCKET"],
    )


# --------------------------------------------------------------------------- #
# Actions (each returns a plain dict payload; the router wraps the response)
# --------------------------------------------------------------------------- #
def _action_generate(req: dict[str, Any]) -> dict[str, Any]:
    return _service().generate(
        count=int(req.get("count", 100)),
        seed=int(req.get("seed", 42)),
        key=req.get("key", "sample/reviews.json"),
    )


def _action_process(req: dict[str, Any]) -> dict[str, Any]:
    """Dispatcher: create the job, kick off async work, return the jobnum now.

    API Gateway times out at 29 seconds, so the heavy work runs in a second
    asynchronous invocation of this function (InvocationType="Event") and the
    GUI polls for the result.
    """
    input_key = req.get("input_key", "sample/reviews.json")
    started = _service().start_job(input_key)

    _lambda.invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(
            {"action": "_worker", "jobnum": started["jobnum"], "input_key": input_key}
        ).encode("utf-8"),
    )
    return started


def _action_worker(req: dict[str, Any]) -> dict[str, Any]:
    """Async worker entry point: runs the job. Invoked by the dispatcher only."""
    return _service().run_job(
        req["jobnum"], req.get("input_key", "sample/reviews.json")
    )


def _action_jobs(_req: dict[str, Any]) -> dict[str, Any]:
    return _service().list_jobs()


def _action_job(req: dict[str, Any]) -> dict[str, Any]:
    jobnum = req.get("jobnum", "")
    if not jobnum:
        return {"error": "jobnum is required"}
    return _service().get_job(jobnum)


def _action_s3_trigger(event: dict[str, Any]) -> dict[str, Any]:
    """Run a job for the first uploaded key in an S3 notification."""
    service = _service()
    for record in event.get("Records", []):
        key = unquote_plus(record.get("s3", {}).get("object", {}).get("key", ""))
        if key:
            started = service.start_job(key)
            return service.run_job(started["jobnum"], key)
    return {"error": "no S3 records in event"}


# --------------------------------------------------------------------------- #
# Event normalization
# --------------------------------------------------------------------------- #
def _normalize(event: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """Return (action, request-dict, is_api_gateway).

    Handles API Gateway proxy events (action comes from the path, params from
    the JSON body + query string) and direct invokes (action + params inline).
    Raises InvalidRequestError when an API Gateway body is not valid JSON, so
    the caller gets a 400 instead of silent defaults.
    """
    # API Gateway REST proxy integration.
    if "httpMethod" in event or "requestContext" in event:
        path = (event.get("path") or "").rstrip("/")
        action = path.rsplit("/", 1)[-1] if path else ""
        req: dict[str, Any] = {}
        body = event.get("body")
        if body:
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError) as exc:
                print("invalid JSON request body:", exc)
                raise InvalidRequestError("request body is not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise InvalidRequestError("request body must be a JSON object")
            req.update(parsed)
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
_DISPATCH = {
    "generate": _action_generate,
    "process": _action_process,
    "_worker": _action_worker,
    "jobs": _action_jobs,
    "job": _action_job,
}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    is_api_gw = "httpMethod" in event or "requestContext" in event
    request_id = getattr(context, "aws_request_id", None)
    try:
        # S3 notifications arrive with a Records array and no action field.
        if "Records" in event:
            return _respond(_action_s3_trigger(event), False)

        action, req, is_api_gw = _normalize(event)

        # CORS preflight from the browser.
        if is_api_gw and event.get("httpMethod") == "OPTIONS":
            return _respond({"ok": True}, True)

        fn = _DISPATCH.get(action)
        if fn is None:
            return _respond({"error": f"unknown action: {action or '(none)'}"}, is_api_gw, 400)
        return _respond(fn(req), is_api_gw)
    except UserFacingError as exc:
        # The message was written by this project, so it is safe to return.
        return _respond({"error": str(exc)}, is_api_gw, 400)
    except Exception:  # noqa: BLE001 - last-resort boundary for every action
        # Full detail stays in CloudWatch. The caller gets a generic message
        # (still with CORS headers, so the browser shows the real status code
        # instead of a CORS error) plus the request id to find the log entry.
        print("handler error:", traceback.format_exc())
        return _respond({"error": "internal error", "request_id": request_id}, is_api_gw, 500)
