# Documentation comparison and recovery — 2026-10-05

The v3 import at `ec81279` removed 37 document files from the older implementation. Other evidence was present only on unmerged branches, and three earlier filenames had deliberately been renamed or superseded. The records were recoverable from Git; they had disappeared from the current `main` tree rather than from every historical revision.

This repair is based on `0529036664a83d498c5484674a61c6d7cd124ac5` and changes documentation only. It restores the shared agent instructions and prompt-recording procedure, recovers the historical evidence, preserves existing rewritten phase documents, carries forward today's local prompts and proposals, and adds version boundaries. It does not merge old application code, change release tags, change the v3 release branch, or claim old test results verify v3.

## Comparison scope

- Audited 30 local/remote branch and tag references and all 77 reachable commits after fetching origin without pruning.
- Compared 57 unique document paths and 147 unique Git blob revisions. Documents include all tracked Markdown and everything under `docs/` and `documentation/`, including the course PDF.
- Recovered 49 document paths absent on v3 `main`: the 37 removed by the rewrite plus 12 paths from branch-only history or superseded filenames. Superseded files are archived rather than reintroduced under their active names.
- Preserved 25 additional snapshots of differing branch documents and locally edited READMEs/project plan. These are alternatives with explicit source revisions, not an assertion that one branch's runtime features were merged into another.
- Preserved the current v3 README's setup instructions and all seven existing `documentation/` files. Phase documents gained a version-scope notice; their narratives and previously recorded claims remain intact.
- Included the uncommitted security finding and the complete same-day prompt record, including the exact branch-tidying prompt in P014 and this recovery request in P015.

The [manifest](2026-10-05-manifest.json) records every compared reference, original path, Git blob ID, immutable source URL, chosen recovery destination, navigation repair and extra snapshot. Git cannot recover uncommitted material that no longer exists on disk; other clones, deleted refs, reflog-only history and inaccessible chats were not audited. Runtime and historical human-review claims were preserved as evidence, not independently re-executed.

## Version map

| Reference or phase | Revision | Implementation and documentation meaning |
| --- | --- | --- |
| Old `v1.0.0` tag / `release/1.0.0` branch | `e13ffb1` / `00c14d5` | Original plaintext baseline. The release branch includes later ignore-file housekeeping. |
| Old `v2.0.0` tag / `release/2.0.0` branch | `9bb782a` | Original ML-KEM session design, reliability work, tests and CI/CD. |
| Old `v2.1.0` tag | `be4965c` | Metrics, dashboard and CI work in the original implementation; no release branch was present at audit time. |
| Old `v2.2.0` tag / `archive/main-pre-rewrite` tag | `b0ca4ef` | Original implementation with the DS18B20 changes; last tagged main tree before the rewrite. |
| Proposed old `v2.3.0` document | `4f2b22d` | Unmerged `feat/secure-channel-hardening` evidence. There was no `v2.3.0` tag. The record still has a release-time placeholder, retained as historical incompleteness. |
| Rewritten phases `v1.0.0`–`v3.0.0` | `4bc9010`, imported at `ec81279` | Different implementation developed on `roland/simplify-v1.0.0`. Phase labels reuse old release numbers, but do not correspond to the old tags. |
| Current `main` / `release/3.0.0` | `0529036` | Rewritten v3 code plus the CI-test README change. No `v3.0.0` tag or GitHub Release was present at recovery time. |

Use the [old release records](../ai/prompts/v2.0.0.md) for old tags and the [rewritten phase sequence](../../documentation/phases/v3.0.0.md) for the new implementation. Do not rename or move the old tags to make the numbering look consistent: that would change the meaning of published historical references.

## Why historical guidance cannot describe current v3

| Topic | Earlier implementation / branches | Current v3 source |
| --- | --- | --- |
| Protected route | `/secure/handshake` and `/secure/data`; reusable ML-KEM sessions | `/data/secure`; per-request encapsulation with Base64 keys supplied through environment variables |
| Cryptographic library | `cryptography` ML-KEM helpers; old test vectors and contract suites | `kyber-py` ML-KEM plus `cryptography` AES-GCM |
| Plaintext-ingestion restriction | `CLOUD_ML_KEM_MODE=required` gate in the old implementation | `/data` remains accepted with warning/counter; the old mode gate is absent |
| Storage | Bounded in-memory collection, 1,000 readings by default | Unbounded `stored_data = []`; data disappears on process restart |
| CI evaluation | Old service/root suites, checker, fault injection and deployment records | Current workflow runs device/gateway/cloud tests and image builds; old root-suite evidence does not apply |
| Monitoring | Prometheus/Grafana and, on a separate security branch, alert rules | Current v3 metrics exports; earlier monitoring infrastructure is absent |

