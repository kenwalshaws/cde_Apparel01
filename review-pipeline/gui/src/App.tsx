// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useState } from "react";
import type { JobDetail } from "./types";
import { fetchJob, fetchJobs, generateReviews, submitJob } from "./api/pipelineClient";
import { authEnabled, getToken, clearToken } from "./api/auth";
import { Login } from "./components/Login";
import { JobResultCard } from "./components/JobResultCard";

const DEFAULT_COUNT = 100;
type Busy = "generate" | "waiting" | "run" | "jobs" | "job" | null;

export default function App() {
  const [authed, setAuthed] = useState<boolean>(!authEnabled() || Boolean(getToken()));
  if (authEnabled() && !authed) {
    return <Login onSignedIn={() => setAuthed(true)} />;
  }
  return (
    <Dashboard
      onSignOut={() => {
        clearToken();
        setAuthed(false);
      }}
    />
  );
}

interface LogEntry {
  time: string;
  message: string;
  tone: "info" | "ok" | "error";
}

function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const [count, setCount] = useState(DEFAULT_COUNT);
  const [jobs, setJobs] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [tab, setTab] = useState<"results" | "inputs">("results");
  const [busy, setBusy] = useState<Busy>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);

  const pushLog = useCallback((message: string, tone: LogEntry["tone"] = "info") => {
    const time = new Date().toLocaleTimeString();
    setLog((prev) => [...prev, { time, message, tone }]);
  }, []);

  const loadJobs = useCallback(async () => {
    setBusy("jobs");
    setError(null);
    pushLog("Loading job list…");
    try {
      const list = await fetchJobs();
      setJobs(list);
      pushLog(`Found ${list.length} job(s).`, "ok");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      pushLog(`Loading jobs failed: ${msg}`, "error");
    } finally {
      setBusy(null);
    }
  }, [pushLog]);

  const openJob = useCallback(
    async (jobnum: string) => {
      setSelected(jobnum);
      setBusy("job");
      setError(null);
      pushLog(`Opening job ${jobnum}…`);
      try {
        const detail = await fetchJob(jobnum);
        setJob(detail);
        pushLog(
          `Loaded ${jobnum}: ${detail.results.length} results, ${detail.inputs.length} inputs.`,
          "ok"
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        pushLog(`Opening job failed: ${msg}`, "error");
      } finally {
        setBusy(null);
      }
    },
    [pushLog]
  );

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  // Auto-refresh every 2 minutes: refresh the jobs list and re-fetch the open
  // job silently (no busy spinner) so async results appear on their own.
  useEffect(() => {
    const id = setInterval(
      () => {
        pushLog("Auto-refresh (2 min)…");
        void fetchJobs()
          .then(setJobs)
          .catch(() => {});
        if (selected) {
          void fetchJob(selected)
            .then(setJob)
            .catch(() => {});
        }
      },
      2 * 60 * 1000
    );
    return () => clearInterval(id);
  }, [selected, pushLog]);

  // Submit a job (fire-and-forget). The backend runs it asynchronously; we
  // show "submitted" and return. Auto-refresh (and Refresh) surface it when done.
  const runProcess = useCallback(async (): Promise<string | null> => {
    setBusy("run");
    setError(null);
    pushLog("Step: submitting job (runs asynchronously in AWS)…");
    try {
      const res = await submitJob();
      const msg = `Job submitted: ${res.jobnum} (${res.reviews ?? "?"} reviews) — running…`;
      setStatus(msg);
      pushLog(msg, "ok");
      pushLog("Processing runs in the background; the list auto-refreshes every 2 min.");
      await loadJobs();
      await openJob(res.jobnum);
      return res.jobnum;
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setError(m);
      pushLog(`Submit failed: ${m}`, "error");
      return null;
    } finally {
      setBusy(null);
    }
  }, [loadJobs, openJob, pushLog]);

  // Generate, then auto-start processing after a 4s pause.
  const onGenerate = useCallback(async () => {
    setBusy("generate");
    setError(null);
    setStatus(null);
    pushLog(`Step: generating ${count} English reviews…`);
    try {
      const res = await generateReviews({ count });
      pushLog(`Generated ${res.count} reviews → s3://${res.bucket}/${res.key}`, "ok");
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setError(m);
      pushLog(`Generate failed: ${m}`, "error");
      setBusy(null);
      return;
    }
    setBusy("waiting");
    pushLog("Step: waiting 4s before processing…");
    await new Promise((r) => setTimeout(r, 4000));
    await runProcess();
  }, [count, pushLog, runProcess]);

  const onRun = useCallback(async () => {
    await runProcess();
  }, [runProcess]);

  const anyBusy = busy !== null;

  return (
    <div
      style={{
        maxWidth: 1080,
        margin: "0 auto",
        padding: "28px 20px",
        fontFamily: "system-ui, -apple-system, sans-serif",
        color: "#111827",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 18,
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 24 }}>Review Translate-and-Summarize</h1>
          <p style={{ color: "#6b7280", marginTop: 6 }}>
            English reviews → English summary → German &amp; French translations.
            Each run is a job; browse jobs and inspect inputs and results.
          </p>
        </div>
        {authEnabled() && (
          <button onClick={onSignOut} style={btnGhost}>
            Sign out
          </button>
        )}
      </header>

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Count{" "}
          <input
            type="number"
            min={1}
            max={1000}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            style={{ width: 70, padding: "6px 8px", borderRadius: 6, border: "1px solid #d1d5db" }}
          />
        </label>
        <button onClick={onGenerate} disabled={anyBusy} style={btn("#0f766e", anyBusy)}>
          {busy === "generate"
            ? "Generating…"
            : busy === "waiting"
              ? "Waiting 4s…"
              : "1. Generate + Process"}
        </button>
        <button onClick={onRun} disabled={anyBusy} style={btn("#2563eb", anyBusy)}>
          {busy === "run" ? "Running job…" : "2. Process only (new job)"}
        </button>
        <button onClick={() => void loadJobs()} disabled={anyBusy} style={btnGhost}>
          {busy === "jobs" ? "Loading…" : "Refresh jobs"}
        </button>
      </div>

      {status && <Banner tone="ok">{status}</Banner>}
      {error && (
        <Banner tone="error">
          {error}
        </Banner>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 18 }}>
        {/* Jobs list */}
        <aside>
          <h2 style={{ fontSize: 13, textTransform: "uppercase", color: "#6b7280", letterSpacing: 0.5 }}>
            Jobs ({jobs.length})
          </h2>
          {jobs.length === 0 ? (
            <p style={{ color: "#6b7280", fontSize: 14 }}>
              No jobs yet. Generate, then run a job.
            </p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
              {jobs.map((j) => (
                <li key={j}>
                  <button
                    onClick={() => void openJob(j)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 10px",
                      borderRadius: 8,
                      border: "1px solid #e5e7eb",
                      background: selected === j ? "#eff6ff" : "white",
                      cursor: "pointer",
                      fontSize: 12.5,
                      fontFamily: "ui-monospace, monospace",
                      color: selected === j ? "#1d4ed8" : "#374151",
                    }}
                  >
                    {j}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* Selected job */}
        <main>
          {!job ? (
            <p style={{ color: "#6b7280" }}>Select a job to see its inputs and results.</p>
          ) : (
            <>
              <div style={{ display: "flex", gap: 8, margin: "0 0 14px" }}>
                <TabButton active={tab === "results"} onClick={() => setTab("results")}>
                  Results ({job.results.length})
                </TabButton>
                <TabButton active={tab === "inputs"} onClick={() => setTab("inputs")}>
                  Inputs ({job.inputs.length})
                </TabButton>
              </div>

              {busy === "job" ? (
                <p style={{ color: "#6b7280" }}>Loading job…</p>
              ) : tab === "results" ? (
                job.results.length === 0 && job.status === "running" ? (
                  <p style={{ color: "#6b7280" }}>
                    Job is still running. Results will appear here when it
                    finishes — the view auto-refreshes every 2 minutes, or click
                    the job again to refresh now.
                  </p>
                ) : (
                  <div style={{ display: "grid", gap: 14 }}>
                    {job.results.map((r) => (
                      <JobResultCard key={r.review_id} row={r} />
                    ))}
                  </div>
                )
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {job.inputs.map((rev) => (
                    <div
                      key={rev.review_id}
                      style={{
                        border: "1px solid #e5e7eb",
                        borderRadius: 10,
                        padding: "10px 12px",
                        background: "white",
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600 }}>
                        {rev.product_name || rev.product}
                      </div>
                      <div style={{ fontSize: 12, color: "#6b7280" }}>
                        {rev.review_id} · {rev.product}
                        {rev.product_id ? ` · ${rev.product_id}` : ""} · {rev.rating}★ ·{" "}
                        {rev.date}
                      </div>
                      <div style={{ fontSize: 14 }}>{rev.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </main>
      </div>

      <ActivityLog log={log} onClear={() => setLog([])} />
    </div>
  );
}

function ActivityLog({ log, onClear }: { log: LogEntry[]; onClear: () => void }) {
  return (
    <section style={{ marginTop: 24 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <h2
          style={{
            fontSize: 13,
            textTransform: "uppercase",
            color: "#6b7280",
            letterSpacing: 0.5,
            margin: 0,
          }}
        >
          Activity log
        </h2>
        {log.length > 0 && (
          <button
            onClick={onClear}
            style={{
              fontSize: 12,
              border: "none",
              background: "none",
              color: "#6b7280",
              cursor: "pointer",
            }}
          >
            clear
          </button>
        )}
      </div>
      <div
        style={{
          background: "#0b1021",
          color: "#d1d5db",
          borderRadius: 10,
          padding: "12px 14px",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 12.5,
          lineHeight: 1.6,
          maxHeight: 200,
          overflowY: "auto",
        }}
      >
        {log.length === 0 ? (
          <span style={{ color: "#6b7280" }}>No activity yet.</span>
        ) : (
          log.map((e, i) => (
            <div key={i}>
              <span style={{ color: "#6b7280" }}>{e.time} </span>
              <span
                style={{
                  color:
                    e.tone === "ok" ? "#6ee7b7" : e.tone === "error" ? "#fca5a5" : "#93c5fd",
                }}
              >
                {e.message}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "6px 14px",
        borderRadius: 8,
        border: "1px solid #d1d5db",
        background: active ? "#2563eb" : "white",
        color: active ? "white" : "#374151",
        fontWeight: 600,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function Banner({ tone, children }: { tone: "ok" | "error"; children: React.ReactNode }) {
  const palette =
    tone === "ok"
      ? { bg: "#ecfdf5", border: "#a7f3d0", color: "#065f46" }
      : { bg: "#fef2f2", border: "#fecaca", color: "#991b1b" };
  return (
    <div
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.color,
        padding: "10px 14px",
        borderRadius: 8,
        marginBottom: 16,
        fontSize: 14,
      }}
    >
      {children}
    </div>
  );
}

const btnGhost: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: 8,
  border: "1px solid #d1d5db",
  background: "white",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

function btn(bg: string, disabled: boolean): React.CSSProperties {
  return {
    padding: "8px 16px",
    borderRadius: 8,
    border: "none",
    background: disabled ? "#9ca3af" : bg,
    color: "white",
    fontWeight: 600,
    cursor: disabled ? "default" : "pointer",
  };
}
