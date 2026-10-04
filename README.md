# ML-KEM Legacy Modernization

A small edge-cloud system used to study the modernization of a legacy
communication system with post-quantum cryptography and LLM-assisted software development.

## Project Overview

This project is part of the Software Development, Maintenance & Operations course.

The project focuses on modernizing a simulated legacy edge-cloud system.
The original system consists of a legacy device, an edge gateway, and a
cloud service. During the project, the system is gradually improved through
testing, monitoring, CI/CD, deployment, and the integration of ML-KEM for
post-quantum key establishment.

The project also investigates the use of Large Language Models (LLMs) as
development assistants. Generated code and design suggestions are critically
evaluated for correctness, security, maintainability, testability, and
operational suitability.

## Architecture

```text
┌──────────────────┐
│  Legacy Device   │
│  DS18B20 sensor  │
│  simulation      │
└────────┬─────────┘
         │ HTTP (plaintext)
         ▼
┌──────────────────┐
│  Edge Gateway    │
│                  │
│  Validation      │
│  Metrics         │
│  ML-KEM client   │
└────────┬─────────┘
         │ ML-KEM-768 + AES-256-GCM
         │ (POST /data/secure)
         ▼
┌──────────────────┐
│  Cloud Service   │
│                  │
│  ML-KEM server   │
│  Data Storage    │
│  API             │
└──────────────────┘
```

Device→gateway stays plaintext HTTP (that was never in scope for encryption).
Gateway→cloud is encrypted end-to-end with ML-KEM-768 key establishment and
AES-256-GCM. The old plaintext `/data` endpoint still exists on the cloud for
backward compatibility, but every use of it is logged as a warning.

## Getting Started (clone → run → verify)

Requirements: Docker Desktop (with Compose), Python 3.12 if you also want to
run tests locally outside Docker.

**1. Clone and enter the repo**
```powershell
git clone https://github.com/Rolko6/Software-Development-and-Maintenance-Project.git
cd Software-Development-and-Maintenance-Project
```

**2. Build and start everything (detached, keeps your terminal free)**
```powershell
docker compose up --build -d
```
First build takes a bit longer (installs `kyber-py`, `cryptography`, etc.);
later runs are fast since layers are cached.

**3. Check everything is actually running**
```powershell
docker compose ps
```
All three services (`device`, `gateway`, `cloud`) should show `Up`.

**4. Health checks**
```powershell
curl http://localhost:8000/health
curl http://localhost:8001/health
```
Both should return `{"status":"healthy"}`.

**5. Watch it working**
```powershell
docker compose logs -f device
```
Every 5s you'll see `Sent data: {...} | Response: 200`. Check the cloud side
in another terminal:
```powershell
docker compose logs -f cloud
```
Look for `Received data on secure endpoint from device ...` — that confirms
the ML-KEM-encrypted path is working end-to-end.

**6. Manually exercise the API** (optional — interactive docs also work at
`http://localhost:8000/docs` and `http://localhost:8001/docs`)
```powershell
# send data through the gateway (gets encrypted before forwarding to cloud)
curl -X POST http://localhost:8000/device-data -H "Content-Type: application/json" -d "{\"device_id\":\"manual-test\",\"temperature\":21.5}"

# see everything the cloud has stored (decrypted)
curl http://localhost:8001/data
```

**7. Run the automated tests**

Each service has its own `tests/` folder and must be run **separately**
(gateway and cloud both use a package named `app`, so running them in the
same process causes import collisions):
```powershell
pip install -r requirements-dev.txt
python -m pytest device/tests
python -m pytest gateway/tests
python -m pytest cloud/tests
```
CI runs all of this automatically on every push — see `.github/workflows/ci.yml`.

**8. Stop everything**
```powershell
docker compose down
```

## Security — what's covered, what isn't

**Covered:**
- Gateway→cloud traffic is encrypted with ML-KEM-768 (post-quantum key
  establishment) + AES-256-GCM (payload confidentiality and integrity)
- Replay protection via a 30-second timestamp window on encrypted requests
- Tampering (ciphertext, nonce, or the ML-KEM ciphertext itself) is detected
  and rejected
- The cloud's private key never leaves the cloud process; keys are
  pre-shared via deployment config rather than fetched over the network, so
  there's nothing to intercept on bootstrap

**Not covered (known, documented limitations):**
- Device→gateway traffic is plaintext — out of scope for this project
- The legacy `/data` endpoint on the cloud still accepts unencrypted
  requests from anyone who reaches it; the only protection is an audit-trail
  warning log, not a technical control
- The 30-second replay window is a bounded mitigation, not a complete one —
  a captured request can still be replayed within that window
- No authentication/authorization on any endpoint (anyone who can reach the
  service can post data under any `device_id`)

Full reasoning behind each of these is in `documentation/phases/v2.0.0.md`.

## Version History / Documentation

Each development phase has its own documentation file covering what was
built, which AI prompts shaped the decisions, what was tested, what problems
were found, and what's still open — see `documentation/phases/`:

| Version | Focus | Docs |
| --- | --- | --- |
| v1.0.0 | Initial unencrypted baseline (device/gateway/cloud) | [v1.0.0.md](documentation/phases/v1.0.0.md) |
| v1.1.0 | Unit/API tests for all three services | [v1.1.0.md](documentation/phases/v1.1.0.md) |
| v1.2.0 | CI/CD pipeline (GitHub Actions + GHCR publish) | [v1.2.0.md](documentation/phases/v1.2.0.md) |
| v1.3.0 | Realistic DS18B20 device simulation (errors, drift, disconnects) | [v1.3.0.md](documentation/phases/v1.3.0.md) |
| v2.0.0 | ML-KEM integration (gateway↔cloud encryption) | [v2.0.0.md](documentation/phases/v2.0.0.md) |
| v3.0.0 | Operations — meaningful metrics (cloud + sensor-fault tracking) | [v3.0.0.md](documentation/phases/v3.0.0.md) |

For exact code changes per version, see the commit history (`git log`) or
the corresponding GitHub release/tag. `documentation/template.md` is the
blank template every phase doc is built from.