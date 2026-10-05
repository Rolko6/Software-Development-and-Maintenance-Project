# Documentation — Reliability and monitoring follow-ups

**Date:** October 5, 2026
**Author(s):** yyy-tom (request); Codex with GPT-5.6 SOL implementation subagents
**Scope of this phase:** Implement four approved follow-ups to the active v3
architecture: durable readings, enforced secure cloud ingestion, sensor status
detection, and optional monitoring. This phase does not create a release/version tag.

---

## 1. Overview

Readings now commit to SQLite before acknowledgement and survive cloud restart
and container recreation. Direct plaintext cloud writes are disabled by default.
Devices report failed reads; gateway metrics distinguish disconnects, suspected
stuck readings and silence. An optional stack stores metric history, provisions a
dashboard and delivers outage/recovery notifications to a persistent local inbox.

## 2. AI-Assisted Development

- **Prompt (summary):** implement the four referenced plans with GPT-5.6 SOL
  subagents, a worktree and a PR targeting develop.
- **Output:** three subagents implemented storage, sensor state and security; root
  integrated monitoring, configuration, regression checks and documentation.
- **Decision:** user authorized implementation and selected the local inbox.
  Assistant review corrected timing, metrics and validation edge cases; human
  review of the code remains pending. Detailed prompt: [P021](../../docs/ai/prompts/2026-10-05-yyy-tom.md#p021-implement-four-reliability-and-monitoring-plans).

## 3. Baseline Analysis

The starting v3 stored readings in memory, accepted plaintext cloud writes,
exposed counters without a collector, and sent nothing on disconnected reads.
The new architecture preserves device→gateway→cloud; SQLite lives in cloud, sensor
state in gateway, and monitoring is an optional Compose overlay. See the
[runbook](../operations/reliability-monitoring.md) and
[executed validation](../validation/2026-10-05-reliability.md). Historical v3
results and raw measurement records are preserved.

## 4. Critical Evaluation & Maintenance

New regressions cover transaction rollback, concurrent/fresh-process persistence,
plaintext rejection without storage, invalid startup policy, malformed encrypted
payloads, episode counting/recovery, scrape-time silence and state capacity.
Review caught short simulator episodes clearing before a sustained stuck alert;
the episode counter now retains that signal. Finite temperature validation avoids
misclassifying invalid input as cloud failure, and forwarding failure ratios use
actual attempts. Storage/inbox failures return errors without success claims.

## 5. ML-KEM Integration

ML-KEM-768/AES-GCM remains unchanged. Gateway always encrypts and never falls
back to plaintext on encapsulation failure. The legacy device still posts the
same reading shape to gateway. Cloud legacy ingestion requires explicit opt-in
and warns/counts its use; this migration switch reopens the bypass deliberately.
Development key trust, endpoint authentication and full replay prevention remain
outside this change.

## 6. Operations

Base Compose mounts durable cloud storage. The optional overlay scrapes every
15 seconds, retains 30 days of Prometheus history, provisions twelve Grafana
panels, and routes firing/resolved notifications through Alertmanager. Monitoring
and inbox use separate named volumes. CI validates configuration and alert-rule
behavior, and runs an isolated outage/recovery smoke with retained raw evidence.
The [runbook](../operations/reliability-monitoring.md) describes configuration,
ports, thresholds, volume lifecycle and verification.

## 7. Final Evaluation

- **Strengths:** committed readings/history/notifications survive ordinary
  recreation; plaintext is rejected by default; fault causes have distinct signals
  and tests; the optional stack can be enabled without changing the base workflow.
- **Weaknesses:** local volumes are not backups/high availability; unlimited
  SQLite/inbox retention and unpaginated read responses require operational care.
- **Technical debt:** gateway tracker/counters are process-local, capped at 1000
  known devices by default, and intended for one worker; silence begins after
  first contact; repeating temperatures remain a suspicion.
- **Risks:** unauthenticated gateway/read APIs, development keys, replay within
  the timestamp window and explicit plaintext compatibility opt-in remain.
  Local monitoring ports are loopback-bound, but have no complete access control.
