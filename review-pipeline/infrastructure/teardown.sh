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

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text ${REGION_ARG[@]+"${REGION_ARG[@]}"})"
CODE_BUCKET="${CODE_BUCKET:-${PROJECT_NAME}-code-${ACCOUNT_ID}}"

echo "Account:     ${ACCOUNT_ID}"
echo "Stack:       ${STACK_NAME}"
echo "Code bucket: ${CODE_BUCKET}"
echo

# --------------------------------------------------------------------------- #
# Helpers: tell "does not exist" apart from every other failure. Only a clear
# "not found" is treated as nothing-to-do; anything else (AccessDenied,
# throttling, expired credentials) is recorded in FAILURES and reported at the
# end, so the final message and exit code reflect what actually happened.
# --------------------------------------------------------------------------- #
FAILURES=()

# Sets BUCKET_STATE to exists | missing | error (with the CLI message in STATE_ERR).
check_bucket() {
  STATE_ERR=""
  if STATE_ERR="$(aws s3api head-bucket --bucket "$1" ${REGION_ARG[@]+"${REGION_ARG[@]}"} 2>&1)"; then
    BUCKET_STATE="exists"
  elif [[ "${STATE_ERR}" == *"Not Found"* || "${STATE_ERR}" == *"404"* || "${STATE_ERR}" == *"NoSuchBucket"* ]]; then
    BUCKET_STATE="missing"
  else
    BUCKET_STATE="error"
  fi
}

# Sets STACK_STATE to exists | missing | error (with the CLI message in STATE_ERR).
check_stack() {
  STATE_ERR=""
  if STATE_ERR="$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" ${REGION_ARG[@]+"${REGION_ARG[@]}"} 2>&1 >/dev/null)"; then
    STACK_STATE="exists"
  elif [[ "${STATE_ERR}" == *"does not exist"* ]]; then
    STACK_STATE="missing"
  else
    STACK_STATE="error"
  fi
}

record_failure() {
  echo "WARNING: $1" >&2
  FAILURES+=("$1")
}

# --------------------------------------------------------------------------- #
# 1. Show what the stack contains (resource tracking)
# --------------------------------------------------------------------------- #
check_stack
if [[ "${STACK_STATE}" == "exists" ]]; then
  echo "Resources currently in the stack:"
  # The listing is informational; failing to print it must not stop teardown.
  if ! aws cloudformation list-stack-resources \
      --stack-name "${STACK_NAME}" \
      --query "StackResourceSummaries[].[ResourceType,PhysicalResourceId]" \
      --output table \
      ${REGION_ARG[@]+"${REGION_ARG[@]}"}; then
    echo "  (could not list the stack resources; continuing)"
  fi
elif [[ "${STACK_STATE}" == "missing" ]]; then
  echo "Stack '${STACK_NAME}' not found — will still try to clean the code bucket and local secret."
else
  record_failure "could not check stack '${STACK_NAME}': ${STATE_ERR}"
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
  check_bucket "${bucket}"
  case "${BUCKET_STATE}" in
    exists)
      echo "Emptying s3://${bucket} ..."
      if ! aws s3 rm "s3://${bucket}" --recursive ${REGION_ARG[@]+"${REGION_ARG[@]}"} >/dev/null; then
        record_failure "could not empty s3://${bucket}"
      fi
      ;;
    missing) ;;  # already gone: nothing to empty
    *) record_failure "could not check s3://${bucket}: ${STATE_ERR}" ;;
  esac
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
check_stack
if [[ "${STACK_STATE}" == "error" ]]; then
  record_failure "could not check stack '${STACK_NAME}' before deleting it: ${STATE_ERR}"
elif [[ "${STACK_STATE}" == "exists" ]]; then
  echo "Deleting stack '${STACK_NAME}' (this can take several minutes for CloudFront) ..."
  aws cloudformation delete-stack --stack-name "${STACK_NAME}" ${REGION_ARG[@]+"${REGION_ARG[@]}"}
  if aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" ${REGION_ARG[@]+"${REGION_ARG[@]}"}; then
    echo "Stack deleted."
  else
    record_failure "stack '${STACK_NAME}' did not delete cleanly; check the CloudFormation console"
  fi
fi

# --------------------------------------------------------------------------- #
# 4. Empty and delete the code bucket (created outside the stack)
# --------------------------------------------------------------------------- #
check_bucket "${CODE_BUCKET}"
case "${BUCKET_STATE}" in
  exists)
    echo "Emptying and deleting code bucket s3://${CODE_BUCKET} ..."
    if ! aws s3 rm "s3://${CODE_BUCKET}" --recursive ${REGION_ARG[@]+"${REGION_ARG[@]}"} >/dev/null; then
      record_failure "could not empty s3://${CODE_BUCKET}"
    elif ! aws s3api delete-bucket --bucket "${CODE_BUCKET}" ${REGION_ARG[@]+"${REGION_ARG[@]}"}; then
      record_failure "could not delete s3://${CODE_BUCKET}"
    fi
    ;;
  missing) ;;  # already gone: nothing to delete
  *) record_failure "could not check s3://${CODE_BUCKET}: ${STATE_ERR}" ;;
esac

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
if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo "Teardown finished WITH PROBLEMS:" >&2
  for f in "${FAILURES[@]}"; do echo "  - ${f}" >&2; done
  echo "Fix the cause (permissions, CloudFormation console) and re-run teardown." >&2
  exit 1
fi
echo "Teardown complete."
