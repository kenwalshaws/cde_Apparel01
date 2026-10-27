# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for BedrockClient request/response handling. No AWS calls."""

import io
import json

from src.client.bedrock_client import BedrockClient


class FakeRuntime:
    """Stands in for boto3 bedrock-runtime; records the request, returns a payload."""

    def __init__(self, payload):
        self._payload = payload
        self.request = None

    def invoke_model(self, **kwargs):
        self.request = kwargs
        return {"body": io.BytesIO(json.dumps(self._payload).encode("utf-8"))}


def test_claude_request_and_response_shape():
    fake = FakeRuntime(
        {
            "content": [{"type": "text", "text": " Fits well. "}],
            "usage": {"input_tokens": 11, "output_tokens": 4},
        }
    )
    client = BedrockClient("us-east-1", "global.anthropic.claude-haiku-5-5", client=fake)
    result = client.summarize("Great jacket.")

    body = json.loads(fake.request["body"])
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    # Haiku 5.5 rejects `temperature`; it must never be sent for Claude.
    assert "temperature" not in body
    assert result.summary == "Fits well."
    assert (result.input_tokens, result.output_tokens) == (11, 4)


def test_nova_request_and_response_shape():
    fake = FakeRuntime(
        {
            "output": {"message": {"content": [{"text": "Soft and warm."}]}},
            "usage": {"inputTokens": 9, "outputTokens": 3},
        }
    )
    client = BedrockClient("us-east-1", "us.amazon.nova-2-lite-v1:0", client=fake)
    result = client.summarize("Cozy scarf.")

    body = json.loads(fake.request["body"])
    assert "inferenceConfig" in body
    assert result.summary == "Soft and warm."
    assert (result.input_tokens, result.output_tokens) == (9, 3)
