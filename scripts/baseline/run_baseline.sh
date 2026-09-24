#!/bin/sh
# Reproducible baseline for Work Package 1.
#
# Starts the cloud and gateway services locally from the shared .venv with
# uvicorn (NOT via Docker Compose), on ports 18001 (cloud) and 18000
# (gateway) — chosen so this script never collides with the Compose
# defaults (8000/8001) or another agent's run. It then:
#   1. waits for both /health endpoints to respond,
#   2. runs the functional baseline checks from the README's manual checks
#      (health, a known reading through POST /device-data, GET /data
#      retrieval, invalid device id -> 422, cloud-down -> 502, recovery),
#   3. runs scripts/baseline/measure_latency.py for the latency measurement,
#   4. always tears the started processes down (EXIT/INT/TERM trap),
#   5. exits non-zero if any check fails.
#
# Usage (from the repository root, or from anywhere — the script locates
# itself and the repo root):
#   scripts/baseline/run_baseline.sh
#   scripts/baseline/run_baseline.sh --samples 200   # extra args forwarded
#                                                     # to measure_latency.py
#
# Idempotent: safe to run repeatedly back-to-back. Each run starts its own
# processes and tears them down before exiting; it does not depend on or
# leave behind state from a previous run (other than overwriting
# scripts/baseline/last-baseline.json).

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
VENV_UVICORN="$REPO_ROOT/.venv/bin/uvicorn"

GATEWAY_HOST=127.0.0.1
GATEWAY_PORT=18000
CLOUD_HOST=127.0.0.1
CLOUD_PORT=18001

GATEWAY_URL="http://${GATEWAY_HOST}:${GATEWAY_PORT}"
CLOUD_URL="http://${CLOUD_HOST}:${CLOUD_PORT}"

TMP="${TMPDIR:-/tmp}"
CLOUD_LOG="$TMP/baseline-cloud.$$.log"
GATEWAY_LOG="$TMP/baseline-gateway.$$.log"
BODY_FILE="$TMP/baseline-body.$$.json"

CLOUD_PID=""
GATEWAY_PID=""

log() {
    printf '%s\n' "$*"
}

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [ -n "$GATEWAY_PID" ] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
        kill "$GATEWAY_PID" 2>/dev/null || true
        wait "$GATEWAY_PID" 2>/dev/null || true
    fi
    if [ -n "$CLOUD_PID" ] && kill -0 "$CLOUD_PID" 2>/dev/null; then
        kill "$CLOUD_PID" 2>/dev/null || true
        wait "$CLOUD_PID" 2>/dev/null || true
    fi
    rm -f "$CLOUD_LOG" "$GATEWAY_LOG" "$BODY_FILE"
    exit "$status"
}
trap cleanup EXIT INT TERM

fail() {
    log "FAIL: $*"
    exit 1
}

pass() {
    log "PASS: $*"
}

require_port_free() {
    port=$1
    name=$2
    if command -v lsof >/dev/null 2>&1; then
        if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            fail "port $port ($name) is already in use; free it before running the baseline"
        fi
    fi
}