These findings came from the compared source trees and current workflow, not new runtime measurements. [Current follow-up proposals](../current-follow-ups.md) translate the earlier storage and plaintext-ingestion concerns into the v3 context without treating them as completed fixes.

## Recovery choices

The primary historical source is `feat/secure-channel-hardening` at `4f2b22d`, which contains the last pre-rewrite documentation plus the unmerged security/operations evidence. Tom's later CI/deployment branch at `82599b2` supplies the complete P011 prompt record, corrected deployment guide, CI evaluation and deployment rehearsal. `tom/issue4-remaining-metrics` at `0d9f085` supplies the detection, recovery/delivery and latency evidence absent from the other branches.

Differing monitoring plans, pending-task lists, cryptographic guidance and READMEs were preserved as branch snapshots. For example, alert rules had been implemented on the security branch while Tom's independently evaluated v2.2 baseline still had only proposed rules. Both are valid statements about their own revisions; combining them into a single unqualified claim would be wrong.

Recovered Markdown includes a historical notice. Prose, prompts, attribution, acceptance status and measured results are retained; relative links to old code are pinned to immutable historical commits, and whitespace is normalized. The PDF and thin instruction entry point were recovered byte for byte; shared agent rules gained a version-boundary section. The active documentation index was rebuilt for the two histories. Every one of the 147 original revisions remains linked in the manifest.

The three superseded files below remain historical. The two undated prompt filenames were replaced by person-attributed names. The earlier v2.1 notes were replaced by the later v2.1 record. Their recovery does not re-authorize archived prompts or assert that those files should become the active log.

- [`docs/ai/prompts/v2.1.0-notes.md`](../history/superseded/v2.1.0-notes.md)
- [`docs/ai/prompts/2026-09-15.md`](../history/superseded/2026-09-15.md)
- [`docs/ai/prompts/2026-09-24.md`](../history/superseded/2026-09-24.md)

## Recovered document inventory

