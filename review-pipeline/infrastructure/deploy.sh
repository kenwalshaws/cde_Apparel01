#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Deploy the review pipeline to AWS.
#
# What this does, in order:
#   1. Package the Python pipeline into a Lambda zip.
#   2. Ensure the code bucket exists (create it if missing).
#   3. Upload the zip to the code bucket.
#   4. Deploy the CloudFormation stack.
#   5. Print the stack outputs AND ready-to-paste exports for the local
#      control plane (the values the GUI needs).
#
# Prerequisites (your environment):
#   - AWS credentials configured (env vars, profile, or SSO)
#   - Bedrock model access enabled for the chosen model in your region
#     (Console -> Bedrock -> Model access). Without it, the "process" step
#     fails at the Bedrock call.
#
# Usage:
#   bash infrastructure/deploy.sh
#   CODE_BUCKET=my-artifacts-bucket bash infrastructure/deploy.sh
#
# Optional overrides:
#   CODE_BUCKET  (default: review-pipeline-code-<account-id>) — bucket that
#                holds the Lambda zip. Auto-created if it does not exist.
#   PROJECT_NAME (default: review-pipeline)
#   STACK_NAME   (default: review-pipeline)
#   REGION       (default: your AWS CLI default region)
#   BEDROCK_MODEL_ID (default: anthropic.claude-3-haiku-20240307-v1:0)
#   ENABLE_S3_TRIGGER (default: false) — set to true to let uploads to the
#     input bucket's sample/ prefix auto-trigger the pipeline. Keep false
#     while testing through the GUI; flip to true once that flow is proven.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_NAME="${PROJECT_NAME:-review-pipeline}"
STACK_NAME="${STACK_NAME:-review-pipeline}"
BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-anthropic.claude-3-haiku-20240307-v1:0}"
ENABLE_S3_TRIGGER="${ENABLE_S3_TRIGGER:-false}"
CODE_KEY="lambda/pipeline.zip"

REGION_ARG=()
if [[ -n "${REGION:-}" ]]; then
  REGION_ARG=(--region "${REGION}")
fi

# Resolve the active account and region so defaults work in any account.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text "${REGION_ARG[@]}")"
EFFECTIVE_REGION="${REGION:-$(aws configure get region || true)}"
EFFECTIVE_REGION="${EFFECTIVE_REGION:-us-east-1}"

# Default the code bucket to an account-scoped name so a fresh account just works.
CODE_BUCKET="${CODE_BUCKET:-${PROJECT_NAME}-code-${ACCOUNT_ID}}"

echo "Account:        ${ACCOUNT_ID}"
echo "Region:         ${EFFECTIVE_REGION}"
echo "Code bucket:    ${CODE_BUCKET}"
echo "Stack:          ${STACK_NAME}"
echo "S3 trigger:     ${ENABLE_S3_TRIGGER}"
echo

echo "1/4  Packaging Lambda..."
bash "${ROOT}/infrastructure/package_lambda.sh"

echo "2/4  Ensuring code bucket exists: ${CODE_BUCKET}"
if aws s3api head-bucket --bucket "${CODE_BUCKET}" "${REGION_ARG[@]}" 2>/dev/null; then
  echo "     Bucket already exists."
else
  echo "     Bucket not found — creating it."
  # us-east-1 must NOT get a LocationConstraint; every other region requires one.
  if [[ "${EFFECTIVE_REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${CODE_BUCKET}" "${REGION_ARG[@]}"
  else
    aws s3api create-bucket \
      --bucket "${CODE_BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${EFFECTIVE_REGION}" \
      "${REGION_ARG[@]}"
  fi
  # Private + encrypted by default; this bucket only holds the deployment zip.
  aws s3api put-public-access-block \
    --bucket "${CODE_BUCKET}" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,BlockPublicPolicy=true,IgnorePublicAcls=true,RestrictPublicBuckets=true" \
    "${REGION_ARG[@]}"
fi

echo "3/4  Uploading code to s3://${CODE_BUCKET}/${CODE_KEY} ..."
aws s3 cp "${ROOT}/build/pipeline.zip" "s3://${CODE_BUCKET}/${CODE_KEY}" "${REGION_ARG[@]}"

echo "4/4  Deploying CloudFormation stack '${STACK_NAME}' ..."
aws cloudformation deploy \
  --template-file "${ROOT}/infrastructure/template.json" \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="${PROJECT_NAME}" \
    LambdaCodeS3Bucket="${CODE_BUCKET}" \
    LambdaCodeS3Key="${CODE_KEY}" \
    BedrockModelId="${BEDROCK_MODEL_ID}" \
    EnableS3Trigger="${ENABLE_S3_TRIGGER}" \
  "${REGION_ARG[@]}"

# Pull the outputs the GUI control plane needs straight from the stack.
get_output() {
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text \
    "${REGION_ARG[@]}"
}

FUNCTION_NAME="$(get_output FunctionName)"
OUTPUT_BUCKET="$(get_output OutputBucketName)"
INPUT_BUCKET="$(get_output InputBucketName)"

echo
echo "Done. Stack outputs:"
aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs" \
  --output table \
  "${REGION_ARG[@]}"

echo
echo "=============================================================="
echo " Start the local control plane for the GUI with these values:"
echo "=============================================================="
echo
echo "  cd pipeline"
echo "  PIPELINE_FUNCTION=${FUNCTION_NAME} \\"
echo "  OUTPUT_BUCKET=${OUTPUT_BUCKET} \\"
echo "  AWS_REGION=${EFFECTIVE_REGION} \\"
echo "  ../.venv/bin/uvicorn src.api.local_app:app --port 8000"
echo
echo "Then start the GUI (in another terminal):"
echo "  cd gui && npm install && npm run dev     # http://localhost:5173"
echo
echo "In the GUI: 1) Generate  2) Process  3) View / Refresh"
echo "(Input bucket: ${INPUT_BUCKET})"
echo
if [[ "${ENABLE_S3_TRIGGER}" != "true" ]]; then
  echo "Note: the S3 auto-trigger is OFF. Processing is driven from the GUI."
  echo "To enable it later: ENABLE_S3_TRIGGER=true bash infrastructure/deploy.sh"
fi
