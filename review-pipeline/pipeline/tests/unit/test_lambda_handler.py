# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Lambda router. No AWS calls (the job service is faked)."""

import json
import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.api import lambda_handler as lh  # noqa: E402
from src.errors import UserFacingError  # noqa: E402


def _body(resp):
    return json.loads(resp["body"])


class FakeContext:
    aws_request_id = "req-123"


class FakeService:
    """Records calls; stands in for JobService."""

    def __init__(self):
        self.started = []

    def start_job(self, input_key):
        self.started.append(input_key)
        return {"jobnum": "job-1", "status": "running", "reviews": 2}

    def list_jobs(self):
        return {"jobs": ["job-1"]}

    def get_job(self, jobnum):
        return {"jobnum": jobnum}


def test_unknown_action_returns_400():
    resp = lh.handler({"action": "nope"})
    assert resp["statusCode"] == 400
    assert "unknown action" in _body(resp)["error"]


def test_api_gateway_path_selects_action_and_adds_cors(monkeypatch):
    monkeypatch.setattr(lh, "_service", lambda: FakeService())
    resp = lh.handler({"httpMethod": "GET", "path": "/prod/jobs"})
    assert resp["statusCode"] == 200
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
    assert _body(resp) == {"jobs": ["job-1"]}


def test_options_preflight_ok():
    resp = lh.handler({"httpMethod": "OPTIONS", "path": "/prod/process"})
    assert resp["statusCode"] == 200


def test_unexpected_error_returns_generic_500_without_internal_detail(monkeypatch):
    def boom():
        raise RuntimeError("arn:aws:s3:::secret-bucket exploded")

    monkeypatch.setattr(lh, "_service", boom)
    resp = lh.handler({"httpMethod": "GET", "path": "/jobs"}, FakeContext())

    body = _body(resp)
    assert resp["statusCode"] == 500
    assert body == {"error": "internal error", "request_id": "req-123"}
    assert "secret-bucket" not in resp["body"]
    assert "Access-Control-Allow-Origin" in resp["headers"]


def test_user_facing_error_returns_400_with_its_message(monkeypatch):
    def bad():
        raise UserFacingError("review 'r1' is missing: rating")

    monkeypatch.setattr(lh, "_service", bad)
    resp = lh.handler({"httpMethod": "GET", "path": "/jobs"})
    assert resp["statusCode"] == 400
    assert _body(resp)["error"] == "review 'r1' is missing: rating"


def test_malformed_json_body_returns_400():
    resp = lh.handler({"httpMethod": "POST", "path": "/process", "body": "{not json"})
    assert resp["statusCode"] == 400
    assert _body(resp)["error"] == "request body is not valid JSON"


def test_non_object_json_body_returns_400():
    resp = lh.handler({"httpMethod": "POST", "path": "/process", "body": "[1, 2]"})
    assert resp["statusCode"] == 400


def test_job_requires_jobnum(monkeypatch):
    monkeypatch.setattr(lh, "_service", lambda: FakeService())
    resp = lh.handler({"action": "job"})
    assert _body(resp) == {"error": "jobnum is required"}


def test_process_dispatches_async_worker(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    service = FakeService()
    invoked = {}
    monkeypatch.setattr(lh, "_service", lambda: service)
    monkeypatch.setattr(lh._lambda, "invoke", lambda **kw: invoked.update(kw))

    resp = lh.handler({"action": "process", "input_key": "sample/x.json"})
    out = _body(resp)

    assert resp["statusCode"] == 200
    assert out["status"] == "running"
    assert service.started == ["sample/x.json"]
    assert invoked["InvocationType"] == "Event"
    payload = json.loads(invoked["Payload"])
    assert payload == {"action": "_worker", "jobnum": "job-1", "input_key": "sample/x.json"}