wait_for_health() {
    url=$1
    pid=$2
    name=$3
    i=0
    max=60
    while [ "$i" -lt "$max" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            log "--- $name log ---"
            cat "$4" 2>/dev/null || true
            fail "$name process exited before becoming healthy"
        fi
        if curl -fsS -o /dev/null "$url/health" 2>/dev/null; then
            return 0
        fi
        i=$((i + 1))
        sleep 0.25
    done
    log "--- $name log ---"
    cat "$4" 2>/dev/null || true
    fail "$name did not become healthy at $url/health within 15s"
}

start_cloud() {
    (
        cd "$REPO_ROOT/cloud"
        exec "$VENV_UVICORN" app.main:app --host "$CLOUD_HOST" --port "$CLOUD_PORT" --log-level info
    ) >"$CLOUD_LOG" 2>&1 &
    CLOUD_PID=$!
    wait_for_health "$CLOUD_URL" "$CLOUD_PID" "cloud" "$CLOUD_LOG"
}

start_gateway() {
    (
        cd "$REPO_ROOT/gateway"
        CLOUD_URL="${CLOUD_URL}/data"
        export CLOUD_URL
        exec "$VENV_UVICORN" app.main:app --host "$GATEWAY_HOST" --port "$GATEWAY_PORT" --log-level info
    ) >"$GATEWAY_LOG" 2>&1 &
    GATEWAY_PID=$!
    wait_for_health "$GATEWAY_URL" "$GATEWAY_PID" "gateway" "$GATEWAY_LOG"
}

curl_status() {
    # Usage: curl_status <curl args...>   -- writes body to $BODY_FILE, prints status code
    curl -s -o "$BODY_FILE" -w '%{http_code}' "$@" || true
}

log "== Baseline: starting cloud (port $CLOUD_PORT) and gateway (port $GATEWAY_PORT) from .venv =="

require_port_free "$CLOUD_PORT" "cloud"
require_port_free "$GATEWAY_PORT" "gateway"

start_cloud
pass "cloud became healthy at $CLOUD_URL/health"

start_gateway
pass "gateway became healthy at $GATEWAY_URL/health"

log ""
log "== Functional baseline checks =="

# 1. Health of both services
STATUS=$(curl_status "$GATEWAY_URL/health")
[ "$STATUS" = "200" ] && grep -qF '"status":"healthy"' "$BODY_FILE" \
    || fail "gateway /health returned status=$STATUS body=$(cat "$BODY_FILE" 2>/dev/null)"
pass "gateway /health -> 200 {\"status\":\"healthy\"}"

STATUS=$(curl_status "$CLOUD_URL/health")
[ "$STATUS" = "200" ] && grep -qF '"status":"healthy"' "$BODY_FILE" \
    || fail "cloud /health returned status=$STATUS body=$(cat "$BODY_FILE" 2>/dev/null)"
pass "cloud /health -> 200 {\"status\":\"healthy\"}"

# 2. A known reading through POST /device-data
KNOWN_DEVICE_ID="baseline-known-001"
STATUS=$(curl_status -X POST "$GATEWAY_URL/device-data" \
    -H 'Content-Type: application/json' \
    -d "{\"device_id\":\"$KNOWN_DEVICE_ID\",\"temperature\":22.5}")
[ "$STATUS" = "200" ] \
    && grep -qF '"status":"forwarded"' "$BODY_FILE" \
    && grep -qF '"cloud_response":{"status":"stored"}' "$BODY_FILE" \
    || fail "known reading via POST /device-data returned status=$STATUS body=$(cat "$BODY_FILE" 2>/dev/null)"
pass "known reading POST /device-data -> 200 forwarded/stored"

# 3. GET /data retrieval — confirm the known reading is present
STATUS=$(curl_status "$CLOUD_URL/data")
[ "$STATUS" = "200" ] && grep -qF "\"device_id\":\"$KNOWN_DEVICE_ID\"" "$BODY_FILE" \
    || fail "GET /data did not contain the known reading (status=$STATUS)"
pass "GET /data -> 200, contains the known reading"

# 4. Invalid device id -> 422
STATUS=$(curl_status -X POST "$GATEWAY_URL/device-data" \
    -H 'Content-Type: application/json' \
    -d '{"device_id":"","temperature":22.5}')
[ "$STATUS" = "422" ] || fail "invalid device_id expected 422, got $STATUS"
pass "invalid device_id (empty string) -> 422"

# 5. Cloud-down -> 502
kill "$CLOUD_PID" 2>/dev/null || true
wait "$CLOUD_PID" 2>/dev/null || true
CLOUD_PID=""

STATUS=$(curl_status -X POST "$GATEWAY_URL/device-data" \
    -H 'Content-Type: application/json' \
    -d '{"device_id":"outage-test","temperature":22.5}')
[ "$STATUS" = "502" ] && grep -qF '"detail":"Cloud service unavailable"' "$BODY_FILE" \
    || fail "cloud-down expected 502 Cloud service unavailable, got status=$STATUS body=$(cat "$BODY_FILE" 2>/dev/null)"
pass "cloud stopped -> POST /device-data -> 502 {\"detail\":\"Cloud service unavailable\"}"

# Cheap extra evidence: the gateway's own failure counter observed the outage.
STATUS=$(curl_status "$GATEWAY_URL/metrics/")
[ "$STATUS" = "200" ] && grep -qF 'cloud_forward_failures_total 1.0' "$BODY_FILE" \
    || fail "expected cloud_forward_failures_total 1.0 in gateway metrics after the outage, got status=$STATUS"
pass "gateway /metrics/ -> cloud_forward_failures_total 1.0 after the outage"

# 6. Recovery
start_cloud
pass "cloud restarted and became healthy again at $CLOUD_URL/health"

STATUS=$(curl_status -X POST "$GATEWAY_URL/device-data" \
    -H 'Content-Type: application/json' \
    -d '{"device_id":"recovery-test","temperature":19.9}')
[ "$STATUS" = "200" ] \
    && grep -qF '"status":"forwarded"' "$BODY_FILE" \
    && grep -qF '"cloud_response":{"status":"stored"}' "$BODY_FILE" \
    || fail "post-recovery reading via POST /device-data returned status=$STATUS body=$(cat "$BODY_FILE" 2>/dev/null)"
pass "post-recovery reading POST /device-data -> 200 forwarded/stored"

log ""
log "== Latency measurement =="

"$VENV_PYTHON" "$SCRIPT_DIR/measure_latency.py" \
    --gateway-host "$GATEWAY_HOST" --gateway-port "$GATEWAY_PORT" \
    --cloud-host "$CLOUD_HOST" --cloud-port "$CLOUD_PORT" \
    --json-out "$SCRIPT_DIR/last-baseline.json" \
    ${1+"$@"} \
    || fail "latency measurement reported a failure (see output above)"
pass "latency measurement completed and wrote $SCRIPT_DIR/last-baseline.json"

log ""
log "== All baseline checks passed =="
exit 0
