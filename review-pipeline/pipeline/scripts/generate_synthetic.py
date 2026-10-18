#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Generate a synthetic apparel-review corpus (local CLI wrapper).

Thin wrapper over `src.service.synthetic.generate_reviews` so the generation
logic has a single home that both this script and the Lambda share. No PII:
reviews carry a product, a source language, a rating, a date, and free text.

Usage:
    python3 pipeline/scripts/generate_synthetic.py --count 100 \
        --output data/sample/reviews.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Requires the package to be installed (run `pip install -e pipeline/` once).
from src.service.synthetic import generate_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic reviews.")
    parser.add_argument("--count", type=int, default=100, help="Number of reviews.")
    parser.add_argument(
        "--output",
        type=str,
        default="data/sample/reviews.json",
        help="Output JSON path (relative to the review-pipeline root).",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility.")
    args = parser.parse_args()

    reviews = generate_reviews(args.count, args.seed)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in reviews], fh, ensure_ascii=False, indent=2)

    by_lang: dict[str, int] = {}
    for r in reviews:
        by_lang[r.source_language] = by_lang.get(r.source_language, 0) + 1

    print(f"Wrote {len(reviews)} reviews to {out_path}")
    print("Source-language distribution:")
    for lang, n in sorted(by_lang.items()):
        print(f"  {lang}: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
