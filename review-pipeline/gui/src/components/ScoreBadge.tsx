// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
interface Props {
  score: number;
  passed: boolean;
}

// Color-codes a 0-1 quality score. Green when it passed its threshold,
// amber/red when it did not.
export function ScoreBadge({ score, passed }: Props) {
  const pct = Math.round(score * 100);
  const bg = passed ? "#1b7f4b" : score >= 0.4 ? "#b7791f" : "#b02a2a";
  return (
    <span
      style={{
        display: "inline-block",
        minWidth: 42,
        textAlign: "center",
        padding: "2px 8px",
        borderRadius: 999,
        background: bg,
        color: "white",
        fontSize: 12,
        fontWeight: 600,
      }}
      title={passed ? "Passed quality threshold" : "Below quality threshold"}
    >
      {pct}%
    </span>
  );
}
