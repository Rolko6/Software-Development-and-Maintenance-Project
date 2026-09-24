# Device modularization validation — 2026-09-15

Scope: the restructuring of `device/device.py` into the `device/app/` package
and `device/tests/` suite, recorded as [P005](../ai/prompts/2026-09-15-yyy-tom.md).
This record covers only that change; it does not cover the gateway, cloud,
root, or ML-KEM test suites added by concurrent sessions in the same working
tree.

## Evidence already observed

| Check | Result | Scope |
| --- | --- | --- |
| `cd device && ../.venv/bin/python -m pytest -q` | `43 passed in 0.10s` | `device/tests/` (`test_config.py`, `test_models.py`, `test_sensor.py`, `test_gateway_client.py`, `test_runner.py`), run from inside `device/` so its `app` package does not collide with `gateway/app` or `cloud/app`. |
| `docker compose config --quiet` | Exit code `0` | Confirms `docker-compose.yml` still parses; does not prove the updated `device/Dockerfile` builds or the container runs. |
| `git diff --check` | Clean | Whitespace check on the diff during the modularization task, and again when this record was written. |
| Local end-to-end run without Docker (cloud and gateway started with uvicorn from `.venv` on ports 18001/18000, device run with `python -m app`) | Both `/health` endpoints returned `{"status":"healthy"}`. Device logged 4 deliveries, e.g. `INFO:app.runner:Delivered reading device_id=e2e-sensor-001 temperature=24.59 status_code=200`. `GET /data` on the cloud returned exactly those four readings, each with only `device_id` and `temperature`: `[{"device_id":"e2e-sensor-001","temperature":24.59}, ...]`, confirming the wire contract (`SensorReading.to_payload()`) is unchanged. Gateway metrics showed `device_messages_total 4.0` and `cloud_forward_failures_total 0.0`. | Confirms the modularized device still interoperates with the existing gateway/cloud contract. |
| Same run, gateway stopped | Device logged `ERROR:app.runner:Failed to deliver reading device_id=e2e-outage temperature=27.84 error=<connection refused>` (error text abbreviated in this quote) and never logged a delivered/success outcome. | Confirms the fixed behaviour: a non-2xx or connection failure is never reported as success. |
| Same run, `SIGTERM` sent to the device process | Device stopped 131 ms after the signal, logging `Received signal 15, shutting down`. | Confirms `install_signal_handlers()`/`stop()` in `device/app/runner.py`. |
| Invalid configuration: `SEND_INTERVAL_SECONDS=-1` | `ERROR:__main__:Invalid device configuration: SEND_INTERVAL_SECONDS must be a positive number, got -1.0`, exit code `1`. | Confirms `DeviceConfig.from_env()` validation and the exit-1 path in `device/app/__main__.py`. |
| Invalid configuration: `LOG_LEVEL=verbose` | The equivalent `LOG_LEVEL` validation message, exit code `1`. | Same as above, for `LOG_LEVEL`. |
| `TEMPERATURE_MODEL=random-walk RANDOM_SEED=7` | Produced `[22.32, 21.97, 22.13, 21.7, 21.73, 21.6]`. | Confirms `RandomWalkTemperatureModel` is seeded and reproducible via `RANDOM_SEED`. |

| `PYTHON="$PWD/.venv/bin/python" ./scripts/run-unit-tests.sh` | `--- device: PASSED ---`, `43 passed in 0.07s` | Confirms the device suite also passes through the shared runner script owned by a concurrent session. The same run reported `Failed suites: gateway cloud`; those two suites are that session's in-flight work and are outside this record's scope. |
| `LOG_LEVEL=verbose` before the fix | Uncaught `ValueError: Unknown level: 'VERBOSE'` traceback | Defect found by review of the generated code, not by the test suite. Fixed in `device/app/config.py` by validating against `KNOWN_LOG_LEVELS`; re-checked after the fix as the exit-1 row above. |

## Not run

- `docker compose up --build`, any container image build, and any in-container
  runtime check — the Docker daemon was not running in this environment.
- The repo-root and integration test suites owned by the concurrent session
  recorded as [P004](../ai/prompts/2026-09-15-yyy-tom.md) (ML-KEM verification tests).

## Reproducing

From the repository root, with the `.venv` present:

```bash
cd device
../.venv/bin/python -m pytest -q
```

Run from inside `device/`, not the repository root — `device/app`,
`gateway/app`, and `cloud/app` all use the package name `app`, so collecting
tests from the repository root can pick up the wrong package.

For the Compose config check:

```bash
docker compose config --quiet
```

The end-to-end run (health checks, delivery/outage logging, `SIGTERM`,
invalid-configuration exits, and the seeded random-walk sequence) was done
manually against `uvicorn`-hosted cloud/gateway instances on ports
18001/18000 and is not scripted in this repository; it is recorded here as an
executed, observed result rather than an expected one.
