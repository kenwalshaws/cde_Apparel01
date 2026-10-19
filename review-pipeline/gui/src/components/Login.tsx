// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { signIn, completeNewPassword } from "../api/auth";

interface Props {
  onSignedIn: () => void;
}

type Phase = "signin" | "new_password";

// Two-phase login against Cognito:
//   1. Email + password (the temporary password on first login).
//   2. If Cognito requires it, set a new permanent password.
export function Login({ onSignedIn }: Props) {
  const [phase, setPhase] = useState<Phase>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [session, setSession] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await signIn(email.trim(), password);
      if (res.status === "new_password_required") {
        setSession(res.session);
        setPhase("new_password");
      } else {
        onSignedIn();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const doNewPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await completeNewPassword(email.trim(), newPassword, session);
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={card}>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>Review Pipeline</h1>

      {phase === "signin" ? (
        <>
          <p style={hint}>Sign in to continue.</p>
          <form onSubmit={doSignIn}>
            <Field label="Email">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
                style={input}
              />
            </Field>
            <Field label="Password">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                style={input}
              />
            </Field>
            <button type="submit" disabled={busy} style={button(busy)}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </>
      ) : (
        <>
          <p style={hint}>
            First sign-in: set a new password. Must include upper and lower case,
            a number, and a symbol.
          </p>
          <form onSubmit={doNewPassword}>
            <Field label="New password">
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                required
                style={input}
              />
            </Field>
            <Field label="Confirm new password">
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                style={input}
              />
            </Field>
            <button type="submit" disabled={busy} style={button(busy)}>
              {busy ? "Saving…" : "Set password & sign in"}
            </button>
          </form>
        </>
      )}

      {error && <div style={errorBox}>{error}</div>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <label style={{ display: "block", fontSize: 13, color: "#555", marginBottom: 4 }}>
        {label}
      </label>
      {children}
    </>
  );
}

const card: React.CSSProperties = {
  maxWidth: 360,
  margin: "80px auto",
  padding: 24,
  fontFamily: "system-ui, -apple-system, sans-serif",
  border: "1px solid #e2e2e2",
  borderRadius: 12,
  background: "white",
};
const hint: React.CSSProperties = { color: "#666", fontSize: 14 };
const input: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  marginBottom: 12,
  borderRadius: 8,
  border: "1px solid #ccc",
  boxSizing: "border-box",
};
function button(busy: boolean): React.CSSProperties {
  return {
    width: "100%",
    padding: "10px 16px",
    borderRadius: 8,
    border: "none",
    background: busy ? "#9ca3af" : "#2563eb",
    color: "white",
    fontWeight: 600,
    cursor: busy ? "default" : "pointer",
    marginTop: 4,
  };
}
const errorBox: React.CSSProperties = {
  marginTop: 14,
  background: "#fef2f2",
  border: "1px solid #fecaca",
  color: "#991b1b",
  padding: "8px 12px",
  borderRadius: 8,
  fontSize: 13,
};
