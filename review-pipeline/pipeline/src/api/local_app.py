# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local control plane backing the TypeScript GUI.

api layer: a thin HTTP surface that lets a locally running GUI drive the
*deployed* AWS backend. It runs on your machine with your AWS credentials and
forwards each request to the deployed Lambda:

  - POST /generate  : Lambda action "generate" (builds the synthetic corpus and
                      uploads it to the input bucket)
  - POST /run       : Lambda action "process" (starts an asynchronous job and
                      returns its jobnum)
  - GET  /jobs      : Lambda action "jobs" (job ids, newest first)
  - GET  /job/{id}  : Lambda action "job" (one job's inputs, results, summary)
  - GET  /health    : the configuration this service is running with

The browser never holds AWS credentials or talks to AWS directly. AWS error
details are logged here and are not returned to the browser.

Run (from the `pipeline/` directory, with AWS creds + the stack deployed):
    PIPELINE_FUNCTION=review-pipeline-processor \
    AWS_REGION=us-east-1 \
    uvicorn src.api.local_app:app --reload

Environment variables:
    PIPELINE_FUNCTION  (required)  deployed Lambda function name
    OUTPUT_BUCKET      (optional)  shown by /health only
    AWS_REGION         (optional)  defaults to us-east-1
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_REGION = os.environ.get("AWS_REGION", "us-east-1")
logger = logging.getLogger("review_pipeline.local_app")
_lambda = boto3.client("lambda", region_name=_REGION)


def _function_name() -> str:
    name = os.environ.get("PIPELINE_FUNCTION")
    if not name:
        raise HTTPException(
            status_code=500,
            detail="PIPELINE_FUNCTION env var is not set (deployed Lambda name).",
        )
    return name


def _invoke_lambda(payload: dict[str, Any]) -> dict[str, Any]:
    """Synchronously invoke the deployed Lambda and parse its response."""
    function = _function_name()
    try:
        resp = _lambda.invoke(
            FunctionName=function,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=500,
            detail="No AWS credentials found for the control plane. "
            "Set them in the shell before starting uvicorn.",
        ) from exc
    except ClientError as exc:
        # Keep the AWS error (it can name the function, region and account)
        # in this process's log; return only the error code to the browser.
        err = exc.response.get("Error", {})
        code = err.get("Code", "ClientError")
        logger.error("Lambda invoke failed (%s): %s", code, err.get("Message", exc))
        raise HTTPException(
            status_code=502, detail=f"pipeline invocation failed ({code}); see the server log"
        ) from exc
    except BotoCoreError as exc:
        logger.error("AWS SDK error invoking the pipeline: %s", exc)
        raise HTTPException(
            status_code=502, detail="pipeline invocation failed; see the server log"
        ) from exc

    raw = resp["Payload"].read()
    if resp.get("FunctionError"):
        # The payload holds errorMessage and a stack trace: log it, do not return it.
        logger.error("Lambda function error: %s", raw.decode("utf-8", errors="replace"))
        raise HTTPException(
            status_code=502, detail="pipeline function error; see the server log"
        )

    outer = json.loads(raw) if raw else {}
    # The handler returns {"statusCode": ..., "body": "<json string>"}.
    body = outer.get("body")
    parsed_body = json.loads(body) if isinstance(body, str) else body
    status = outer.get("statusCode", 200)
    if status >= 400:
        raise HTTPException(status_code=status, detail=parsed_body)
    return parsed_body


app = FastAPI(title="Review Pipeline (local control plane)", version="0.2.0")

# The Vite dev server runs on 5173 by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    count: int = 100
    seed: int = 42
    key: str = "sample/reviews.json"


class ProcessRequest(BaseModel):
    input_key: str = "sample/reviews.json"
    # Not forwarded to the Lambda; targets come from config.json there.
    targets: list[str] | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "function": os.environ.get("PIPELINE_FUNCTION"),
        "output_bucket": os.environ.get("OUTPUT_BUCKET"),
        "region": _REGION,
    }


@app.post("/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    """Ask the deployed Lambda to generate a corpus and upload it to S3."""
    return _invoke_lambda(
        {"action": "generate", "count": req.count, "seed": req.seed, "key": req.key}
    )


@app.post("/run")
def run(req: ProcessRequest) -> dict[str, Any]:
    """Ask the deployed Lambda to run a job over the corpus. Returns the job summary."""
    return _invoke_lambda({"action": "process", "input_key": req.input_key})


@app.get("/jobs")
def jobs() -> dict[str, Any]:
    """List job ids (newest first)."""
    return _invoke_lambda({"action": "jobs"})


@app.get("/job/{jobnum}")
def job(jobnum: str) -> dict[str, Any]:
    """Return one job's inputs, results, and summary."""
    return _invoke_lambda({"action": "job", "jobnum": jobnum})
