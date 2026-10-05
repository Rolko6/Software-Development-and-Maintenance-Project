> Historical pre-v3 documentation, recovered from the uncommitted local checkout on 2026-10-05. Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../../../../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Proposed project plan

Recorded: 2026-09-15. Source: the prototype inspection and course brief discussed in [P001](../../../pre-v3/docs/ai/prompts/2026-09-15-yyy-tom.md#p001-next-work-suggestions).

This was a proposed backlog. On 2026-09-15 the user asked for the listed work to be carried out, so the implementation status below is now part of the record. Owners and estimates were still never agreed by the group, and the items marked **human step** cannot be discharged by an assistant at all.

| Order | Work package | Completion evidence | Status |
| --- | --- | --- | --- |
| 1 | Establish a reproducible baseline | A team member starts a fresh checkout using the README; known readings reach the cloud; environment, commands, latency method, and results are recorded. | **Implemented.** `scripts/baseline/` plus a measured container baseline (end-to-end mean 3.605 ms, p95 4.751 ms over 200 samples). Fresh-checkout run by a team member is a **human step**. See [baseline](../../../pre-v3/docs/validation/2026-09-15-baseline.md) and [integration](../../../pre-v3/docs/validation/2026-09-15-integration.md). |
| 2 | Test and improve reliability | Checks cover valid and invalid readings, cloud outage, and recovery; each fix links a demonstrated problem to verification. | **Implemented.** All four README gaps closed, each linked to a regression test; a readiness defect was found by container testing and fixed. See [reliability](../../../pre-v3/docs/validation/2026-09-15-reliability.md). |
| 3 | Design and integrate ML-KEM | An existing library is selected with documented reasons; the protected path, key trust, message protection, and legacy migration are documented; successful and failed exchanges are tested. | **Implemented.** ML-KEM-768 via `cryptography`, chosen with reasons in [Decision 0002](../../../pre-v3/docs/decisions/0002-ml-kem-key-establishment.md); design in [ML-KEM integration](../../../pre-v3/docs/security/ml-kem-integration.md); successful and failed exchanges tested and verified in containers. Group acceptance of the library is a **human step**. |
| 4 | Automate build and deployment | Pull requests run the agreed checks and container builds; a shared test environment has reproducible deployment instructions and recorded deployment evidence. | **Partly implemented.** Pipeline and runbook exist. `CI` and `Docs check` run on every pull request and on pushes to `develop` and `main`; since the [CI evaluation](../../../pre-v3/docs/validation/2026-09-24-ci-evaluation.md) `CI` also runs the root `tests/` suites. Image publishing succeeded for `v2.0.0` and the published images were pulled and run. No shared environment is provisioned — a **human step**. See [CI](../../../pre-v3/docs/operations/ci.md) and [deployment](../../../pre-v3/docs/operations/deployment.md). |
| 5 | Monitor and evaluate | Delivery and cryptographic failures are observable; baseline and secured measurements use comparable conditions; limitations are explained. | **Partly implemented.** Delivery, retry, validation-rejection, storage and duration metrics are wired and were observed moving against a live stack after a real outage; a plaintext-vs-secured comparison was measured (+1.0% mean). The handshake and encrypt/decrypt counters inside the crypto packages still read zero, and no Prometheus instance has been run. See [monitoring](../../../pre-v3/docs/operations/monitoring.md) and [integration](../../../pre-v3/docs/validation/2026-09-15-integration.md). |

## Suggested initial scope

Investigate protecting the gateway–cloud link while keeping the simulated legacy device compatible. This is a recommendation, not a selected protocol or a claim of end-to-end protection. Document the remaining device–gateway exposure.

Start reliability work with the existing gaps identified in the [README](../../../../../README.md): device success reporting, inconsistent validation, failed-reading loss, and fixed health responses. Choose a bounded issue and define its expected behaviour before changing it.

## Group coordination

For a group of four or five, possible responsibilities are baseline/testing, cryptographic integration, CI/deployment, monitoring/evaluation, and migration/report coordination. Assign actual owners in issues after the group agrees. Each contributor records their own evidence; human acceptance and individual reflection must come from the students.

Select the report perspective early and gather evidence alongside implementation. The supplied brief lists peer-review submission on 11 October 2026 and final submission on 25 October 2026; confirm course announcements before relying on those dates.

## Proposed security follow-up — 2026-10-05

**Priority: close the plaintext cloud-ingestion bypass.** Compose currently selects
`CLOUD_ML_KEM_MODE=enabled`, which accepts direct plaintext `POST /data` alongside the
encrypted endpoint. This is a migration option, but it leaves encryption optional at
the receiving boundary. The legacy device can remain unchanged when the cloud
requires encryption, because the gateway performs the encryption.

Recommended work: default the cloud and gateway to `required` in the secured deployment
and when their mode variables are absent; reject empty or unknown application mode
values at startup instead of treating them as `off`; retain `off` and `enabled` only
as explicit baseline/migration choices. Verify the real cloud route rejects plaintext
without storing it, and that the unchanged device still delivers through the gateway's
secure path. Include negative tests for invalid configuration and failed secure
establishment with no plaintext fallback. Details, alternatives, and acceptance
criteria: [security finding](../../../pre-v3/docs/security/plaintext-ingestion-bypass.md).

Status: **Proposed, not implemented.** Source: [P012](../../../../ai/prompts/2026-10-05-yyy-tom.md#p012-record-the-plaintext-ingestion-bypass-and-suggest-a-fix).
