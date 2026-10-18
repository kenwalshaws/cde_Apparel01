# Review Translate-and-Summarize Pipeline

A portable, self-contained prototype that ingests apparel product reviews,
translates them, summarizes them into a tight 1–2 sentence overview, and
re-translates that summary into the target shopper's language — applying a
quality-scoring check at each step so low-quality output is never surfaced.

Built for AnyCompany Apparel as a non-production prototype. Proven end-to-end
on **French** and **German** across synthetic (no-PII) sample reviews.

---

## Architecture

```
Reviews (synthetic feed)
        │
        ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  PipelineService  (service layer — orchestration)            │
   │                                                              │
   │   1. Translate source review → English   (Amazon Translate)  │
   │   2. Summarize to 1–2 sentences          (Amazon Bedrock)    │
   │   3. Translate summary → target language (Amazon Translate)  │
   │   4. Quality-score each step; drop below threshold           │
   └─────────────────────────────────────────────────────────────┘
        │
        ▼
   Outputs (per-language JSON)  ───►  TypeScript GUI (results + scores)
```

The pipeline logic lives in Python and runs in **AWS Lambda**. The GUI is a
TypeScript (React + Vite) app that runs locally and drives the deployed
backend through a thin local control plane:

```
TypeScript GUI (localhost:5173)
      │  /api/generate · /api/run · /api/results · /api/summary
      ▼
Local control plane (localhost:8000, uses your AWS credentials)
      │  Lambda invoke (generate) · Lambda invoke (process) · S3 read
      ▼
Deployed AWS:  Lambda  →  Translate + Bedrock
   generate ──► writes reviews JSON to the input bucket
   process  ──► reads input, runs the pipeline, writes results + run_summary
                to the output bucket
```

The browser never holds AWS credentials or calls AWS directly — it only talks
to the local control plane over `/api`. The S3 object-created trigger exists in
the template but is **OFF by default** (the `EnableS3Trigger` parameter);
processing is driven explicitly from the GUI. Flip the parameter to `true`
once the GUI flow is proven to let uploads auto-trigger the pipeline.

The CloudFormation template under `infrastructure/` is a handoff artifact the
customer's team can adapt — scaling and hardening are the customer's own
separate effort, out of scope for this proof of concept.

---

## Layered structure

The pipeline follows a strict layered architecture (one responsibility per
layer, dependencies point inward):

```
review-pipeline/
├── pipeline/                         # Python — core pipeline
│   ├── src/
│   │   ├── model/                    # dataclasses: Review, StepResult, PipelineResult
│   │   ├── client/                   # thin AWS SDK wrappers (Translate, Bedrock)
│   │   ├── service/                  # orchestration + quality scoring
│   │   ├── api/                      # local FastAPI app exposing the pipeline
│   │   └── config.py                 # settings (region, model id, languages, threshold)
│   ├── scripts/
│   │   ├── generate_synthetic.py     # generate synthetic review corpus
│   │   └── run_local.py              # run the pipeline over a corpus, write outputs
│   └── tests/
│       ├── unit/
│       └── integration/
├── gui/                              # TypeScript — React + Vite results viewer
├── infrastructure/
│   └── template.json                 # CloudFormation (handoff artifact)
├── data/
│   ├── sample/                       # generated synthetic reviews
│   └── outputs/translated_summaries/<lang>/<id>.json
└── README.md
```

Layer dependency direction:

```
api  →  service  →  client  →  (AWS)
          │
          └──────►  model  ◄── (everything depends on model)
```

- **model** — plain data structures, no logic, no dependencies.
- **client** — one wrapper per AWS service. Knows how to call Translate /
  Bedrock. Knows nothing about the pipeline.
- **service** — orchestrates the steps, runs quality scoring, and generates
  the synthetic corpus. The only layer that knows the full flow.
- **api** — thin adapters. The Lambda handler (`lambda_handler.py`) runs in
  AWS and routes `generate` / `process` actions. The local control plane
  (`local_app.py`) runs on your machine, invokes the Lambda, and reads results
  from S3 for the GUI. No business logic in either.

---

## Prerequisites

- Python 3.12, Node 18+, npm
- AWS credentials in your environment (env vars, profile, or SSO) with access to
  Amazon Translate and Amazon Bedrock
- **Bedrock model access enabled** for the summarization model
  (`anthropic.claude-3-haiku-20240307-v1:0` by default) in your region

