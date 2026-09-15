# Software Development and Maintenance Project

A small edge–cloud prototype for the University of Oulu course **Software Development, Maintenance and Operations (811372A-3008)**.

The project simulates a legacy temperature sensor sending readings through an edge gateway to a cloud service. It provides a baseline for testing, maintenance, operations, and a planned migration to post-quantum key establishment using ML-KEM.

**Current status:** the repository contains the sensor simulator, gateway, cloud service, and Docker Compose configuration. ML-KEM, automated tests, and CI/CD are not implemented yet.

## Project documentation and AI assistants

Start with the [documentation index](docs/README.md) for the project plan, decisions, prompt history, and verification records.

AI assistants working here should follow [AGENTS.md](AGENTS.md). [CLAUDE.md](CLAUDE.md) imports the same shared rules for Claude Code. See the index for a startup instruction for other clients.

## Architecture

```text
Simulated device                 Edge gateway                    Cloud service
device/device.py                 gateway/app/                    cloud/app/
                   HTTP POST                       HTTP POST
                  /device-data                       /data
               ─────────────────►               ─────────────────►
Temperature readings             Validate and forward            Store in memory
                                 Logs and metrics                Retrieve via GET /data
                                 Host port 8000                  Host port 8001
```

- **Device:** generates a random temperature between 15 and 30, attempts to send it, then waits five seconds before the next attempt.
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

These are manual checks, not an automated test suite. Run them after the services have started.

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

## API endpoints

| Service | Method | Path | Purpose |
| --- | --- | --- | --- |
| Gateway | GET | `/health` | Check that the gateway API responds |
| Gateway | POST | `/device-data` | Validate and forward a sensor reading |
| Gateway | GET | `/metrics/` | Read Prometheus metrics |
| Cloud | GET | `/health` | Check that the cloud API responds |
| Cloud | POST | `/data` | Store a sensor reading directly |
| Cloud | GET | `/data` | Retrieve all readings in memory |

Interactive API documentation is available while the services are running:

- [Gateway API documentation](http://localhost:8000/docs)
- [Cloud API documentation](http://localhost:8001/docs)

The payload contains `device_id` (a string) and `temperature` (a number). The gateway additionally requires a device ID between 1 and 100 characters. Neither service currently enforces a physical temperature range.

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
│   ├── Dockerfile
│   └── requirements.txt
├── device/
│   ├── device.py            # Simulated temperature sensor
│   ├── Dockerfile
│   └── requirements.txt
├── gateway/
│   ├── app/
│   │   ├── main.py          # Gateway routes and error handling
│   │   ├── cloud_client.py  # HTTP forwarding to the cloud
│   │   ├── metrics.py       # Gateway counters
│   │   └── models.py        # Gateway input validation
│   ├── Dockerfile
│   └── requirements.txt
├── docs/                   # Plan, decisions, prompts, and verification records
├── AGENTS.md               # Shared agent instructions
├── CLAUDE.md               # Claude Code import of the shared instructions
├── docker-compose.yml
└── README.md
```

## Known limitations

- **Communication security:** both links use plain HTTP. Authentication, authorization, and ML-KEM are not implemented. The APIs are intended for a controlled development environment; the current port mappings do not restrict access to host loopback.
- **Storage:** readings disappear on cloud restart, and the in-memory list grows without a retention limit.
- **Delivery:** failed readings are discarded. There is no delivery queue, retry of the same reading, or duplicate detection.
- **Device reporting:** the simulator prints “Sent data” even for HTTP error responses; inspect the response code to determine success.
- **Validation:** the cloud accepts device IDs that the gateway rejects. Input rules are not yet consistent.
- **Readiness:** health endpoints return a fixed response, and Compose has no configured health checks.
- **Verification and operations:** automated tests, CI/CD, shared test deployment, and cryptographic performance measurements are not yet included.

## Planned next steps

See the [proposed project plan](docs/project-plan.md) for work packages, completion evidence, and suggested group coordination. The plan describes future work, not completed features.

## AI-assisted development records

Follow the [AI evidence guide](docs/ai/README.md) to record significant prompts, generated artifacts, review decisions, and verification. The [initial prompt record](docs/ai/prompts/2026-09-15.md) includes the request that established the shared agent rules.

Expected responses in this README are derived from the source. See the [documentation validation record](docs/validation/2026-09-15-documentation.md) for checks performed so far.

## References

- [Docker Compose installation](https://docs.docker.com/compose/install/)
- [Docker Compose CLI reference](https://docs.docker.com/reference/cli/docker/compose/)
- [Docker Compose startup order and readiness](https://docs.docker.com/compose/how-tos/startup-order/)
- [NIST FIPS 203: ML-KEM standard](https://csrc.nist.gov/pubs/fips/203/final)
