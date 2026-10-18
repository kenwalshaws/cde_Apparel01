// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { RunSummary } from "../types";

interface Props {
  summary: RunSummary;
}

// Top-of-page strip of aggregate metrics from the latest run — the numbers
// the customer takes to leadership (surfaced %, latency, per-language scores).
export function SummaryBar({ summary }: Props) {
  return (
    <div
      style={{
        display: "flex",
        gap: 24,
        flexWrap: "wrap",
        padding: "14px 18px",
        background: "#111827",
        color: "white",
        borderRadius: 10,
        marginBottom: 20,
      }}
    >
      <Metric label="Results" value={String(summary.total_results)} />
      <Metric label="Surfaced" value={`${summary.surfaced} (${summary.surfaced_pct}%)`} />
      <Metric label="Total time" value={`${summary.elapsed_seconds}s`} />
      <Metric label="Per result" value={`${summary.mean_seconds_per_result}s`} />
      {Object.entries(summary.per_language).map(([lang, s]) => (
        <Metric
          key={lang}
          label={`${lang.toUpperCase()} mean score`}
          value={`${Math.round(s.mean_score * 100)}%`}
        />
      ))}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, textTransform: "uppercase", color: "#9ca3af", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
