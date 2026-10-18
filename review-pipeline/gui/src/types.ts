// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Mirrors the Python model layer (model/review.py). Keep in sync with the
// PipelineResult / StepResult dataclasses.

export interface StepResult {
  name: string;
  output: string;
  score: number;
  passed: boolean;
  detail: Record<string, unknown>;
}

export interface PipelineResult {
  review_id: string;
  product: string;
  source_language: string;
  target_language: string;
  original_text: string;
  english_text: string;
  summary_en: string;
  summary_translated: string;
  steps: StepResult[];
  surfaced: boolean;
}

export interface PerLanguageSummary {
  count: number;
  surfaced: number;
  surfaced_pct: number;
  mean_score: number;
}

export interface RunSummary {
  total_results: number;
  surfaced: number;
  surfaced_pct: number;
  elapsed_seconds: number;
  mean_seconds_per_result: number;
  per_language: Record<string, PerLanguageSummary>;
}
