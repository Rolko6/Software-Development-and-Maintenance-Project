<!--
Checklist tied to this repository's rules (AGENTS.md "Work sequence" and
"Verification"; docs/operations/ci.md). Delete anything that genuinely does
not apply and say why in the description above.
-->

## What changed and why

<!-- One or two sentences: the behaviour or documentation change and its reason. -->

## Checks run

CI (`.github/workflows/ci.yml`) and the docs check (`.github/workflows/docs-check.yml`)
run automatically on this pull request. List anything you also ran locally,
with the actual result observed (not the expected one):

- [ ] `python -m compileall` / `ruff check .` — result:
- [ ] Unit tests (`pytest`, per service) — result:
- [ ] `docker compose config --quiet` — result:
- [ ] Image build(s) — result:
- [ ] Smoke test (`scripts/smoke-test.sh` or the manual README checks) — result:
- [ ] `.github/scripts/check_docs.py` — result:
- [ ] Other (name it): — result:

## Evidence recorded under `docs/`

- [ ] Verification results are recorded under `docs/validation/` (or another
      appropriate `docs/` location) with actual observed output, not an
      expected/assumed one.
- [ ] N/A — no behaviour or verification claim needs recording for this change.

## AI evidence record

- [ ] This change involved significant AI-assisted work (new rules, an
      architecture/security choice, a substantial generated artifact, a
      meaningful bug fix, or a verification/deployment behaviour change),
      and an entry was added or updated per [`docs/ai/README.md`](../docs/ai/README.md).
- [ ] N/A — no significant AI-assisted work to record.

## Documentation

- [ ] `README.md`, `docs/`, or both were updated to match the new behaviour.
- [ ] N/A — no user-facing or operational behaviour changed.

## Reviewer notes

<!-- Anything a reviewer should specifically look at: risk, scope
     boundaries, files intentionally left untouched, follow-up work. -->
