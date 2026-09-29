# Deployment: shared test environment

How to deploy a released version of this prototype (device, gateway, cloud) to a shared test environment: a machine or VM that more than one team member can reach, as opposed to one contributor's laptop. This is part of work package 4 ("Automate build and deployment", [project plan](../project-plan.md)).

**No shared environment has been provisioned yet.** The only recorded run is the author's rehearsal on a laptop (see [Deployment evidence](#deployment-evidence)); the real measurement is a teammate following [Teammate deployment check](#teammate-deployment-check).

This guide describes release **v2.2.0**. For what CI checks before a release, see [ci.md](ci.md). For what can be observed once deployed, see [monitoring.md](monitoring.md). For the single-machine quick start this extends, see the [README](../../README.md).

## Prerequisites

On the host:

- Docker Engine with the Compose plugin, or Docker Desktop, running: `docker --version && docker compose version`. The guide was checked with Docker 29.4.3 and Compose v5.1.3.
- `git` and `curl`.
- Outbound internet access for the first image build (`python:3.12-slim` and the pip dependencies of each image).
- A user allowed to run `docker` (in the `docker` group, or root/sudo).
- Free host ports `8000` and `8001`, or different ports chosen with an override (below).

## What the stack contains

| Service | Host port | Notes |
| --- | --- | --- |
| `gateway` | `8000` | `/health`, `/ready`, `/device-data`, `/metrics/`, `/docs` |
| `cloud` | `8001` | `/health`, `/data`, `/secure/handshake`, `/secure/data`, `/docs` |
| `device` | none | sends a reading to the gateway every 5 s over the internal Compose network |

- **Security.** The gateway→cloud link uses ML-KEM-768 key establishment and AES-256-GCM (`*_ML_KEM_MODE=enabled` by default), authenticated by the pre-shared secret `ML_KEM_PSK`. The device→gateway hop is plain HTTP without authentication, and in `enabled` mode the cloud still accepts plaintext `POST /data` and serves `GET /data` without authentication. Treat both ports as unauthenticated.
- **Volume.** `cloud-keys` holds the cloud's ML-KEM private key (`/keys/ml-kem-key.der`), so the key survives container recreation.
- **Stored readings** live in the cloud process's memory, at most `CLOUD_MAX_STORED_READINGS` (1000 in Compose); the oldest are dropped. See [Data-loss caveat](#data-loss-caveat).

## Configuration

Compose reads these from the shell environment or from a `.env` file next to `docker-compose.yml` (the repository has none; create it on the host and do not commit it):

| Variable | Default | Set it on a shared host? |
| --- | --- | --- |
| `ML_KEM_PSK` | `dev-only-insecure-psk-change-me` (committed placeholder) | **Yes, always.** Same value for gateway and cloud; generate one with `openssl rand -hex 32`. The placeholder is accepted without a warning. |
| `CLOUD_ML_KEM_MODE` | `enabled` | `off`, `enabled` or `required`. `required` closes plaintext `POST /data`. |
| `GATEWAY_ML_KEM_MODE` | `enabled` | `off`, `enabled` or `required` (the last two behave the same on the gateway). |
| `TEMPERATURE_MODEL` | `uniform` | `uniform`, `random-walk` or `ds18b20`. |
| `FAULT_DISCONNECT_RATE`, `FAULT_POWER_ON_RESET_RATE`, `FAULT_NAN_RATE`, `FAULT_STUCK_RATE` | `0` | Only for fault experiments; see the README's "Simulate a faulty sensor". |
| `COMPOSE_PROJECT_NAME` | the directory name | **Yes, if the host has more than one checkout.** Two clones in directories with the same name share one project, and `up` in one replaces the other's containers. |

Example `.env`:

```bash
ML_KEM_PSK=<output of openssl rand -hex 32>
COMPOSE_PROJECT_NAME=sdmp-shared
```

### Ports and firewall

Compose publishes `8000` and `8001` on all interfaces (`0.0.0.0`). On a shared host, restrict them at the firewall or security group to the team's addresses or a VPN, or bind them to loopback and reach them through an SSH tunnel.

To change the binding, put a `docker-compose.override.yml` next to `docker-compose.yml` (Compose loads it automatically; keep it untracked). Compose **appends** list fields such as `ports` when it merges files, so the list must be tagged `!override`, or the original `0.0.0.0` binding stays and the port is published twice:

```yaml
services:
  cloud:
    ports: !override
      - "127.0.0.1:8001:8001"
  gateway:
    ports: !override
      - "127.0.0.1:8000:8000"
```

Check the result with `docker compose config | grep -A4 ports:` before starting.

## Deploy a release

```bash
# 1. Clone and select the release
git clone git@github.com:Rolko6/Software-Development-and-Maintenance-Project.git
cd Software-Development-and-Maintenance-Project
git checkout v2.2.0
git describe --tags            # expect: v2.2.0

# 2. Configure: create .env (and the override, if needed) as above
docker compose config --quiet

# 3. Build and start, detached
docker compose up --build -d

# 4. Confirm the containers are up
docker compose ps
```

