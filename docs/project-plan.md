# Proposed project plan

Recorded: 2026-09-15. Source: the prototype inspection and course brief discussed in [P001](ai/prompts/2026-09-15.md#p001-next-work-suggestions).

This is a proposed backlog. Owners, implementation choices, and estimates have not been agreed by the group. A listed task is not authorization for an agent to start it.

| Order | Work package | Completion evidence |
| --- | --- | --- |
| 1 | Establish a reproducible baseline | A team member starts a fresh checkout using the README; known readings reach the cloud; environment, commands, latency method, and results are recorded. |
| 2 | Test and improve reliability | Checks cover valid and invalid readings, cloud outage, and recovery; each fix links a demonstrated problem to verification. |
| 3 | Design and integrate ML-KEM | An existing library is selected with documented reasons; the protected path, key trust, message protection, and legacy migration are documented; successful and failed exchanges are tested. |
| 4 | Automate build and deployment | Pull requests run the agreed checks and container builds; a shared test environment has reproducible deployment instructions and recorded deployment evidence. |
| 5 | Monitor and evaluate | Delivery and cryptographic failures are observable; baseline and secured measurements use comparable conditions; limitations are explained. |

## Suggested initial scope

Investigate protecting the gateway–cloud link while keeping the simulated legacy device compatible. This is a recommendation, not a selected protocol or a claim of end-to-end protection. Document the remaining device–gateway exposure.

Start reliability work with the existing gaps identified in the [README](../README.md): device success reporting, inconsistent validation, failed-reading loss, and fixed health responses. Choose a bounded issue and define its expected behaviour before changing it.

## Group coordination

For a group of four or five, possible responsibilities are baseline/testing, cryptographic integration, CI/deployment, monitoring/evaluation, and migration/report coordination. Assign actual owners in issues after the group agrees. Each contributor records their own evidence; human acceptance and individual reflection must come from the students.

Select the report perspective early and gather evidence alongside implementation. The supplied brief lists peer-review submission on 11 October 2026 and final submission on 25 October 2026; confirm course announcements before relying on those dates.

