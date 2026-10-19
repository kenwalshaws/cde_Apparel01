// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
// Minimal Cognito auth via the InitiateAuth / RespondToAuthChallenge REST APIs
// (USER_PASSWORD_AUTH). Avoids pulling in the full Cognito SDK.
//
// Supports the first-login flow: a user created with a temporary password is
// in FORCE_CHANGE_PASSWORD state, so the first sign-in returns a
// NEW_PASSWORD_REQUIRED challenge; the GUI collects a new password and
// completes it. No permanent password is ever set by the deploy.
//
// Active only when built with Cognito config (VITE_COGNITO_CLIENT_ID,
// VITE_COGNITO_REGION); otherwise authEnabled() is false and the app runs open.

const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
const REGION = (import.meta.env.VITE_COGNITO_REGION as string | undefined) ?? "us-east-1";

const TOKEN_KEY = "review_pipeline_id_token";
const ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;

export function authEnabled(): boolean {
  return Boolean(CLIENT_ID);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

interface CognitoResponse {
  AuthenticationResult?: { IdToken: string; AccessToken: string; RefreshToken?: string };
  ChallengeName?: string;
  Session?: string;
  ChallengeParameters?: Record<string, string>;
  message?: string;
  __type?: string;
}

async function cognito(target: string, body: unknown): Promise<CognitoResponse> {
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  });
  const data = (await res.json()) as CognitoResponse;
  if (!res.ok) {
    throw new Error(data.message || data.__type || `request failed (${res.status})`);
  }
  return data;
}

function storeToken(data: CognitoResponse): string {
  const token = data.AuthenticationResult?.IdToken;
  if (!token) throw new Error("Sign-in succeeded but no token was returned.");
  localStorage.setItem(TOKEN_KEY, token);
  return token;
}

// Result of a sign-in attempt: either signed in (token stored) or a new
// password is required (caller must call completeNewPassword with the session).
export type SignInResult =
  | { status: "ok" }
  | { status: "new_password_required"; email: string; session: string };

export async function signIn(email: string, password: string): Promise<SignInResult> {
  if (!CLIENT_ID) throw new Error("Cognito client id is not configured for this build.");

  const data = await cognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: CLIENT_ID,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });

  if (data.ChallengeName === "NEW_PASSWORD_REQUIRED") {
    if (!data.Session) throw new Error("No session returned for the password-reset challenge.");
    return { status: "new_password_required", email, session: data.Session };
  }
  if (data.ChallengeName) {
    throw new Error(`Unsupported sign-in challenge: ${data.ChallengeName}`);
  }
  storeToken(data);
  return { status: "ok" };
}

// Complete the first-login NEW_PASSWORD_REQUIRED challenge with the user's
// chosen permanent password. On success the ID token is stored.
export async function completeNewPassword(
  email: string,
  newPassword: string,
  session: string
): Promise<void> {
  if (!CLIENT_ID) throw new Error("Cognito client id is not configured for this build.");

  const data = await cognito("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    ClientId: CLIENT_ID,
    Session: session,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: newPassword },
  });
  storeToken(data);
}
