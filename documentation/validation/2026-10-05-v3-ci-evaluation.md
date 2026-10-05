# Carry PRs #6, #13 and #14 forward to v3

The old PRs contain useful checks, but their session-based APIs and metrics do not match v3. This change implements their applicable ideas on active v3 `develop` (`0529036`), preserving the existing human README/phase organization and application behaviour.

| Source work | Active v3 equivalent |
| --- | --- |
| #6/#13 suite isolation | Existing service test jobs stay separate; a separate tooling job is added. |
| #6/#13 JUnit summaries and skip/xfail budgets | Restored summary helper, uploaded reports, zero skip/xfail budgets and a guard against a suite with no passes. |
| #6 protected-path requirements | Existing v3 crypto/tampering tests retained; added fresh per-reading KEM material and fail-closed encapsulation tests. |
| #13 import/static/Compose checks and smoke gating | V3 dependency imports, source compilation, Compose validation and an isolated encrypted-delivery/fault check gate publication. |
| #14 latency | Fresh request-to-ack samples, failure counts, median/p95; each successful request must increment v3 secure receipt counter once. No session-reuse labels. |
| #14 delivery/recovery | Unique reading IDs, pre-outage and final snapshots, explicit missing/duplicate counts and recovery to first stored new reading. |
| #14 detection | Direct polling of current forwarding-failure, rejected-envelope and sentinel counters; gateway availability observed through health polling. |

## Run it

Install the existing requirements, then use one command to build a separate temporary project, exercise the scenarios and clean it up:

```sh
pip install -r requirements-dev.txt
python scripts/evaluation/run_isolated.py --samples 30 --json-out /tmp/v3-evaluation.json
```

The runner starts gateway and cloud only, uses a unique project and stable temporary loopback ports, saves raw samples/results, and removes only its own containers/network. Config/key material is not included in the output. Port selection and container startup can fail if another process takes a selected port; that fails the run rather than changing a shared stack.

For an already running isolated stack, run a single scenario:

```sh
python scripts/evaluation/measure_v3.py latency --gateway-url http://127.0.0.1:8000 --cloud-url http://127.0.0.1:8001 --samples 30 --json-out /tmp/v3-latency.json
```

Available scenarios are `latency`, `delivery`, `outage-delivery`, `recovery`, and `detection`. Interruption scenarios also require `--project <your-isolated-project>`, `-f <compose-file>` if needed, and `--allow-interruption`. Before stopping a service the tool verifies that both URL ports belong to the named local Compose project. Detection faults are `cloud-outage`, `gateway-outage`, `sensor-sentinel`, and `invalid-envelope`.

## Interpret the evidence

- Latency includes gateway validation, per-reading encapsulation/encryption, forwarding, cloud processing and the HTTP response. Metric scrapes occur outside the timed interval. It does not isolate cryptographic CPU cost or compare a nonexistent reusable-session mode. Unexpected/missing counters and counter resets fail measurement.
- Delivery during an outage stops cloud after the first third of sends and restarts it after the second third. A pre-stop snapshot separates never-observed failed deliveries from acknowledged records lost across restart. Duplicate counts apply separately to each snapshot. Snapshot union is not proof of all transient storage events.
- Recovery starts at restart-command invocation. Sends start after that command completes, so the result includes command duration and polling/sending resolution; it is not a precise downtime measurement. Marker retention is reported, not assumed.
- Detection timing uses direct host polling, including fault-command/request duration. It does not deploy a Prometheus alert, measure production detection accuracy or establish sensor-disconnect/stuck detection. The short no-fault baseline only checks the isolated run for unexpected counter changes.
- Small CI samples verify the harness and contracts; they are not performance claims. CI uploads its raw JSON. Historical v2 reports are still evidence of their named versions, not fresh v3 measurements. Independent teammate deployment and cross-release comparison remain separate course deliverables.

## Source and verification

PR #6 head: `b297b28`; PR #13 head: `82599b2`; PR #14 head: `0d9f085`. The JUnit helper and its nine original regression tests come from #13 (which contains #6); two no-passes checks are added. The evaluation tool carries forward #14's measurement methods and reporting concepts, rewritten for current routes/counters. Old session/PSK/mode assertions, wire-file equality and old skip allowances do not apply to v3 and are not copied.

Current verification results and raw evidence are recorded in [the shared prompt record in PR #16](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/codex/restore-project-documentation/docs/ai/prompts/2026-10-05-yyy-tom.md#p020-carry-historical-ci-and-measurement-changes-into-active-v3). The implementation does not change application endpoints, encryption parameters, storage, dependencies, human phase documents or the existing main-only publication condition.

## Observed local check — 2026-10-05

[Raw results](data/2026-10-05-v3-evaluation.json) record the successful isolated run, including its dirty working-tree status during development. Application code matches v3 main; the new measurement code was under test.

- 76 tests passed: device 7, gateway 20, cloud 24, tooling 25.
- Six normal delivery readings were acknowledged and stored, with no loss or duplicates. During the controlled outage, two of six were rejected, and two previously stored readings were lost across cloud restart; these are separate loss causes.
- Recovery to a newly stored reading took about 0.94 seconds under the definition above. All four injected detection cases were observed and the restored stack delivered three further readings through secure ingestion.
- Isolated project cleanup passed and the two pre-existing unrelated containers remained running. These six-sample checks validate the tools; they are not benchmark comparisons or teammate deployment acceptance.

The old cryptography-implementation ACVP/vector suite is not transferred unchanged to v3's different `kyber-py` implementation. V3's existing primitive/tampering tests remain, with the two additional protected-path requirements above. Further implementation-assurance work needs matching vectors and an explicit verification scope.
