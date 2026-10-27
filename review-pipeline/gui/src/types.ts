// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Shapes returned by the pipeline backend (job-scoped).

// One row in a job's results.json.
export interface ResultRow {
  review_id: string;
  product: string;
  product_id: string;
  product_name: string;
  english_review: string;
  english_summary: string;
  surfaced: boolean;
  // One `<code>_summary` field per target language (e.g. de_summary), driven
  // by config.json `target_languages`. Read these dynamically.
  [translation: `${string}_summary`]: string | undefined;
}

// One review in a job's inputs/samples.json.
export interface ReviewInput {
  review_id: string;
  product: string;
  product_id: string;
  product_name: string;
  source_language: string;
  rating: number;
  text: string;
  date: string;
}

// Per-job summary (results/summary.json, also returned by /process).
export interface JobSummary {
  jobnum: string;
  reviews: number;
  rows: number;
  surfaced: number;
  surfaced_pct: number;
  elapsed_seconds: number;
  targets: string[];
  // Display names from config.json `language_labels` (may be missing/partial).
  target_labels?: Record<string, string>;
  model_id: string;
  created_utc: string;
}

export type JobStatus = "running" | "complete" | "error" | "unknown";

// Response from /process (dispatcher): returns immediately with the jobnum.
export interface SubmitResponse {
  jobnum: string;
  status: JobStatus;
  reviews?: number;
}

// Full job detail returned by /job.
export interface JobDetail {
  jobnum: string;
  status: JobStatus;
  status_detail?: Record<string, unknown>;
  inputs: ReviewInput[];
  results: ResultRow[];
  summary: Partial<JobSummary>;
}
