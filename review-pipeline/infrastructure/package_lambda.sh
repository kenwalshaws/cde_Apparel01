#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Package the Python pipeline into a Lambda deployment zip.
#
# boto3 ships in the Lambda Python runtime, so we do NOT bundle it (keeps the
# zip small). Only the `src/` package is included. FastAPI/uvicorn are local-
# only dev deps and are intentionally excluded.
#
# Output: build/pipeline.zip
#
# Run from the review-pipeline root:
#   bash infrastructure/package_lambda.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT}/build"
ZIP_PATH="${BUILD_DIR}/pipeline.zip"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# The handler is referenced as `src.api.lambda_handler.handler`, so the zip
# root must contain the `src/` package directory.
cd "${ROOT}/pipeline"
zip -r -q "${ZIP_PATH}" src \
  -x "*/__pycache__/*" "*.pyc"

echo "Built ${ZIP_PATH}"
unzip -l "${ZIP_PATH}" | tail -n 1
