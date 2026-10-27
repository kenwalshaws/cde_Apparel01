# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for JobStore against an in-memory fake S3 client."""

import io
import json

from src.client import JobStore


class NoSuchKey(Exception):
    pass


class FakeS3:
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        NoSuchKey = NoSuchKey

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix, Delimiter):  # noqa: N803
                keys = [k for (b, k) in objects if b == Bucket and k.startswith(Prefix)]
                prefixes = sorted({"/".join(k.split("/")[:2]) + "/" for k in keys})
                yield {"CommonPrefixes": [{"Prefix": p} for p in prefixes]}

        return Paginator()


def test_write_and_read_round_trip_keeps_unicode():
    s3 = FakeS3()
    store = JobStore(s3, "in", "out")
    store.write_json("jobs/j1/results/results.json", [{"de_summary": "Größe passt"}])

    assert ("out", "jobs/j1/results/results.json") in s3.objects
    assert store.read_json_or_none("jobs/j1/results/results.json") == [
        {"de_summary": "Größe passt"}
    ]


def test_missing_key_returns_none():
    assert JobStore(FakeS3(), "in", "out").read_json_or_none("jobs/none/status.json") is None


def test_input_bucket_is_separate_from_output_bucket():
    s3 = FakeS3()
    store = JobStore(s3, "in", "out")
    store.write_input_json("sample/reviews.json", [{"review_id": "r1"}])

    assert store.read_input_json("sample/reviews.json") == [{"review_id": "r1"}]
    assert json.loads(s3.objects[("in", "sample/reviews.json")]) == [{"review_id": "r1"}]


def test_list_job_ids():
    s3 = FakeS3()
    store = JobStore(s3, "in", "out")
    store.write_json("jobs/job-a/status.json", {})
    store.write_json("jobs/job-b/status.json", {})
    assert sorted(store.list_job_ids()) == ["job-a", "job-b"]
