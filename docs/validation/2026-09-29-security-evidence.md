# Security evidence for the ML-KEM link — 2026-09-29

Scope: S7 in [pending-tasks.md](../ai/notes/pending-tasks.md). For each failure
the secure channel is meant to handle, the expected and the actual outcome,
whether anything was wrongly stored, and which metric recorded it; then the
latency of a request that needs a new session compared with one that reuses a
session. Everything below ran over real HTTP against the cloud container.

## Method

[`scripts/evaluation/security_evidence.py`](../../scripts/evaluation/security_evidence.py)
drives the real gateway client (`gateway/app/crypto/client.py`, loaded from the
checkout) against the cloud's published port. Faults are injected in the
client's transport: a flipped ciphertext byte, a relabelled `device_id`, a
captured body sent twice, a response dropped after delivery, a forged reply.
Each case uses its own `device_id`, so "stored" counts only that case's
readings. Metric deltas are read from the cloud's `/metrics/` before and after
each case.

The stack ran with a random 64-character `ML_KEM_PSK`, the cloud in `required`
mode, and a 20-second session TTL (from a temporary Compose override, so the
expired-session case could be waited out):

```sh
export ML_KEM_PSK=$(openssl rand -hex 32)
CLOUD_ML_KEM_MODE=required docker compose -f docker-compose.yml -f ttl-override.yml up -d --build
python scripts/evaluation/security_evidence.py --json evidence.json
```

`ttl-override.yml` sets only `services.cloud.environment.CLOUD_ML_KEM_SESSION_TTL_SECONDS: "20"`.

| Item | Value |
| --- | --- |
| Revision | `e40e325` (branch `feat/secure-channel-hardening`) |
| Host | macOS 27.0, arm64 |
| Docker Engine / Compose | 29.4.0 / 5.1.2 |
| Containers | Python 3.12-slim, `cryptography` 50.0.1 |
| Script | Python 3.14, `requirements-dev.txt` |

## Negative cases

| Case | Expected | Actual | Stored (expected) | Metric | Result |
| --- | --- | --- | --- | --- | --- |
| Wrong PSK on the gateway | `401` | `401` | 0 (0) | `cloud_handshake_failed_total{reason="verification_failed"}` +1 | as expected |
| Tampered ciphertext | `400` | `400` | 0 (0) | `cloud_crypto_decrypt_failures_total` +1 | as expected |
| Tampered associated data (`device_id` relabelled) | `400` | `400` | 0 (0) | `cloud_crypto_decrypt_failures_total` +1 | as expected |
| Replayed message | `409` | `409` | 1 (1) | `cloud_secure_data_rejected_total{reason="replay"}` +1 | as expected |
| Unknown session | `404` | `404` | 0 (0) | `cloud_secure_data_rejected_total{reason="unknown_session"}` +1 | as expected |
| Expired session | `410` | `410` | 1 (1) | `cloud_secure_data_rejected_total{reason="expired_session"}` +1 | as expected |
| Plaintext `POST /data` in `required` mode | `403` | `403` | 0 (0) | — | as expected |
| Lost response, then the next reading (S1) | `200` | `200` | 3 (3) | — | as expected |
| Forged `200` reply, reading never delivered (S8) | `200` | `200` | 0 (0) | — | known gap confirmed |

Reading the table:

- In every rejected case nothing was stored, except the one reading each of the
  replay and expiry cases stores legitimately before the rejected request.
- **S1:** the reading whose response was lost was stored, and the next reading
  was accepted under a new nonce. The same case run with the gateway client from
  before the fix (`0f309bd`), against the same containers, gave
  `409, nonce reused` with 2 of 3 readings stored, and the script exited with 1.
- **S8** is a known, open weakness, not a pass: the client reported
  `{"status": "stored"}` for a reading the cloud never received, because the
  reply is not authenticated. No metric shows it.
- The tampering cases change a field after encryption, as an attacker on the
  network would; they do not test an attacker who holds the session key.

## Latency

Same run, 200 samples each after 10 warm-up requests, host → published cloud
port, milliseconds. "New session" is a fresh client: `GET` and `POST
/secure/handshake`, then `POST /secure/data`. "Reused session" is only the
`POST /secure/data`. "Handshake only" is the two handshake requests.

| Request | n | min | median | p95 | mean | max |
| --- | --- | --- | --- | --- | --- | --- |
| Reused session | 200 | 2.13 | 3.51 | 6.12 | 3.88 | 26.32 |
| New session | 200 | 4.61 | 10.75 | 14.82 | 10.49 | 20.65 |
| Handshake only | 200 | 3.17 | 7.14 | 10.44 | 7.01 | 12.02 |

A new session costs about 7 ms more at the median, mostly the two extra round
trips of the handshake. With the default 300-second TTL the gateway pays that
once per session, roughly once in 60 readings at one reading every 5 seconds.

## Limits

- One host, loopback networking through the Docker port mapping; no real
  network latency or loss. The device and gateway containers were running and
  sending to the same cloud during the measurement.
- The client ran on the host (Python 3.14), not inside the gateway container
  (Python 3.12). The cloud side ran in its container.
- The short TTL was chosen for the expiry case; the latency figures do not
  depend on it, because reused-session samples rekey outside the timed request.
- Not covered here: a wrong PSK on the cloud side answered by a
  machine-in-the-middle (the gateway's server-MAC check), a pinned-fingerprint
  mismatch, and handshake flooding (S6). The first two are covered by the
  in-process tests in `tests/crypto/test_handshake.py`.
