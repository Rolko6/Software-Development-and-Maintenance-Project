# Software Development and Maintenance Project

A small edge–cloud prototype for the University of Oulu course **Software Development, Maintenance and Operations (811372A-3008)**.

The project simulates a legacy temperature sensor sending readings through an edge gateway to a cloud service. It provides a baseline for testing, maintenance, operations, and a planned migration to post-quantum key establishment using ML-KEM.

**Current status:** the repository contains the sensor simulator, gateway, cloud service, and Docker Compose configuration, along with automated unit test suites for all three services, an integration test suite, and CI/CD workflows (see [Run the tests](#run-the-tests)). ML-KEM key establishment now protects the gateway→cloud link and is switched on in Compose; the device→gateway hop is still plaintext by design (see [Known limitations](#known-limitations)).

## Versions

Each release is a Git tag and a GitHub Release. A long-lived `release/*` branch is kept for each version so the two can be checked out and evaluated side by side.

| Version | Milestone | Branch | Release notes and AI record |
| --- | --- | --- | --- |
| v1.0.0 | Initial edge–cloud baseline: plaintext device → gateway → cloud | `release/1.0.0` | [GitHub release](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/releases/tag/v1.0.0), [v1.0.0 record](docs/ai/prompts/v1.0.0.md) |
| v2.0.0 | ML-KEM-768 on the gateway → cloud link, reliability fixes, observability, automated tests and CI/CD | `release/2.0.0` | [GitHub release](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/releases/tag/v2.0.0), [v2.0.0 record](docs/ai/prompts/v2.0.0.md) |

Upgrading from v1.0.0 changes the default wire behaviour; see [Migrating from v1.0.0](docs/ai/prompts/v2.0.0.md#migrating-from-v100).

## Project documentation and AI assistants

Start with the [documentation index](docs/README.md) for the project plan, decisions, prompt history, and verification records.

AI assistants working here should follow [AGENTS.md](AGENTS.md). [CLAUDE.md](CLAUDE.md) imports the same shared rules for Claude Code. See the index for a startup instruction for other clients.

## Architecture

```text
Simulated device                 Edge gateway                    Cloud service
device/app/                      gateway/app/                    cloud/app/
                   HTTP POST                       HTTP POST
                  /device-data                       /data
               ─────────────────►               ─────────────────►
Temperature readings             Validate and forward            Store in memory
                                 Logs and metrics                Retrieve via GET /data
                                 Host port 8000                  Host port 8001
```

- **Device:** `device/app/` splits the simulator into `config.py` (environment validation), `models.py` (the reading and its wire payload), `sensor.py` (the temperature models), `gateway_client.py` (delivery to the gateway), `runner.py` (the send loop and signal handling), and `__main__.py` (entry point). By default it still generates a uniform random temperature between 15 and 30, attempts to send it, then waits five seconds before the next attempt; the temperature range, model, and interval are now configurable (see Configuration below).
- **Gateway:** validates incoming readings and forwards them to the cloud. Forwarding failures return HTTP `502` and increment a failure counter.
- **Cloud:** stores readings in a process-local list and exposes them through an API. Stored readings are lost when the cloud process restarts.

Both API services use FastAPI. Containers use Python 3.12, and the gateway exposes metrics through the Prometheus Python client.

## Requirements

- Docker Desktop, or Docker Engine with the Docker Compose plugin, installed and running.
- Host ports `8000` and `8001` available.
- Internet access for the initial image build and dependency installation.
- `curl` for the manual checks below.

Check the installed tools:

```bash
docker --version
docker compose version
```

Python dependencies are installed inside the containers; a local Python environment is not required for this setup.

## Quick start

Open a terminal in the repository root, the directory containing `docker-compose.yml`, and run:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

The device starts sending readings automatically. The first build may take a few minutes.

The current Compose configuration starts services in dependency order but does not wait for application readiness. An initial connection failure is possible; the simulator continues with its next reading after a five-second pause.

View service logs:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop following logs. The detached containers keep running.

## Verify the data flow

These are manual checks; they sit alongside the automated test suites described in [Run the tests](#run-the-tests) below. Run them after the services have started.

### 1. Check both APIs

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
```

Both endpoints should return:

```json
{"status":"healthy"}
```

These endpoints only confirm that each API responds. The gateway health endpoint does not check its connection to the cloud.

### 2. Send a known reading through the gateway

```bash
curl -fsS -X POST http://localhost:8000/device-data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"manual-sensor-001","temperature":22.5}'
```

Expected response:

```json
{"status":"forwarded","cloud_response":{"status":"stored"}}
```

### 3. Retrieve stored readings

```bash
curl -fsS http://localhost:8001/data
```

The response should be a JSON array containing the manual reading, alongside readings from the simulator.

### 4. Inspect gateway metrics

```bash
curl -fsS http://localhost:8000/metrics/
```

Look for:

- `device_messages_total`: validated readings received by the gateway, including those whose forwarding fails.
- `cloud_forward_failures_total`: exceptions encountered while forwarding readings to the cloud.

Counters reset when the gateway process restarts. A Prometheus server and dashboard are not included.

## Run the tests

`gateway/`, `cloud/`, and `device/` each have their own `pytest` suite, and `tests/integration/` has a suite that exercises the running Docker Compose stack over HTTP. Running them needs a local Python environment; the Quick start above does not.

Install a service's test dependencies (each `requirements-dev.txt` also pulls in the service's own `requirements.txt`):

```bash
pip install -r gateway/requirements-dev.txt
```

Run that service's suite from inside its own directory — `gateway/app`, `cloud/app`, and `device/app` are three separate packages all named `app`, so each suite must run from its own service directory rather than the repository root:

```bash
cd gateway && python -m pytest
```

To run all three service suites together, continuing past a failing suite and printing a combined summary:

```bash
./scripts/run-unit-tests.sh
```

For a full end-to-end run, use `./scripts/smoke-test.sh`. It builds the service images, starts the Docker Compose stack, runs the integration suite (`tests/integration/`) against the running containers, and always tears the stack down afterwards, including on failure. It needs host ports `8000` and `8001` free, the same as the Quick start above.

The device suite covers configuration validation, the reading and its wire payload, both temperature models, the gateway client, and the send loop. Observed on 2026-09-15 with `cd device && ../.venv/bin/python -m pytest -q`: `43 passed`; see the [device modularization validation record](docs/validation/2026-09-15-device-modularization.md) for the full evidence.

Both scripts accept a `PYTHON` environment variable to select a specific interpreter. It must be an absolute path, because the runner changes directory into each service before invoking it: `PYTHON="$PWD/.venv/bin/python" ./scripts/run-unit-tests.sh`. CI installs the same dependency files and runs the same commands on Python 3.12, matching the containers.

### Continuous integration

Two GitHub Actions workflows automate the checks above:

- **CI** (`.github/workflows/ci.yml`) runs on pull requests and on pushes to `main` and `develop`. It runs each service's unit test suite, validates and builds the Docker Compose configuration, and runs a smoke test that brings up the full stack and runs the integration suite against it.
- **Publish images** (`.github/workflows/publish.yml`) runs on pushes to `main` and on version tags (`v*.*.*`). It builds the gateway, cloud, and device images and pushes them to the GitHub Container Registry (GHCR).

Image publishing targets GHCR only; no deployment environment is configured yet.

## Verify the secure channel

Compose starts with `CLOUD_ML_KEM_MODE=enabled` and `GATEWAY_ML_KEM_MODE=enabled`, so every
reading the gateway forwards already goes through ML-KEM-768 key establishment. The cloud still
accepts the legacy plaintext `POST /data` in this mode, which is what makes the migration
possible while the device remains a plaintext producer.

Confirm the cloud is publishing an encapsulation key:

```bash
curl -fsS http://localhost:8001/secure/handshake
```

Confirm readings actually travel the protected path rather than falling back to plaintext, by
looking at which endpoints the cloud is serving:

```bash
docker compose logs cloud | grep -oE '"(GET|POST) /[a-z/]*' | sort | uniq -c | sort -rn
```

`POST /secure/data` should dominate and plaintext `POST /data` should not appear at all unless
you sent one yourself.

To prove the legacy path can be closed, switch the cloud to `required` and restart just that
service:

```bash
CLOUD_ML_KEM_MODE=required docker compose up -d --no-deps cloud
curl -i -X POST http://localhost:8001/data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"plain-probe","temperature":20.0}'
```

Expected result: HTTP `403`, and the reading is not stored, while readings sent through the
gateway continue to arrive. Put the cloud back with:

```bash
docker compose up -d --no-deps cloud
```

Rolling back is `CLOUD_ML_KEM_MODE=off` and `GATEWAY_ML_KEM_MODE=off`, which restores the
original plaintext behaviour. The services deliberately do not import the cryptographic code at
all in `off` mode, so a broken dependency cannot stop them from starting.

**Set `ML_KEM_PSK` to a real shared secret before using this anywhere that matters.** Without it
the handshake is unauthenticated; the value in `docker-compose.yml` is a visible placeholder.
Full design, threat model and residual risks: [ML-KEM integration](docs/security/ml-kem-integration.md).

## API endpoints

| Service | Method | Path | Purpose |
| --- | --- | --- | --- |
| Gateway | GET | `/health` | Liveness: the gateway API responds |
| Gateway | GET | `/ready` | Readiness: the gateway can actually reach the cloud |
| Gateway | POST | `/device-data` | Validate and forward a sensor reading |
| Gateway | GET | `/metrics/` | Read Prometheus metrics |
| Cloud | GET | `/health` | Liveness: the cloud API responds |
| Cloud | GET | `/ready` | Readiness: the cloud process is serving |
| Cloud | POST | `/data` | Store a sensor reading directly (legacy plaintext path) |
| Cloud | GET | `/data` | Retrieve all readings in memory |
| Cloud | GET | `/secure/handshake` | Publish the ML-KEM encapsulation key |
| Cloud | POST | `/secure/handshake` | Complete key establishment and open a session |
| Cloud | POST | `/secure/data` | Store an AEAD-protected reading |

Interactive API documentation is available while the services are running:

- [Gateway API documentation](http://localhost:8000/docs)
- [Cloud API documentation](http://localhost:8001/docs)

The payload contains `device_id` (a string) and `temperature` (a number). Both services now apply the same rules: a device ID of 1–100 characters and a temperature within −40 °C to 60 °C. A rejected reading returns HTTP 422.

`/health` keeps its original fixed response so existing probes are unaffected. `/ready` is the new endpoint that reflects reality: the gateway's returns 503 when the cloud is unreachable.

## Manual failure checks

### Invalid device ID

```bash
curl -i -X POST http://localhost:8000/device-data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"","temperature":22.5}'
```

Expected result: HTTP `422`. The gateway rejects the reading before forwarding it.

### Cloud unavailable

Stopping the cloud clears its in-memory readings. Use this check with disposable test data.

```bash
docker compose stop cloud
curl -i -X POST http://localhost:8000/device-data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"outage-test","temperature":22.5}'
```

Expected result: HTTP `502` with `{"detail":"Cloud service unavailable"}`. The gateway logs the exception and increments `cloud_forward_failures_total`.

Restore the cloud:

```bash
docker compose start cloud
```

Once its health endpoint responds, repeat the known-reading check above. New readings should be stored successfully. Failed readings are not queued or replayed.

## Configuration

Compose supplies these environment variables to the containers:

| Service | Variable | Compose value | Default when unset |
| --- | --- | --- | --- |
| Gateway | `CLOUD_URL` | `http://cloud:8001/data` | `http://localhost:8001/data` |
| Device | `GATEWAY_URL` | `http://gateway:8000/device-data` | `http://localhost:8000/device-data` |
| Device | `DEVICE_ID` | `legacy-sensor-001` | `legacy-sensor-001` |
| Device | `SEND_INTERVAL_SECONDS` | not set | `5.0` (must be greater than 0) |
| Device | `REQUEST_TIMEOUT_SECONDS` | not set | `5.0` (must be greater than 0) |
| Device | `TEMPERATURE_MIN` | not set | `15.0` |
| Device | `TEMPERATURE_MAX` | not set | `30.0` (must be greater than or equal to `TEMPERATURE_MIN`) |
| Device | `TEMPERATURE_MODEL` | not set | `uniform` (or `random-walk`, case-sensitive) |
| Device | `RANDOM_SEED` | not set | unset (an integer; makes runs reproducible) |
| Device | `LOG_LEVEL` | not set | `INFO` (one of `CRITICAL`/`ERROR`/`WARNING`/`INFO`/`DEBUG`, case-insensitive) |
| Gateway | `CLOUD_HEALTH_URL` | not set | derived from `CLOUD_URL` by swapping `/data` for `/health` |
| Gateway | `CLOUD_REQUEST_TIMEOUT_SECONDS` | not set | `1` |
| Gateway | `CLOUD_READINESS_TIMEOUT_SECONDS` | not set | `2` |
| Gateway | `CLOUD_FORWARD_MAX_ATTEMPTS` | not set | `3` |
| Gateway | `CLOUD_FORWARD_BACKOFF_SECONDS` | not set | `0.2` (doubles per attempt) |
| Gateway | `CLOUD_FORWARD_TOTAL_BUDGET_SECONDS` | not set | `4` (ceiling across all attempts) |
| Cloud | `CLOUD_MAX_STORED_READINGS` | `1000` | `1000` (oldest readings are evicted past this) |
| Cloud | `CLOUD_ML_KEM_MODE` | `enabled` (overridable from the environment) | `off` (`off` / `enabled` / `required`) |
| Gateway | `GATEWAY_ML_KEM_MODE` | `enabled` (overridable from the environment) | `off` (`off` / `enabled` / `required`) |
| Both | `ML_KEM_PSK` | `dev-only-insecure-psk-change-me` | unset (unset means the handshake is **not** authenticated) |
| Cloud | `CLOUD_ML_KEM_KEY_PATH` | `/keys/ml-kem-key.der` | unset (a fresh key pair each start) |
| Cloud | `CLOUD_ML_KEM_SESSION_TTL_SECONDS` | `300` | `300` |
| Gateway | `GATEWAY_CLOUD_BASE_URL` | `http://cloud:8001` | `http://localhost:8001` |
| Gateway | `GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT` | not set | unset (optional hex SHA-256 pin of the cloud key) |

The current `docker-compose.yml` sets only `GATEWAY_URL` and `DEVICE_ID` for the device; the remaining device variables fall back to the defaults above unless set in the environment.

Edit the `environment` entries in `docker-compose.yml` to change the container configuration. Compose uses service names (`cloud` and `gateway`) for communication within its network; the host-side checks use `localhost`.

After changing source files, dependencies, or Compose configuration, run:

```bash
docker compose up --build -d
```

Source files are copied into images; there are no live source mounts. Recreating the cloud container loses its stored readings.

## Stop the system

```bash
docker compose down
```

This stops and removes the project containers and network. Sensor data is not persisted.

## Repository structure

```text
.
├── cloud/
│   ├── app/
│   │   ├── main.py          # Cloud API routes
│   │   ├── models.py        # Cloud input model
│   │   └── storage.py       # In-memory reading storage
│   ├── tests/                 # Automated unit tests
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements-dev.txt
│   └── requirements.txt
├── device/
│   ├── app/
│   │   ├── __main__.py       # Entry point
│   │   ├── config.py         # Environment configuration and validation
│   │   ├── models.py         # Sensor reading and wire payload
│   │   ├── sensor.py         # Temperature models and reading generation
│   │   ├── gateway_client.py # HTTP delivery to the gateway
│   │   └── runner.py         # Send loop and signal handling
│   ├── tests/                # Unit tests (43 tests)
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── gateway/
│   ├── app/
│   │   ├── main.py          # Gateway routes and error handling
│   │   ├── cloud_client.py  # HTTP forwarding to the cloud
│   │   ├── metrics.py       # Gateway counters
│   │   └── models.py        # Gateway input validation
│   ├── tests/                 # Automated unit tests
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements-dev.txt
│   └── requirements.txt
├── docs/                   # Plan, decisions, prompts, and verification records
├── .github/
│   └── workflows/          # CI and image-publish GitHub Actions workflows
├── scripts/                # Test-running and smoke-test helper scripts
├── tests/
│   └── integration/        # HTTP-level integration tests against the running stack
├── AGENTS.md               # Shared agent instructions
├── CLAUDE.md               # Claude Code import of the shared instructions
├── docker-compose.yml
└── README.md
```

## Known limitations

- **Communication security:** the gateway→cloud link is protected by ML-KEM-768 key establishment with AES-256-GCM (see the [design](docs/security/ml-kem-integration.md)). The **device→gateway hop is still plain HTTP** — that is the legacy compatibility the project is about, not an oversight. ML-KEM establishes a shared secret but does **not** authenticate the peer: without a matching `ML_KEM_PSK` on both sides the handshake is open to an active machine-in-the-middle, and the value shipped in Compose is a visible development placeholder that must be replaced. There is still no user authentication or authorization, and the port mappings do not restrict access to host loopback.
- **Storage:** readings still disappear on cloud restart. Retention is now bounded by `CLOUD_MAX_STORED_READINGS` (default 1000); past that, the oldest readings are silently evicted. There is still no database.
- **Delivery:** the gateway now retries a transient cloud failure with backoff, bounded by `CLOUD_FORWARD_MAX_ATTEMPTS` and a total time budget. A 4xx rejection is never retried. This is **not** a durable queue: once the budget is exhausted the reading is still lost, and there is no duplicate detection.
- **Device reporting:** the simulator now logs each delivery outcome and never reports a non-2xx response as success: a delivered reading logs at INFO, a non-2xx gateway response logs at WARNING, and a connection or timeout failure logs at ERROR. Failed readings are still discarded — see Delivery above; there is no retry or queue.
- **Validation:** gateway and cloud now enforce the same device ID and temperature rules.
- **Readiness:** `/ready` on both services reflects the real dependency state, but Compose still has no `healthcheck:` entries, so startup ordering remains best-effort.
- **Verification and operations:** unit suites for all three services, an integration suite and CI/CD workflows are included (see [Run the tests](#run-the-tests)), and a plaintext-vs-ML-KEM latency comparison has been measured in containers (see the [integration record](docs/validation/2026-09-15-integration.md)). The `CI` and `Docs check` workflows have run green on GitHub for pull requests #1–#3; the `Publish images` workflow first runs on the `v2.0.0` release (see [P009](docs/ai/prompts/2026-09-24.md#p009-merge-develop-into-main-and-release-v200) for its outcome). No shared test environment is provisioned and no Prometheus instance has been run. Delivery, retry, validation, storage and duration metrics are wired; the handshake and encrypt/decrypt counters in the crypto packages still read zero.

## Planned next steps

See the [project plan](docs/project-plan.md) for the work packages, their completion evidence and their current status. Work packages 1–3 are implemented and 4–5 are partly implemented; the remaining items are human steps (a fresh-checkout baseline run, group acceptance of the cryptographic library, provisioning a shared environment, and actually executing the CI workflows).

## AI-assisted development records

Follow the [AI evidence guide](docs/ai/README.md) to record significant prompts, generated artifacts, review decisions, and verification. The [initial prompt record](docs/ai/prompts/2026-09-15.md) includes the request that established the shared agent rules. Each release also has a version record summarising its prompts and decisions: [v1.0.0](docs/ai/prompts/v1.0.0.md) and [v2.0.0](docs/ai/prompts/v2.0.0.md).

Expected responses in this README are derived from the source. See the [documentation validation record](docs/validation/2026-09-15-documentation.md) for checks performed so far.

## References

- [Docker Compose installation](https://docs.docker.com/compose/install/)
- [Docker Compose CLI reference](https://docs.docker.com/reference/cli/docker/compose/)
- [Docker Compose startup order and readiness](https://docs.docker.com/compose/how-tos/startup-order/)
- [NIST FIPS 203: ML-KEM standard](https://csrc.nist.gov/pubs/fips/203/final)
