> Historical pre-v3 documentation, recovered from [0d9f085](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/docs/validation/2026-09-29-recovery-and-delivery.md). Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Recovery time and delivery, loss and duplication — 2026-09-29

Metrics from [issue #4](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/issues/4): recovery time is assigned to Tiago; delivery, loss and duplication to Tiago and Roland. This run was performed by yyy-tom with Claude Code (Opus); Tiago and Roland did not take part in it. Human review: not recorded.

Scope: the two issue #4 metrics below, measured on the v2.2.0 code (`0f309bd`, branch `tom/issue4-remaining-metrics`) with no production code changed. It also covers the reliability experiment [C6 and the S1 check](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/docs/ai/notes/pending-tasks.md) as far as a black-box run can.

| Metric (issue #4, verbatim) | Result on this run |
| --- | --- |
| Recovery time — Measure from cloud restart to the first successfully stored new reading. Record whether operator intervention was required. | `restart cloud`: median 0.723 s (min 0.714, max 1.154, n = 10). `start cloud` after a 5–6 s stop: median 0.647 s (min 0.636, max 0.939, n = 10). No operator intervention in any of the 20 secure-path trials (nor in the 10 plaintext comparison trials). The times are bounded by the 0.5 s send interval and the gateway's retry backoff, not by cloud start-up alone; see [Explanations](#explanations). |
| Delivery, loss, and duplication — Send a known set of valid readings. Count unique readings stored, missing readings, and extra duplicate records after a defined observation period. Repeat during normal operation and an outage. | Normal: 600 sent, 600 stored, 0 missing, 0 duplicates. 15 s outage: 600 sent, 531 acknowledged, 69 rejected with `502` and never stored, 0 duplicates; 150 acknowledged readings stored before the stop were wiped by it, so only 381 were still in `GET /data` at the end. |

## Environment

| Item | Value |
| --- | --- |
| Host | Apple M4 Pro laptop, 48 GB RAM, macOS 15.7.5 |
| Docker | Docker Desktop, engine and client 29.4.3, Compose v5.1.3; Docker VM with 12 CPUs and 7.7 GiB |
| Code | `0f309bd` (v2.2.0 code), images built from this worktree with `up -d --build cloud gateway` |
| Compose project | `m4deliver`, with `docker-compose.yml` and an untracked override outside the repository that replaces the published ports (`ports: !override`) with `127.0.0.1:38000` (gateway) and `127.0.0.1:38001` (cloud) |
| Services started | `cloud` and `gateway` only. The `device` service was never started, so the only readings were the ones this script sent. |
| Configuration | Compose defaults: `CLOUD_ML_KEM_MODE=enabled`, `GATEWAY_ML_KEM_MODE=enabled` (every reading goes over the ML-KEM secure path), `CLOUD_MAX_STORED_READINGS=1000`, gateway retry defaults (3 attempts, 0.2 s backoff doubling, 1 s per attempt, 4 s budget). The plaintext comparison recreated only the gateway with `GATEWAY_ML_KEM_MODE=off`. |
| Client | [`scripts/evaluation/measure_recovery_delivery.py`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/0d9f085a2895910871e1dadf10d9ef07ba88a8c0/scripts/evaluation/measure_recovery_delivery.py) run from the host with Python 3.12 and `requests` 2.34.2 in a virtual environment outside the repository |
| Concurrent load | The team's long-running stack (`software-development-and-maintenance-project`, ports 8000/8001, with its device) and another agent's `m4detect` stack (ports 28000–29090, 23000) were running on the same Docker VM during the whole run. Neither was touched. |

Times below are UTC on 2026-09-29. The run took place from 11:01 to 11:13.

## Method

Every reading is `{"device_id": "m4-<label>-<trial>-<seq>", "temperature": 20.0}`, sent to the gateway's `POST /device-data`, so each one can be found in the cloud's `GET /data`. The script sends one reading at a time (the gateway serialises secure sends on one lock anyway), with a 30 s client timeout. Warm-up and marker readings are excluded from the counts.

**Recovery.** Before each trial the script sends a marker reading and confirms it is stored, so the gateway holds a live secure session. It then records `t0` and runs `docker compose -p m4deliver restart cloud` (or, for the stop/start variant, `stop cloud`, keeps sending for about 5 s, then records `t0` and runs `start cloud`). From `t0` it sends a reading every 0.5 s; after each `200` it reads `GET /data`. Recovery ends at the first reading that the gateway acknowledged with `200`, is present in `GET /data`, **and** the marker is absent. The marker check matters: the first reading after `restart` was always accepted by the old process during its graceful shutdown and then wiped (column "acked by old process"), which would otherwise read as ~0.01 s recovery. Background threads record when the Compose command returned and when the cloud's `/health` came back. A trial with no recovery within 60 s would count as needing intervention. The gateway's Prometheus counters and the cloud's access log are read before and after each trial.

**Delivery.** Each trial starts with `restart cloud` (which empties the in-memory store) and a warm-up reading, then sends 200 readings at 0.2 s intervals (40 s), waits a 5 s observation period and reads `GET /data`. In the outage variant the cloud is stopped 10 s into the trial and started again 15 s later while sending continues. Because a stop wipes the store, the script pauses sending, takes a `GET /data` snapshot and only then issues `stop`; readings stored before the stop are counted from that snapshot. Duplicates are extra records with the same `device_id` in one snapshot.

## Recovery results

### `docker compose restart cloud` (secure path)

`t0` is when the command was issued. All times in seconds after `t0`. "First stored" is the sequence number of the first stored new reading and when it was sent.

| Trial | `t0` (UTC) | Command returned | Cloud `/health` back | First stored (seq @ sent) | Its gateway latency | Recovery | Gateway `200`/`502` | Forced rekeys | Acked by old process | Intervention |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:02:49.253 | 0.488 | 0.697 | 0002 @ 0.505 | 0.213 | **0.720** | 2/0 | 1 | 1 | no |
| 2 | 11:02:51.609 | 0.557 | 0.759 | 0002 @ 0.502 | 0.227 | **0.732** | 2/0 | 1 | 1 | no |
| 3 | 11:02:53.969 | 0.466 | 0.674 | 0002 @ 0.505 | 0.212 | **0.719** | 2/0 | 1 | 1 | no |
| 4 | 11:02:56.306 | 0.523 | 0.719 | 0002 @ 0.504 | 0.217 | **0.723** | 2/0 | 1 | 1 | no |
| 5 | 11:02:58.630 | 0.502 | 0.703 | 0002 @ 0.501 | 0.211 | **0.716** | 2/0 | 1 | 1 | no |
| 6 | 11:03:01.017 | 0.514 | 0.714 | 0002 @ 0.501 | 0.219 | **0.723** | 2/0 | 1 | 1 | no |
| 7 | 11:03:03.397 | 0.590 | 0.784 | 0002 @ 0.505 | 0.629 | **1.136** | 2/0 | 1 | 1 | no |
| 8 | 11:03:06.162 | 0.512 | 0.700 | 0002 @ 0.500 | 0.211 | **0.714** | 2/0 | 1 | 1 | no |
| 9 | 11:03:08.472 | 0.596 | 0.803 | 0002 @ 0.505 | 0.646 | **1.154** | 2/0 | 1 | 1 | no |
| 10 | 11:03:11.261 | 0.599 | 1.000 | 0002 @ 0.502 | 0.633 | **1.139** | 2/0 | 1 | 1 | no |

Recovery: median **0.723 s**, min 0.714 s, max 1.154 s. Command duration: median 0.519 s (0.466–0.599). `/health` back: median 0.717 s (0.674–1.000).

### `docker compose stop cloud`, gap, `docker compose start cloud` (secure path)

`t0` is when `start` was issued; the gap is from `stop` issued to `start` issued. Readings sent during the gap all got `502`.

| Trial | `t0` (UTC) | Gap | Command returned | Cloud `/health` back | First stored (seq @ sent) | Its gateway latency | Recovery | Gateway `200`/`502` | Forced rekeys | Acked by old process | Intervention |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:03:19.516 | 5.31 | 0.296 | 0.786 | 0006 @ 0.694 | 0.236 | **0.939** | 1/5 | 1 | 0 | no |
| 2 | 11:03:27.152 | 5.04 | 0.149 | 0.332 | 0005 @ 0.003 | 0.632 | **0.639** | 1/4 | 1 | 0 | no |
| 3 | 11:03:35.573 | 6.12 | 0.191 | 0.400 | 0006 @ 0.007 | 0.639 | **0.649** | 1/5 | 1 | 0 | no |
| 4 | 11:03:43.918 | 6.08 | 0.146 | 0.341 | 0006 @ 0.003 | 0.641 | **0.647** | 1/5 | 1 | 0 | no |
| 5 | 11:03:52.335 | 6.15 | 0.174 | 0.342 | 0006 @ 0.009 | 0.644 | **0.656** | 1/5 | 1 | 0 | no |
| 6 | 11:03:59.661 | 5.04 | 0.178 | 0.402 | 0005 @ 0.008 | 0.638 | **0.648** | 1/4 | 1 | 0 | no |
| 7 | 11:04:06.998 | 5.02 | 0.184 | 0.397 | 0005 @ 0.004 | 0.635 | **0.642** | 1/4 | 1 | 0 | no |
| 8 | 11:04:14.350 | 5.08 | 0.148 | 0.334 | 0005 @ 0.002 | 0.632 | **0.636** | 1/4 | 1 | 0 | no |
| 9 | 11:04:21.757 | 5.14 | 0.177 | 0.345 | 0005 @ 0.006 | 0.636 | **0.645** | 1/4 | 1 | 0 | no |
| 10 | 11:04:30.201 | 6.16 | 0.172 | 0.398 | 0006 @ 0.002 | 0.652 | **0.659** | 1/5 | 1 | 0 | no |

Recovery from `start`: median **0.647 s**, min 0.636 s, max 0.939 s. Command duration: median 0.176 s (0.146–0.296). `/health` back: median 0.371 s (0.332–0.786).

### Plaintext comparison (`GATEWAY_ML_KEM_MODE=off`)

Same procedure after recreating only the gateway with the secure path switched off (confirmed with `gateway_security_mode{gateway_security_mode="off"} 1.0`).

| Scenario | Trials | Recovery median | Min | Max | Forced rekeys | Intervention |
| --- | --- | --- | --- | --- | --- | --- |
| `restart cloud` | 5 (11:09:51–11:10:01) | 0.722 s | 0.715 s | 1.125 s | 0 | none |
| `stop` + ~5 s + `start` | 5 (11:10:08–11:10:38) | 0.633 s | 0.625 s | 0.643 s | 0 | none |

### Operator intervention

None was needed in any of the 30 recovery trials: no command other than the restart (or stop/start) was issued, and every trial recovered within 1.2 s, far below the 60 s ceiling. On the secure path each trial shows exactly one `POST /secure/data 404` in the cloud access log, followed by one `GET` and one `POST /secure/handshake 200`, and the gateway's `gateway_session_rekeys_total{reason="forced"}` and `gateway_handshake_succeeded_total` rose by 1: the gateway re-handshook on its own. `docker compose restart cloud` did not restart the gateway (its `State.StartedAt` was unchanged after a restart, checked at 10:59–11:00 before the trials).

## Delivery results

Columns: sent; acknowledged by the gateway with `200`; not acknowledged (all were `502 Cloud service unavailable`; no client timeouts, no `409`, no other status); unique readings in `GET /data` after the 5 s observation period; missing at the end; missing from every snapshot (never stored); extra duplicate records; acknowledged but never stored; answered as failed but stored.

### Normal operation (secure path)

| Trial | Start (UTC) | Sent | `200` | Not acked | Stored at end | Missing at end | Never stored | Duplicates | Acked, never stored | Failed but stored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:04:45 | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 |
| 2 | 11:05:31 | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 |
| 3 | 11:06:17 | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 |
| **Total** | | **600** | **600** | **0** | **600** | **0** | **0** | **0** | **0** | **0** |

Gateway latency for acknowledged readings: median 0.012 s, max 0.072 s.

### 15 s cloud outage (secure path)

The outage window is from `stop` issued to `start` issued, in seconds after the first send. "Stored before stop" is the snapshot taken with sending paused, immediately before `stop`; "wiped by stop" are those readings that were no longer in `GET /data` at the end.

| Trial | Start (UTC) | Sent | `200` | `502` | Outage window | Sent in window | Stored before stop | Wiped by stop | Stored at end | Missing at end | Never stored | Duplicates | Acked, never stored | Failed but stored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:07:03 | 200 | 177 | 23 | 10.01–25.01 | 23 | 50 | 50 | 127 | 73 | 23 | 0 | 0 | 0 |
| 2 | 11:07:49 | 200 | 177 | 23 | 10.01–25.01 | 23 | 50 | 50 | 127 | 73 | 23 | 0 | 0 | 0 |
| 3 | 11:08:35 | 200 | 177 | 23 | 10.01–25.02 | 23 | 50 | 50 | 127 | 73 | 23 | 0 | 0 | 0 |
| **Total** | | **600** | **531** | **69** | | **69** | **150** | **150** | **381** | **219** | **69** | **0** | **0** | **0** |

Every `502` was a reading sent inside the outage window, and every reading sent in the window got `502`. Each `502` took 0.620–0.654 s at the gateway (median 0.634 s), so only 23 readings were sent in the 15 s window instead of the nominal 75; the sender caught up afterwards, so each trial still sent 200 readings in 40 s. The first reading after `start` was acknowledged in all three trials (sent 0.07–0.26 s after `start` was issued, latency 0.22–0.64 s).

### 15 s cloud outage (plaintext comparison, `GATEWAY_ML_KEM_MODE=off`)

| Trial | Start (UTC) | Sent | `200` | `502` | Sent in window | Stored before stop | Wiped by stop | Stored at end | Missing at end | Never stored | Duplicates | Acked, never stored | Failed but stored |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 11:10:40 | 200 | 177 | 23 | 23 | 51 | 51 | 126 | 74 | 23 | 0 | 0 | 0 |
| 2 | 11:11:26 | 200 | 177 | 23 | 23 | 50 | 50 | 127 | 73 | 23 | 0 | 0 | 0 |
| 3 | 11:12:12 | 200 | 177 | 23 | 23 | 50 | 50 | 127 | 73 | 23 | 0 | 0 | 0 |
| **Total** | | **600** | **531** | **69** | **69** | **151** | **151** | **380** | **220** | **69** | **0** | **0** | **0** |

## S1 observations

**Not observed.** Over the whole run the cloud's access log (`docker compose logs cloud`, collected just before teardown) held `1223× POST /secure/data 200`, `41× POST /secure/data 404`, `42×` each of `GET` and `POST /secure/handshake 200`, and **no `409`**, no other error status and no traceback. No reading was answered as failed but stored, and no reading was acknowledged but never stored, in any delivery trial.

This is not evidence that S1 is fixed. S1 needs a reading that the cloud stores while its response is lost. Here the cloud was always stopped with `SIGTERM`, which uvicorn handles by finishing in-flight requests, and a stopped cloud refuses connections outright, so every request either completed or never reached the cloud. The procedure could not create a lost response and did not try to.

## Explanations

These are interpretations of the observed values above, not separate measurements.

- **What the recovery time is made of.** Readings are sent every 0.5 s, and the gateway retries a refused connection after 0.2 s and then 0.4 s. The first reading that reached the new cloud process therefore arrived when it had been sent plus one or two backoffs: 0.21–0.23 s latency after one refused attempt, 0.62–0.65 s after two. The new process was usually already serving `/health` before that (for example 0.33–0.40 s after `start` in stop/start trials 2–10, while the first stored reading took 0.64–0.66 s). The measured recovery is thus bounded by the send interval and the gateway's retry schedule rather than by the cloud's start-up; the 1.1 s outliers are trials where the reading sent at 0.5 s needed a second backoff. The same values in plaintext mode indicate that the secure re-handshake adds no visible time at this resolution.
- **Why a restart looks like zero downtime at first.** The reading sent at `t0` was acknowledged by the old process before it shut down, then lost with the rest of the store. This is the in-memory storage behaviour documented in `cloud/app/storage.py`, not a delivery defect.
- **Loss during an outage.** The gateway has no durable queue: a reading whose short retry budget runs out is answered with `502` and discarded, and the load generator (like the simulated device) does not resend. Every reading sent during the outage was lost this way.
- **Loss caused by the outage itself.** Stopping the cloud also discarded everything it had stored before, which is the larger loss here (150 of 219 missing readings in the secure trials). Only the pre-stop snapshot makes the two losses distinguishable.
- **No duplicates.** On the secure path a `5xx` is not retried, and a retry after a lost response would reuse the nonce and be rejected with `409` (S1), so duplicates are not expected there. The plaintext path retries `5xx` and connection failures, which could duplicate a reading if the cloud stored it but the reply was lost; this procedure produced no lost replies, so it did not exercise that case either.

## Limits

- The three measurements in this series (detection, recovery and delivery, latency) ran at the same time on one laptop. At about 11:00 UTC the latency run briefly overwrote the recovery run's untracked Compose override file with its own. It was restored from the recovery run's container settings a few minutes later. The recovery run's containers were created before the overwrite and kept ports 38000/38001, but whether any later recreation used the overwritten file cannot be fully ruled out.
- One laptop, with the cloud, gateway and client on the same Docker VM, and two other Compose stacks running concurrently. No network latency or packet loss between gateway and cloud.
- Recovery resolution is limited by the 0.5 s send interval and the gateway's backoff schedule; sub-second differences between scenarios should not be over-read.
- Only clean stops (`SIGTERM`) were tested. A crash (`docker kill`), a network partition or a slow cloud that times out could produce lost responses, and with them S1 symptoms or plaintext duplicates.
- Cloud storage is in memory; each delivery trial started from an empty store and stayed far below the 1000-reading cap, so no eviction occurred. The `--since` window of `docker compose logs` counted `199` instead of `200` stored `POST /secure/data` in normal trial 3, most likely a small clock offset between the host and the Docker VM at the window start; the `GET /data` counts are authoritative.
- Single readings, one sender, one device ID family. The real device's 5 s interval and its own client timeout were not used, and the device container was not run.
- A first 10-trial `restart` run at 11:01:53–11:02:12 is not reported: the script then measured the command duration only between sends, so that column was wrong. Its recovery values (median 0.724 s, 0.721–1.138 s) matched the reported run. The script was fixed before all reported trials.
- The 2.0.0 vs 2.1.0 comparison asked for in C6 was not run; only the v2.2.0 code was measured.

## Not run

- Unit, integration and root test suites, CI workflows and `scripts/smoke-test.sh`; no production code changed.
- Grafana and Prometheus; gateway counters were read directly from `GET /metrics/`.

## Reproducing

From the repository root, with an override file outside the repository, for example `/tmp/m4/override.yml`:

```yaml
services:
  cloud:
    ports: !override
      - "127.0.0.1:38001:8001"
  gateway:
    ports: !override
      - "127.0.0.1:38000:8000"
```

```bash
python3 -m venv /tmp/m4/venv && /tmp/m4/venv/bin/pip install requests
docker compose -p m4deliver -f docker-compose.yml -f /tmp/m4/override.yml up -d --build cloud gateway

RUN="/tmp/m4/venv/bin/python scripts/evaluation/measure_recovery_delivery.py \
  --gateway-url http://127.0.0.1:38000 --cloud-url http://127.0.0.1:38001 \
  --project m4deliver -f docker-compose.yml -f /tmp/m4/override.yml"
$RUN --scenario restart   --trials 10 --json-out /tmp/m4/restart.json
$RUN --scenario stopstart --trials 10 --gap 5 --json-out /tmp/m4/stopstart.json
$RUN --scenario normal    --trials 3 --count 200 --interval 0.2 --json-out /tmp/m4/normal.json
$RUN --scenario outage    --trials 3 --count 200 --interval 0.2 \
  --outage-at 10 --outage-seconds 15 --json-out /tmp/m4/outage.json

# Plaintext comparison: recreate only the gateway, then rerun with another --label
GATEWAY_ML_KEM_MODE=off docker compose -p m4deliver -f docker-compose.yml \
  -f /tmp/m4/override.yml up -d --no-deps gateway
$RUN --scenario outage --label outageoff --trials 3 --count 200 --interval 0.2

docker compose -p m4deliver -f docker-compose.yml -f /tmp/m4/override.yml down -v
```

Each trial prints one JSON line; `--json-out` also keeps every send with its timestamp, status and latency. The script restarts and stops the `cloud` service of the named project, so never point it at a stack whose data matters. The raw JSON files from this run were kept outside the repository and are not committed.
