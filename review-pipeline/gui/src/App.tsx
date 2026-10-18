// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useState } from "react";
import type { PipelineResult, RunSummary } from "./types";
import {
  fetchResults,
  fetchSummary,
  generateReviews,
  runPipeline,
} from "./api/pipelineClient";
import { ReviewCard } from "./components/ReviewCard";
import { SummaryBar } from "./components/SummaryBar";

const TARGETS = ["fr", "de"] as const;
const DEFAULT_COUNT = 100;

type Busy = "generate" | "run" | "load" | null;

export default function App() {
  const [results, setResults] = useState<PipelineResult[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [lang, setLang] = useState<string>("");
  const [count, setCount] = useState<number>(DEFAULT_COUNT);
  const [busy, setBusy] = useState<Busy>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (selectedLang: string) => {
    setBusy("load");
    setError(null);
    try {
      const [res, sum] = await Promise.all([
        fetchResults(selectedLang || undefined),
        fetchSummary(),
      ]);
      setResults(res);
      setSummary(sum);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    void load(lang);
  }, [lang, load]);

  // Step 1: generate synthetic reviews (runs in the deployed Lambda).
  const onGenerate = useCallback(async () => {
    setBusy("generate");
    setError(null);
    setStatus(null);
    try {
      const res = await generateReviews({ count });
      const dist = Object.entries(res.by_source_language)
        .map(([l, n]) => `${l}:${n}`)
        .join(", ");
      setStatus(`Generated ${res.count} reviews → s3://${res.bucket}/${res.key} (${dist})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [count]);

  // Step 2: process the corpus (runs in the deployed Lambda), then refresh.
  const onRun = useCallback(async () => {
    setBusy("run");
    setError(null);
    setStatus(null);
    try {
      const sum = await runPipeline({ targets: [...TARGETS] });
      setStatus(
        `Processed ${sum.total_results} results, ${sum.surfaced} surfaced ` +
          `(${sum.surfaced_pct}%) in ${sum.elapsed_seconds}s`
      );
      await load(lang);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [lang, load]);

  const btn = (bg: string, disabled: boolean) => ({
    padding: "8px 16px",
    borderRadius: 8,
    border: "none",
    background: disabled ? "#9ca3af" : bg,
    color: "white",
    fontWeight: 600,
    cursor: disabled ? ("default" as const) : ("pointer" as const),
  });

  return (
    <div
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: "32px 20px",
        fontFamily: "system-ui, -apple-system, sans-serif",
        color: "#111",
      }}
    >
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Review Translate-and-Summarize</h1>
        <p style={{ color: "#666", marginTop: 6 }}>
          Generate, process, and view translated review summaries with per-step
          quality scoring. French and German proof of concept, running against
          the deployed AWS backend.
        </p>
      </header>

      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <label style={{ fontSize: 13, color: "#555" }}>
          Count{" "}
          <input
            type="number"
            min={1}
            max={1000}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            style={{ width: 72, padding: "6px 8px", borderRadius: 6, border: "1px solid #ccc" }}
          />
        </label>

        <button onClick={onGenerate} disabled={busy !== null} style={btn("#0f766e", busy !== null)}>
          {busy === "generate" ? "Generating…" : "1. Generate"}
        </button>

        <button onClick={onRun} disabled={busy !== null} style={btn("#2563eb", busy !== null)}>
          {busy === "run" ? "Processing…" : "2. Process"}
        </button>

        <select
          value={lang}
          onChange={(e) => setLang(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #ccc" }}
        >
          <option value="">All languages</option>
          {TARGETS.map((t) => (
            <option key={t} value={t}>
              {t.toUpperCase()}
            </option>
          ))}
        </select>

        <button
          onClick={() => void load(lang)}
          disabled={busy !== null}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "1px solid #ccc",
            background: "white",
            cursor: busy !== null ? "default" : "pointer",
          }}
        >
          {busy === "load" ? "Loading…" : "3. View / Refresh"}
        </button>
      </div>

      {status && (
        <div
          style={{
            background: "#ecfdf5",
            border: "1px solid #a7f3d0",
            color: "#065f46",
            padding: "10px 14px",
            borderRadius: 8,
            marginBottom: 16,
            fontSize: 14,
          }}
        >
          {status}
        </div>
      )}

      {error && (
        <div
          style={{
            background: "#fef2f2",
            border: "1px solid #fecaca",
            color: "#991b1b",
            padding: "10px 14px",
            borderRadius: 8,
            marginBottom: 20,
          }}
        >
          {error}
          <div style={{ fontSize: 12, marginTop: 4, color: "#b91c1c" }}>
            Is the local control plane running with AWS creds? Start it with:{" "}
            <code>
              PIPELINE_FUNCTION=… OUTPUT_BUCKET=… uvicorn src.api.local_app:app --port 8000
            </code>
          </div>
        </div>
      )}

      {summary && <SummaryBar summary={summary} />}

      {busy === "load" ? (
        <p style={{ color: "#666" }}>Loading…</p>
      ) : results.length === 0 ? (
        <p style={{ color: "#666" }}>
          No results yet. Generate a corpus, then process it to produce
          translated summaries.
        </p>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          {results.map((r) => (
            <ReviewCard key={`${r.review_id}-${r.target_language}`} result={r} />
          ))}
        </div>
      )}
    </div>
  );
}
