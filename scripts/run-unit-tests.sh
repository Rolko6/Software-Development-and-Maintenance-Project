#!/usr/bin/env bash
# Run each service's unit test suite in isolation and report a combined
# result. Every suite runs even if an earlier one fails, so a single
# invocation always reports the full picture.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

PYTHON="${PYTHON:-python3}"

SERVICES=(gateway cloud device)
FAILED_SERVICES=()

for service in "${SERVICES[@]}"; do
    echo "=============================================="
    echo "Running unit tests: ${service}"
    echo "=============================================="

    if (cd "${REPO_ROOT}/${service}" && "${PYTHON}" -m pytest "$@"); then
        echo "--- ${service}: PASSED ---"
    else
        echo "--- ${service}: FAILED ---"
        FAILED_SERVICES+=("${service}")
    fi
    echo
done

echo "=============================================="
echo "Unit test summary"
echo "=============================================="

if [ "${#FAILED_SERVICES[@]}" -eq 0 ]; then
    echo "All service suites passed: ${SERVICES[*]}"
    exit 0
else
    echo "Failed suites: ${FAILED_SERVICES[*]}"
    exit 1
fi