| Original path | Recovered document | Source revision |
| --- | --- | --- |
| `.github/pull_request_template.md` | [Open](../../.github/pull_request_template.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/.github/pull_request_template.md) |
| `AGENTS.md` | [Open](../../AGENTS.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/AGENTS.md) |
| `CLAUDE.md` | [Open](../../CLAUDE.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/CLAUDE.md) |
| `docs/README.md` | [Open](../history/pre-v3-documentation-index.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/README.md) |
| `docs/ai/README.md` | [Open](../ai/README.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/README.md) |
| `docs/ai/notes/ai-docs-guide.md` | [Open](../ai/notes/ai-docs-guide.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/notes/ai-docs-guide.md) |
| `docs/ai/notes/pending-tasks.md` | [Open](../ai/notes/pending-tasks.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/notes/pending-tasks.md) |
| `docs/ai/prompts/2026-09-15-yyy-tom.md` | [Open](../ai/prompts/2026-09-15-yyy-tom.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/2026-09-15-yyy-tom.md) |
| `docs/ai/prompts/2026-09-15.md` | [Open](../history/superseded/2026-09-15.md) | [c3c3ef2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/c3c3ef22e7986069df5aa49831fe53992dcebfca/docs/ai/prompts/2026-09-15.md) |
| `docs/ai/prompts/2026-09-24-yyy-tom.md` | [Open](../ai/prompts/2026-09-24-yyy-tom.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/ai/prompts/2026-09-24-yyy-tom.md) |
| `docs/ai/prompts/2026-09-24.md` | [Open](../history/superseded/2026-09-24.md) | [c3c3ef2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/c3c3ef22e7986069df5aa49831fe53992dcebfca/docs/ai/prompts/2026-09-24.md) |
| `docs/ai/prompts/2026-09-26-Rolko6.md` | [Open](../ai/prompts/2026-09-26-Rolko6.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/2026-09-26-Rolko6.md) |
| `docs/ai/prompts/2026-09-28-Rolko6.md` | [Open](../ai/prompts/2026-09-28-Rolko6.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/2026-09-28-Rolko6.md) |
| `docs/ai/prompts/2026-09-29-Rolko6.md` | [Open](../ai/prompts/2026-09-29-Rolko6.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/2026-09-29-Rolko6.md) |
| `docs/ai/prompts/2026-09-29-yyy-tom.md` | [Open](../ai/prompts/2026-09-29-yyy-tom.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/ai/prompts/2026-09-29-yyy-tom.md) |
| `docs/ai/prompts/v1.0.0.md` | [Open](../ai/prompts/v1.0.0.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/v1.0.0.md) |
| `docs/ai/prompts/v2.0.0.md` | [Open](../ai/prompts/v2.0.0.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/v2.0.0.md) |
| `docs/ai/prompts/v2.1.0-notes.md` | [Open](../history/superseded/v2.1.0-notes.md) | [566e12c](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/566e12c7fbe56739aa686c2722fc89333366639e/docs/ai/prompts/v2.1.0-notes.md) |
| `docs/ai/prompts/v2.1.0.md` | [Open](../ai/prompts/v2.1.0.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/v2.1.0.md) |
| `docs/ai/prompts/v2.2.0.md` | [Open](../ai/prompts/v2.2.0.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/v2.2.0.md) |
| `docs/ai/prompts/v2.3.0.md` | [Open](../ai/prompts/v2.3.0.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/prompts/v2.3.0.md) |
| `docs/decisions/0001-shared-agent-instructions.md` | [Open](../decisions/0001-shared-agent-instructions.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/decisions/0001-shared-agent-instructions.md) |
| `docs/decisions/0002-ml-kem-key-establishment.md` | [Open](../decisions/0002-ml-kem-key-establishment.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/decisions/0002-ml-kem-key-establishment.md) |
| `docs/monitoring/future-features.md` | [Open](../monitoring/future-features.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/monitoring/future-features.md) |
| `docs/operations/ci.md` | [Open](../operations/ci.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/operations/ci.md) |
| `docs/operations/deployment.md` | [Open](../operations/deployment.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/operations/deployment.md) |
| `docs/operations/monitoring.md` | [Open](../operations/monitoring.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/operations/monitoring.md) |
| `docs/project-description.pdf` | [Open](../project-description.pdf) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/project-description.pdf) |
| `docs/project-plan.md` | [Open](../project-plan.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/project-plan.md) |
| `docs/security/ml-kem-integration.md` | [Open](../security/ml-kem-integration.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/security/ml-kem-integration.md) |
| `docs/testing/ml-kem-verification.md` | [Open](../testing/ml-kem-verification.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/testing/ml-kem-verification.md) |
| `docs/validation/2026-09-15-baseline.md` | [Open](../validation/2026-09-15-baseline.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-baseline.md) |
| `docs/validation/2026-09-15-device-modularization.md` | [Open](../validation/2026-09-15-device-modularization.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-device-modularization.md) |
| `docs/validation/2026-09-15-documentation.md` | [Open](../validation/2026-09-15-documentation.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-documentation.md) |
| `docs/validation/2026-09-15-integration.md` | [Open](../validation/2026-09-15-integration.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-integration.md) |
| `docs/validation/2026-09-15-measurement-method.md` | [Open](../validation/2026-09-15-measurement-method.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-measurement-method.md) |
| `docs/validation/2026-09-15-ml-kem-tests.md` | [Open](../validation/2026-09-15-ml-kem-tests.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-ml-kem-tests.md) |
| `docs/validation/2026-09-15-reliability.md` | [Open](../validation/2026-09-15-reliability.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-reliability.md) |
| `docs/validation/2026-09-15-tests-and-ci.md` | [Open](../validation/2026-09-15-tests-and-ci.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-tests-and-ci.md) |
| `docs/validation/2026-09-24-ci-evaluation.md` | [Open](../validation/2026-09-24-ci-evaluation.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/validation/2026-09-24-ci-evaluation.md) |
| `docs/validation/2026-09-28-ds18b20-faults.md` | [Open](../validation/2026-09-28-ds18b20-faults.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-28-ds18b20-faults.md) |
| `docs/validation/2026-09-29-ci-effectiveness.md` | [Open](../validation/2026-09-29-ci-effectiveness.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/validation/2026-09-29-ci-effectiveness.md) |
| `docs/validation/2026-09-29-deployment-rehearsal.md` | [Open](../validation/2026-09-29-deployment-rehearsal.md) | [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/validation/2026-09-29-deployment-rehearsal.md) |
| `docs/validation/2026-09-29-detection-time.md` | [Open](../validation/2026-09-29-detection-time.md) | [0d9f085](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/docs/validation/2026-09-29-detection-time.md) |
| `docs/validation/2026-09-29-latency.md` | [Open](../validation/2026-09-29-latency.md) | [0d9f085](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/docs/validation/2026-09-29-latency.md) |
| `docs/validation/2026-09-29-recovery-and-delivery.md` | [Open](../validation/2026-09-29-recovery-and-delivery.md) | [0d9f085](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/docs/validation/2026-09-29-recovery-and-delivery.md) |
| `docs/validation/2026-09-29-security-evidence.md` | [Open](../validation/2026-09-29-security-evidence.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-29-security-evidence.md) |
| `monitoring/README.md` | [Open](../../monitoring/README.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/monitoring/README.md) |
| `scripts/baseline/README.md` | [Open](../../scripts/baseline/README.md) | [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/scripts/baseline/README.md) |

