<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
This documentation is licensed under CC BY 4.0:
https://creativecommons.org/licenses/by/4.0/
-->

# AGENTS.md

Instructions for AI coding agents (and a quick orientation for humans) working
in `review-pipeline/`. Read `README.md` for the full picture and
`docs/decisions.md` for why things are the way they are.

## What this is

A proof of concept that takes English apparel reviews, summarizes each once
with Amazon Bedrock, translates the summary to German and French with Amazon
Translate, scores quality, and shows results in a Cognito-protected React GUI
on CloudFront. Synthetic data only. Not hardened for live traffic.

## Layout

| Path | Role |
|---|---|
| `pipeline/src/model` | Data classes (`Review`, `PipelineResult`) |
| `pipeline/src/client` | AWS wrappers (Bedrock, Translate, `JobStore` for S3). No pipeline logic |
| `pipeline/src/service` | `PipelineService`, `JobService`, scoring, synthetic data. No boto3 calls |
| `pipeline/src/api` | Lambda handler (thin adapter) and local FastAPI app |
| `pipeline/src/errors.py` | `UserFacingError`: only these messages may be returned to callers |
| `pipeline/src/config.py`, `factory.py` | Configuration and wiring |
| `gui/` | React + Vite + TypeScript |
| `infrastructure/` | CloudFormation `template.json`, `deploy.sh`, `teardown.sh`, `config.json` |

Dependencies point inward: api -> service -> client -> model. Do not import
upward. Keep business logic out of `api/`.

## Commands

```bash
# Python tests (no AWS needed)
cd pipeline && ../.venv/bin/pytest

# GUI typecheck and build
cd gui && npm run build

# Script and template syntax checks
bash -n infrastructure/deploy.sh infrastructure/teardown.sh infrastructure/package_lambda.sh
python3 -c "import json; json.load(open('infrastructure/template.json'))"
```

Run the tests after any change under `pipeline/`. Run the GUI build after any
change under `gui/`.

## Conventions

- Python 3.12, type hints, `from __future__ import annotations`.
- Every source file starts with the Amazon copyright and
  `SPDX-License-Identifier: Apache-2.0` header. Docs carry the CC BY 4.0 notice.
- Dependencies are pinned exactly. `pipeline/requirements.txt` is a generated
  lock; regenerate it from a clean venv, do not hand-edit. Direct pins live in
  `pipeline/pyproject.toml`. After changing dependencies run `pip check`.
- Use inclusive language (allowlist/denylist, primary/replica).
- Do not use the phrase "production path" in docs or comments.
- Tests use fake clients. A fake must mirror what the real AWS API returns
  (for example Translate reports the **source** language, not the target).

## Boundaries

- Never return raw exception text to API callers or write it to `status.json`;
  log it. Raise `UserFacingError` for messages that are safe to show.
- Never write secrets, passwords or tokens to disk or to the repo. Cognito
  emails the temporary password.
- Never commit `cde_back_ground_folder/` (it is gitignored), `.protoshield/`,
  `node_modules/`, `dist/` or `build/`.
- Do not run AWS, deploy, teardown or git push commands for the user. Show the
  commands; the user runs them.
- Do not widen IAM to `*` actions or resources without a written reason. The
  one known `*` is Translate (no resource-level permissions).
- Source reviews must be English and synthetic or de-identified (no PII).

## Runtime configuration

Target languages, the Bedrock model, labels and the debug flag live in
`infrastructure/config.json`, which the Lambda reads from the input bucket at
the start of each job. Do not hard-code languages in code or the GUI; the
built-in default (`de`, `fr`) in `pipeline/src/config.py` is only a fallback.
`deploy.sh` re-seeds this file on every deploy.

## Git workflow

Git Flow. Check `git branch --show-current` before branching, and never
commit directly to `main` or `develop`.

| Branch | Purpose | Branch from | Merges into |
|---|---|---|---|
| `main` | Released code only; every merge is tagged (`vX.Y.Z`) | — | — |
| `develop` | Integration of finished features | `main` | — |
| `feature/<name>` | One focused change | `develop` | `develop` |
| `release/<X.Y.Z>` | Release preparation (version bumps, final fixes) | `develop` | `main`, then back into `develop` |
| `hotfix/<X.Y.Z>` | Urgent fix to a release | `main` | `main`, then back into `develop` |

- Open a pull request for every merge and fill in the PR template.
- Merge with a merge commit (no squash), so feature and release history stays
  visible.
- After a release or hotfix merges to `main`, tag it on `main` and merge
  `main` back into `develop`.
