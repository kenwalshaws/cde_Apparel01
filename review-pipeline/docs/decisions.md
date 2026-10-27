<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
This documentation is licensed under CC BY 4.0:
https://creativecommons.org/licenses/by/4.0/
-->

# Decision records

Short records of choices a reviewer cannot recover from the code alone. Each
lists the decision, why, and what was rejected.

## 1. Async jobs with a self-invoking Lambda

**Decision:** `process` creates the job, writes `status.json` as `running`,
invokes the same Lambda with `InvocationType=Event` (`_worker` action), and
returns the job number at once. The GUI polls.
**Why:** API Gateway times out at 29 seconds; a batch takes minutes.
**Rejected:** synchronous processing. A queue/Step Functions design is a valid
next step but adds services for a PoC.
**Consequence:** a job that exceeds the 10-minute Lambda limit is killed and
stays `running`.

## 2. Cognito temporary password by email

**Decision:** Cognito creates the first admin and emails the temporary
password. The email is a `deploy.sh` argument. The GUI handles the forced
password change.
**Why:** no secret ever touches disk, the terminal or the repo.
**Rejected:** a generated password written to a `.secrets/` file; a printed
password; `$RANDOM`-based passwords.

## 3. Summarize once, translate per target

**Decision:** one Bedrock call per review; the English summary is translated
into each target language.
**Why:** fewer model calls, and an identical English summary across languages.
**Rejected:** summarizing per target; an English pass-through "target".

## 4. Reviews are template-generated

**Decision:** synthetic reviews come from templates (5-8 sentences, unique
`product_id` and `product_name`), not an LLM.
**Why:** deterministic, free, reproducible with a seed.
**Option:** an LLM-generated mode could be added for more variety.

## 5. Exact dependency pins

**Decision:** `requirements.txt` is a full exact lock; `pyproject.toml` pins
direct dependencies and the transitive ones the scanner flagged.
**Why:** the scanner resolves unpinned transitive packages to their minimum
versions, which carry known CVEs. The GUI uses Vite 7.3.7 with
`@vitejs/plugin-react` 4.7.0 because the newest plugin requires Vite 8.
**Rejected:** `>=` floors.

## 6. Bedrock and Translate IAM

**Decision:** Bedrock access is limited to the configured inference profiles
and their foundation models. Inference-profile ARNs are scoped to the deploy
Region and account; foundation-model ARNs keep Region `*` because cross-Region
profiles route requests to other Regions. Translate allows only
`translate:TranslateText`, restricted by `aws:RequestedRegion`.
**Why:** least privilege that still works with cross-Region profiles.
**How it is built:** `BedrockModelIds` is one template parameter that
`deploy.sh` fills from the `models` list in `infrastructure/config.json`. A
`Fn::ForEach` loop (AWS::LanguageExtensions transform, which is why the deploy
uses `CAPABILITY_AUTO_EXPAND`) creates one managed policy per profile, granting
the profile ARN and its foundation model (the profile id without the geo
prefix). Adding a model means editing `config.json` and redeploying.
**Known limit:** Translate has no resource-level permissions, so its resource
is `*`. This is the one remaining HIGH scanner finding.
**Not verified against live AWS:** the ARN patterns were checked locally with
pattern matching and by a successful deployment and run.

## 7. English source only

**Decision:** source reviews are English; targets default to German and
French and are set in `config.json` (`target_languages`), validated at job
start. The GUI renders one tile per `<code>_summary` field in each row, so
adding a language needs no code change.
**Why:** the original scoping discussion considered more source languages.
The PoC narrowed to English source to prove the summarize-then-translate flow
first. Adding source languages means adding detection or declared-language
handling; `source_language` is currently required but unused.

## 8. Scoring cannot verify output language

**Decision:** translation scoring checks that Translate saw the declared
source language and that the output is not an untranslated echo.
**Why:** Translate reports the language of the input, not the output. An
earlier version compared that value to the target language and failed every
real translation; unit tests hid it because their fake returned the target.
**Next step:** add output language detection if that guarantee is needed.

## 9. Medium and low scanner findings left open

**Decision:** logging, versioning, WAF, VPC, DLQ, reserved concurrency and KMS
findings are listed in the README as customer hardening, not fixed here.
CloudFront minimum TLS cannot be set with the default `*.cloudfront.net`
certificate.

## 10. API errors are generic; jobs never re-raise

**Decision:** the Lambda returns a project-written message only for
`UserFacingError` (bad request, bad config, bad input review). Any other
exception is logged in full and the caller gets `internal error` plus the
Lambda request id. A failed job writes the same kind of message to
`status.json`.
**Why:** raw exception text from boto3 can contain bucket names, ARNs and
request details.
**Also:** the async worker records a failure and returns instead of raising,
because an error from an asynchronous Lambda invocation triggers automatic
retries that would re-run the whole job.

## 11. Job lifecycle lives in the service layer

**Decision:** `JobService` (service layer) owns create, run, list and read for
jobs; `JobStore` (client layer) owns the S3 reads and writes; the Lambda handler
only normalizes events, routes and wraps responses.
**Why:** keeps the layering rule true, lets the job logic be tested with a fake
store, and lets another entry point reuse it.
