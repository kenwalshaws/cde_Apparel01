// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { PipelineResult } from "../types";
import { ScoreBadge } from "./ScoreBadge";

interface Props {
  result: PipelineResult;
}

const STEP_LABELS: Record<string, string> = {
  translate_source: "Translate → EN",
  summarize: "Summarize",
  translate_summary: "Translate summary",
};

// Shows one review's journey through the pipeline: original text, English
// translation, English summary, translated summary, plus the per-step scores.
export function ReviewCard({ result }: Props) {
  return (
    <article
      style={{
        border: "1px solid #e2e2e2",
        borderRadius: 10,
        padding: 16,
        background: "white",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <div>
          <strong>{result.review_id}</strong>{" "}
          <span style={{ color: "#666" }}>· {result.product}</span>
        </div>
        <div style={{ fontSize: 13, color: "#666" }}>
          {result.source_language.toUpperCase()} → {result.target_language.toUpperCase()}
        </div>
      </header>

      <Field label="Original" value={result.original_text} muted />
      <Field label="Summary (target language)" value={result.summary_translated} highlight />

      <details style={{ marginTop: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 13, color: "#555" }}>
          Pipeline detail
        </summary>
        <div style={{ marginTop: 8 }}>
          <Field label="English translation" value={result.english_text} muted small />
          <Field label="English summary" value={result.summary_en} muted small />
          <table style={{ width: "100%", marginTop: 10, borderCollapse: "collapse" }}>
            <tbody>
              {result.steps.map((step) => (
                <tr key={step.name}>
                  <td style={{ padding: "4px 0", fontSize: 13 }}>
                    {STEP_LABELS[step.name] ?? step.name}
                  </td>
                  <td style={{ padding: "4px 0", textAlign: "right" }}>
                    <ScoreBadge score={step.score} passed={step.passed} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}

function Field({
  label,
  value,
  muted,
  highlight,
  small,
}: {
  label: string;
  value: string;
  muted?: boolean;
  highlight?: boolean;
  small?: boolean;
}) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, textTransform: "uppercase", color: "#999", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: small ? 13 : 15,
          color: muted ? "#555" : "#111",
          fontWeight: highlight ? 600 : 400,
          background: highlight ? "#f3f8ff" : "transparent",
          padding: highlight ? "6px 10px" : 0,
          borderRadius: highlight ? 6 : 0,
        }}
      >
        {value}
      </div>
    </div>
  );
}
