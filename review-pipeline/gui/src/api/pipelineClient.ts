// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Client for the pipeline backend. Two modes, chosen at build time:
//
//   VITE_API_BASE set   -> call API Gateway directly (everything runs in AWS).
//                          Routes: /generate, /process, /jobs, /job.
//   VITE_API_BASE unset -> call the local FastAPI control plane via the Vite
//                          proxy (/api -> localhost:8000). Process route /run,
//                          job detail route /job/<jobnum>.
//
// The rest of the app calls the same functions regardless of mode.

import type { SubmitResponse, JobDetail } from "../types";
import { getToken } from "./auth";

const API_BASE = import.meta.env.VITE_API_BASE as string | undefined;
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

const USING_APIGW = Boolean(API_BASE);
const BASE = API_BASE ? API_BASE.replace(/\/$/, "") : "/api";
const PROCESS_PATH = USING_APIGW ? "/process" : "/run";

function headers(withBody: boolean): HeadersInit {
  const h: Record<string, string> = {};
  if (withBody) h["Content-Type"] = "application/json";
  if (API_KEY) h["x-api-key"] = API_KEY;
  const token = getToken();
  if (token) h["Authorization"] = token; // Cognito JWT for the API GW authorizer
  return h;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: headers(false) });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const err = await res.json();
      if (err?.detail) detail = JSON.stringify(err.detail);
      else if (err?.error) detail = String(err.error);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`POST ${path} failed: ${detail}`);
  }
  return (await res.json()) as T;
}

export interface GenerateRequest {
  count?: number;
  seed?: number;
}

export interface GenerateResponse {
  action: string;
  bucket: string;
  key: string;
  count: number;
  by_source_language: Record<string, number>;
}

// Generate a synthetic corpus in-Lambda and upload it to the input bucket.
export async function generateReviews(req: GenerateRequest = {}): Promise<GenerateResponse> {
  return postJson<GenerateResponse>("/generate", req);
}

// Submit a job. The backend returns immediately with the jobnum and status
// "running"; the actual work runs asynchronously. Poll fetchJob for completion.
export async function submitJob(): Promise<SubmitResponse> {
  return postJson<SubmitResponse>(PROCESS_PATH, { input_key: "sample/reviews.json" });
}

// List job ids, newest first.
export async function fetchJobs(): Promise<string[]> {
  const data = await getJson<{ jobs: string[] }>("/jobs");
  return data.jobs ?? [];
}

// Fetch one job's inputs, results, and summary.
export async function fetchJob(jobnum: string): Promise<JobDetail> {
  if (USING_APIGW) {
    // API Gateway: /job with jobnum in the query string.
    return getJson<JobDetail>(`/job?jobnum=${encodeURIComponent(jobnum)}`);
  }
  // Local control plane: path param.
  return getJson<JobDetail>(`/job/${encodeURIComponent(jobnum)}`);
}
