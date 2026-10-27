#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the pipeline locally over a review corpus and write outputs.

Calls real Amazon Translate and Bedrock using whatever AWS credentials are in
your environment. Writes one JSON file per surfaced result under
`data/outputs/translated_summaries/<lang>/<review_id>.json`, plus a run
summary with aggregate quality and latency metrics for the handoff report.

Usage:
    python3 pipeline/scripts/run_local.py \
        --input data/sample/reviews.json \
        --targets fr,de
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

# Requires the package to be installed (run `pip install -e pipeline/` once).
from src.config import load_config
from src.factory import build_pipeline
from src.model import Review, PipelineResult


def _load_reviews(path: Path) -> list[Review]:
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Review.from_dict(item) for item in raw]


def _write_result(out_root: Path, result: PipelineResult) -> None:
    lang_dir = out_root / result.target_language
    lang_dir.mkdir(parents=True, exist_ok=True)
    out_path = lang_dir / f"{result.review_id}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)


def _summarize_run(results: list[PipelineResult], elapsed: float) -> dict:
    total = len(results)
    surfaced = sum(1 for r in results if r.surfaced)
    by_lang: dict[str, dict[str, float]] = {}
    for r in results:
        bucket = by_lang.setdefault(
            r.target_language, {"count": 0, "surfaced": 0, "score_sum": 0.0}
        )
        bucket["count"] += 1
        bucket["surfaced"] += 1 if r.surfaced else 0
        bucket["score_sum"] += r.overall_score

    per_language = {
        lang: {
            "count": int(b["count"]),
            "surfaced": int(b["surfaced"]),
            "surfaced_pct": round(100 * b["surfaced"] / b["count"], 1) if b["count"] else 0.0,
            "mean_score": round(b["score_sum"] / b["count"], 4) if b["count"] else 0.0,
        }
        for lang, b in by_lang.items()
    }

    return {
        "total_results": total,
        "surfaced": surfaced,
        "surfaced_pct": round(100 * surfaced / total, 1) if total else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "mean_seconds_per_result": round(elapsed / total, 3) if total else 0.0,
        "per_language": per_language,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the review pipeline locally.")
    parser.add_argument("--input", required=True, help="Path to reviews JSON.")
    parser.add_argument(
        "--targets",
        default=",".join(load_config().target_languages),
        help="Comma-separated target language codes (default: the Config default, de,fr).",
    )
    parser.add_argument(
        "--output-dir",
        default="data/outputs/translated_summaries",
        help="Root dir for per-language result files.",
    )
    parser.add_argument(
        "--summary-out",
        default="data/outputs/run_summary.json",
        help="Where to write the aggregate run summary.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N reviews (0 = all). Handy for a smoke test.",
    )
    args = parser.parse_args()

    config = load_config()
    pipeline = build_pipeline(config)

    reviews = _load_reviews(Path(args.input))
    if args.limit > 0:
        reviews = reviews[: args.limit]

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    print(f"Processing {len(reviews)} reviews × {len(targets)} target(s): {targets}")
    out_root = Path(args.output_dir)

    start = time.time()
    results: list[PipelineResult] = []
    for i, review in enumerate(reviews, start=1):
        # process_batch summarizes the review once and reuses the summary for
        # every target (N Bedrock calls, not N x targets).
        for result in pipeline.process_batch([review], targets):
            results.append(result)
            if result.surfaced:
                _write_result(out_root, result)
        if i % 10 == 0:
            print(f"  ...{i}/{len(reviews)} reviews done")
    elapsed = time.time() - start

    summary = _summarize_run(results, elapsed)
    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("\nRun summary:")
    print(json.dumps(summary, indent=2))
    print(f"\nSurfaced results written under: {out_root}")
    print(f"Run summary written to: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
