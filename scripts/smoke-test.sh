#!/usr/bin/env bash
# Bring up the full Docker Compose stack and run the integration suite
# against it. docker-compose.yml has no healthchecks (documented known
# limitation), so this script polls the /health endpoints itself before
# running any tests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python3}"

cleanup() {
    local exit_code=$?

    if [ "${exit_code}" -ne 0 ]; then
        echo "Smoke test failed (exit code ${exit_code}); dumping service logs:"
        docker compose logs --no-color || true
    fi

    # Unconditional: tear the stack down no matter where the script failed
    # (including a failed `up`, which can still create containers/networks
    # under set -e before reaching any later step).
    echo "Tearing down Docker Compose stack..."
    docker compose down -v --remove-orphans || true

    exit "${exit_code}"
}
trap cleanup EXIT

echo "Validating docker-compose.yml..."
docker compose config --quiet

echo "Building and starting the stack..."
docker compose up --build -d

GATEWAY_HEALTH_URL="http://localhost:8000/health"
CLOUD_HEALTH_URL="http://localhost:8001/health"
TIMEOUT_SECONDS=90
INTERVAL_SECONDS=2
elapsed=0
gateway_ready=0
cloud_ready=0

echo "Waiting for services to become healthy (up to ${TIMEOUT_SECONDS}s)..."
while [ "${elapsed}" -lt "${TIMEOUT_SECONDS}" ]; do
    if [ "${gateway_ready}" -eq 0 ] && curl -fsS "${GATEWAY_HEALTH_URL}" >/dev/null 2>&1; then
        gateway_ready=1
    fi
    if [ "${cloud_ready}" -eq 0 ] && curl -fsS "${CLOUD_HEALTH_URL}" >/dev/null 2>&1; then
        cloud_ready=1
    fi

    if [ "${gateway_ready}" -eq 1 ] && [ "${cloud_ready}" -eq 1 ]; then
        break
    fi

    sleep "${INTERVAL_SECONDS}"
    elapsed=$((elapsed + INTERVAL_SECONDS))
done

if [ "${gateway_ready}" -ne 1 ] || [ "${cloud_ready}" -ne 1 ]; then
    echo "Services did not become healthy within ${TIMEOUT_SECONDS}s."
    # The EXIT trap above dumps `docker compose logs` for any non-zero exit.
    exit 1
fi

echo "Both services are healthy. Running integration suite..."
"${PYTHON}" -m pytest tests/integration -m integration "$@"
