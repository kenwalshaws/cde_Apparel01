// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Thin client over the local FastAPI backend. Requests go through the Vite
// proxy (/api -> http://localhost:8000), so these are same-origin in dev.

import type { PipelineResult, RunSummary } from "../types";

const BASE = "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function fetchResults(lang?: string): Promise<PipelineResult[]> {
  const query = lang ? `?lang=${encodeURIComponent(lang)}` : "";
  return getJson<PipelineResult[]>(`/results${query}`);
}

export async function fetchSummary(): Promise<RunSummary | null> {
  const res = await fetch(`${BASE}/summary`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`GET /summary failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as RunSummary;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const err = await res.json();
      if (err?.detail) detail = JSON.stringify(err.detail);
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new Error(`POST ${path} failed: ${detail}`);
  }
  return (await res.json()) as T;
}

export interface GenerateRequest {
  count?: number;
  seed?: number;
  key?: string;
}

export interface GenerateResponse {
  action: string;
  bucket: string;
  key: string;
  count: number;
  by_source_language: Record<string, number>;
}

// Asks the deployed Lambda (via the local control plane) to generate a
// synthetic corpus and upload it to the input bucket.
export async function generateReviews(req: GenerateRequest = {}): Promise<GenerateResponse> {
  return postJson<GenerateResponse>("/generate", req);
}

export interface RunRequest {
  input_key?: string;
  targets?: string[];
}

// Asks the deployed Lambda (via the local control plane) to process the corpus.
export async function runPipeline(req: RunRequest = {}): Promise<RunSummary> {
  return postJson<RunSummary>("/run", req);
}
