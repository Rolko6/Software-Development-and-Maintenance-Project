# Deployment: shared test environment

Reproducible instructions for deploying this prototype (device, gateway,
cloud) to a shared test environment — a machine or VM reachable by more
than one team member, as opposed to a single contributor's laptop. This is
part of Work Package 4 ("Automate build and deployment",
[project plan](../project-plan.md)).

**No shared environment has been provisioned yet, and no deployment
evidence has been recorded.** The "Deployment evidence" section at the
bottom is a fill-in table for whoever provisions one; do not treat any row
in it as filled until a real deployment has actually happened and someone
recorded the actual observed result.

For what the CI pipeline checks before code reaches this stage, see
[ci.md](ci.md). For what is (and is not) observable once deployed, see
[monitoring.md](monitoring.md). For the single-machine quick start this
extends, see the [README](../../README.md).

## Prerequisites

On the host that will run the shared environment:

- Docker Engine with the Compose plugin (or Docker Desktop), installed and
  running: `docker --version && docker compose version`.
- `git`, to clone the repository.
- `curl`, for the verification checks below.
- Outbound internet access for the initial image build (pulling
  `python:3.12-slim` and installing pip dependencies inside each image).
- A user account with permission to run `docker` (in the `docker` group,
  or root/sudo).

## Host, ports, and firewall expectations

`docker-compose.yml` publishes two host ports:

| Port | Service | Purpose |
| --- | --- | --- |
| `8000` | gateway | `/health`, `/device-data`, `/metrics/`, interactive docs at `/docs` |
| `8001` | cloud | `/health`, `/data`, interactive docs at `/docs` |

By default Compose binds published ports to all interfaces on the host
(`0.0.0.0`), not just loopback. That is fine for a single contributor's
laptop but matters on a shared host that other machines can reach. Both
services communicate over plain HTTP with no authentication (see the
README's "Known limitations") and are, as shipped, "intended for a
controlled development environment." For a shared test environment:

- Restrict inbound access to `8000`/`8001` at the host firewall (or cloud
  security group) to the team's known IP ranges or a VPN, rather than
  opening them to the public internet.
- If tighter binding is wanted (e.g. `127.0.0.1:8000:8000` plus an SSH
  tunnel or reverse proxy for shared access), do this with a local,
  untracked `docker-compose.override.yml` on the host rather than editing
  the tracked `docker-compose.yml` — Compose merges override files
  automatically, and this keeps the host-specific choice out of version
  control.
- No inbound port is needed for outbound-only traffic: the device
  container only makes outbound calls to the gateway over the internal
  Compose network and does not need a published port itself.

## Deploy

From a shell on the host, with the prerequisites above satisfied:

```bash
# 1. Clone
git clone git@github.com:Rolko6/Software-Development-and-Maintenance-Project.git
cd Software-Development-and-Maintenance-Project

# 2. Configure (optional — only if you need non-default values)
# Compose's environment: entries for CLOUD_URL, GATEWAY_URL, and DEVICE_ID
# are the current configuration surface (see the README's "Configuration"
# table). There is no .env file in this repository to fill in; edit
# docker-compose.yml directly if a value must change, or override at the
# host level with docker-compose.override.yml as described above.

# 3. Build and start, detached
docker compose up --build -d

# 4. Confirm the containers are up
docker compose ps
```

The first build takes a few minutes (base image pull plus `pip install`
inside each of the three images). Compose has no configured health checks
(a documented limitation — see the README), so `docker compose ps` will
show containers as "running" as soon as the process starts, not once the
application is actually ready to serve requests; use the checks below to
confirm actual readiness.

## Verify the deployment

Replace `localhost` with the shared host's address if running these from
another machine.

**1. Health:**

```bash
curl -fsS http://localhost:8000/health   # gateway
curl -fsS http://localhost:8001/health   # cloud
```

Both should return `{"status":"healthy"}`.

**2. A known reading reaches the cloud** (the same check as the README's
"Verify the data flow" → "Send a known reading through the gateway"):

```bash
curl -fsS -X POST http://localhost:8000/device-data \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"deploy-check-001","temperature":22.5}'
```

Expect `{"status":"forwarded","cloud_response":{"status":"stored"}}`, then
confirm it is retrievable:

```bash
curl -fsS http://localhost:8001/data | grep -c deploy-check-001
```

Expect a count of at least `1`.

**3. Metrics are exposed:**

```bash
curl -fsS http://localhost:8000/metrics/ | grep -E 'device_messages_total|cloud_forward_failures_total'
```

Both counter names should appear. See [monitoring.md](monitoring.md) for
what these counters do and do not tell you, and for scraping them with a
real Prometheus instance rather than one-off `curl` checks.

Record the actual output of these three checks — not just "passed" — as
part of the deployment evidence below.

## View logs

```bash
docker compose logs -f            # all services, follow
docker compose logs -f gateway    # one service
docker compose logs --no-color --tail 200   # last 200 lines, no ANSI color (useful when pasting into an evidence record)
```

`Ctrl+C` stops following; the containers keep running.

## Roll back to the previous commit

There is no persistent volume in this stack — the cloud service's
readings live only in that process's memory (see "Data-loss caveat"
below) — so a rollback has no data-migration step to worry about; it is
purely a matter of checking out the previous code and rebuilding.

```bash
# Find the commit currently running vs. the one before it
git log --oneline -5

# Roll back the working tree to the previous commit
git checkout <previous-commit-sha>

# Rebuild and restart from that commit
docker compose down
docker compose up --build -d

# Re-run the verification checks above before declaring the rollback done
```

To return to the latest commit afterwards: `git checkout main` (or
whichever branch/ref was deployed), then `docker compose up --build -d`
again.

## Tear down

```bash
docker compose down       # stop and remove containers + network; images and any local cache remain
docker compose down -v    # same, and also remove any anonymous/named volumes (this stack defines none, so -v currently changes nothing beyond the plain form)
```

Stopping or removing the `cloud` container at any point — including via
either form of `down`, or `docker compose restart cloud` — discards all
stored readings immediately (see "Data-loss caveat").

## Data-loss caveat

The cloud service stores readings in a process-local Python list (see
`cloud/app/storage.py` and the README's "Known limitations" and
"Storage"). There is no database and no volume backing it. Concretely:

- Restarting, rebuilding, or recreating the `cloud` container empties it.
- The list has no retention limit or eviction; left running indefinitely,
  memory usage grows without bound.
- A rollback or redeploy on the shared environment will always start the
  cloud service with zero stored readings, regardless of what was stored
  before.

Do not treat this environment as a place to accumulate meaningful test
data across deployments. If a specific reading must be preserved for a
report or evidence record, capture the `curl` output at the time, not a
promise to re-query it later.

## Deployment evidence

Fill in one row per actual deployment to a shared environment. Do not
pre-fill "expected" results — only record what was actually observed,
per this repository's verification rule (AGENTS.md, "Verification": *"Match
the completion claim to the checks performed"*).

| Date | Commit (`git rev-parse --short HEAD`) | Environment (host/provider) | Operator | Checks run | Result |
| --- | --- | --- | --- | --- | --- |
| _(none yet)_ | | | | | |

Suggested "Checks run" shorthand: `health`, `known-reading`, `metrics`,
`logs-reviewed`. Suggested "Result" values: `success`, `partial (describe)`,
`failed (describe, link to logs if captured)`. Link supporting output
(command transcripts, log excerpts) from a `docs/validation/` entry or an
[AI evidence record](../ai/README.md) rather than pasting large logs
directly into this table.
