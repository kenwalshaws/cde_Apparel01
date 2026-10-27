#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Deploy the review pipeline to AWS.
#
# What this does, in order:
#   1. Package the Python pipeline into a Lambda zip (content-hashed key).
#   2. Ensure the code bucket exists (create it if missing) and upload the zip.
#   3. Deploy the CloudFormation stack (S3, Lambda, API Gateway, Cognito,
#      CloudFront, IAM).
#   4. Seed config.json to the input bucket.
#   5. Invite the Cognito login user — Cognito generates and EMAILS a one-time
#      temporary password to the user's email.
#   6. Build the GUI (API + auth baked in), sync it to the GUI bucket, and
#      invalidate CloudFront.
#   7. Print the stack outputs and the CloudFront GUI URL.
#
# Prerequisites (your environment):
#   - AWS credentials configured (env vars, profile, or SSO)
#   - Bedrock model access enabled for the chosen model in your region
#     (Console -> Bedrock -> Model access). Without it, the "process" step
#     fails at the Bedrock call.
#
# Usage:
#   bash infrastructure/deploy.sh [GUI_USER_EMAIL]
#   bash infrastructure/deploy.sh someone@example.com
#   CODE_BUCKET=my-artifacts-bucket bash infrastructure/deploy.sh
#
# Optional overrides:
#   CODE_BUCKET  (default: review-pipeline-code-<account-id>) — bucket that
#                holds the Lambda zip. Auto-created if it does not exist.
#   PROJECT_NAME (default: review-pipeline)
#   STACK_NAME   (default: review-pipeline)
#   REGION       (default: your AWS CLI default region)
#   BEDROCK_MODEL_IDS (default: the "models" list in infrastructure/config.json,
#     default model first) — comma-separated Bedrock inference profile IDs the
#     Lambda role may invoke. config.json stays the single source of truth; the
#     first id is also the fallback model if config.json is absent at runtime.
#   ENABLE_S3_TRIGGER (default: false) — set to true to let uploads to the
#     input bucket's sample/ prefix auto-trigger the pipeline. Keep false
#     while testing through the GUI; flip to true once that flow is proven.
#   API_AUTH (default: COGNITO) — API Gateway auth mode. COGNITO: user/password
#     login via Cognito (GUI served from CloudFront). API_KEY: x-api-key header.
#     NONE: open endpoint (plumbing/PoC only).
#   GUI_USER_EMAIL (default: kenwalsh+cdejump@amazon.com) — the Cognito login
#     user. Can also be passed as the first positional argument. Cognito emails
#     a one-time temporary password to this address; the user sets their own
#     permanent password on first sign-in. Nothing is stored locally.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_NAME="${PROJECT_NAME:-review-pipeline}"
STACK_NAME="${STACK_NAME:-review-pipeline}"

# Allowed Bedrock models: derived from config.json so the model list lives in
# one place (the default model is listed first).
if [[ -z "${BEDROCK_MODEL_IDS:-}" ]]; then
  BEDROCK_MODEL_IDS="$(python3 - "${ROOT}/infrastructure/config.json" <<'PYEOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
ids = [m["id"] for m in cfg["models"]]
default = cfg.get("default_model")
if default in ids:
    ids.remove(default)
    ids.insert(0, default)
print(",".join(ids))
PYEOF
)"
fi
echo "Bedrock models: ${BEDROCK_MODEL_IDS}"
ENABLE_S3_TRIGGER="${ENABLE_S3_TRIGGER:-false}"
API_AUTH="${API_AUTH:-COGNITO}"
# GUI login user email: first positional arg wins, else GUI_USER_EMAIL env,
# else the default. Cognito emails a temporary password to this address.
GUI_USER_EMAIL="${1:-${GUI_USER_EMAIL:-kenwalsh+cdejump@amazon.com}}"
# CODE_KEY is set after packaging, using a content hash so the S3 key changes
# whenever the code changes. A changing key makes CloudFormation redeploy the
# Lambda every time the code changes (a fixed key can leave stale code).
CODE_KEY=""

REGION_ARG=()
if [[ -n "${REGION:-}" ]]; then
  REGION_ARG=(--region "${REGION}")
fi

# Resolve the active account and region so defaults work in any account.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text ${REGION_ARG[@]+"${REGION_ARG[@]}"})"
EFFECTIVE_REGION="${REGION:-$(aws configure get region || true)}"
EFFECTIVE_REGION="${EFFECTIVE_REGION:-us-east-1}"

# Default the code bucket to an account-scoped name so a fresh account just works.
CODE_BUCKET="${CODE_BUCKET:-${PROJECT_NAME}-code-${ACCOUNT_ID}}"

