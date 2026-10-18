# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Local control plane backing the TypeScript GUI.

api layer: a thin HTTP surface that lets the local GUI drive the *deployed*
AWS backend. It runs on your machine with your AWS credentials and does three
things on the GUI's behalf:

  - generate : invoke the deployed Lambda with action "generate" (the Lambda
               builds the synthetic corpus and uploads it to the input bucket)
  - process  : invoke the deployed Lambda with action "process" (the Lambda
               runs the translate/summarize/score pipeline, writing results to
               the output bucket)
  - results  : read surfaced result files from the output bucket
  - summary  : read run_summary.json from the output bucket

The browser never holds AWS credentials or talks to AWS directly — it only
calls this local service over /api.

Run (from the `pipeline/` directory, with AWS creds + the stack deployed):
    PIPELINE_FUNCTION=review-pipeline-processor \
    OUTPUT_BUCKET=review-pipeline-output-<account-id> \
    AWS_REGION=us-east-1 \
    uvicorn src.api.local_app:app --reload --port 8000

Environment variables:
    PIPELINE_FUNCTION  (required)  deployed Lambda function name
    OUTPUT_BUCKET      (required)  output bucket to read results from
    AWS_REGION         (optional)  defaults to us-east-1
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_REGION = os.environ.get("AWS_REGION", "us-east-1")
_lambda = boto3.client("lambda", region_name=_REGION)
_s3 = boto3.client("s3", region_name=_REGION)


def _function_name() -> str:
    name = os.environ.get("PIPELINE_FUNCTION")
    if not name:
        raise HTTPException(
            status_code=500,
            detail="PIPELINE_FUNCTION env var is not set (deployed Lambda name).",
        )
    return name


def _output_bucket() -> str:
    bucket = os.environ.get("OUTPUT_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="OUTPUT_BUCKET env var is not set.")
    return bucket


def _invoke_lambda(payload: dict[str, Any]) -> dict[str, Any]:
    """Synchronously invoke the deployed Lambda and parse its response."""
    resp = _lambda.invoke(
        FunctionName=_function_name(),
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = resp["Payload"].read()
    if resp.get("FunctionError"):
        raise HTTPException(status_code=502, detail=f"Lambda error: {raw.decode('utf-8')}")

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
    targets: list[str] = ["fr", "de"]


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
    """Ask the deployed Lambda to process the corpus for the target languages."""
    return _invoke_lambda(
        {"action": "process", "input_key": req.input_key, "targets": req.targets}
    )


@app.get("/results")
def results(lang: str | None = None) -> list[dict[str, Any]]:
    """Read surfaced result files from the output bucket, optionally by language."""
    bucket = _output_bucket()
    prefix = f"translated_summaries/{lang}/" if lang else "translated_summaries/"

    out: list[dict[str, Any]] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            out.append(json.loads(body))
    return out


@app.get("/summary")
def summary() -> dict[str, Any]:
    bucket = _output_bucket()
    try:
        body = _s3.get_object(Bucket=bucket, Key="run_summary.json")["Body"].read()
    except _s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="no run summary yet; run the pipeline first")
    return json.loads(body)
