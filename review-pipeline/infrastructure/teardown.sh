#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Tear down everything the deploy created, in a safe order.
#
# The stack owns almost all resources (buckets, Lambda, API Gateway, Cognito,
# CloudFront). S3 buckets cannot be deleted while non-empty, so this script:
#   1. Lists the stack's resources (for visibility / tracking).
#   2. Empties the stack-owned S3 buckets (input, output, GUI).
#   3. Deletes the CloudFormation stack and waits for completion.
#   4. Empties and deletes the code bucket (created outside the stack).
#   5. Removes any legacy local .secrets/ dir (current deploys store nothing;
#      Cognito emails the temporary password).
#
# This is destructive and irreversible. It requires confirmation unless FORCE=1.
#
# Usage:
#   REGION=us-east-1 bash infrastructure/teardown.sh
#   FORCE=1 REGION=us-east-1 bash infrastructure/teardown.sh   # no prompt
#
# Optional overrides (must match what you deployed with):
#   PROJECT_NAME (default: review-pipeline)
#   STACK_NAME   (default: review-pipeline)
#   CODE_BUCKET  (default: review-pipeline-code-<account-id>)
#   REGION       (default: your AWS CLI default region)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_NAME="${PROJECT_NAME:-review-pipeline}"
STACK_NAME="${STACK_NAME:-review-pipeline}"

REGION_ARG=()
if [[ -n "${REGION:-}" ]]; then
  REGION_ARG=(--region "${REGION}")
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text "${REGION_ARG[@]}")"
CODE_BUCKET="${CODE_BUCKET:-${PROJECT_NAME}-code-${ACCOUNT_ID}}"

echo "Account:     ${ACCOUNT_ID}"
echo "Stack:       ${STACK_NAME}"
echo "Code bucket: ${CODE_BUCKET}"
echo

# --------------------------------------------------------------------------- #
# 1. Show what the stack contains (resource tracking)
# --------------------------------------------------------------------------- #
if aws cloudformation describe-stacks --stack-name "${STACK_NAME}" "${REGION_ARG[@]}" >/dev/null 2>&1; then
  echo "Resources currently in the stack:"
  aws cloudformation list-stack-resources \
    --stack-name "${STACK_NAME}" \
    --query "StackResourceSummaries[].[ResourceType,PhysicalResourceId]" \
    --output table \
    "${REGION_ARG[@]}" || true
else
  echo "Stack '${STACK_NAME}' not found — will still try to clean the code bucket and local secret."
fi

echo
if [[ "${FORCE:-0}" != "1" ]]; then
  read -r -p "Delete all of the above and the code bucket? Type 'yes' to proceed: " CONFIRM
  if [[ "${CONFIRM}" != "yes" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

# --------------------------------------------------------------------------- #
# 2. Empty stack-owned S3 buckets so the stack can delete them
# --------------------------------------------------------------------------- #
empty_bucket() {
  local bucket="$1"
  if aws s3api head-bucket --bucket "${bucket}" "${REGION_ARG[@]}" 2>/dev/null; then
    echo "Emptying s3://${bucket} ..."
    aws s3 rm "s3://${bucket}" --recursive "${REGION_ARG[@]}" >/dev/null 2>&1 || true
  fi
}

INPUT_BUCKET="${PROJECT_NAME}-input-${ACCOUNT_ID}"
OUTPUT_BUCKET="${PROJECT_NAME}-output-${ACCOUNT_ID}"
GUI_BUCKET="${PROJECT_NAME}-gui-${ACCOUNT_ID}"

empty_bucket "${INPUT_BUCKET}"
empty_bucket "${OUTPUT_BUCKET}"
empty_bucket "${GUI_BUCKET}"

# --------------------------------------------------------------------------- #
# 3. Delete the stack (CloudFront can take several minutes)
# --------------------------------------------------------------------------- #
if aws cloudformation describe-stacks --stack-name "${STACK_NAME}" "${REGION_ARG[@]}" >/dev/null 2>&1; then
  echo "Deleting stack '${STACK_NAME}' (this can take several minutes for CloudFront) ..."
  aws cloudformation delete-stack --stack-name "${STACK_NAME}" "${REGION_ARG[@]}"
  aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" "${REGION_ARG[@]}" || {
    echo "WARNING: stack delete did not complete cleanly. Check the CloudFormation console."
  }
  echo "Stack deleted."
fi

# --------------------------------------------------------------------------- #
# 4. Empty and delete the code bucket (created outside the stack)
# --------------------------------------------------------------------------- #
if aws s3api head-bucket --bucket "${CODE_BUCKET}" "${REGION_ARG[@]}" 2>/dev/null; then
  echo "Emptying and deleting code bucket s3://${CODE_BUCKET} ..."
  aws s3 rm "s3://${CODE_BUCKET}" --recursive "${REGION_ARG[@]}" >/dev/null 2>&1 || true
  aws s3api delete-bucket --bucket "${CODE_BUCKET}" "${REGION_ARG[@]}" || true
fi

# --------------------------------------------------------------------------- #
# 5. Remove the local generated secret
# --------------------------------------------------------------------------- #
# Current deploys store no secret (Cognito emails the temp password), but older
# deploys may have left a .secrets/ dir — clean it up if present.
if [[ -d "${ROOT}/.secrets" ]]; then
  rm -rf "${ROOT}/.secrets"
  echo "Removed local .secrets/ (legacy)."
fi

echo
echo "Teardown complete."
