# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for runtime config parsing (target languages). No AWS calls."""

import io
import json

import pytest

from src.config import (
    load_config,
    load_runtime_settings,
    parse_language_labels,
    parse_target_languages,
)

DEFAULT = ("de", "fr")


class FakeS3:
    def __init__(self, payload=None, fail=False):
        self._payload = payload
        self._fail = fail

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
        if self._fail:
            raise RuntimeError("NoSuchKey")
        return {"Body": io.BytesIO(json.dumps(self._payload).encode("utf-8"))}


def test_absent_key_uses_default():
    assert parse_target_languages({}, DEFAULT) == DEFAULT


def test_codes_are_read_in_order_and_deduplicated():
    raw = {"target_languages": ["es", "de", "es", "zh-TW"]}
    assert parse_target_languages(raw, DEFAULT) == ("es", "de", "zh-TW")


@pytest.mark.parametrize(
    "bad",
    [[], "de", ["de", 5], ["German"], ["en"], ["de;drop"], [""]],
)
def test_invalid_values_raise(bad):
    with pytest.raises(ValueError):
        parse_target_languages({"target_languages": bad}, DEFAULT)


def test_labels_ignore_malformed_entries():
    raw = {"language_labels": {"de": "German", "fr": 3}}
    assert parse_language_labels(raw) == {"de": "German"}
    assert parse_language_labels({"language_labels": "x"}) == {}


def test_settings_from_config_json():
    s3 = FakeS3(
        {
            "debug": False,
            "target_languages": ["es", "it"],
            "language_labels": {"es": "Spanish"},
            "models": [{"id": "m1"}],
            "default_model": "m1",
        }
    )
    s = load_runtime_settings(s3, "bucket", load_config())
    assert s.target_languages == ("es", "it")
    assert s.language_labels == {"es": "Spanish"}
    assert s.model_id == "m1"
    assert s.debug is False


def test_missing_file_falls_back_to_defaults():
    s = load_runtime_settings(FakeS3(fail=True), "bucket", load_config())
    assert s.target_languages == DEFAULT
    assert s.debug is True


def test_invalid_targets_in_readable_file_fail_loudly():
    s3 = FakeS3({"target_languages": ["en"]})
    with pytest.raises(ValueError):
        load_runtime_settings(s3, "bucket", load_config())
