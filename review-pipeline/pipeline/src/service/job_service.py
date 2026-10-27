# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Job lifecycle.

Service layer: creates jobs, runs them, and reads them back. Persistence goes
through the injected `JobStore` (client layer), so this module makes no AWS
calls itself and can be tested with a fake store.

A job is: snapshot the input reviews, mark it `running`, summarize and
translate every review, write results and a summary, mark it `complete`
(or `error`). The API layer only normalizes events and calls these methods.
"""

from __future__ import annotations

import datetime
import time
import traceback
import uuid
from typing import Any, Callable

from ..client import JobStore
from ..config import Config, RuntimeSettings, with_model_id, with_target_languages
from ..debug import debug_print, set_debug
from ..errors import UserFacingError
from ..model import Review
from .pipeline_service import PipelineService
from .synthetic import generate_reviews

DEFAULT_INPUT_KEY = "sample/reviews.json"


def new_jobnum() -> str:
    """Unique, sortable job id: job-YYYYMMDD-HHMMSS-<rand>, UTC."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"job-{ts}-{uuid.uuid4().hex[:6]}"


class JobService:
    def __init__(
        self,
        store: JobStore,
        settings_loader: Callable[[], RuntimeSettings],
        pipeline_factory: Callable[[Config], PipelineService],
        base_config: Config,
    ) -> None:
        self._store = store
        self._load_settings = settings_loader
        self._build_pipeline = pipeline_factory
        self._base_config = base_config

    # -- helpers ----------------------------------------------------------- #
    def _read_reviews(self, input_key: str) -> list[Review]:
        raw = self._store.read_input_json(input_key)
        if not isinstance(raw, list):
            raise UserFacingError(f"{input_key} must hold a JSON array of reviews")
        return [Review.from_dict(item) for item in raw]

    def _write_status(self, jobnum: str, status: str, **extra: Any) -> None:
        """Write jobs/<jobnum>/status.json so the GUI can poll the state."""
        payload = {"jobnum": jobnum, "status": status, **extra}
        self._store.write_json(f"jobs/{jobnum}/status.json", payload)

    # -- actions ----------------------------------------------------------- #
    def generate(self, count: int, seed: int, key: str) -> dict[str, Any]:
        """Generate a synthetic corpus and store it in the input bucket."""
        try:
            set_debug(self._load_settings().debug)
        except UserFacingError:
            pass  # a bad target_languages value must not block generating data
        debug_print(f"generate: count={count} seed={seed} key={key}")

        reviews = generate_reviews(count, seed)
        self._store.write_input_json(key, [r.to_dict() for r in reviews])

        by_lang: dict[str, int] = {}
        for r in reviews:
            by_lang[r.source_language] = by_lang.get(r.source_language, 0) + 1
        return {
            "action": "generate",
            "bucket": self._store.input_bucket,
            "key": key,
            "count": len(reviews),
            "by_source_language": by_lang,
        }

    def start_job(self, input_key: str = DEFAULT_INPUT_KEY) -> dict[str, Any]:
        """Create a job: snapshot the input and mark it running.

        Returns at once. The caller (or an async worker) then calls `run_job`.
        Snapshotting first makes the inputs viewable while the job runs.
        """
        reviews = self._read_reviews(input_key)
        jobnum = new_jobnum()
        self._store.write_json(
            f"jobs/{jobnum}/inputs/samples.json", [r.to_dict() for r in reviews]
        )
        self._write_status(jobnum, "running", reviews=len(reviews))
        return {"jobnum": jobnum, "status": "running", "reviews": len(reviews)}

    def run_job(self, jobnum: str, input_key: str = DEFAULT_INPUT_KEY) -> dict[str, Any]:
        """Do the work for a job: summarize, translate, score, store results.

        Failures are recorded in status.json (and the full traceback is logged)
        and returned as an error dict. They are deliberately NOT re-raised: for
        an asynchronous Lambda invocation a raised error triggers automatic
        retries that would re-run the whole job.
        """
        prefix = f"jobs/{jobnum}"
        try:
            settings = self._load_settings()
            set_debug(settings.debug)
            config = with_target_languages(
                with_model_id(self._base_config, settings.model_id),
                settings.target_languages,
            )
            pipeline = self._build_pipeline(config)
            targets = list(config.target_languages)
            debug_print(
                f"job {jobnum}: model={settings.model_id} targets={targets} input={input_key}"
            )

            reviews = self._read_reviews(input_key)
            rows: list[dict[str, Any]] = []
            surfaced_count = 0
            start = time.time()
            for review in reviews:
                row = pipeline.summarize_and_translate(review, targets)
                surfaced_count += 1 if row.get("surfaced") else 0
                rows.append(row)
            elapsed = time.time() - start
            debug_print(f"job {jobnum}: {len(rows)} rows in {round(elapsed, 2)}s")

            self._store.write_json(f"{prefix}/results/results.json", rows)
            summary = {
                "jobnum": jobnum,
                "reviews": len(reviews),
                "rows": len(rows),
                "surfaced": surfaced_count,
                "surfaced_pct": round(100 * surfaced_count / len(rows), 1) if rows else 0.0,
                "elapsed_seconds": round(elapsed, 2),
                "targets": targets,
                "target_labels": {
                    t: settings.language_labels[t]
                    for t in targets
                    if t in settings.language_labels
                },
                "model_id": settings.model_id,
                "created_utc": jobnum.split("job-")[-1],
            }
            self._store.write_json(f"{prefix}/results/summary.json", summary)
            self._write_status(
                jobnum, "complete", **{k: v for k, v in summary.items() if k != "jobnum"}
            )
            return summary
        except Exception as exc:  # noqa: BLE001 - recorded in the job status
            print(f"job {jobnum} failed:", traceback.format_exc())
            if isinstance(exc, UserFacingError):
                message = str(exc)
            else:
                # Raw exceptions can carry bucket names or ARNs; keep them in
                # the logs only.
                message = f"internal error ({type(exc).__name__}); see the Lambda logs"
            self._write_status(jobnum, "error", error=message)
            return {"jobnum": jobnum, "status": "error", "error": message}

    def list_jobs(self) -> dict[str, Any]:
        """Job ids, newest first."""
        return {"jobs": sorted(self._store.list_job_ids(), reverse=True)}

    def get_job(self, jobnum: str) -> dict[str, Any]:
        """One job's inputs, results, summary and status."""
        prefix = f"jobs/{jobnum}"
        status = self._store.read_json_or_none(f"{prefix}/status.json") or {}
        return {
            "jobnum": jobnum,
            "status": status.get("status", "unknown"),
            "status_detail": status,
            "inputs": self._store.read_json_or_none(f"{prefix}/inputs/samples.json") or [],
            "results": self._store.read_json_or_none(f"{prefix}/results/results.json") or [],
            "summary": self._store.read_json_or_none(f"{prefix}/results/summary.json") or {},
        }
