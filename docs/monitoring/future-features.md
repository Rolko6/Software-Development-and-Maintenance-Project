> Historical pre-v3 documentation, recovered from [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/monitoring/future-features.md). Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

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

## 2. Alerts are not delivered anywhere

Prometheus evaluates the rules in `monitoring/alerts.yml` (service down, no readings
stored, delivery failures, failing handshakes, and the security signals behind the
alarm panels), and firing alerts are listed at http://localhost:9090/alerts. No
Alertmanager is configured, so nobody is notified: someone has to look. A real
deployment would add Alertmanager with an email or chat receiver.

For a course project running locally this is acceptable — no one is monitoring the
system overnight.

---

## 3. Build info panels not on the dashboard

Both services expose `gateway_build_info` and `cloud_build_info` metrics containing
the running version, git commit, and Python version. These are not currently shown on
the dashboard. Adding two stat panels in a header row would make it immediately clear
which version of the code is running when looking at a graph, which is useful when
comparing results across releases.
