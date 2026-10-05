# Reliability and monitoring runbook

The base stack stores readings durably and disables direct plaintext cloud writes.
The monitoring overlay adds Prometheus, Grafana, Alertmanager and a local alert inbox.

## Run the base stack

```sh
docker compose up --build -d
curl http://localhost:8001/data
docker compose down
```

`cloud-data` holds `/data/readings.sqlite3`. Ordinary `down`, restart and container
recreation retain the volume. Keep the Compose project name stable to reuse its
volumes. Do not use `down --volumes` on data you want to keep. Already-lost in-memory
readings cannot be recovered. SQLite retention is unlimited, matching v3; monitor
free disk space. GET `/data` remains an insertion-ordered JSON list, so large
histories increase response size. Back up the database using SQLite's backup API
or stop cloud writes before copying the database; do not copy a live database
without a consistent backup procedure. The base cloud volume is separate from
monitoring volumes.

For Python outside Docker, create a writable database directory and set
`CLOUD_DB_PATH` to its database file. Docker creates the mounted `/data` directory.
Empty database paths and `:memory:` are rejected at startup because they would
lose data between operations. A failed read/write returns 503, and a failed write does not count as a stored
reading. One cloud replica is supported.

## Cloud ingestion policy

Plaintext `POST /data` returns 403 by default; `GET /data` is unchanged. Legacy
devices keep sending readings to gateway `/device-data`, which encrypts them for
cloud `/data/secure`. Encryption failure has no plaintext fallback.

`CLOUD_ALLOW_LEGACY_INGESTION` accepts only `true` or `false` (case and surrounding
whitespace ignored). Unset means `false`; an empty or unknown setting stops cloud
startup. A temporary migration can explicitly select `true` in Compose's shell
or `.env`, recreate the cloud container, and observe accepted legacy submissions
in warnings/metrics. Set it back to `false` and recreate the cloud to close the
bypass. Opt-in permits reachable callers to bypass encryption; it is not needed
for the device→gateway legacy link. Secure success metrics count committed
readings. The gateway/read API remain unauthenticated, development keys are still
visible in Compose, and replay within the existing timestamp window remains possible.

## Sensor signals

| Signal | Meaning |
| --- | --- |
| `sensor_read_failures_total` | Every explicit disconnected read report |
| `sensor_stuck_episodes_total` | One event per repeated-value suspicion episode |
| `sensor_disconnected_devices` | Devices whose latest contact reports disconnect |
| `sensor_suspected_stuck_devices` | Devices currently suspected stuck |
| `sensor_silent_devices` | Previously observed devices without recent contact |
| `sensor_fault_readings_total{type}` | Known DS18B20 sentinel faults |

A failed device read posts `{ "device_id": "...", "status": "disconnected" }`
to `/device-status`; no temperature is forwarded or fabricated. The default
`DEVICE_STATUS_URL` is derived beside `GATEWAY_URL`, and may be overridden.
`SENSOR_STUCK_THRESHOLD` defaults to 3 identical normal readings;
`SENSOR_SILENCE_TIMEOUT_SECONDS` defaults to 30 seconds. Changed readings,
sentinels and disconnect reports clear stuck suspicion. Stable real temperatures
may also repeat, so this is a suspicion, not proof of hardware failure. Silence
identifies stopped devices/network outages separately; it begins only after first
contact. Gauges evaluate the monotonic last-contact clock at scrape time.

`SENSOR_STATE_MAX_DEVICES` defaults to 1000. Unknown devices at capacity receive
503 without forwarding, while known devices continue reporting. The registry and
counters reset on gateway restart; it is intended for one gateway worker/replica.
Metric gauges are aggregate counts, with no device ID labels. The current registry
has no automatic eviction; restart clears it. Increasing the bound should be an
operator decision.

## Enable monitoring

Create a git-ignored `.env` file containing a chosen password:

```dotenv
GRAFANA_ADMIN_PASSWORD=replace-with-a-local-password
```

Then run:

```sh
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up --build -d
```

- [Prometheus targets](http://localhost:9090/targets): both gateway and cloud healthy.
- [Grafana dashboard](http://localhost:3000/d/edge-cloud-operations): user `admin`,
  your configured password. Twelve provisioned panels; no manual datasource setup.
- [Alertmanager](http://localhost:9093): active alerts, routing and silences.
- [Persistent alert inbox](http://localhost:9080/alerts): latest 100 notification
  records in JSON, including firing and resolved statuses. Container logs also
  show receipt. Storage is unlimited and durable on `alert-inbox-data`.

Host ports can be changed with `PROMETHEUS_PORT`, `GRAFANA_PORT`,
`ALERTMANAGER_PORT` and `ALERT_INBOX_PORT`. All monitoring host bindings are
loopback-only. Keep these APIs on trusted local hosts; the inbox has no authentication.
`GRAFANA_ADMIN_USER` defaults to `admin`. The initial password is applied when a
fresh Grafana database is created; changing the environment does not reset a user
in an existing Grafana volume. Use Grafana's account/password controls thereafter.

Prometheus keeps 30 days of history on `prometheus-data`; Grafana persists its
state on `grafana-data` and Alertmanager its silences/log on `alertmanager-data`.
All survive normal container recreation. Named volumes are local persistence,
not backups or high availability. These images are pinned: Prometheus 3.15.0,
Grafana 13.2.3 and Alertmanager 0.34.1. Update them deliberately and rerun validation.

## Alerts and recovery

Rules live in `monitoring/prometheus/alerts.yml`:

- Gateway/cloud unavailable for 2 minutes.
- Cloud forwarding failures divided by actual forwarding attempts above 5% for
  5 minutes; gateway capacity rejections do not dilute the denominator.
- Secure rejections or blocked plaintext attempts in a 5-minute window.
- Accepted plaintext submissions, indicating explicit compatibility mode use.
- Sensor sentinel fault rate above 20% for 5 minutes; this leaves room for the
  simulator's deliberate 1% sentinel injection.
- Disconnected or silent device count above zero for 30 seconds.
- Current stuck suspicion or a new suspected-stuck episode within 5 minutes;
  short simulator episodes remain observable through the episode counter.

The 15-second scrape/evaluation cadence and Alertmanager's 10-second grouping
wait add notification delay. Short injected faults may appear in dashboard
counters without satisfying sustained-state rules. Tune thresholds to a measured
baseline before treating them as operational objectives. First-event detection
with `increase()` requires an earlier counter sample. Known rejection/sentinel
labels start at zero to make those samples available.

Stop the overlay with the same file selection, retaining history:

```sh
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down
```

## Reproduce validation

```sh
pip install -r requirements-dev.txt
python -m pytest device/tests
python -m pytest gateway/tests
python -m pytest cloud/tests
python -m pytest tests/tooling
python scripts/evaluation/verify_reliability.py --json-out reliability-evaluation.json
```

The last command builds an isolated project with free loopback ports and checks
storage, plaintext rejection/explicit opt-in, sensors, provisioning, metric history,
a real cloud outage and firing/recovery notifications. It takes several minutes.
Only its own session-created test containers and volumes are removed. Existing
projects remain running. CI also validates Compose, promtool rule behavior and
amtool routing; see `.github/workflows/ci.yml`. Executed local results are in the
[validation record](../validation/2026-10-05-reliability.md).

Configuration references checked through Context7: [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/),
[Alertmanager webhook/routing](https://prometheus.io/docs/alerting/latest/configuration/),
[Compose multiple files](https://docs.docker.com/compose/how-tos/multiple-compose-files/),
and [Python SQLite transactions](https://docs.python.org/3/library/sqlite3.html).