Set up the Python environment. The pipeline is a proper installable package
(`pipeline/pyproject.toml`); an editable install puts `src` on the path so the
scripts and tests import it without any path hacks:

```bash
cd review-pipeline
python3 -m venv .venv
.venv/bin/pip install -e "pipeline/[dev,local]"
```

Extras: `dev` adds pytest; `local` adds FastAPI/uvicorn for the GUI control
plane. The Lambda deployment zip bundles only `src/` and relies on the boto3
already present in the Lambda runtime, so neither extra ships to AWS.
(`pipeline/requirements.txt` is kept as a pinned mirror of the same deps for
tools that expect it.)

## How to test (deployed backend + local GUI)

The backend runs in a test AWS account; the GUI runs locally and drives it.
The S3 auto-trigger stays off so everything flows through the GUI.

> **Enable Bedrock model access first.** In the target account and region,
> open Bedrock → Model access and enable the summarization model
> (`anthropic.claude-3-haiku-20240307-v1:0` by default). Without it, the
> **Process** step fails at the Bedrock call.

### Step 1 — Deploy the AWS backend

One command. It packages `src/` into a Lambda zip, creates a code bucket if
one does not exist, uploads the zip, and deploys the stack (S3 buckets,
Lambda, IAM) via CloudFormation. `EnableS3Trigger` defaults to `false`. Run
with your own credentials against the target account:

```bash
bash infrastructure/deploy.sh
```

No bucket to pre-create — the script derives an account-scoped code bucket
(`review-pipeline-code-<account-id>`) and makes it if needed. Override with
`CODE_BUCKET=<name>` if you prefer your own.

When it finishes, the script prints the stack outputs **and** a ready-to-paste
block with the exact `PIPELINE_FUNCTION` / `OUTPUT_BUCKET` / `AWS_REGION`
values for the next step — no need to copy them by hand.

### Step 2 — Start the local control plane

Paste the block the deploy script printed. It uses your local AWS credentials
to invoke the Lambda and read S3. It looks like this (with your real values
filled in):

```bash
cd pipeline
PIPELINE_FUNCTION=review-pipeline-processor \
OUTPUT_BUCKET=review-pipeline-output-<account-id> \
AWS_REGION=us-east-1 \
../.venv/bin/uvicorn src.api.local_app:app --port 8000
```

### Step 3 — Start the GUI and drive the flow

```bash
cd gui
npm install
npm run dev        # http://localhost:5173
```

In the browser:

1. **Generate** — invokes the Lambda to build a synthetic corpus and upload it
   to the input bucket.
2. **Process** — invokes the Lambda to translate, summarize, score, and write
   results to the output bucket.
3. **View / Refresh** — reads surfaced results and the run summary from the
   output bucket. Filter by language with the dropdown.

### Later — flip the S3 trigger on

Once the GUI flow is proven, redeploy with the trigger enabled so uploads to
the input bucket's `sample/` prefix auto-run the pipeline:

```bash
CODE_BUCKET=<bucket> ENABLE_S3_TRIGGER=true bash infrastructure/deploy.sh
```

## Tests

Unit + integration tests run without AWS (clients are faked). Test paths and
options come from `pipeline/pyproject.toml`:

```bash
cd pipeline
../.venv/bin/pytest        # add -v for per-test output
```

## Optional: offline local run

`pipeline/scripts/run_local.py` runs the pipeline entirely on your machine
against a local reviews file (calling real Translate + Bedrock) and writes to
`data/outputs/`. It's a debugging aid, separate from the GUI-driven AWS flow:

```bash
.venv/bin/python pipeline/scripts/generate_synthetic.py --count 20 \
  --output data/sample/reviews.json
cd pipeline
../.venv/bin/python scripts/run_local.py \
  --input ../data/sample/reviews.json --targets fr,de --limit 5
```

---

## Scope

**In scope:** French + German, synthetic reviews, quality evaluation,
local-first run, IaC the customer's team can adapt.

**Out of scope:** PDP redesign, real reviewer PII, production deployment,
languages beyond French and German. These are separate workstreams owned by
the customer's team.

---

© Amazon.com, Inc. or its affiliates.
This documentation is licensed under the Creative Commons Attribution 4.0
International License (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/

Source code in this project is licensed under the Apache License 2.0; see the
repository-root `LICENSE` file.