The first build takes a few minutes (148 s in the rehearsal, with some base-image layers cached). `docker compose ps` shows containers as running as soon as the process starts, because Compose has no health checks; use the checks below. The device's first reading may fail with `Connection refused` while the gateway starts; later readings succeed.

### Using the published images instead

`Publish images` pushes each release to GHCR as `ghcr.io/rolko6/software-development-and-maintenance-project-{cloud,gateway,device}:2.2.0`. The images are built for `linux/amd64` only: they run natively on x86-64 hosts and only under emulation (`--platform linux/amd64`) on arm64 hosts such as Apple Silicon. `docker-compose.yml` builds from source and has no `image:` entries, so using the published images needs an override that sets `image:` for each service. This path has not been rehearsed for 2.2.0; building from the tag is the documented route.

## Verify the deployment

Replace `localhost` with the host's address when checking from another machine. Record the actual output, not only "passed".

```bash
# 1. Health and readiness
curl -fsS http://localhost:8000/health        # {"status":"healthy"}
curl -fsS http://localhost:8001/health        # {"status":"healthy"}
curl -fsS http://localhost:8000/ready         # {"status":"ready","cloud":"reachable"}

# 2. A known reading reaches the cloud
curl -fsS -X POST http://localhost:8000/device-data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"deploy-check-001","temperature":22.5}'
# {"status":"forwarded","cloud_response":{"status":"stored"}}
curl -fsS http://localhost:8001/data | grep -c deploy-check-001   # at least 1

# 3. Metrics
curl -fsS http://localhost:8000/metrics/ | grep -E '^(device_messages_total|cloud_forward_failures_total|gateway_delivery_outcome_total)'

# 4. Readings use the protected path
curl -fsS http://localhost:8001/secure/handshake | head -c 80; echo    # "algorithm":"ML-KEM-768"
docker compose logs cloud | grep -oE '"(GET|POST) /[a-z/]*' | sort | uniq -c
# POST /secure/data present; no plaintext POST /data unless you sent one
```

See [monitoring.md](monitoring.md) for what the counters do and do not show, and the README's "Verify the secure channel" for switching the cloud to `required`.

## View logs

```bash
docker compose logs -f                        # all services, follow
docker compose logs -f gateway                # one service
docker compose logs --no-color --tail 200     # for pasting into an evidence record
```

## Roll back to the previous release

```bash
git checkout v2.1.0            # the previous release tag
docker compose down            # keeps the cloud-keys volume
docker compose up --build -d
# re-run the verification checks
```

Stored readings are lost on every redeploy (see below). The `cloud-keys` volume is kept by `down` and reused by the older release. To return, `git checkout v2.2.0` and run `docker compose up --build -d` again.

## Tear down

```bash
docker compose down        # removes containers and network; keeps images and the cloud-keys volume
docker compose down -v     # also deletes the cloud-keys volume, i.e. the cloud's ML-KEM private key
```

After `down -v` the cloud generates a new key pair on the next start. Gateways then re-handshake against the new key; a gateway configured with `GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT` (not set in Compose) needs the new fingerprint.

## Data-loss caveat

Readings are kept in a bounded in-memory `deque` in the cloud process (`cloud/app/storage.py`). There is no database. Restarting, rebuilding or recreating the `cloud` container empties it, and past `CLOUD_MAX_STORED_READINGS` the oldest readings are dropped without notice. If a reading must be kept for a report, capture the `curl` output at the time.

## Teammate deployment check

The deployment-reproducibility metric in issue #4 is measured by a teammate who did not write this guide, following it without help:

1. Start a timer. Follow [Deploy a release](#deploy-a-release) and [Verify the deployment](#verify-the-deployment) exactly as written, on the shared host if one exists, otherwise on your own machine.
2. Write down every step you had to guess, every command that failed, and every question you had to ask. These are the "undocumented steps".
3. Stop the timer when all four verification checks pass, or after 60 minutes.
4. Add a row to the table below and save the command output in a `docs/validation/` record.

## Deployment evidence

One row per actual deployment. Record only what was observed.

| Date | Release / commit | Environment | Operator | Checks run | Time | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-29 | `v2.2.0` / `b0ca4ef` | Author's laptop (macOS arm64, Docker 29.4.3), ports 18000/18001, not a shared host | yyy-tom with Claude Code — **rehearsal, not the teammate metric** | health, ready, known-reading, metrics, secure-path, rollback to `v2.1.0`, teardown | ~3 min clone to verified | success; 9 documentation gaps found and fixed in this guide ([record](../validation/2026-09-29-deployment-rehearsal.md)) |

Suggested "Result" values: `success`, `partial (describe)`, `failed (describe)`.
