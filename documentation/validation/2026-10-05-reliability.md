# Reliability and monitoring validation — 2026-10-05

Baseline: active v3 `9f4ecee` on `origin/develop`. Worktree branch:
`codex/reliability-monitoring`. The user requested all four proposals, GPT-5.6 SOL
subagents, a worktree and a PR to `develop`; selected a local persistent inbox.
The implementation and review were delegated to those subagents; root integrated
monitoring and executed container checks. Human code review remains pending.

## Executed source and test checks

| Check | Observed result |
| --- | --- |
| Device tests, separate process | 9 passed |
| Gateway tests, separate process | 50 passed |
| Cloud tests, separate process | 68 passed |
| Tooling tests | 34 passed |
| Current Python compilation | Passed |
| Base and optional Compose validation | Passed |
| Prometheus pinned-binary config check | Passed; 9 alert rules |
| promtool rule tests | Passed; availability hold-down/recovery, delivery ratios, sentinel threshold and all three sensor alerts |
| Alertmanager pinned-binary routing check | Passed; one configured local webhook receiver |
| `git diff --check` | Passed |

161 tests total. Gateway/cloud emit one existing Starlette/AnyIO deprecated-alias
warning per process. Local unit checks used the main checkout's existing `.venv`,
Python 3.13.12; CI/container Python is 3.12. Each service suite runs separately to
avoid the existing `app` package collision. No skips/xfails are reported.

## Executed Docker checks

The [v3 smoke evidence](data/2026-10-05-reliability-v3-smoke.json) records all nine
scenarios passing and cleanup passing: encrypted delivery, latency batches,
normal/outage delivery, cloud restart recovery with the committed marker retained,
and sentinel/invalid-envelope/cloud/gateway fault detection. These scenarios
poll directly; they do not themselves claim notification timing.

The [monitoring evidence](data/2026-10-05-reliability.json) records an isolated
six-service Docker stack, free loopback host ports and no simulator/background
traffic. It observed:

- Both Prometheus scrape targets healthy and a twelve-panel provisioned dashboard.
- Default plaintext submission rejected with 403 and no stored reading.
- Exact encrypted reading survives a process restart and cloud container recreation.
- Explicitly opted-in legacy reading survives return to secure-default recreation.
- Temperature-free disconnected status, stuck detection, recovery and silence.
- Historical metric values still queryable after Prometheus recreation.
- Actual cloud outage sends a firing notification, then recovery sends resolved.
- Notifications survive inbox recreation; final encrypted delivery succeeds.
- Session-created containers/networks/volumes removed; existing deployments untouched.

The initial run completed before the final review corrections and is preserved
in commit `d5be7ca`. The final evidence replaces the working record with a run
against that committed implementation; all checks passed. The script now also checks the disconnected gauge/failure counter
at a real scrape and enforces a two-minute minimum outage hold-down. It forces
secured cloud policy and known Grafana test credentials independent of ambient
shell settings.

## Review corrections and limits

Independent subagent review corrected the short stuck-alert pending period,
added sensor alert-rule tests, finite gateway validation, actual-forward-attempt
failure ratios, a storage-write inbox readiness check, test volume cleanup,
transient SQLite-path rejection and oversized timestamp handling. SQLite errors
cannot acknowledge failed writes or increment stored-success counters.

No shared deployment, external webhook, release tag or merge was performed.
Single cloud replica/single gateway worker, process-local bounded sensor state,
unlimited reading/inbox retention, unpaginated cloud reads, local-volume backups,
endpoint authentication, development keys and within-window replay remain as
[documented limits](../operations/reliability-monitoring.md). No earlier lost
in-memory readings can be recovered.

## Documentation and tools

Current syntax was fetched with Context7 from official Python sqlite3/FastAPI,
Prometheus client, Prometheus, Grafana, Alertmanager, Compose, Git and GitHub CLI
sources. Release tags were checked via official project GitHub APIs. Executed
images: Prometheus 3.15.0, Grafana 13.2.3, Alertmanager 0.34.1; Docker engine 29.4.3,
Compose v5.1.3, GitHub CLI 2.92.0. Runtime checks use the actual pinned tools,
not a claim inferred from configuration.

The historical documentation checker is executed as a session-only `/tmp` copy
from `ci/root-suites`, checking current Markdown links/anchors/fences/whitespace
and the standalone Claude import. Exact outcomes are appended at handoff.

## Final committed-source run and PR

The final isolated run used source `d5be7ca83c588a18e1ea0696ecaa5fbdc4dffff9` with a clean
working tree at invocation. Outcome and session cleanup both passed. The actual
cloud outage notification arrived after 157.6 seconds, exceeding the configured
two-minute hold-down; resolved notification arrived after recovery and remained
after inbox recreation. The disconnected gauge and read-failure counter were
observed at a real scrape before normal-reading recovery. All exact readings,
history, dashboard provisioning and post-outage secure delivery checks passed.

All twelve dashboard PromQL expressions also passed the pinned promtool parser
with the Grafana interval variable replaced by five minutes. Final documentation
validation passed for 97 Markdown files and 734 local links; compilation, config
and whitespace checks passed. [PR #18](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/18)
is open, non-draft, on `codex/reliability-monitoring` targeting `develop`.
GitHub CI service tests/builds pass where completed; some jobs were still queued
at the final evidence update. Local completed checks are distinct from queued
remote jobs. No merge was performed.
