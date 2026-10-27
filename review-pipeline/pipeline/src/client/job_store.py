# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""S3 persistence for jobs.

Client layer: the only code that reads or writes the input and output buckets
for job data. It knows the bucket layout and nothing about the pipeline.

Layout in the output bucket:
    jobs/<jobnum>/inputs/samples.json     snapshot of the input reviews
    jobs/<jobnum>/status.json             running | complete | error
    jobs/<jobnum>/results/results.json    one row per review
    jobs/<jobnum>/results/summary.json    job statistics
"""

from __future__ import annotations

import json
from typing import Any


class JobStore:
    def __init__(self, s3_client: Any, input_bucket: str, output_bucket: str) -> None:
        self._s3 = s3_client
        self._input_bucket = input_bucket
        self._output_bucket = output_bucket

    @property
    def input_bucket(self) -> str:
        return self._input_bucket

    @property
    def output_bucket(self) -> str:
        return self._output_bucket

    # -- input bucket ------------------------------------------------------ #
    def read_input_json(self, key: str) -> Any:
        """Read and parse a JSON object from the input bucket."""
        obj = self._s3.get_object(Bucket=self._input_bucket, Key=key)
        return json.loads(obj["Body"].read())

    def write_input_json(self, key: str, payload: Any) -> None:
        self._put(self._input_bucket, key, payload)

    # -- output bucket ----------------------------------------------------- #
    def write_json(self, key: str, payload: Any) -> None:
        self._put(self._output_bucket, key, payload)

    def read_json_or_none(self, key: str) -> Any:
        """Read a JSON object from the output bucket; None if the key is absent."""
        try:
            body = self._s3.get_object(Bucket=self._output_bucket, Key=key)["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None
        return json.loads(body)

    def list_job_ids(self) -> list[str]:
        """Job ids found under jobs/, unsorted."""
        jobs: set[str] = set()
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self._output_bucket, Prefix="jobs/", Delimiter="/"
        ):
            for cp in page.get("CommonPrefixes", []):
                parts = cp["Prefix"].rstrip("/").split("/")  # jobs/<jobnum>/
                if len(parts) == 2:
                    jobs.add(parts[1])
        return list(jobs)

    # -- internals --------------------------------------------------------- #
    def _put(self, bucket: str, key: str, payload: Any) -> None:
        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