## Preserved differing branch and local documents

| Original path | Snapshot | Source |
| --- | --- | --- |
| `README.md` | [Open](../history/branches/secure-channel-hardening/README.md) | `feat/secure-channel-hardening` |
| `docs/ai/prompts/2026-09-24-yyy-tom.md` | [Open](../history/branches/secure-channel-hardening/docs/ai/prompts/2026-09-24-yyy-tom.md) | `feat/secure-channel-hardening` |
| `docs/operations/ci.md` | [Open](../history/branches/secure-channel-hardening/docs/operations/ci.md) | `feat/secure-channel-hardening` |
| `docs/operations/deployment.md` | [Open](../history/branches/secure-channel-hardening/docs/operations/deployment.md) | `feat/secure-channel-hardening` |
| `docs/testing/ml-kem-verification.md` | [Open](../history/branches/secure-channel-hardening/docs/testing/ml-kem-verification.md) | `feat/secure-channel-hardening` |
| `README.md` | [Open](../history/branches/ci-deploy-evaluation/README.md) | `tom/ci-deploy-evaluation` |
| `docs/ai/notes/pending-tasks.md` | [Open](../history/branches/ci-deploy-evaluation/docs/ai/notes/pending-tasks.md) | `tom/ci-deploy-evaluation` |
| `docs/monitoring/future-features.md` | [Open](../history/branches/ci-deploy-evaluation/docs/monitoring/future-features.md) | `tom/ci-deploy-evaluation` |
| `docs/operations/monitoring.md` | [Open](../history/branches/ci-deploy-evaluation/docs/operations/monitoring.md) | `tom/ci-deploy-evaluation` |
| `docs/project-plan.md` | [Open](../history/branches/ci-deploy-evaluation/docs/project-plan.md) | `tom/ci-deploy-evaluation` |
| `docs/security/ml-kem-integration.md` | [Open](../history/branches/ci-deploy-evaluation/docs/security/ml-kem-integration.md) | `tom/ci-deploy-evaluation` |
| `monitoring/README.md` | [Open](../history/branches/ci-deploy-evaluation/monitoring/README.md) | `tom/ci-deploy-evaluation` |
| `README.md` | [Open](../history/branches/issue4-remaining-metrics/README.md) | `tom/issue4-remaining-metrics` |
| `docs/ai/notes/pending-tasks.md` | [Open](../history/branches/issue4-remaining-metrics/docs/ai/notes/pending-tasks.md) | `tom/issue4-remaining-metrics` |
| `docs/ai/prompts/2026-09-24-yyy-tom.md` | [Open](../history/branches/issue4-remaining-metrics/docs/ai/prompts/2026-09-24-yyy-tom.md) | `tom/issue4-remaining-metrics` |
| `docs/monitoring/future-features.md` | [Open](../history/branches/issue4-remaining-metrics/docs/monitoring/future-features.md) | `tom/issue4-remaining-metrics` |
| `docs/operations/ci.md` | [Open](../history/branches/issue4-remaining-metrics/docs/operations/ci.md) | `tom/issue4-remaining-metrics` |
| `docs/operations/deployment.md` | [Open](../history/branches/issue4-remaining-metrics/docs/operations/deployment.md) | `tom/issue4-remaining-metrics` |
| `docs/operations/monitoring.md` | [Open](../history/branches/issue4-remaining-metrics/docs/operations/monitoring.md) | `tom/issue4-remaining-metrics` |
| `docs/security/ml-kem-integration.md` | [Open](../history/branches/issue4-remaining-metrics/docs/security/ml-kem-integration.md) | `tom/issue4-remaining-metrics` |
| `docs/testing/ml-kem-verification.md` | [Open](../history/branches/issue4-remaining-metrics/docs/testing/ml-kem-verification.md) | `tom/issue4-remaining-metrics` |
| `monitoring/README.md` | [Open](../history/branches/issue4-remaining-metrics/monitoring/README.md) | `tom/issue4-remaining-metrics` |
| `README.md` | [Open](../history/local-2026-10-05/README.md) | `uncommitted original checkout` |
| `docs/README.md` | [Open](../history/local-2026-10-05/docs/README.md) | `uncommitted original checkout` |
| `docs/project-plan.md` | [Open](../history/local-2026-10-05/docs/project-plan.md) | `uncommitted original checkout` |

