# Reliability and monitoring design — 2026-10-05

The user authorized implementation of four referenced proposals on a new worktree
and a PR targeting `develop`, using GPT-5.6 SOL subagents. Baseline: active v3 at
`9f4ecee`. The original checkout has unrelated uncommitted records and is preserved.

## Scope and choices

- Cloud storage: SQLite at `/data/readings.sqlite3` on the `cloud-data` named
  volume. One connection per operation, parameterized inserts, commit before
  acknowledgement, insertion-order reads. Unlimited retention preserves v3's
  contract; monitor disk usage and add a separately agreed retention policy later.
  SQLite fits the single-cloud deployment; PostgreSQL adds unnecessary operations
  for this scope, and an append-only JSON file would need custom concurrency and
  recovery handling. Storage errors return HTTP 503 without success metrics.
- Security: v3 has no old `off/enabled/required` gate. Disable plaintext cloud
  ingestion by default. The explicit `CLOUD_ALLOW_LEGACY_INGESTION=true`
  compatibility choice retains the legacy path and warnings; empty/unknown
  settings fail startup. Preserve the reading API and encrypted gateway delivery.
  Gateway encryption never falls back to plaintext. Endpoint authentication,
  development key replacement and complete replay prevention are separate work.
- Sensors: device read failure sends a temperature-free `/device-status` report;
  gateway distinguishes explicit disconnects, repeated-value suspicions and
  missing contact. Three consecutive identical normal readings start one suspected
  stuck episode; changed values, sentinels or disconnects clear the suspicion.
  Thirty seconds without contact flags silence. Configurable thresholds, bounded
  process-local registry and aggregate gauges avoid unlimited metric labels.
- Monitoring: optional Compose overlay; Prometheus scrapes gateway/cloud every
  15 seconds and retains 30 days on a named volume. Provisioned Grafana datasource
  and twelve-panel dashboard. Alertmanager routes firing/recovery notifications
  to the user-selected local persistent inbox. An external webhook would require
  a user-selected destination; a dashboard without a receiver would not meet the
  notification acceptance criterion. Monitoring ports bind only to loopback.

## Verification and completion

Run each service's test suite in its own Python process, plus tooling regressions,
Python compilation, Compose validation, promtool configuration/rule tests and
amtool configuration validation. A generated isolated Docker project exercises
exact secure and explicitly enabled legacy readings across restart/recreation,
default plaintext rejection without storage, sensor status/stuck/recovery/silence,
healthy scrape targets, dashboard provisioning, retained Prometheus history,
and a real two-minute cloud outage followed by firing and resolved inbox records.
Recreate the inbox to verify notifications persist. CI repeats these checks.

Update the current README/runbook and add a new human phase summary; preserve old
phase documents as historical evidence. Append the exact user prompt and executed
results to the existing person/date AI record. Publish a PR to `develop`; no merge
or shared deployment is requested. Human review of the resulting code is pending.