echo "Account:        ${ACCOUNT_ID}"
echo "Region:         ${EFFECTIVE_REGION}"
echo "Code bucket:    ${CODE_BUCKET}"
echo "Stack:          ${STACK_NAME}"
echo "API auth:       ${API_AUTH}"
echo "S3 trigger:     ${ENABLE_S3_TRIGGER}"
echo

echo "1/4  Packaging Lambda..."
bash "${ROOT}/infrastructure/package_lambda.sh"

# Content-hashed key so the Lambda Code property changes whenever the code
# changes, forcing CloudFormation to redeploy the function (a fixed key can
# leave stale code running).
CODE_HASH="$(shasum -a 256 "${ROOT}/build/pipeline.zip" | cut -c1-12)"
CODE_KEY="lambda/pipeline-${CODE_HASH}.zip"

echo "2/4  Ensuring code bucket exists: ${CODE_BUCKET}"
if aws s3api head-bucket --bucket "${CODE_BUCKET}" ${REGION_ARG[@]+"${REGION_ARG[@]}"} 2>/dev/null; then
  echo "     Bucket already exists."
else
  echo "     Bucket not found — creating it."
  # us-east-1 must NOT get a LocationConstraint; every other region requires one.
  if [[ "${EFFECTIVE_REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${CODE_BUCKET}" ${REGION_ARG[@]+"${REGION_ARG[@]}"}
  else
    aws s3api create-bucket \
      --bucket "${CODE_BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${EFFECTIVE_REGION}" \
      ${REGION_ARG[@]+"${REGION_ARG[@]}"}
  fi
  # Private + encrypted by default; this bucket only holds the deployment zip.
  aws s3api put-public-access-block \
    --bucket "${CODE_BUCKET}" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,BlockPublicPolicy=true,IgnorePublicAcls=true,RestrictPublicBuckets=true" \
    ${REGION_ARG[@]+"${REGION_ARG[@]}"}
fi

echo "3/4  Uploading code to s3://${CODE_BUCKET}/${CODE_KEY} ..."
aws s3 cp "${ROOT}/build/pipeline.zip" "s3://${CODE_BUCKET}/${CODE_KEY}" ${REGION_ARG[@]+"${REGION_ARG[@]}"}

echo "4/4  Deploying CloudFormation stack '${STACK_NAME}' ..."
aws cloudformation deploy \
  --template-file "${ROOT}/infrastructure/template.json" \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    ProjectName="${PROJECT_NAME}" \
    LambdaCodeS3Bucket="${CODE_BUCKET}" \
    LambdaCodeS3Key="${CODE_KEY}" \
    BedrockModelIds="${BEDROCK_MODEL_IDS}" \
    EnableS3Trigger="${ENABLE_S3_TRIGGER}" \
    ApiAuth="${API_AUTH}" \
  ${REGION_ARG[@]+"${REGION_ARG[@]}"}

# Pull the outputs straight from the stack.
get_output() {
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text \
    ${REGION_ARG[@]+"${REGION_ARG[@]}"}
}

INPUT_BUCKET="$(get_output InputBucketName)"
API_BASE_URL="$(get_output ApiBaseUrl)"
GUI_BUCKET="$(get_output GuiBucketName)"
GUI_URL="$(get_output GuiUrl)"
USER_POOL_ID="$(get_output UserPoolId)"
USER_POOL_CLIENT_ID="$(get_output UserPoolClientId)"

# Seed the runtime model config into the input bucket (idempotent: overwrites).
echo
echo "Seeding model config to s3://${INPUT_BUCKET}/config.json ..."
aws s3 cp "${ROOT}/infrastructure/config.json" "s3://${INPUT_BUCKET}/config.json" ${REGION_ARG[@]+"${REGION_ARG[@]}"}

# --------------------------------------------------------------------------- #
# Cognito user (COGNITO auth only)
# --------------------------------------------------------------------------- #
# Security model: Cognito GENERATES a temporary password and EMAILS it to the
# user (via the pool's invite message template). We never set, see, or store
# the password. On first sign-in the user is required to set their own
# permanent password (NEW_PASSWORD_REQUIRED, handled by the GUI).
if [[ "${API_AUTH}" == "COGNITO" ]]; then
  echo
  echo "Inviting Cognito user ${GUI_USER_EMAIL} (Cognito emails a temporary password)…"
  # admin-create-user without --temporary-password: Cognito generates one and,
  # because the pool has an invite template and SUPPRESS is NOT set, emails it.
  # Capture stderr so a real failure (access denied, bad email, wrong pool) is
  # shown instead of being mistaken for "user already exists".
  if CREATE_ERR="$(aws cognito-idp admin-create-user \
        --user-pool-id "${USER_POOL_ID}" \
        --username "${GUI_USER_EMAIL}" \
        --user-attributes Name=email,Value="${GUI_USER_EMAIL}" Name=email_verified,Value=true \
        ${REGION_ARG[@]+"${REGION_ARG[@]}"} 2>&1 >/dev/null)"; then
    echo "  Invite email sent to ${GUI_USER_EMAIL}."
  elif [[ "${CREATE_ERR}" == *UsernameExistsException* ]]; then
    # User already exists (re-deploy): re-send the invite so a fresh temporary
    # password is emailed. RESEND only works while the user is still in
    # FORCE_CHANGE_PASSWORD state (i.e. has not yet set a permanent password).
    echo "  User already exists — resending the invite email."
    if ! RESEND_ERR="$(aws cognito-idp admin-create-user \
          --user-pool-id "${USER_POOL_ID}" \
          --username "${GUI_USER_EMAIL}" \
          --message-action RESEND \
          ${REGION_ARG[@]+"${REGION_ARG[@]}"} 2>&1 >/dev/null)"; then
      echo "  NOTE: could not resend an invite: ${RESEND_ERR}"
      echo "        If this user already set a permanent password, sign in with it"
      echo "        (or use 'Forgot password'). To force a new invite, delete the"
      echo "        user and re-run deploy."
    fi
  else
    echo "ERROR: could not create the Cognito user ${GUI_USER_EMAIL}:" >&2
    echo "  ${CREATE_ERR}" >&2
    exit 1
  fi
fi

# --------------------------------------------------------------------------- #
# Build and publish the GUI to the CloudFront-backed bucket
# --------------------------------------------------------------------------- #
echo
echo "Building the GUI (API + auth baked in) ..."
GUI_ENV="${ROOT}/gui/.env.production.local"
{
  echo "VITE_API_BASE=${API_BASE_URL}"
  if [[ "${API_AUTH}" == "COGNITO" ]]; then
    echo "VITE_COGNITO_CLIENT_ID=${USER_POOL_CLIENT_ID}"
    echo "VITE_COGNITO_REGION=${EFFECTIVE_REGION}"
  fi
} > "${GUI_ENV}"

( cd "${ROOT}/gui" && npm install --silent && npm run build )

echo "Publishing the GUI to s3://${GUI_BUCKET} ..."
aws s3 sync "${ROOT}/gui/dist/" "s3://${GUI_BUCKET}/" --delete ${REGION_ARG[@]+"${REGION_ARG[@]}"}

# Invalidate CloudFront so the new build is served immediately. A failure here
# is not fatal (the deploy itself succeeded) but is always reported, with the
# manual command, so a stale GUI is never a silent surprise.
if ! DIST_ID="$(aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='${PROJECT_NAME} GUI'].Id | [0]" \
      --output text 2>&1)"; then
  echo "WARNING: could not look up the CloudFront distribution: ${DIST_ID}" >&2
  echo "         Invalidate manually: aws cloudfront create-invalidation --distribution-id <id> --paths '/*'" >&2
elif [[ -z "${DIST_ID}" || "${DIST_ID}" == "None" ]]; then
  echo "WARNING: no CloudFront distribution with comment '${PROJECT_NAME} GUI' was found;" >&2
  echo "         the GUI cache was not invalidated." >&2
elif ! INVALIDATE_ERR="$(aws cloudfront create-invalidation \
      --distribution-id "${DIST_ID}" --paths "/*" 2>&1 >/dev/null)"; then
  echo "WARNING: CloudFront invalidation for ${DIST_ID} failed: ${INVALIDATE_ERR}" >&2
  echo "         Invalidate manually: aws cloudfront create-invalidation --distribution-id ${DIST_ID} --paths '/*'" >&2
else
  echo "CloudFront invalidation requested for ${DIST_ID}."
fi
echo
echo "Done. Stack outputs:"
aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs" \
  --output table \
  ${REGION_ARG[@]+"${REGION_ARG[@]}"}

echo
echo "=============================================================="
echo " GUI (default: served from CloudFront)"
echo "=============================================================="
echo
echo "  Open: ${GUI_URL}"
if [[ "${API_AUTH}" == "COGNITO" ]]; then
  echo "  Sign in as: ${GUI_USER_EMAIL}"
  echo "  Temporary password: sent by email from Amazon Cognito (check inbox/spam)."
  echo "  (One-time only — you'll set your own password on first sign-in.)"
fi
echo "  (CloudFront can take several minutes to finish its first deploy.)"
echo
echo "API base URL: ${API_BASE_URL}"
echo "Model config: s3://${INPUT_BUCKET}/config.json  (edit to switch models, no redeploy)"
echo
echo "--------------------------------------------------------------"
echo " Optional: run the GUI locally against the same API"
echo "--------------------------------------------------------------"
echo "  cd gui"
echo "  cp .env.production.local .env.local   # reuse the baked API + auth config"
echo "  npm run dev                            # http://localhost:5173"
echo
if [[ "${ENABLE_S3_TRIGGER}" != "true" ]]; then
  echo "S3 auto-trigger: OFF. Processing is driven from the GUI/API."
fi
