// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { ResultRow } from "../types";

interface Props {
  row: ResultRow;
  // Optional code -> display name map (from the job summary).
  labels?: Record<string, string>;
}

// Language codes present in a row: every `<code>_summary` field except the
// English one, in the order the backend wrote them.
function translationCodes(row: ResultRow): string[] {
  return Object.keys(row)
    .filter((k) => k.endsWith("_summary") && k !== "english_summary")
    .map((k) => k.slice(0, -"_summary".length));
}

// A card showing one review end-to-end:
//   English review  →  English summary  →  one tile per target language.
export function JobResultCard({ row, labels }: Props) {
  const codes = translationCodes(row);
  return (
    <article
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 14,
        padding: 18,
        background: "white",
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
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
          <div style={{ fontWeight: 700 }}>{row.product_name || row.product}</div>
          <div style={{ fontSize: 12, color: "#9ca3af" }}>
            {row.review_id} · {row.product}
            {row.product_id ? (
              <span style={{ fontFamily: "ui-monospace, monospace" }}> · {row.product_id}</span>
            ) : null}
          </div>
        </div>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            padding: "2px 10px",
            borderRadius: 999,
            background: row.surfaced ? "#dcfce7" : "#fee2e2",
            color: row.surfaced ? "#166534" : "#991b1b",
          }}
        >
          {row.surfaced ? "surfaced" : "below threshold"}
        </span>
      </header>

      {/* English review */}
      <Section label="English review" tone="muted">
        {row.english_review}
      </Section>

      {/* English summary — the hero */}
      <div
        style={{
          margin: "12px 0",
          padding: "12px 14px",
          borderRadius: 10,
          background: "linear-gradient(90deg,#eff6ff,#f5f3ff)",
          border: "1px solid #e0e7ff",
        }}
      >
        <Label>English summary</Label>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#111827" }}>
          {row.english_summary}
        </div>
      </div>

      {/* Translations side by side */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 12,
        }}
      >
        {codes.map((code) => (
          <Translation
            key={code}
            lang={labels?.[code] ? `${labels[code]} (${code})` : code.toUpperCase()}
            text={row[`${code}_summary`] ?? ""}
          />
        ))}
      </div>
    </article>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        color: "#9ca3af",
        marginBottom: 3,
      }}
    >
      {children}
    </div>
  );
}

function Section({
  label,
  tone,
  children,
}: {
  label: string;
  tone?: "muted";
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 6 }}>
      <Label>{label}</Label>
      <div style={{ fontSize: 14, color: tone === "muted" ? "#4b5563" : "#111827" }}>
        {children}
      </div>
    </div>
  );
}

function Translation({ lang, text }: { lang: string; text: string }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        border: "1px solid #e5e7eb",
        background: "#fafafa",
      }}
    >
      <Label>{lang}</Label>
      <div style={{ fontSize: 14, color: "#111827" }}>{text}</div>
    </div>
  );
}
