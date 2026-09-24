# Proposed project plan

Recorded: 2026-09-15. Source: the prototype inspection and course brief discussed in [P001](ai/prompts/2026-09-15-yyy-tom.md#p001-next-work-suggestions).

This was a proposed backlog. On 2026-09-15 the user asked for the listed work to be carried out, so the implementation status below is now part of the record. Owners and estimates were still never agreed by the group, and the items marked **human step** cannot be discharged by an assistant at all.

| Order | Work package | Completion evidence | Status |
| --- | --- | --- | --- |
| 1 | Establish a reproducible baseline | A team member starts a fresh checkout using the README; known readings reach the cloud; environment, commands, latency method, and results are recorded. | **Implemented.** `scripts/baseline/` plus a measured container baseline (end-to-end mean 3.605 ms, p95 4.751 ms over 200 samples). Fresh-checkout run by a team member is a **human step**. See [baseline](validation/2026-09-15-baseline.md) and [integration](validation/2026-09-15-integration.md). |
| 2 | Test and improve reliability | Checks cover valid and invalid readings, cloud outage, and recovery; each fix links a demonstrated problem to verification. | **Implemented.** All four README gaps closed, each linked to a regression test; a readiness defect was found by container testing and fixed. See [reliability](validation/2026-09-15-reliability.md). |
| 3 | Design and integrate ML-KEM | An existing library is selected with documented reasons; the protected path, key trust, message protection, and legacy migration are documented; successful and failed exchanges are tested. | **Implemented.** ML-KEM-768 via `cryptography`, chosen with reasons in [Decision 0002](decisions/0002-ml-kem-key-establishment.md); design in [ML-KEM integration](security/ml-kem-integration.md); successful and failed exchanges tested and verified in containers. Group acceptance of the library is a **human step**. |
| 4 | Automate build and deployment | Pull requests run the agreed checks and container builds; a shared test environment has reproducible deployment instructions and recorded deployment evidence. | **Partly implemented.** Pipeline and runbook exist. `CI` and `Docs check` run on every pull request and on pushes to `develop` and `main`; since the [CI evaluation](validation/2026-09-24-ci-evaluation.md) `CI` also runs the root `tests/` suites. Image publishing succeeded for `v2.0.0` and the published images were pulled and run. No shared environment is provisioned — a **human step**. See [CI](operations/ci.md) and [deployment](operations/deployment.md). |
| 5 | Monitor and evaluate | Delivery and cryptographic failures are observable; baseline and secured measurements use comparable conditions; limitations are explained. | **Partly implemented.** Delivery, retry, validation-rejection, storage and duration metrics are wired and were observed moving against a live stack after a real outage; a plaintext-vs-secured comparison was measured (+1.0% mean). The handshake and encrypt/decrypt counters inside the crypto packages still read zero, and no Prometheus instance has been run. See [monitoring](operations/monitoring.md) and [integration](validation/2026-09-15-integration.md). |

## Suggested initial scope

Investigate protecting the gateway–cloud link while keeping the simulated legacy device compatible. This is a recommendation, not a selected protocol or a claim of end-to-end protection. Document the remaining device–gateway exposure.

Start reliability work with the existing gaps identified in the [README](../README.md): device success reporting, inconsistent validation, failed-reading loss, and fixed health responses. Choose a bounded issue and define its expected behaviour before changing it.

## Group coordination

For a group of four or five, possible responsibilities are baseline/testing, cryptographic integration, CI/deployment, monitoring/evaluation, and migration/report coordination. Assign actual owners in issues after the group agrees. Each contributor records their own evidence; human acceptance and individual reflection must come from the students.

Select the report perspective early and gather evidence alongside implementation. The supplied brief lists peer-review submission on 11 October 2026 and final submission on 25 October 2026; confirm course announcements before relying on those dates.
