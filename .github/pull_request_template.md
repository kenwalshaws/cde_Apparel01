## Summary
<!-- What changed and why, in 2-4 sentences. -->

## Changes
<!-- Bullet list grouped by area: pipeline, gui, infrastructure, docs. -->

## How it was verified
<!-- Commands run and results, e.g. pytest count, npm run build, bash -n, security scan. -->

## Not verified
<!-- Anything you could not check (live AWS behavior, GUI in a browser, etc.). -->

## Security and IAM
<!-- New permissions, new dependencies, new exposed endpoints. "None" if none. -->

## Reviewer guide
<!-- Where to start reading; riskiest files; related docs/decisions.md entries. -->

## Checklist
- [ ] Tests pass (`cd review-pipeline/pipeline && ../.venv/bin/pytest`)
- [ ] GUI builds (`npm run build`) if `gui/` changed
- [ ] No secrets, `cde_back_ground_folder/` or build artifacts included
- [ ] License headers on new source files
- [ ] README / `docs/decisions.md` updated if behavior or design changed
