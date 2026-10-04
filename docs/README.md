# Project documentation

Start with the [current project README](../README.md) to run the rewritten v3 system. The [version comparison and recovery record](recovery/2026-10-05-documentation-recovery.md) explains which evidence belongs to each implementation and where missing documents were recovered.

## Current workflow and proposals

| Need | Document |
| --- | --- |
| Shared agent rules | [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md) |
| Record prompts, attribution, decisions and executed checks | [AI evidence guide](ai/README.md) |
| Today's prompts, including branch tidying and this recovery | [2026-10-05 — yyy-tom](ai/prompts/2026-10-05-yyy-tom.md) |
| Current proposed storage and security follow-up | [Follow-up proposals](current-follow-ups.md) |
| Course brief | [Project description](project-description.pdf) |
| Compare every audited branch, tag and document revision | [Recovery report](recovery/2026-10-05-documentation-recovery.md), [machine-readable manifest](recovery/2026-10-05-manifest.json) |

## Rewritten phase sequence

These labels belong to the rewritten line imported in `ec81279`. In particular, its v1/v2 documents do not describe the old v1/v2 Git tags.

| Phase | Document |
| --- | --- |
| Initial baseline | [Rewritten v1.0.0](../documentation/phases/v1.0.0.md) |
| Automated tests | [Rewritten v1.1.0](../documentation/phases/v1.1.0.md) |
| CI/CD | [Rewritten v1.2.0](../documentation/phases/v1.2.0.md) |
| DS18B20 device | [Rewritten v1.3.0](../documentation/phases/v1.3.0.md) |
| ML-KEM integration | [Rewritten v2.0.0](../documentation/phases/v2.0.0.md) |
| Metrics | [Rewritten v3.0.0](../documentation/phases/v3.0.0.md) |
| Phase record template | [Template](../documentation/template.md) |

## Recovered historical prompts and release evidence

Historical records retain their attribution, original results, limits and review status. Their source revisions are linked in each document. Matching version labels across the two implementations do not mean matching code.

| Need | Documents |
| --- | --- |
| Old tagged release history | [v1.0.0](ai/prompts/v1.0.0.md), [v2.0.0](ai/prompts/v2.0.0.md), [v2.1.0](ai/prompts/v2.1.0.md), [v2.2.0](ai/prompts/v2.2.0.md) |
| Unreleased security/operations work | [Proposed v2.3.0 branch record](ai/prompts/v2.3.0.md) |
| Tom's original work | [2026-09-15](ai/prompts/2026-09-15-yyy-tom.md), [2026-09-24](ai/prompts/2026-09-24-yyy-tom.md), [2026-09-29](ai/prompts/2026-09-29-yyy-tom.md) |
| Roland's original work | [2026-09-26](ai/prompts/2026-09-26-Rolko6.md), [2026-09-28](ai/prompts/2026-09-28-Rolko6.md), [2026-09-29](ai/prompts/2026-09-29-Rolko6.md) |
| Agent workflow decision | [Decision 0001](decisions/0001-shared-agent-instructions.md) |
| Old cryptographic design and choice | [Decision 0002](decisions/0002-ml-kem-key-establishment.md), [ML-KEM integration](security/ml-kem-integration.md), [test boundaries](testing/ml-kem-verification.md) |
| Old CI and deployment guidance | [CI](operations/ci.md), [deployment](operations/deployment.md) |
| Old monitoring and proposed work | [Monitoring](operations/monitoring.md), [future features](monitoring/future-features.md), [pending tasks](ai/notes/pending-tasks.md), [old project plan](project-plan.md) |
| Old instructions about release records | [AI documentation guide](ai/notes/ai-docs-guide.md) |
| Plaintext-ingestion finding on the older checkout | [Finding and proposal](security/plaintext-ingestion-bypass.md) |

## Recovered validation records

- [2026 09 15 baseline](validation/2026-09-15-baseline.md)
- [2026 09 15 device modularization](validation/2026-09-15-device-modularization.md)
- [2026 09 15 documentation](validation/2026-09-15-documentation.md)
- [2026 09 15 integration](validation/2026-09-15-integration.md)
- [2026 09 15 measurement method](validation/2026-09-15-measurement-method.md)
- [2026 09 15 ml kem tests](validation/2026-09-15-ml-kem-tests.md)
- [2026 09 15 reliability](validation/2026-09-15-reliability.md)
- [2026 09 15 tests and ci](validation/2026-09-15-tests-and-ci.md)
- [2026 09 24 ci evaluation](validation/2026-09-24-ci-evaluation.md)
- [2026 09 28 ds18b20 faults](validation/2026-09-28-ds18b20-faults.md)
- [2026 09 29 ci effectiveness](validation/2026-09-29-ci-effectiveness.md)
- [2026 09 29 deployment rehearsal](validation/2026-09-29-deployment-rehearsal.md)
- [2026 09 29 detection time](validation/2026-09-29-detection-time.md)
- [2026 09 29 latency](validation/2026-09-29-latency.md)
- [2026 09 29 recovery and delivery](validation/2026-09-29-recovery-and-delivery.md)
- [2026 09 29 security evidence](validation/2026-09-29-security-evidence.md)

## Preserved alternatives and local work

The recovery report lists branch-specific versions of documents with conflicting content, snapshots of the three locally edited documents, and superseded filenames. Earlier revisions remain accessible through immutable source links in the manifest. The local security and storage proposals are preserved as proposals; no runtime fix was applied by this recovery.
