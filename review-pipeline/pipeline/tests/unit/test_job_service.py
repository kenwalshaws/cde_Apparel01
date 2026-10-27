# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the job lifecycle. A fake store replaces S3."""

from src.config import RuntimeSettings, load_config
from src.errors import InvalidConfigError
from src.service import JobService

REVIEW = {
    "review_id": "r1",
    "product": "jacket",
    "source_language": "en",
    "rating": 4,
    "text": "Fits well.",
    "date": "2026-10-01",
}


class FakeStore:
    input_bucket = "in"
    output_bucket = "out"

    def __init__(self, reviews):
        self._reviews = reviews
        self.written = {}

    def read_input_json(self, key):
        return self._reviews

    def write_input_json(self, key, payload):
        self.written[f"in:{key}"] = payload

    def write_json(self, key, payload):
        self.written[key] = payload

    def read_json_or_none(self, key):
        return self.written.get(key)

    def list_job_ids(self):
        return ["job-20260101-000000-aaaaaa", "job-20261001-000000-bbbbbb"]


class FakePipeline:
    def __init__(self):
        self.targets = None

    def summarize_and_translate(self, review, targets):
        self.targets = list(targets)
        row = {"review_id": review.review_id, "english_summary": "s", "surfaced": True}
        row.update({f"{t}_summary": f"[{t}]" for t in targets})
        return row


def _service(store, settings=None, loader_error=None):
    pipeline = FakePipeline()

    def loader():
        if loader_error:
            raise loader_error
        return settings or RuntimeSettings(
            model_id="m1", debug=False, target_languages=("de", "fr"), language_labels={}
        )

    svc = JobService(store, loader, lambda cfg: pipeline, load_config())
    return svc, pipeline


def test_start_job_snapshots_input_and_marks_running():
    store = FakeStore([REVIEW])
    svc, _ = _service(store)
    started = svc.start_job("sample/reviews.json")

    jobnum = started["jobnum"]
    assert started["status"] == "running" and started["reviews"] == 1
    assert store.written[f"jobs/{jobnum}/inputs/samples.json"][0]["review_id"] == "r1"
    assert store.written[f"jobs/{jobnum}/status.json"]["status"] == "running"


def test_run_job_uses_targets_and_labels_from_settings_and_completes():
    store = FakeStore([REVIEW])
    settings = RuntimeSettings("m1", False, ("es", "it"), {"es": "Spanish"})
    svc, pipeline = _service(store, settings)

    summary = svc.run_job("job-1")

    assert pipeline.targets == ["es", "it"]
    assert summary["targets"] == ["es", "it"]
    assert summary["target_labels"] == {"es": "Spanish"}
    assert summary["surfaced"] == 1
    status = store.written["jobs/job-1/status.json"]
    assert status["status"] == "complete"
    assert store.written["jobs/job-1/results/results.json"][0]["es_summary"] == "[es]"


def test_user_facing_failure_is_recorded_with_its_message():
    store = FakeStore([REVIEW])
    svc, _ = _service(store, loader_error=InvalidConfigError("config.json: 'en' is the source"))

    result = svc.run_job("job-2")

    assert result["status"] == "error"
    assert store.written["jobs/job-2/status.json"]["error"] == "config.json: 'en' is the source"


def test_unexpected_failure_hides_internal_detail_and_does_not_raise():
    store = FakeStore([REVIEW])
    svc, _ = _service(store, loader_error=RuntimeError("arn:aws:s3:::secret-bucket"))

    result = svc.run_job("job-3")  # must not raise (async retries would re-run the job)

    error = store.written["jobs/job-3/status.json"]["error"]
    assert result["status"] == "error"
    assert "RuntimeError" in error and "secret-bucket" not in error


def test_missing_required_field_gives_a_clear_error():
    bad = {k: v for k, v in REVIEW.items() if k != "rating"}
    svc, _ = _service(FakeStore([bad]))
    result = svc.run_job("job-4")
    assert "rating" in result["error"]


def test_list_jobs_newest_first_and_get_job_defaults():
    svc, _ = _service(FakeStore([REVIEW]))
    assert svc.list_jobs()["jobs"][0].startswith("job-20261001")
    job = svc.get_job("job-missing")
    assert job["status"] == "unknown" and job["results"] == []
