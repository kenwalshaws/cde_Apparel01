// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
/// <reference types="vite/client" />

interface ImportMetaEnv {
  // API Gateway base URL. When set, the GUI calls AWS directly; when unset,
  // it uses the local control-plane proxy at /api.
  readonly VITE_API_BASE?: string;
  // Optional API key sent as x-api-key (used when API_KEY auth is enabled).
  readonly VITE_API_KEY?: string;
  // Cognito config (used when COGNITO auth is enabled). When VITE_COGNITO_CLIENT_ID
  // is set, the GUI shows a login screen and sends the JWT as Authorization.
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_COGNITO_REGION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