## Reference-by-reference comparison

Counts include all Markdown files plus other files in the documentation directories. References are the fetched snapshot used for this audit; the new recovery branch is intentionally excluded from the baseline counts.

| Reference | Commit | Document files |
| --- | --- | --- |
| `refs/heads/ci/root-suites` | `b297b28` | 29 |
| `refs/heads/develop` | `24bbe31` | 28 |
| `refs/heads/main` | `0529036` | 8 |
| `refs/heads/release/1.0.0` | `00c14d5` | 1 |
| `refs/heads/release/2.0.0` | `9bb782a` | 28 |
| `refs/heads/release/3.0.0` | `0529036` | 8 |
| `refs/heads/tom/ci-deploy-evaluation` | `82599b2` | 42 |
| `refs/heads/tom/issue4-remaining-metrics` | `0d9f085` | 41 |
| `refs/remotes/origin/HEAD` | `0529036` | 8 |
| `refs/remotes/origin/add-claude-github-actions-1790067039896` | `acece0f` | 1 |
| `refs/remotes/origin/ci/root-suites` | `b297b28` | 29 |
| `refs/remotes/origin/develop` | `0f309bd` | 38 |
| `refs/remotes/origin/docs/p008-outcome` | `172ef46` | 25 |
| `refs/remotes/origin/feat/ds18b20-device` | `e5ea58e` | 38 |
| `refs/remotes/origin/feat/project-plan-work-packages` | `18ed206` | 25 |
| `refs/remotes/origin/feat/secure-channel-hardening` | `4f2b22d` | 40 |
| `refs/remotes/origin/fix/check-docs-exit-code` | `a4e7385` | 25 |
| `refs/remotes/origin/main` | `0529036` | 8 |
| `refs/remotes/origin/release/1.0.0` | `00c14d5` | 1 |
| `refs/remotes/origin/release/2.0.0` | `9bb782a` | 28 |
| `refs/remotes/origin/release/3.0.0` | `0529036` | 8 |
| `refs/remotes/origin/roland/simplify-v1.0.0` | `4bc9010` | 8 |
| `refs/remotes/origin/test-ci-pr` | `6b4b797` | 8 |
| `refs/remotes/origin/tom/ci-deploy-evaluation` | `82599b2` | 42 |
| `refs/remotes/origin/tom/issue4-remaining-metrics` | `0d9f085` | 41 |
| `refs/tags/archive/main-pre-rewrite` | `b0ca4ef` | 38 |
| `refs/tags/v1.0.0` | `e13ffb1` | 1 |
| `refs/tags/v2.0.0` | `9bb782a` | 28 |
| `refs/tags/v2.1.0` | `be4965c` | 33 |
| `refs/tags/v2.2.0` | `b0ca4ef` | 38 |

## Verification and limits

- Git comparison: all original document paths and all 147 recorded blob revisions are represented in the manifest; selected historical sources and pinned link targets were checked against their original Git trees.
- The recovered course brief was readable with pypdf: 4 pages, 6,169 extracted characters. Its bytes match the original Git blob.
- Navigation, section anchors, code-fence balance, whitespace, instruction imports, and staged diff validation are checked using the previously existing checker from `ci/root-suites`, run as a session-only tool. Final pre-commit check: 86 Markdown files and 626 local links, no violations; staged diff whitespace check passed. Detailed results are recorded in today's P015 entry.
- Application code, workflows, dependencies and deployment configuration are unchanged relative to v3. No services were restarted and no runtime tests were claimed for this documentation repair.
- Original checkout preservation is checked before handoff. Earlier local changes remain available there; their snapshots and proposals are also included in this repair.
- Human review of the recovered collection is not recorded. Published historical tags and release branches remain unchanged. The repair is submitted separately so it can be reviewed before merging into `main`.
