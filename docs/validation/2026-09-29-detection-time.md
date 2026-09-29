# Detection time and accuracy — 2026-09-29

Metric from [issue #4](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/issues/4), where it is assigned to Francisca. This run was performed by yyy-tom with Claude Code (Opus); Francisca did not take part in it. Human review: not recorded.

Issue #4 row: "Inject a known outage or authentication failure. Measure time until the monitoring system signals it; compare reported event counts with the injected events. Record missed and false signals."

The repository has no Prometheus alert rules, so the main measurement is how long an injected fault takes to become visible in Prometheus as `up == 0` or as a failure counter going up. Four candidate alert rules were tested separately, in a scratch Prometheus configuration outside the repository. They are a [proposal](#proposal-alert-rules-and-their-time-to-fire) and have not been added to `monitoring/`.

## Summary

| Injection (3 trials each) | First signal in Prometheus, median from injection | Candidate alert firing, median from injection | Injected failed readings | Counted by metrics | Missed | False |
| --- | --- | --- | --- | --- | --- | --- |
| Cloud stopped for 90 s | `up{job="cloud"} == 0`: 3.0 s; `cloud_forward_failures_total` up: 16.1 s | `CloudForwardFailures` 27.1 s; `CloudTargetDown` 46.2 s | 54 | 54 | 0 | 0 |
| Gateway with a wrong `ML_KEM_PSK` for 90 s | a failure counter up: 6.0 s; `cloud_handshake_failed_total{reason="verification_failed"}` up: 10.0 s | `CloudForwardFailures` 20.1 s; `HandshakeAuthFailure` 29.1 s | 54 | 54 | 0 | 0 |
| Gateway stopped for 90 s | `up{job="gateway"} == 0`: 13.1 s | `GatewayTargetDown` 56.2 s | 54 | 0 (no counter can see them) | 0 outages; readings not countable | 0 |

- Every injected fault was signalled in every trial. For the cloud outage and the authentication failure, each failure counter matched the injected count exactly (18 per trial).
- No signal appeared without an injection: none in the 5-minute quiet baseline, none in the recovery periods. The rules only kept firing for their look-back window after recovery.
- Six valid readings were lost without any injection, between the device and the gateway (`Connection aborted`), and no metric recorded them. These are the only missed signals found. They repeat the [open `RemoteDisconnected` finding](2026-09-28-ds18b20-faults.md#open-finding-remotedisconnected-on-valid-readings) with the default `uniform` device.

## Environment

| Item | Value |
| --- | --- |
| Code | `0f309bd` (v2.2.0, branch `tom/issue4-remaining-metrics`), no source changes |
| Host | Apple M4 Pro (arm64), 12 cores, macOS 15.7.5 |
| Docker | Docker Desktop, Engine 29.4.3 (linux/arm64), Compose v5.1.3; VM has 12 CPUs and 7.75 GiB |
| Monitoring | `prom/prometheus:v2.54.1`, `grafana/grafana:11.2.0`, from [`monitoring/docker-compose.monitoring.yml`](../../monitoring/docker-compose.monitoring.yml) |
| Compose project | `m4detect`, host ports bound to `127.0.0.1`: gateway 28000, cloud 28001, Prometheus 29090, Grafana 23000 |
| Scrape and rule evaluation | `scrape_interval: 15s`, `scrape_timeout: 10s`, `evaluation_interval: 15s`, as in [`monitoring/prometheus.yml`](../../monitoring/prometheus.yml) |
| Security mode | Compose defaults: `CLOUD_ML_KEM_MODE=enabled`, `GATEWAY_ML_KEM_MODE=enabled` |
| Device | Compose defaults: `uniform` model, no faults, one reading every 5 s |
| Measurement script | [`scripts/evaluation/measure_detection.py`](../../scripts/evaluation/measure_detection.py), host Python 3.13.12, `requests` 2.34.2 |
| Clock | Prometheus `time()` minus host time: +0.001 s at the start of the run. Docker log timestamps come from the same Docker Desktop VM clock. |
| Run | 2026-09-29, 11:06:46–11:49:14 UTC |

Two other Compose projects, `m4deliver` (ports 38000–38001) and `m4latency` (ports 48000–48001), were running on the same host during the run. The main project stack on ports 8000/8001 was not touched.

### Scratch configuration outside the repository

The Compose files were used unchanged. A session-scratch override file changed only the port bindings (`ports: !override`) and the Prometheus mounts, so that Prometheus loaded a copy of `monitoring/prometheus.yml` with one addition:

```yaml
rule_files:
  - /etc/prometheus/rules.yml
```

For the authentication trials, a second override set `ML_KEM_PSK: wrong-psk-injected-for-detection-test` on the `gateway` service only. The cloud kept the Compose default key. Both override files were deleted after the run.

## Method

`measure_detection.py` ran one 300-second quiet baseline and then three trials of each injection in sequence. During each trial it polled Prometheus once per second: the latest raw sample of `up` and of every failure counter (`cloud_forward_failures_total`, `gateway_delivery_outcome_total`, `gateway_cloud_retries_exhausted_total`, `gateway_handshake_failed_total`, `cloud_handshake_failed_total`, `cloud_crypto_decrypt_failures_total`), plus `/api/v1/alerts`.

| Injection | Injected with | Injection time `t0` | Recovered with |
| --- | --- | --- | --- |
| Cloud outage | `docker compose -p m4detect … stop cloud` | `stop` returned | `start cloud`, recovered when cloud `/health` returned 200 |
| Authentication failure | `up -d --no-deps gateway` with the wrong-key override | recreated gateway's `/health` returned 200 | `stop device`, 20 s wait, `up -d --no-deps gateway` without the override, `start device` |
| Gateway down | `stop gateway` | `stop` returned | `start gateway`, recovered when gateway `/health` returned 200 |

Each fault was held for 90 s after `t0`, and each trial then watched 150 s of recovery. In the authentication trials the device was stopped at the end of the 90 s, and the gateway was restored 20 s later, more than one scrape interval. Without this wait, failures counted by the wrong-key gateway after its last scrape would be lost when the process is replaced, and would show up as missed counts.

Detection times are reported two ways, both from `t0`:

- **Seen**: the poll in which the script first saw the signal, which is what someone watching Prometheus would see.
- **Scraped**: the timestamp of the Prometheus sample carrying it. This is the lower limit; the difference is the 1 s poll interval and query time.

Injected events come from the container logs (`docker compose logs --timestamps`): device lines `Gateway rejected reading … status_code=502` for the cloud outage and the authentication failure, device lines `Failed to deliver reading` for the gateway outage, and cloud access-log lines `POST /secure/handshake … 401` for the authentication failure. Counts in Prometheus are the increase over the trial computed from raw samples, with counter resets handled and without the extrapolation `increase()` applies.

A signal is **false** when it appears with no injection active: in the baseline, or during recovery after the look-back window of the rule has passed. A signal during an injection, or a rule still firing within its look-back window after recovery, is not false.

A 5 s, single-trial dry run of the authentication injection was made before the recorded run to check the script. It is not part of the results. Its `HandshakeAuthFailure` alert was still firing, from that dry run, when the baseline began; it cleared at 11:07:48 UTC and is not counted as a false signal.

## Cloud outage

| Trial | `t0` (UTC) | First failed reading | `up{job="cloud"} == 0` seen (scraped) | `cloud_forward_failures_total` up, seen (scraped) | `CloudForwardFailures` firing | `CloudTargetDown` pending / firing |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:11:47.502 | +1.7 s | +3.0 s (+2.2 s) | +5.0 s (+4.9 s) | +16.1 s | +16.1 s / +46.2 s |
| 2 | 11:15:49.724 | +4.6 s | +0.0 s (−0.0 s) | +18.1 s (+17.7 s) | +29.1 s | +14.1 s / +44.2 s |
| 3 | 11:19:51.931 | +2.6 s | +13.1 s (+12.8 s) | +16.1 s (+15.5 s) | +27.1 s | +27.1 s / +57.2 s |
| Median | | +2.6 s | +3.0 s | +16.1 s | +27.1 s | +16.1 s / +46.2 s |

In trial 2 a scrape happened while the container was being stopped, 0.02 s before `stop` returned, so `up == 0` appeared at `t0`.

| Trial | Device `502` (injected) | Gateway log forwarding errors | `cloud_forward_failures_total` | `gateway_delivery_outcome_total{outcome="failed_after_retries"}` | `gateway_cloud_retries_exhausted_total` |
| --- | --- | --- | --- | --- | --- |
| 1 | 18 | 18 | 18 | 18 | 18 |
| 2 | 18 | 18 | 18 | 18 | 18 |
| 3 | 18 | 18 | 18 | 18 | 18 |

Recovery: the cloud answered `/health` 0.4–0.8 s after `start`. `up{job="cloud"}` returned to 1 after 2.0, 15.1 and 12.0 s. After the restart the gateway re-established its session on its own: `gateway_session_rekeys_total{reason="forced"}` went up by 1 in each trial, and no failure counter moved. `CloudTargetDown` resolved 13–14 s after `up` returned, and `CloudForwardFailures` resolved 55–60 s after recovery, when the last failure left its 1-minute window.

## Authentication failure (wrong `ML_KEM_PSK` on the gateway)

The recreated gateway starts with no session, so the first reading after `t0` triggers a handshake. The cloud rejects the client MAC with 401, the gateway returns 502 to the device, and every following reading repeats this.

| Trial | `t0` (UTC) | First failed reading | First failure counter up, seen (scraped) | `cloud_handshake_failed_total{reason="verification_failed"}` seen (scraped) | `gateway_handshake_failed_total` seen (scraped) | `CloudForwardFailures` firing | `HandshakeAuthFailure` firing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:23:55.076 | +4.0 s | +10.0 s (+9.6 s) | +10.0 s (+9.6 s) | +13.0 s (+12.3 s) | +23.1 s | +38.1 s |
| 2 | 11:28:19.364 | +3.0 s | +4.0 s (+3.1 s) | +16.1 s (+15.4 s) | +4.0 s (+3.1 s) | +14.1 s | +29.1 s |
| 3 | 11:32:44.034 | +2.7 s | +6.0 s (+5.7 s) | +6.0 s (+5.7 s) | +9.0 s (+8.4 s) | +20.1 s | +20.1 s |
| Median | | +3.0 s | +6.0 s | +10.0 s | +9.0 s | +20.1 s | +29.1 s |

No `up` signal appeared: each recreation took 1.1–1.3 s and fell between two scrapes in all six cases.

| Trial | Device `502` (injected) | Cloud `401` on `/secure/handshake` | `cloud_handshake_failed_total{reason="verification_failed"}` | `gateway_handshake_failed_total{reason="other"}` | `cloud_forward_failures_total` | `failed_after_retries` | `gateway_cloud_retries_exhausted_total` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 18 | 18 | 18 | 18 | 18 | 18 | 0 |
| 2 | 18 | 18 | 18 | 18 | 18 | 18 | 0 |
| 3 | 18 | 18 | 18 | 18 | 18 | 18 | 0 |

Two points about how the failure is reported:

- **The gateway labels it `reason="other"`, not `verification_failed`.** The cloud's 401 reaches the gateway as `requests.HTTPError` from `raise_for_status()`, which `_classify_handshake_error` in [`gateway/app/crypto/client.py`](../../gateway/app/crypto/client.py) does not map. `verification_failed` is only used when the gateway itself rejects the server MAC. On its own, the gateway metric cannot tell a wrong key from other HTTP errors; the cloud's label can.
- **It is not retried.** `HTTPError` is not in `RETRYABLE_EXCEPTIONS` in [`gateway/app/cloud_client.py`](../../gateway/app/cloud_client.py), so it leaves the retry loop at once and is counted by the generic `except Exception` branch in [`gateway/app/main.py`](../../gateway/app/main.py) as `failed_after_retries`. `gateway_cloud_retries_exhausted_total` does not move. A rule on that counter alone would miss this fault.

In trial 1 `HandshakeAuthFailure` fired 9–18 s later than in trials 2 and 3. The cloud had been restarted by the cloud-outage trials, so `cloud_handshake_failed_total{reason="verification_failed"}` did not exist yet. Its first sample already had the value 2, and `increase()` needs two samples in the window, so the rule could only fire one scrape later.

## Gateway down

| Trial | `t0` (UTC) | First failed reading | `up{job="gateway"} == 0` seen (scraped) | `GatewayTargetDown` pending / firing |
| --- | --- | --- | --- | --- |
| 1 | 11:37:07.854 | +3.7 s | +15.1 s (+14.6 s) | +26.1 s / +56.2 s |
| 2 | 11:41:10.231 | +1.5 s | +13.1 s (+12.2 s) | +23.1 s / +53.2 s |
| 3 | 11:45:12.905 | +3.9 s | +10.0 s (+9.5 s) | +36.1 s / +65.2 s |
| Median | | +3.7 s | +13.1 s | +26.1 s / +56.2 s |

The device's failed readings, 18 per trial, 54 in total, are not in any metric. The device exposes no metrics, and the gateway holds `device_messages_total`, so its counters stop with it and restart from zero. The outage itself was signalled every time; how many readings it cost can only be estimated from the length of the gap. `up` returned to 1 after 14.1, 12.1 and 9.1 s, and the alert resolved 10–26 s after that.

## Missed and false signals

**False signals: 0.** From 11:06:46 to 11:11:46 UTC (baseline) and in every recovery period, no `up == 0`, no failure-counter change and no alert appeared without an injection. The only baseline alert was the dry run's trailing `HandshakeAuthFailure`, described under [Method](#method).

**Missed injected faults: 0.** All nine injections were signalled. Every failed reading in the cloud outage and authentication trials was counted, 108 of 108.

**Missed events without an injection: 6.** Six of 498 readings from 11:06:46 to 11:49:14 UTC (1.2 %) failed at the device with `('Connection aborted.', RemoteDisconnected(...))` or `ConnectionResetError(104, ...)`. They were at 11:08:53, 11:18:03, 11:23:19, 11:38:56, 11:39:41 and 11:48:41 UTC: one in the quiet baseline and five in recovery periods, 18 s or more after the service had recovered. The two checked in the gateway log (11:08:53 and 11:18:03) have no matching request there. No gateway counter can see them: in the baseline the device sent 60 readings and logged one such failure, and the gateway log shows 59 received. The device uses one `requests.Session`, and the gateway runs uvicorn with its default 5-second keep-alive timeout, equal to the device's send interval. This fits the hypothesis in the [DS18B20 record](2026-09-28-ds18b20-faults.md#open-finding-remotedisconnected-on-valid-readings), and this run is the longer `uniform`-device run suggested there. It is still not a proven cause.

## Proposal: alert rules and their time-to-fire

**Proposal only. These rules are not in the repository.** They were loaded into the scratch Prometheus described above, with the repository's 15 s scrape and evaluation interval:

```yaml
groups:
  - name: detection-proposal
    rules:
      - alert: CloudTargetDown
        expr: up{job="cloud"} == 0
        for: 30s
      - alert: GatewayTargetDown
        expr: up{job="gateway"} == 0
        for: 30s
      - alert: CloudForwardFailures
        expr: increase(cloud_forward_failures_total[1m]) > 0
      - alert: HandshakeAuthFailure
        expr: increase(cloud_handshake_failed_total{reason="verification_failed"}[2m]) > 0
```

| Rule | Injection | Firing after `t0`, trials 1 / 2 / 3 | Median | Resolved after recovery | Fired without injection |
| --- | --- | --- | --- | --- | --- |
| `CloudForwardFailures` | cloud outage | 16.1 / 29.1 / 27.1 s | 27.1 s | 55–60 s | 0 |
| `CloudForwardFailures` | wrong key | 23.1 / 14.1 / 20.1 s | 20.1 s | 61–69 s after the last failure | 0 |
| `HandshakeAuthFailure` | wrong key | 38.1 / 29.1 / 20.1 s | 29.1 s | 122–129 s after the last failure | 0 |
| `CloudTargetDown` (`for: 30s`) | cloud outage | 46.2 / 44.2 / 57.2 s | 46.2 s | 13–14 s after `up` returned | 0 |
| `GatewayTargetDown` (`for: 30s`) | gateway down | 56.2 / 53.2 / 65.2 s | 56.2 s | 10–26 s after `up` returned | 0 |

The expected worst case for an `up` rule with `for: 30s` is one scrape (15 s), plus one evaluation (15 s), plus 30 s, plus one more evaluation (15 s): about 75 s. This is why each fault was held for 90 s. The observed 44–65 s is within that. The `pending` times in the tables above show what the same rule with `for: 0s` would have done: 14–27 s for the cloud and 23–36 s for the gateway. The `for` clause guards against a single failed scrape; none happened in this run, so the run gives no evidence on whether it is needed.

Choices the rules make:

- Alert on `cloud_forward_failures_total`, not on `gateway_cloud_retries_exhausted_total`. The latter missed all 54 authentication failures.
- Alert on the cloud's `verification_failed` label. The gateway reports a wrong key as `reason="other"`.
- Take the "Target down" row of [Alerting suggestions](../operations/monitoring.md#alerting-suggestions). The rate-and-ratio suggestions there use 5-minute windows with `for: 5m`, so they would fire only after about 5 minutes; they were not tested here.
- No rule can report how many readings a gateway outage cost, and none sees the keep-alive losses. Both would need a device-side metric or a device-side log count.

## Limits

- One host, one device at 5-second intervals, no network latency or loss between containers, and other projects' stacks sharing the CPU. Times depend mainly on where the injection falls in the 15 s scrape and evaluation cycle, so three trials per type show the spread, not a distribution; a median of three is a rough figure.
- Injections were made with `docker compose stop` and container recreation. These are clean stops: DNS for the stopped service fails at once. A hung process or a network partition would show up in `up` only after the 10 s scrape timeout, and the gateway would fail each reading only after its 1 s per-attempt timeout and retries.
- A wrong key is injected by recreating the gateway, which also restarts its counters. For the same reason, the wrong-key gateway's own log was removed with its container, so its received count is missing (`0` in the saved JSON). The device and cloud logs cover those trials.
- The count comparison uses counter increases over each trial. That window is bounded by scrape times at both ends (the last sample before the injection command and the last sample before the end of recovery), while the log window is bounded by wall-clock times, so `forwarded` totals differ from the device's count by up to 3 in either direction. Failure counts are not affected: failures began after `t0` and ended long before the end of the window.
- The 1 s poll interval limits the "seen" time; the "scraped" time does not depend on it.
- No notification path (Alertmanager, Grafana alerting) exists or was tested. Times in this record end at Prometheus showing an alert as `firing`.

## Not run

- Injections without a clean stop: `docker pause`, network disconnection, or a hung handler.
- A mismatched key injected on the cloud side, or a pinned-fingerprint mismatch (`GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT`).
- Grafana. It was started with the stack but not used.
- The rate-and-ratio alert suggestions from [docs/operations/monitoring.md](../operations/monitoring.md#alerting-suggestions).

## Reproducing

Use a separate Compose project with its own ports. Create two override files outside the repository:

```yaml
# override.yml; replace /abs/scratch with the directory holding these files
services:
  cloud:
    ports: !override
      - "127.0.0.1:28001:8001"
  gateway:
    ports: !override
      - "127.0.0.1:28000:8000"
  prometheus:
    ports: !override
      - "127.0.0.1:29090:9090"
    volumes: !override
      - /abs/scratch/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /abs/scratch/rules.yml:/etc/prometheus/rules.yml:ro
  grafana:
    ports: !override
      - "127.0.0.1:23000:3000"
```

```yaml
# wrong-psk.yml
services:
  gateway:
    environment:
      ML_KEM_PSK: wrong-psk-injected-for-detection-test
```

`/abs/scratch/prometheus.yml` is a copy of `monitoring/prometheus.yml` with the `rule_files` block shown under [Scratch configuration](#scratch-configuration-outside-the-repository). `rules.yml` holds the rules from the [proposal](#proposal-alert-rules-and-their-time-to-fire); an empty `groups: []` measures without alerts. Then, from the repository root:

```sh
docker compose -p m4detect -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml \
  -f /abs/scratch/override.yml up --build -d
python3 scripts/evaluation/measure_detection.py --project m4detect \
  -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml -f /abs/scratch/override.yml \
  --wrong-psk-file /abs/scratch/wrong-psk.yml --out /abs/scratch/run.json
docker compose -p m4detect -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml \
  -f /abs/scratch/override.yml down -v
```

The defaults are the values used here: 300 s baseline, 3 trials of each injection, 90 s fault, 20 s settle, 150 s recovery and 1 s polling. The full run takes about 43 minutes. The script only calls `docker compose` with the given `--project` and files, and it only stops, starts or recreates single services. It writes every trial, including the raw signal events and log counts, to the `--out` JSON file. The JSON of this run was kept in session scratch space and is not committed; the tables above were taken from it and from the container logs.
