# Monitoring stack

Prometheus (and optionally Grafana) for the gateway and cloud services.
Neither is included in the project's `docker-compose.yml` yet — this
directory provides everything needed to add them. See
[docs/operations/monitoring.md](../docs/operations/monitoring.md) for the
full metric inventory, PromQL reference, and what is/isn't observable.

## Why the gateway is scraped at `/metrics/` (trailing slash)

Both services mount their Prometheus ASGI app with
`app.mount("/metrics", metrics_app)`. FastAPI/Starlette's `Mount` answers a
bare `GET /metrics` with an HTTP 307 redirect to `/metrics/`; only
`/metrics/` itself returns `200` with the exposition body. Verified with a
FastAPI `TestClient` reproducing this exact mount call:

```
GET /metrics  -> 307, Location: http://testserver/metrics/
GET /metrics/ -> 200, "# HELP python_gc_objects_collected_total ..."
```

Prometheus's scrape HTTP client follows 3xx redirects by default
(`follow_redirects: true`, per the
[Prometheus scrape_config HTTP settings](https://github.com/prometheus/prometheus/blob/main/docs/configuration/configuration.md)),
so `metrics_path: /metrics` would work too — but
[`monitoring/prometheus.yml`](prometheus.yml) points at the exact serving
path (`/metrics/`) rather than relying on that default, so scraping keeps
working even if redirect-following is ever disabled in the Prometheus
deployment.

## Run it

### Option A — overlay file (no edits to `docker-compose.yml`)

```sh
docker compose -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml up --build -d
```

This starts `gateway`, `cloud`, `device` as usual, plus `prometheus`
(http://localhost:9090) and `grafana` (http://localhost:3000, login
`admin` / `admin`, which Grafana will prompt to change on first login).
Grafana already has a "Prometheus" datasource provisioned (see
[`grafana/provisioning/datasources/prometheus.yml`](grafana/provisioning/datasources/prometheus.yml)) — no manual setup
needed before running the PromQL queries below in Explore or a new panel.

### Option B — merge into `docker-compose.yml` directly

Paste this into the `services:` block of the project's `docker-compose.yml`
(this agent does not own that file — the main agent adds it):

```yaml
  prometheus:
    image: prom/prometheus:v2.54.1
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    depends_on:
      - gateway
      - cloud

  grafana:
    image: grafana/grafana:11.2.0
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      - prometheus
```

Grafana is optional — drop that block and keep only `prometheus:` for a
metrics-only setup (Prometheus's own UI at `:9090/graph` can run the
PromQL queries below without Grafana).

Image tags are known-good pins as of when this was written; there is no
Docker daemon in this sandbox to pull and verify them (see
[docs/operations/monitoring.md](../docs/operations/monitoring.md), "Not
run") — confirm current tags on Docker Hub before a real deployment.

### Stop it

```sh
docker compose -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml down
```

(or `docker compose down` if merged into the main file per Option B).

## Verify Prometheus is scraping both targets

Once running: http://localhost:9090/targets should show `gateway` and
`cloud` both `UP`. If a target is `DOWN`, check
`docker compose logs prometheus` — a common cause outside Compose is
scraping `localhost:PORT` from inside the Prometheus container, where
`localhost` refers to the container itself, not the host or the other
service.

## Useful PromQL queries

All metric names, labels, and units are defined in
[docs/operations/monitoring.md](../docs/operations/monitoring.md). Windows
below use `5m`; shorten for a short manual test run, lengthen for a
longer soak.

**Delivery failure rate** (share of gateway requests that ultimately
failed after retries were exhausted):

```promql
sum(rate(gateway_delivery_outcome_total{outcome="failed_after_retries"}[5m]))
/
sum(rate(gateway_delivery_outcome_total[5m]))
```

**Retry exhaustion rate** (requests per second that exhausted all
retries, and — normalized — as a share of all validated device
messages):

```promql
rate(gateway_cloud_retries_exhausted_total[5m])

rate(gateway_cloud_retries_exhausted_total[5m])
/
rate(device_messages_total[5m])
```

**p95 end-to-end latency** (gateway's whole `POST /device-data` handling
time, all outcomes and modes combined):

```promql
histogram_quantile(
  0.95,
  sum(rate(gateway_request_duration_seconds_bucket[5m])) by (le)
)
```

**Handshake failure rate** (share of initiated ML-KEM handshakes that
failed — denominator is `_started_total`, matching
[docs/operations/monitoring.md](../docs/operations/monitoring.md)'s alerting table; a handshake still
in flight when the window is evaluated is counted as started but not
yet as failed or succeeded, so this slightly underestimates the rate
among *completed* attempts only):

```promql
sum(rate(gateway_handshake_failed_total[5m]))
/
sum(rate(gateway_handshake_started_total[5m]))
```

**Plaintext-vs-secured latency comparison** (p95 end-to-end latency,
split by the `security_mode` label — requires requests to actually have
been served under both modes within the query window; a single process
only carries one mode's data unless the mode was switched and requests
sent again while Prometheus kept scraping):

```promql
histogram_quantile(0.95, sum(rate(gateway_request_duration_seconds_bucket{security_mode="off"}[5m])) by (le))

histogram_quantile(0.95, sum(rate(gateway_request_duration_seconds_bucket{security_mode="enabled"}[5m])) by (le))
```

For a controlled, reproducible plaintext-vs-secured comparison that does
not depend on Prometheus having scraped both windows, use
[`scripts/evaluation/compare_latency.py`](../scripts/evaluation/compare_latency.py)
instead — it measures both modes directly via HTTP and reports the delta
in one run. See [docs/operations/monitoring.md](../docs/operations/monitoring.md)
for why in-process Prometheus counters/histograms reset on restart and
cannot alone reconstruct a clean two-mode comparison after the fact.
