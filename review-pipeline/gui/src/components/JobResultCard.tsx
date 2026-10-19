// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { ResultRow } from "../types";

interface Props {
  row: ResultRow;
}

// A fancy card showing one review end-to-end:
//   English review  →  English summary  →  German + French translations.
export function JobResultCard({ row }: Props) {
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
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Translation flag="🇩🇪" lang="German (de)" text={row.de_summary} />
        <Translation flag="🇫🇷" lang="French (fr)" text={row.fr_summary} />
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

function Translation({ flag, lang, text }: { flag: string; lang: string; text: string }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        border: "1px solid #e5e7eb",
        background: "#fafafa",
      }}
    >
      <Label>
        {flag} {lang}
      </Label>
      <div style={{ fontSize: 14, color: "#111827" }}>{text}</div>
    </div>
  );
}
