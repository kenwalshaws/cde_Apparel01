# Review Translate-and-Summarize Pipeline

A portable, self-contained proof of concept for AnyCompany Apparel. It takes
English product reviews, summarizes each into a tight 1–2 sentence overview
with Amazon Bedrock, and translates that summary into the target shopper
languages (**German** and **French**) with Amazon Translate — applying a
quality-scoring check at each step so low-quality output is filtered out.

Everything runs in AWS. The GUI is served from CloudFront and talks to an
API Gateway + Lambda backend; a user signs in via Amazon Cognito. Non-production,
synthetic (no-PII) data only.

Working on this code, or pointing a coding agent at it? Start with
[`AGENTS.md`](AGENTS.md) (commands, conventions, boundaries) and
[`docs/decisions.md`](docs/decisions.md) (why it is built this way).

---

## Architecture

![Architecture diagram](arc_draio.png)

> The diagram above is exported from `arc_draio.xml` (open it in
> [draw.io](https://app.diagrams.net), then export a PNG to `arc_draio.png`).
> The ASCII sketch below is the text fallback.

```
Browser GUI (CloudFront)                 sign in with Cognito (JWT)
      │  /generate · /process · /jobs · /job        (Authorization: JWT)
      ▼
Amazon API Gateway  ──(Cognito authorizer)──►  Lambda (pipeline)
      │                                            │
      │  generate ─► synthesize reviews ─────────► input bucket
      │  process  ─► create jobnum, snapshot input, async self-invoke,
      │              return jobnum immediately
      │                 └─ worker: read config.json (model, target languages)
      │                    summarize (Bedrock) → translate each target
      │                    (Amazon Translate) → score → write results
      ▼                                            ▼
   output bucket:  jobs/<jobnum>/inputs/samples.json
                   jobs/<jobnum>/results/results.json
                   jobs/<jobnum>/status.json
```

Per review the pipeline does:

1. **Summarize** the English review into 1–2 sentences (Amazon Bedrock).
2. **Translate** that summary into each target language (Amazon Translate;
   `target_languages` in `config.json`, default **de** and **fr**).
3. **Quality-score** the summary and each translation; a review is "surfaced"
   only if every step passes the threshold (default 0.7).

Each run is a **job** with a unique id (`job-YYYYMMDD-HHMMSS-<rand>`, UTC).
Processing is **asynchronous**: `process` returns the jobnum right away and the
work runs in a background Lambda invocation (up to the function's 10-minute
timeout), so large runs don't hit the API Gateway 29-second limit. The GUI
polls / auto-refreshes to show results when the job completes.

The browser never holds AWS credentials or calls AWS directly — it calls API
Gateway, authenticated with the Cognito JWT from login. On deploy, Cognito
emails the login user a one-time temporary password; the user sets their own
permanent password on first sign-in.

The S3 object-created trigger exists in the template but is **OFF by default**
(`EnableS3Trigger`); processing is driven from the GUI/API. The CloudFormation
template under `infrastructure/` is a handoff artifact the customer's team can
adapt — scaling and hardening are their own separate effort, out of scope for
this proof of concept.

---

## Layered structure

The pipeline follows a strict layered architecture (dependencies point inward):

```
review-pipeline/
├── pipeline/                         # Python — core pipeline
│   ├── src/
│   │   ├── model/                    # dataclasses: Review, StepResult, PipelineResult
│   │   ├── client/                   # thin AWS SDK wrappers (Translate, Bedrock, S3 job store)
│   │   ├── service/                  # pipeline + job orchestration, quality scoring, synthetic data
│   │   ├── api/                      # Lambda handler + optional local control plane
│   │   ├── config.py                 # static settings + config.json resolution
│   │   ├── errors.py                 # UserFacingError (messages safe to return to callers)
│   │   ├── factory.py                # wires clients and services together
│   │   └── debug.py                  # debug-logging toggle (from config.json)
│   ├── scripts/                      # generate_synthetic.py, run_local.py (offline aids)
│   ├── tests/                        # unit + integration (no AWS)
│   └── pyproject.toml
├── gui/                              # TypeScript (React + Vite) job browser
├── infrastructure/
│   ├── template.json                 # CloudFormation (full stack)
│   ├── config.json                   # runtime model + debug config (seeded to input bucket)
│   ├── deploy.sh                     # package + deploy + publish GUI
│   └── teardown.sh                   # delete everything
└── README.md
```

- **model** — plain data structures, no logic, no dependencies.
- **client** — one wrapper per AWS service (Translate, Bedrock) plus `JobStore`,
  the only code that reads and writes job data in S3. Knows nothing
  about the pipeline. The Bedrock client auto-detects Claude vs. Amazon Nova
  request/response shapes.
- **service** — `PipelineService` (summarize once, translate per target, score),
  `JobService` (create, run, list and read jobs through `JobStore`), quality
  scoring, and synthetic data generation. The only layer that knows the full
  flow; it makes no AWS calls itself.
- **api** — thin adapters. `lambda_handler.py` runs in AWS, normalizes the
  event, routes the actions (generate / process / _worker / jobs / job) to
  `JobService`, and wraps the response. `local_app.py` is an
  optional local control plane that proxies to the same Lambda (for running the
  GUI locally instead of from CloudFront).

### Runtime configuration (`config.json`)

The deploy seeds `infrastructure/config.json` to the input bucket. The Lambda
reads it on each run, so you can change behavior **without redeploying** by
editing it in S3:

- `default_model` — the Bedrock model/inference-profile id to use. Options are
  listed under `models` (Claude Haiku 5.5 US/global, Amazon Nova 2 Lite).
- `debug` — `true` (default) emits verbose debug logging to CloudWatch.
- `target_languages` — Amazon Translate codes to translate each summary into
  (default `["de", "fr"]`). See "Extending: more target languages".
- `language_labels` — optional display names for the GUI, e.g.
  `{"de": "German"}`.

> `deploy.sh` re-seeds this file from `infrastructure/config.json` on every
> run. Edits made directly in S3 take effect immediately but are overwritten
> by the next deploy, so make lasting edits in the repo file.

> Claude and Nova models on the `bedrock-runtime` endpoint require a geo/global
> **inference profile id** (e.g. `us.anthropic.claude-haiku-5-5`), not a bare
> model id. Ensure the chosen model's access is enabled in Bedrock.

---

## Prerequisites

- Python 3.12, Node 20.19+ or 22.12+ (required by Vite 7), npm, AWS CLI
- AWS credentials in your environment (env vars, profile, or SSO)
- **Bedrock model access enabled** for the summarization model
  (`us.anthropic.claude-haiku-5-5` by default) in your deploy region
- The AWS identity used for deploy needs permissions for CloudFormation, S3,
  Lambda, API Gateway, Cognito, CloudFront, IAM, Translate, and Bedrock

Set up the Python environment (installable package; no path hacks):

```bash
cd review-pipeline
python3 -m venv .venv
.venv/bin/pip install -e "pipeline/[dev,local]"
```

Extras: `dev` adds pytest; `local` adds FastAPI/uvicorn for the optional local
control plane. The Lambda zip bundles only `src/` and uses the boto3 already in
the Lambda runtime, so neither extra ships to AWS. `pipeline/requirements.txt`
is a pinned mirror for tools that expect it.

Make the scripts executable (or invoke them with `bash infrastructure/<name>.sh`):

```bash
chmod u+x infrastructure/deploy.sh infrastructure/package_lambda.sh infrastructure/teardown.sh
```

---

## What the scripts do

Two scripts under `infrastructure/` manage the whole lifecycle.

### `deploy.sh`

Packages the code, provisions the stack, and publishes the GUI — idempotent, so
re-running it updates in place. In order:

1. **Package the Lambda** — zips `pipeline/src/` (via `package_lambda.sh`) and
   names the S3 key with a content hash, so the function reliably redeploys
   whenever the code changes.
2. **Ensure the code bucket** — derives an account-scoped bucket
   (`review-pipeline-code-<account-id>`), creating it (private + encrypted) if
   missing, and uploads the zip.
3. **Deploy the CloudFormation stack** — S3 buckets (input/output/GUI), the
   Lambda, API Gateway, the Cognito user pool + client, CloudFront, and IAM.
4. **Seed `config.json`** to the input bucket (model selection + debug flag).
5. **Invite the Cognito login user** (when `API_AUTH=COGNITO`) — Cognito
   generates a one-time temporary password and **emails it to the user**.
   Nothing is stored locally; the user sets their own permanent password on
   first sign-in.
6. **Build and publish the GUI** — builds with the API URL + Cognito config
   baked in, syncs `gui/dist/` to the GUI bucket, and invalidates CloudFront so
   the new build serves immediately.
7. **Print outputs** — the stack outputs plus the CloudFront `GuiUrl` and login
   details, and an optional block for running the GUI locally against the same
   API.

### `teardown.sh`

Removes everything the deploy created, in a safe order. Destructive and
irreversible; prompts for a typed `yes` unless `FORCE=1`. In order:

1. **List the stack's resources** (visibility before deleting).
2. **Empty the stack-owned buckets** (input/output/GUI) — S3 will not delete a
   non-empty bucket, so this must happen before the stack delete.
3. **Delete the CloudFormation stack** and wait for completion (CloudFront
   deletion takes several minutes).
4. **Empty and delete the code bucket** (it is created outside the stack).
5. **Remove any local `.secrets/` leftover** (none is created now; this is a
   safety cleanup for older deploys).

---

## Deploy

One command builds and deploys everything: the Lambda, API Gateway, Cognito
user pool + login user, the S3 buckets, and the CloudFront-hosted GUI.

```bash
export REGION=us-east-1
bash infrastructure/deploy.sh first-admin@example.com
```

Pass the **first administrator's email** as the first argument (or set
`GUI_USER_EMAIL`). That address becomes the first user the deploy creates, and
Cognito emails it a one-time temporary password, so it must be a mailbox the
administrator can read. If you omit it, the script falls back to the engagement
owner's address, so always pass your own.

- `REGION` should be the region where you enabled Bedrock model access.
- No bucket to pre-create — the script derives and creates an account-scoped
  code bucket (`review-pipeline-code-<account-id>`).
- The Lambda code key is content-hashed, so each deploy reliably updates the
  function.
- A login user is created in Cognito; **Cognito generates a temporary password
  and emails it to the user**. Nothing is printed to the terminal or written to
  disk. The user sets their own permanent password on first sign-in.
- The GUI is built with the API URL + Cognito config baked in, synced to its
  S3 bucket, and CloudFront is invalidated.

When it finishes, the stack outputs include **`GuiUrl`** (the CloudFront URL).

### Use it

Check the login user's **email** for a message from Amazon Cognito with the
one-time temporary password (check spam too). Open the `GuiUrl` and sign in
with the email and that temporary password. On first sign-in the GUI prompts
you to set your own permanent password (the Cognito `NEW_PASSWORD_REQUIRED`
flow). The temporary password stops working once you reset it, and no password
is ever stored by the deploy. Then:

1. **Generate** — creates a synthetic English review corpus in the input bucket.
2. **Process** — submits a job (returns immediately); the summarize + translate
   work runs asynchronously. The job list auto-refreshes every 2 minutes.
3. **Select a job** — browse its **Inputs** (the reviews) and **Results** (each
   review's English summary with its German and French translations).

An **activity log** at the bottom of the GUI shows which step is running.

> CloudFront can take 10–15 minutes to finish its first deploy before the GUI
> URL serves.

### Optional overrides

| Variable | Default | Purpose |
|---|---|---|
| `REGION` | CLI default → us-east-1 | Deploy region (match Bedrock access) |
| `API_AUTH` | `COGNITO` | `COGNITO`, `API_KEY`, or `NONE` (open; PoC only) |
| `ENABLE_S3_TRIGGER` | `false` | `true` lets input uploads auto-run a job |
| `BEDROCK_MODEL_IDS` | `models` list in `infrastructure/config.json` | Comma-separated inference profile IDs the Lambda role may invoke (default model first; also the fallback if config.json is absent). Normally leave unset so `config.json` stays the single source of truth |
| `GUI_USER_EMAIL` | engagement owner's address | Email of the **first administrator**: the one Cognito user the deploy creates, emailed the temporary password. Always pass your own, as the first positional argument or this variable. |
| `CODE_BUCKET` | account-scoped | Bucket that holds the Lambda zip |

> **Email delivery (temporary password).** The user pool uses Cognito's default
> email sender, which is rate-limited (~50/day) and intended for testing. If the
> invite does not arrive, check spam. For production, configure Amazon SES as the
> pool's email sender (verified sender identity, out of the SES sandbox) — a
> customer hardening step, out of scope for this proof of concept.
>
> On re-deploy the script re-sends the invite; this only works while the user
> has not yet set a permanent password. If they have, use the GUI's reset flow
> or delete the user and re-deploy.

### Adding more users

The user pool is admin-create-only (no self sign-up), and there is a single
access level. Add users in the Cognito console, or with the CLI (take the
pool ID from the stack outputs):

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> --username new.user@example.com \
  --user-attributes Name=email,Value=new.user@example.com Name=email_verified,Value=true \
  --region us-east-1
```

Cognito emails the temporary password; the GUI prompts for a new one at
first sign-in.

---

## Input review format

The pipeline reads a **JSON array** of review objects from
`s3://review-pipeline-input-<account-id>/sample/reviews.json` (the default
`input_key`).

| Field | Required | Notes |
|---|---|---|
| `review_id` | yes | Unique identifier for the review |
| `product` | yes | Product label |
| `source_language` | yes | Must be present, but currently unused: text is treated as English |
| `rating` | yes | Integer (values are coerced with `int()`) |
| `text` | yes | The English review body (the generator makes 5-8 sentences) |
| `date` | yes | Date string, e.g. `2026-10-01` |
| `product_id` | no | Defaults to empty; the generator makes it unique per review |
| `product_name` | no | Defaults to empty |

Unknown keys are ignored and are not copied to the results.

```json
[
  {
    "review_id": "r-0001",
    "product_id": "P-1001",
    "product_name": "Classic Oxford Shirt",
    "product": "Shirt",
    "source_language": "en",
    "rating": 4,
    "text": "The fabric feels great. It fits true to size. Shipping was quick. The color matches the photos. Stitching looks durable. I would buy it again.",
    "date": "2026-10-01"
  }
]
```

Notes:

- A missing required field or a non-integer `rating` makes the job fail with an
  `error` status whose message names the review and the field.
- **Generate** overwrites `sample/reviews.json`. After uploading your own
  file, use **Process only** so it is not replaced.
- If the stack was deployed with `ENABLE_S3_TRIGGER=true`, uploading a
  `sample/*.json` file starts a job automatically.
- Reviews are processed sequentially inside the 10-minute Lambda limit, so
  keep files to roughly a few hundred reviews.
- Source reviews must be English. Use synthetic or de-identified data only (no PII).

---

## Extending: more target languages

Target languages are configuration, not code. Edit `target_languages` (and
optionally `language_labels`) in `infrastructure/config.json`:

```json
"target_languages": ["de", "fr", "es", "ja"],
"language_labels": { "de": "German", "fr": "French", "es": "Spanish", "ja": "Japanese" }
```

No code change is needed: the pipeline writes one `<code>_summary` field per
language and the GUI draws one tile per language found in each result row.
Amazon Translate IAM is not language-specific.

To apply the change:

- **Lasting:** edit the repo file and run
  `bash infrastructure/deploy.sh <first admin email>` (this re-seeds
  `config.json` to the input bucket).
- **Quick trial:** edit `config.json` in the input bucket. The next job picks
  it up with no redeploy, but the next deploy overwrites it.

Rules, checked when a job starts (a violation marks the job `error` with a
clear message in its `status.json`):

- Codes must be a non-empty list of Translate codes (`es`, `zh-TW`, `fr-CA`).
- `en` is rejected: source reviews are English.
- Duplicates are dropped.
- A job whose `config.json` is missing or unreadable uses the built-in default
  (`de`, `fr`).

Old jobs keep displaying correctly because each result row carries its own
language fields.

Use language codes from the
[Amazon Translate supported languages](https://docs.aws.amazon.com/translate/latest/dg/what-is-languages.html)
list. Each added language adds one Translate call per review, so job time
and cost grow roughly linearly; watch the 10-minute Lambda limit for large files.

---

## Tear down

Deletes the stack and empties all buckets (and cleans up any legacy local
`.secrets/`). Destructive and irreversible (set `FORCE=1` to skip the prompt):

```bash
export REGION=us-east-1
bash infrastructure/teardown.sh
```

CloudFront deletion takes several minutes. Pull anything you want to keep from
the output bucket first.

---

## Tests

Unit + integration tests run without AWS (clients are faked). Config comes from
`pipeline/pyproject.toml`:

```bash
cd pipeline
../.venv/bin/pytest        # add -v for per-test output
```

Coverage: the scorer, the data model, the pipeline service, the Bedrock
client (Claude and Nova request/response shapes) and the Lambda router
(action routing, CORS, error handling, async dispatch). Not covered: the
CloudFormation template and shell scripts (only `bash -n` and JSON validity
checks), the GUI, and real AWS calls.

---

## How scoring works

Each English summary and each translation gets a score from 0.0 to 1.0. A row
is `surfaced` only if every step scores at or above `QUALITY_THRESHOLD`
(default `0.7`). The heuristics live in
`pipeline/src/service/quality_scorer.py` and are deliberately simple so a
customer team can tune or replace them.

| Step | Dimensions (score is their mean) |
|---|---|
| Summary | length within 40-320 characters; 1-2 sentences; not a copy of the review |
| Translation | Translate saw the declared source language ("en"); output is not identical to the input |

Empty output scores 0.0. Amazon Translate reports the language of its
**input**, not its output, so the translation score cannot confirm the output
is really German or French. It catches empty output, untranslated echoes and
unexpected source languages. Verifying the output language would need a
language-detection call (for example Amazon Comprehend) and is a listed
extension, not a current feature.

---

## Operate and troubleshoot

| Symptom | Likely cause and fix |
|---|---|
| GUI login fails or no email arrives | Check spam; the invite is sent once per new user. Re-run `deploy.sh` to resend while the password is still temporary |
| Process returns a 400 or the job shows `error` with a message about a review | Input JSON is missing a required field or has a bad value (see Input review format); the message names the review |
| Job stays `running` | Check the Lambda log group `/aws/lambda/<function name>`; a job over the 10-minute limit is killed and stays `running` (use a smaller file) |
| Job shows `error` | `status.json` holds a short message. Messages about config or input are specific; anything else says `internal error (<type>)` and the full traceback is only in the Lambda logs. A 500 response carries a `request_id` you can search for in the logs |
| Bedrock `AccessDenied` or model-not-found | Model access is not enabled in the account/Region, or `config.json` names a model not in the IAM policy |
| Bedrock `ValidationException` about a parameter | The model rejects a request field (Claude Haiku 5.5 rejects `temperature`); edit `client/bedrock_client.py` |
| Browser shows a CORS error | Usually a 5xx hidden behind it; read the Lambda log for the real error |
| GUI changes not visible | Re-run `deploy.sh` (builds, syncs and invalidates CloudFront) and hard-refresh |
| Many rows show "below threshold" | Compare scores against the table above; lower `QUALITY_THRESHOLD` only after reading the rows |

Debug output: set the debug flag in `config.json` (input bucket); it takes
effect on the next invocation with no redeploy.

---

## Results against success criteria

This PoC has been deployed and the end-to-end flow verified by the engineer who
built it (generate, process, view in the GUI). **Formal measurements have not
been recorded.** The customer team should capture these before relying on the
output:

| Criterion | How to measure | Recorded result |
|---|---|---|
| Translation accuracy | Have native speakers rate a sample of 30-50 `de` and `fr` summaries | Not yet measured |
| Summary faithfulness | Compare sample summaries to the source reviews | Not yet measured |
| Surfaced rate | `surfaced_pct` in a job's `summary.json` | Not yet recorded |
| Latency | `elapsed_seconds` in `summary.json` (whole job); divide by review count | Not yet recorded |
| Cost | Bedrock token counts plus Translate characters per job | Not yet recorded |

## Optional: offline local run

`pipeline/scripts/run_local.py` runs the pipeline on your machine against a
local reviews file (calling real Translate + Bedrock), writing to
`data/outputs/`. A debugging aid, separate from the deployed flow:

```bash
.venv/bin/python pipeline/scripts/generate_synthetic.py --count 20 \
  --output data/sample/reviews.json
cd pipeline
../.venv/bin/python scripts/run_local.py \
  --input ../data/sample/reviews.json --targets de,fr --limit 5
```

The GUI can also run locally (instead of CloudFront) by pointing it at the API
and starting the Vite dev server — see the deploy script's printed output for
the exact env block.

---

## Security notes

The project is scanned with ProtoShield (Semgrep, Bandit, Checkov, cfn-nag,
Gitleaks, a CVE scan, and an IAM least-privilege review). Decisions worth
knowing:

- **Dependencies are fully pinned.** `pipeline/requirements.txt` is an exact
  lock of direct and transitive packages. Unpinned transitive dependencies can
  resolve to old, vulnerable minimums, so re-generate the lock (see the header
  in that file) when bumping a direct dependency. The GUI is locked by
  `gui/package-lock.json`; `npm audit` reports no known vulnerabilities. The
  deployed Lambda uses the runtime's boto3 and bundles only `src/`.
- **Bedrock access is scoped to the models in `config.json`.** The Lambda role
  may invoke only Claude Haiku 5.5 (US and global inference profiles) and Nova 2
  Lite. Foundation-model ARNs keep a region wildcard because cross-Region
  inference profiles route to other Regions. **To enable another model, add its
  inference profile ID (geo.provider.model form, for example
  `us.anthropic.claude-haiku-5-5`) to the `models` list in
  `infrastructure/config.json` and re-run `deploy.sh`.** The deploy copies that
  list into the template's `BedrockModelIds` parameter, and a loop in
  `infrastructure/template.json` creates one IAM policy per listed profile (and
  its foundation model). Do not edit the generated policies by hand. Editing
  `config.json` in S3 without redeploying lets you select a listed model, but a
  model that was never deployed fails with an access-denied error by design.
- **Translate uses `Resource: "*"` with a Region condition.** Amazon Translate
  text translation has no resource-level permissions to scope to, so the role
  is limited to the single action `translate:TranslateText` in the deploy
  Region. This is a known limitation, not an oversight; the customer can add
  organization-level controls (SCPs, CloudTrail monitoring) if needed.
- **No secrets in the repo or on disk.** Cognito generates and emails the
  one-time temporary password; the deploy never sees or stores it.
- **Not included in this proof of concept** (hardening for the customer's own
  production effort): S3/API Gateway/CloudFront access logging, S3 versioning,
  AWS WAF, a VPC for the Lambda, a dead-letter queue, reserved concurrency, and
  KMS-encrypted Lambda environment variables.

---

## Scope

**In scope:** English source reviews → summary → German + French translations,
synthetic data, quality evaluation, Cognito-protected GUI on CloudFront, IaC
the customer's team can adapt.

The original scoping discussion considered more source languages; this PoC
narrowed to English source reviews (see `docs/decisions.md`, ADR 7).

**Out of scope:** PDP redesign, real reviewer PII, production deployment and
hardening, languages beyond German and French. These are separate workstreams
owned by the customer's team.

---

© Amazon.com, Inc. or its affiliates.
This documentation is licensed under the Creative Commons Attribution 4.0
International License (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/

Source code in this project is licensed under the Apache License 2.0; see the
`LICENSE` file in this directory (a copy also sits at the repository root).
