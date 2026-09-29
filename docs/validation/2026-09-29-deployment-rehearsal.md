# Deployment reproducibility, v2.2.0: author's rehearsal — 2026-09-29

Metric from [issue #4](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/issues/4) ("Deployment reproducibility", owners Francisca and Tom): *have another teammate deploy from the documented release; record success, time taken, undocumented steps, and configuration problems.* This is item C5 in [pending-tasks.md](../ai/notes/pending-tasks.md). Recorded as prompt [P012](../ai/prompts/2026-09-29-yyy-tom.md#p012-issue-4-test-and-ci-effectiveness-and-deployment-reproducibility).

**This is not the metric itself.** The metric needs a teammate who did not write the guide, on a shared environment. This is Tom's rehearsal on his own laptop, done to find and fix gaps in [deployment.md](../operations/deployment.md) before Francisca's run. Her run, with the corrected guide, is the measurement; its checklist is in [deployment.md](../operations/deployment.md#teammate-deployment-check).

## Setup

| Item | Value |
| --- | --- |
| Release | `v2.2.0` (tag at `b0ca4ef`, `main`), followed as documented in `docs/operations/deployment.md` at that commit |
| Host | macOS on Apple Silicon (arm64), Docker 29.4.3, Docker Compose v5.1.3 |
| Operator | yyy-tom, with Claude Code driving the commands; not an independent teammate |
| Constraint | Another copy of the stack (project `software-development-and-maintenance-project`, started 2026-09-15) was already using host ports 8000/8001 and was left running. The rehearsal therefore used project name `tomrehearsal` and host ports 18000/18001 bound to 127.0.0.1 through `docker-compose.override.yml`. |

## Timeline

| Step | Command (as run) | Time | Result |
| --- | --- | --- | --- |
| Clone | `git clone git@github.com:Rolko6/Software-Development-and-Maintenance-Project.git` | 7 s | `HEAD` `b0ca4ef`, `git describe` → `v2.2.0` |
| Override | `docker-compose.override.yml` with `ports: !override` (see finding 4) | — | `docker compose -p tomrehearsal config --quiet` exit 0 |
| Build and start | `docker compose -p tomrehearsal up --build -d` | 148 s | 3 containers up |
| Verify | the three checks in the guide, plus `/ready`, `/secure/handshake` and the cloud log | < 1 min | all passed, below |
| Total | clone to verified | about 3 min | success |
| Rollback | `git checkout v2.1.0`, `down`, `up --build -d` | 4 s (layers cached) | healthy; a new reading forwarded and stored |
| Tear down | `docker compose -p tomrehearsal down -v` | — | containers, network and the `cloud-keys` volume removed |

Verification output (ports as used):

```text
GET  :18000/health           {"status":"healthy"}
GET  :18001/health           {"status":"healthy"}
POST :18000/device-data      {"status":"forwarded","cloud_response":{"status":"stored"}}
GET  :18001/data | grep -c deploy-check-001      1
GET  :18000/metrics/         device_messages_total 2.0 / cloud_forward_failures_total 0.0
GET  :18000/ready            {"status":"ready","cloud":"reachable"}
GET  :18001/secure/handshake {"key_id":"cloud-mlkem768-1","algorithm":"ML-KEM-768",...}
cloud log endpoints          POST /secure/handshake 1, POST /secure/data 2, no plaintext POST /data
```

The device's first reading failed with `Connection refused` because the gateway was not yet listening; the next one succeeded. The README documents this start-up race.

After rollback to v2.1.0 the cloud held 2 readings, neither of them `deploy-check-001`: stored readings are lost on redeploy, as the guide says. The `tomrehearsal_cloud-keys` volume survived the rollback; whether the cloud reused the key from it was not checked.

## Findings: undocumented steps and configuration problems

The guide at v2.2.0 was written for v2.0.0-era plaintext and was not updated since. Each item below was either observed in the rehearsal or checked in the release's files.

1. **The release is not named.** The guide clones the default branch and never says `git checkout v2.2.0`; the rollback section uses commits, not release tags.
2. **The secure channel and its secret are missing.** The guide says both services use "plain HTTP with no authentication". In v2.2.0 the gateway→cloud link uses ML-KEM-768 by default and is authenticated by `ML_KEM_PSK`. Without that variable Compose uses the committed placeholder `dev-only-insecure-psk-change-me`, and the rehearsal started with it without any visible warning. A shared deployment must set its own PSK; the guide never mentions it.
3. **The configuration surface is out of date.** The guide says the only settings are `CLOUD_URL`, `GATEWAY_URL` and `DEVICE_ID`, and that values must be changed by editing `docker-compose.yml`. v2.2.0 reads `CLOUD_ML_KEM_MODE`, `GATEWAY_ML_KEM_MODE`, `ML_KEM_PSK`, `TEMPERATURE_MODEL` and four `FAULT_*` rates from the shell or a `.env` file.
4. **The suggested override does not work.** The guide says to rebind ports to `127.0.0.1` with a `docker-compose.override.yml`. Compose appends list fields when it merges files, so that override publishes port 8000 twice (`0.0.0.0:8000` and `127.0.0.1:8000`, confirmed with `docker compose config`), which fails to bind. The list needs the `!override` tag (Compose documentation, checked through Context7 for `/docker/compose`).
5. **A second checkout collides with the first.** Compose names the project after the directory. Two clones of the repository both become `software-development-and-maintenance-project` (the running stack's `com.docker.compose.project` label), so `up` in one would replace the other's containers. The guide should say to use `-p` or `COMPOSE_PROJECT_NAME` on a host shared by several people.
6. **Volumes are described wrongly.** The guide says the stack has no volume and that `down -v` "currently changes nothing". v2.2.0 has the `cloud-keys` volume holding the cloud's ML-KEM private key; `down -v` deleted it in the rehearsal. The rollback section also says there is no persistent volume.
7. **Storage is described wrongly.** The guide says stored readings have no retention limit; v2.2.0 keeps at most `CLOUD_MAX_STORED_READINGS` (1000 in Compose) and drops the oldest.
8. **Readiness and security checks are missing.** The guide does not use the gateway's `/ready` endpoint or the README's secure-channel checks, so a deployment could pass the guide's checks while falling back to plaintext.
9. **Published images are not mentioned, and are amd64 only.** `Publish images` pushed `2.2.0` to GHCR (runs 36486502993 and 36486767499, both successful). `docker manifest inspect` shows `linux/amd64` only for all three, so they need emulation on Apple Silicon or other arm64 hosts. The guide only covers building from source.

All nine are corrected in [deployment.md](../operations/deployment.md) on this branch. The rehearsal row in its evidence table is marked as a rehearsal.

## Limits

- Same person who fixed the guide; no shared host; ports and project name changed because of the other running stack.
- Build time depends on network and cache: the 148 s build pulled `python:3.12-slim` layers that were partly cached on this machine.
- The published GHCR images were inspected, not run, for 2.2.0 (the 2.0.0 images were run end to end on 2026-09-24).
- Human review of this record: not recorded.
