# Monitoring — future improvements

Recorded: 2026-09-25. Current state: Prometheus scrapes both services, all delivery
and crypto metrics are wired, and the Grafana dashboard loads automatically. The items
below are improvements worth considering but not required for the current evaluation.

---

## 1. Latency comparison requires running both modes

The last row of the Grafana dashboard compares plaintext vs ML-KEM request latency by
splitting on the `security_mode` label. Because the current Compose setup always runs
with `GATEWAY_ML_KEM_MODE=enabled`, only one mode appears in the history. To see both
lines on the same chart you need to run the stack in `off` mode for a period, then
switch to `enabled` — Prometheus stores the history so both series will eventually
appear together.

Practical approach: bring the stack up with `GATEWAY_ML_KEM_MODE=off` for a few
minutes, then restart the gateway with `GATEWAY_ML_KEM_MODE=enabled` and let it run
for another few minutes. The comparison panel will then show both series.

---

## 2. No alerts configured

The security alarm panels (AEAD decrypt failures, handshake auth failures, forced
rekeys) are visual only. Grafana supports email and Slack alerting but nothing is
configured here. In a real deployment you would want an alert that fires immediately
if `cloud_crypto_decrypt_failures_total` starts rising, since any non-zero value
indicates either tampering or a session bug.

For a course project running locally this is acceptable — no one is monitoring the
system overnight.

---

## 3. Build info panels not on the dashboard

Both services expose `gateway_build_info` and `cloud_build_info` metrics containing
the running version, git commit, and Python version. These are not currently shown on
the dashboard. Adding two stat panels in a header row would make it immediately clear
which version of the code is running when looking at a graph, which is useful when
comparing results across releases.
