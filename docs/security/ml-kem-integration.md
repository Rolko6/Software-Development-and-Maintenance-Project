# ML-KEM gateway-cloud secure channel: design

Status (updated 2026-09-24): `cloud/app/crypto/` and `gateway/app/crypto/`
are wired into the running services and switched on in Compose (see the
[README](../../README.md#verify-the-secure-channel)). This paragraph
originally said they were not yet wired in; "Integration steps for the main
agent" at the end of this document is kept as the record of how that was
done. Library
selection and alternatives are recorded in
[docs/decisions/0002-ml-kem-key-establishment.md](../decisions/0002-ml-kem-key-establishment.md);
this document is the design itself.

ML-KEM (FIPS 203) is a **key-encapsulation mechanism**. On its own it gives
two parties a shared secret; it does not encrypt application data and does
not authenticate either party. Every one of those additional properties
below (message protection, peer trust) had to be decided and built
separately on top of it -- they are not something "ML-KEM" provides for
free.

## Scope: what link this protects

```
Simulated device --HTTP,plain--> Edge gateway --ML-KEM+AEAD--> Cloud service
device/device.py                 gateway/app/                  cloud/app/
```

Only the **gateway-to-cloud** leg is protected by this design, per the
project plan's suggested initial scope. The **device-to-gateway** leg is
unchanged: plain HTTP, no confidentiality, no integrity protection, no
authentication. This is a deliberate, documented exposure, not an oversight:

- A quantum-capable adversary recording device-to-gateway traffic today
  gains temperature readings and a device_id in the clear, now and later.
  Given the sensitivity of a simulated temperature sensor this is judged
  low-impact for this project, but it is real and unaddressed.
- An active attacker on the device-to-gateway segment can inject or alter
  readings with no cryptographic barrier at all; the gateway's existing
  input validation (`gateway/app/models.py`) is the only check.
- Extending protection to this leg would need the device simulator itself
  to speak the secure client, which the project plan explicitly treats as
  future work, not this work package's scope.

## Peer / key trust

A bare ML-KEM handshake carried over unauthenticated HTTP is vulnerable to
an active machine-in-the-middle: nothing stops an attacker from answering
`GET /secure/handshake` with their *own* encapsulation key, completing a
session with the gateway, and silently relaying (or not relaying) traffic to
the real cloud. ML-KEM's shared secret is only as trustworthy as the
encapsulation key it was computed against.

Two independent, optional mechanisms are provided. **Both are off by
default**, and the gap that leaves is stated plainly rather than hidden:

1. **`ML_KEM_PSK`** (shared secret, same value configured on both services):
   used as an HMAC-SHA256 key over the handshake transcript, in *both*
   directions:
   - **Client MAC** (gateway -> cloud): `HMAC(PSK, "client" | key_id |
     client_nonce | ek_fingerprint | ciphertext)`. Proves the gateway knows
     the PSK; without it, the cloud rejects the handshake (`401`).
   - **Server MAC** (cloud -> gateway): `HMAC(PSK, "server" | key_id |
     client_nonce | ek_fingerprint | ciphertext | session_id)`. Proves the
     responder that decapsulated the ciphertext also knows the PSK; the
     gateway verifies this *before* trusting the session. Without it, a
     machine-in-the-middle that answered the handshake with its own key
     (and therefore has a shared secret the gateway does not) still cannot
     produce a valid server MAC, so the gateway raises
     `HandshakeAuthenticationError` and never uses that session.

   This gives **mutual** authentication from one shared secret, which is
   why both directions are implemented rather than only the client
   direction (a client-only MAC stops a rogue *initiator* but does nothing
   against a rogue *responder* impersonating the cloud).

   If `ML_KEM_PSK` is unset on either side, that side simply does not send
   or check a MAC -- **the handshake is then unauthenticated**, and the
   cloud logs a one-time warning to that effect. This is the explicit
   fallback the task's design constraints allow ("or state plainly that
   authentication is out of scope"): it is stated here, and at runtime, not
   hidden.

2. **`GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT`** (gateway-only, optional,
   independent of the PSK): a pre-distributed SHA-256 fingerprint of the
   cloud's expected encapsulation key. If set, the gateway refuses to
   proceed with a handshake whose fetched key does not match
   (`PeerTrustError`), regardless of PSK configuration. This only helps if
   the cloud's key is stable across restarts, i.e. `CLOUD_ML_KEM_KEY_PATH`
   is also set (see "Key lifecycle" below) -- pinning a fingerprint that
   changes on every cloud restart is not useful.

Operators should set `ML_KEM_PSK` (and, for defense in depth, pin the
fingerprint with a persisted cloud key) for any deployment where an active
network attacker is in the threat model. Neither is required by the code;
the mode switch (below) only controls whether the channel exists at all,
not whether it is authenticated.

## Message protection

- **KDF:** HKDF-SHA256 (`cryptography.hazmat.primitives.kdf.hkdf.HKDF`).
  `salt = client_nonce` (16 random bytes chosen fresh by the gateway per
  handshake attempt); `info = "mlkem-gw-cloud-v1|session|" + key_id`. A
  single `derive()` call produces a 32-byte key -- HKDF objects in this
  library can only be used once, so a fresh `HKDF` instance is constructed
  per derivation (see `wire.py::derive_session_key`).
- **AEAD:** AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`).
- **Nonce strategy:** the nonce is the big-endian 12-byte encoding of a
  per-session message counter, starting at 0. This is safe from reuse
  because:
  1. Every session has a freshly HKDF-derived key (never reused across
     sessions -- the salt is fresh random bytes per handshake).
  2. The cloud enforces the counter is **strictly increasing** per session
     (`SessionStore.check_counter`/`commit_counter`); a repeated or
     lower counter is rejected with `409` before decryption is even
     attempted for freshness, and the counter is only committed *after* a
     ciphertext successfully authenticates (see "Failure behaviour" for why
     that ordering matters).
  3. The gateway's session cache is **in-process memory only, never
     persisted to disk**. A gateway process restart starts with no cached
     session, so its first send always re-handshakes (fresh salt, fresh
     key) before the counter resets to 0 -- the reset counter is always
     paired with a new key, so no (key, nonce) pair is ever reused across a
     restart. **This is a load-bearing invariant**: persisting the
     gateway's cached session (e.g. to survive a restart without
     re-handshaking) would break it, and must not be done without also
     durably and atomically persisting the counter.
  4. Sending is serialized per gateway process with a lock held across
     "read counter -> encrypt -> POST -> commit" (see
     `gateway/app/crypto/client.py`), so two concurrent callers in the same
     process cannot race the counter and reuse a nonce. This project's
     single-device, one-reading-per-five-seconds workload does not need
     more than this; a sliding replay window (rather than one strict
     counter) would be the natural extension for concurrent senders
     sharing one session.
- **Associated data (AAD):** `"mlkem-gw-cloud-v1" | session_id | device_id |
  nonce`. This binds a ciphertext to the specific session it was encrypted
  under, the device_id claimed alongside it on the wire, and its own nonce.
  Consequences:
  - A valid ciphertext cannot be replayed under a *different* session_id
    (even one that happens to share the same underlying key -- see the
    handshake-replay residual risk below) without failing AEAD
    authentication.
  - The device_id carried in cleartext next to the ciphertext (for
    cloud-side routing/logging without decrypting) cannot be swapped for a
    different one without failing authentication -- this is the
    "tampered associated data" case exercised in
    `tests/crypto/test_secure_data.py::test_tampered_associated_data_rejected`.
- **What tampering looks like at each layer**, because it differs from
  naive intuition:
  - A **content-tampered ML-KEM ciphertext** (correct length) does **not**
    raise during decapsulation. FIPS 203 uses *implicit rejection*: the
    responder silently derives a different (wrong) shared secret rather
    than signalling failure, specifically to avoid giving an attacker a
    decryption oracle. The handshake therefore appears to succeed (a
    session_id is returned) even if the ciphertext was corrupted in
    transit; the corruption is only detected when the resulting session
    key fails to authenticate the *first* `/secure/data` message
    (`InvalidTag` -> `400`). This is confirmed directly against the shipped
    implementation in `tests/crypto/test_kem_primitives.py::test_tampered_ciphertext_is_not_rejected_by_decapsulate_itself`.
  - A **wrong-length** ciphertext or client_nonce at the handshake *does*
    raise/is rejected explicitly (`400`), checked before decapsulation is
    even attempted.
  - A **tampered AEAD ciphertext or AAD** at the data endpoint raises
    `cryptography.exceptions.InvalidTag`, mapped to `400`.

## Key lifecycle

- **Generation:** the cloud generates an ML-KEM-768 key pair with
  `MLKEM768PrivateKey.generate()` (OpenSSL-backed CSPRNG) the first time it
  starts with no persisted key.
- **Distribution:** the encapsulation key is public data (KEM security does
  not depend on it being secret) and is served in-band over
  `GET /secure/handshake`; its *authenticity* is what the PSK MAC and/or
  fingerprint pin protect, not its secrecy.
- **Persistence / loading:** if `CLOUD_ML_KEM_KEY_PATH` is set, the private
  key is stored as unencrypted PKCS8 DER at that path (`chmod 600`) and
  reloaded on the next start, so the encapsulation key -- and its
  fingerprint -- stay stable across cloud restarts. This is what makes
  `GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT` meaningful. If unset (default), a
  fresh ephemeral key pair is generated every start; functionally this is
  fine (the gateway always re-handshakes rather than trusting a cached
  session across a cloud restart -- see "Failure behaviour") but the
  fingerprint is not stable and pinning it is not useful.
- **Session lifetime:** `CLOUD_ML_KEM_SESSION_TTL_SECONDS`, default 300s (5
  minutes). At a 5-second device polling interval that is roughly 60
  messages per session before a rekey.
- **Rekey:** the gateway proactively re-handshakes when the cached
  session's remaining lifetime drops below `rekey_skew_seconds` (default
  15s), so the common path never pays for a round trip that discovers
  expiry the hard way. If it is ever late (clock drift, or the session was
  evicted early), the cloud's `410` response on `/secure/data` triggers a
  reactive re-handshake-and-retry instead.
- **Rotation of the long-term key:** not scheduled/automatic in this
  version. Rotate by restarting the cloud process with
  `CLOUD_ML_KEM_KEY_PATH` unset, or by deleting the persisted key file
  before restart. Rotating the long-term key does **not** invalidate
  existing sessions -- session keys are derived once at handshake time and
  cached independently of the long-term key -- it only affects *future*
  handshakes. Automated/scheduled rotation is a documented gap (see
  "Residual risks").

## Failure behaviour

| Failure | Cloud HTTP status | Gateway behaviour |
| --- | --- | --- |
| `CLOUD_ML_KEM_MODE=off` (secure endpoints disabled) | `403` on any `/secure/*` route | Raised as `requests.exceptions.HTTPError`; propagates like any other `send_to_cloud` failure -> gateway's existing handler returns `502` |
| Malformed handshake/data request body (missing/wrong-typed field) | `422` (FastAPI/pydantic) | Same as above -> `502` |
| Malformed base64, or wrong-length `client_nonce`/`ciphertext`/`nonce` | `400` | Same as above -> `502` |
| Unknown `key_id` at handshake | `404` | The gateway always fetches a fresh `ek`/`key_id` via `GET /secure/handshake` immediately before every `POST /secure/handshake` -- it never caches the encapsulation key across handshakes. This status is therefore only reachable if the cloud rotates its key in the narrow window between those two calls (e.g. a restart with a new ephemeral key), not from gateway-side staleness. Propagates as `HTTPError` -> `502`; the next `send_secure` call fetches the current key and succeeds |
| PSK configured on cloud, missing/wrong client MAC | `401` | Cloud rejects the handshake; propagates to the gateway as a plain `requests.exceptions.HTTPError` -> `502` |
| PSK configured on gateway, cloud's server MAC missing/wrong (e.g. a machine-in-the-middle answered the handshake, or a PSK mismatch) | *(cloud returns `200`; the gateway rejects the response itself)* | `HandshakeAuthenticationError` raised locally before the session is ever cached -- no cloud-side status code is involved -> `502` |
| Cloud's encapsulation key fails the gateway's pinned-fingerprint check | *(no cloud round trip needed for the POST)* | `PeerTrustError` raised locally by the gateway -> `502` |
| ML-KEM ciphertext tampered in transit (implicit rejection; see above) | Handshake itself returns `200`; the **first** `/secure/data` call under that session gets `400` | Propagates as `HTTPError` -> `502` for that reading; the gateway does not know to blame the handshake specifically, only that the send failed |
| Tampered AEAD ciphertext or AAD | `400` | `HTTPError` -> `502`. **Not** auto-retried: a `400` indicates possible tampering, and silently re-handshaking and resending would mask that rather than surface it |
| Unknown `session_id` at `/secure/data` (cloud never saw it, or restarted and forgot it) | `404` | **Auto-recovered**: the client clears its cached session, re-handshakes, and retries the same reading once, transparently |
| Expired `session_id` | `410` | **Auto-recovered**, same as unknown-session (re-handshake + retry once) |
| Replayed or out-of-order counter | `409` | `HTTPError` -> `502`. **Not** auto-retried, for the same "don't mask a possible attack" reason as tampering |
| Cloud unreachable (connection refused/timeout) during handshake or data send | *(no response)* | `requests.exceptions.ConnectionError`/`Timeout` (both `RequestException` subclasses) propagate unchanged -> `502`, identical in shape to today's plaintext `send_to_cloud` failure |
| `CLOUD_ML_KEM_MODE=required` and a legacy client still POSTs plaintext `/data` | `403` (via `enforce_legacy_mode`, wired into `cloud/app/main.py` by the integration patch) | N/A (this is the device/legacy-gateway path, not the secure client) |

Two design choices worth calling out explicitly:

- **Auto-recovery is scoped narrowly.** Only "the cloud doesn't know this
  session" (`404`/`410`) triggers an automatic, transparent re-handshake
  and retry -- this is exactly "cloud restarted and forgot the session,"
  which must not cost the operator a dropped reading. Every other failure
  (tamper, replay, auth failure, connectivity) is a hard failure for that
  reading, surfaced the same way a plaintext forwarding failure is today
  (`502`), rather than silently retried in a way that could mask an
  ongoing attack or a persistent misconfiguration.
- **The counter is only committed after successful decryption**
  (`SessionStore.commit_counter`, called only once `aead_decrypt` has
  already succeeded). If the counter were advanced as soon as a
  syntactically valid request arrived, an attacker could send a bogus
  ciphertext with a very high counter purely to get *later, legitimate*
  messages rejected as "replays" -- a counter-poisoning denial of service.
  Splitting the check (read-only freshness check before decrypting) from
  the commit (only after authentication) closes that.

## Migration strategy

Two independent three-state switches, both read from the environment on
every call (no restart needed to observe a change, though in practice each
service typically only reads them at request time):

- `CLOUD_ML_KEM_MODE`: `off` (default) / `enabled` / `required`.
- `GATEWAY_ML_KEM_MODE`: `off` (default) / `enabled` / `required`.

| Cloud mode | Plaintext `POST /data` | `/secure/*` endpoints |
| --- | --- | --- |
| `off` | accepted (today's behaviour) | `403` |
| `enabled` | accepted | active |
| `required` | `403` | active |

On the gateway, `enabled` and `required` behave **identically**: both mean
"always use the secure channel." This gateway has no plaintext fallback
once switched on -- there was no requirement for one, and building a silent
downgrade path (e.g. "fall back to plaintext if the cloud doesn't support
`/secure/*`") would itself be a security-relevant decision (a downgrade
oracle) that this design deliberately does not make. The two gateway values
exist for symmetry with the cloud switch and so a future gateway-side
policy has a place to live.

**Suggested rollout order** (a fleet with one gateway and one cloud, as in
this project's Compose file, but written for the general case of several
gateways):

1. Deploy the cloud with the new package and
   `CLOUD_ML_KEM_MODE=enabled` (plaintext keeps working; `/secure/*` is now
   live). No gateway has changed yet.
2. Deploy one gateway with `GATEWAY_ML_KEM_MODE=enabled` (and, if using it,
   `ML_KEM_PSK` set identically on both services). Confirm readings still
   arrive and check the cloud's session-store/handshake behaviour (there is
   no dedicated metric shipped by this package; see "Integration steps" for
   a suggested counter to add).
3. Repeat step 2 for every remaining gateway.
4. Once every gateway is confirmed on the secure channel, flip
   `CLOUD_ML_KEM_MODE=required` to stop accepting plaintext.
   `GATEWAY_ML_KEM_MODE=required` can be set at the same time for
   documentation clarity; it changes no behaviour versus `enabled`.

**Rollback:** the reverse order -- set `CLOUD_ML_KEM_MODE=enabled` again
before rolling any gateway back to `off`, so a rolled-back gateway is not
left unable to deliver readings at all.

**What the device still exposes:** none of this touches the device-gateway
leg. The device continues to send plain HTTP `POST /device-data` to the
gateway regardless of either mode switch; see "Scope" above and "Threat
model" below.

## Threat model

**Protected**, when `ML_KEM_PSK` is configured on both sides and
`CLOUD_ML_KEM_MODE`/`GATEWAY_ML_KEM_MODE` are `enabled` or `required`:

- Confidentiality of reading contents (`device_id`, `temperature`) on the
  gateway-cloud link against a passive eavesdropper, including a
  future quantum computer performing "harvest now, decrypt later" against
  today's recorded traffic (the point of using ML-KEM at all).
- Integrity of reading contents and of the (session_id, device_id, nonce)
  envelope on that same link (AEAD `InvalidTag` on any of these being
  altered).
- Replay of a previously sent, valid ciphertext (the strictly-increasing
  counter check).
- An active machine-in-the-middle on the gateway-cloud link impersonating
  *either* endpoint during the handshake (mutual PSK MAC).

**Not protected, even in the best-configured case:**

- The device-gateway link: always plain HTTP, no confidentiality,
  integrity, or authentication (see "Scope").
- Traffic metadata: message timing, size, and frequency on the
  gateway-cloud link are all still observable (no padding, no cover
  traffic).
- Availability: nothing here defends against an attacker who can simply
  block traffic between gateway and cloud (that surfaces as the existing
  `502` "cloud unavailable" path, unchanged).
- The cloud host and the gateway host themselves: if either process or its
  memory is compromised, session keys and (if persisted) the long-term
  private key are directly exposed. This design assumes the *link* is
  hostile, not the endpoints.

**Not protected when `ML_KEM_PSK` is left unset** (the default):

- The handshake is unauthenticated. An active machine-in-the-middle can
  impersonate the cloud (answer the handshake with its own key) or the
  gateway, and the code has no way to detect this on its own --
  `GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT` is the only independent defense
  against a fake cloud in this configuration, and nothing defends the cloud
  against a fake gateway. This is a real, intentional gap: the task's
  design constraints permit shipping either a trust anchor or an explicit
  statement of unauthenticated operation, and this design ships both the
  mechanism and, for the case where it is not configured, this statement.

## Residual risks

- **PSK distribution is out of band and unmanaged.** `ML_KEM_PSK` must be
  provisioned identically on both services by some other means (a secrets
  manager, a manually-copied value in `docker-compose.yml`/an env file);
  nothing here generates, rotates, or distributes it. A leaked PSK
  compromises the mutual-authentication property for as long as it remains
  configured.
- **No scheduled long-term key rotation.** Rotation is a manual operational
  action (restart with the key file removed); nothing forces or reminds an
  operator to do this periodically.
- **Handshake-message replay can mint a duplicate session_id bound to the
  same derived key.** If an attacker replays a captured, byte-identical
  handshake request (`key_id`, `client_nonce`, `ciphertext`, `mac`), the
  cloud will decapsulate the same ciphertext and derive the same session
  key again under a *new* `session_id` (the attacker still never learns the
  key -- decapsulation happens only on the cloud side). This does not break
  confidentiality or integrity of any individual message: the AAD binds
  each ciphertext to the specific `session_id` it was created under, so a
  message captured from the original session cannot be replayed against
  the duplicate one. The impact is bounded to the cloud allocating one
  extra session-table entry per replayed handshake (bounded by the session
  TTL and the store's opportunistic sweep on `create()`) -- a
  resource-consumption nuisance, not a confidentiality or integrity break.
  **`ML_KEM_PSK` does not prevent this replay**: the MAC is a function of
  the handshake's own fields with no server-issued freshness input, so a
  captured MAC-valid handshake stays MAC-valid when replayed verbatim,
  PSK or not. A server-chosen freshness token, rejected on reuse, would
  close this completely; not implemented here.
- **No rate limiting on `/secure/handshake` or `/secure/data`.** A
  malicious or malfunctioning client could hammer either endpoint;
  FastAPI/Starlette and this package add no throttling of their own.
- **The persisted private key file (`CLOUD_ML_KEM_KEY_PATH`), when used, is
  unencrypted on disk** (permissions restricted to the owning user via
  `chmod 600`, but not encrypted at rest). Anyone with filesystem or
  container-volume access to that path can extract the long-term
  decapsulation key.
- **Docker/container verification was not performed.** The Docker daemon
  is unavailable in this environment; all verification here is
  in-process (FastAPI `TestClient`/pytest) or against the raw library
  locally, on Python 3.13 rather than the containers' Python 3.12, and the
  `cryptography==50.0.1` pin's actual resolvability for the container
  base image was not confirmed. See the decision record's Verification
  section.
- **No observability metric ships with this package for handshake
  failures or session-store size.** The integration steps below suggest
  one; it is not implemented here because `gateway/app/metrics.py` and
  `cloud/app/main.py` are out of this task's file ownership.
- **The mode switch guards behaviour, not import-time failures.** `cloud/app/crypto/router.py`
  builds the module-level default `router` (a `KeyManager` -- which
  generates or loads the ML-KEM key pair -- plus a `SessionStore`) as soon
  as `app.crypto` is imported, which happens at process startup once the
  integration patch's `from app.crypto import router as secure_router` line
  runs, *regardless* of `CLOUD_ML_KEM_MODE`. Concretely: if the pinned
  `cryptography` wheel does not actually expose `mlkem` on the target
  platform, or `CLOUD_ML_KEM_KEY_PATH` points at an unwritable/missing
  directory, the cloud process fails at startup even with
  `CLOUD_ML_KEM_MODE=off`. This is worth testing explicitly during rollout
  (start the cloud container with the new image and `CLOUD_ML_KEM_MODE=off`
  *before* relying on it as a safe no-op default) and is called out again
  in the integration steps below.

## Measured overhead

Method: `time.perf_counter` loops, this machine, Python 3.13.12 (the
containers run 3.12; not measured there -- Docker is unavailable here).
`cryptography`'s ML-KEM is a native Rust/OpenSSL binding, not pure Python,
so version sensitivity should be much lower than a pure-Python
implementation would show, but this was not verified across Python
versions. The "full handshake" number is measured through FastAPI's
`TestClient` (in-process ASGI transport, no real socket, no TLS) and is
therefore a lower bound -- a real Docker-bridge-network round trip will add
latency this does not capture. Single-threaded, single-process, no other
load; not benchmark-grade (no cross-process averaging, no isolation from
allocator/JIT warmup effects). See `tests/crypto/test_timing.py` for the
exact code.

| Operation | n | median | p95 |
| --- | --- | --- | --- |
| ML-KEM-768 keygen | 100 | 0.44 ms | 0.454 ms |
| ML-KEM-768 encapsulate | 100 | 0.128 ms | 0.142 ms |
| ML-KEM-768 decapsulate | 100 | 0.188 ms | 0.193 ms |
| Full handshake (2 HTTP round trips, in-process ASGI) | 20 | 2.10 ms | 2.90 ms |
| AES-256-GCM encrypt (post-HKDF, one message) | 1000 | 0.0025 ms | 0.0026 ms |
| AES-256-GCM decrypt (post-HKDF, one message) | 1000 | 0.0025 ms | 0.0027 ms |

The full-handshake number (~2.1 ms) is well above the sum of its raw
crypto operations (~0.8 ms for keygen+encaps+decaps+2 HKDF derivations),
which is expected: it also includes two FastAPI/Starlette request cycles
(routing, pydantic validation, JSON (de)serialization) even with no real
network. Work package 5 should treat this as a floor, not the number a real
Docker Compose deployment will show.

## Wire format

All binary fields are standard base64 (padded). All endpoints are under the
cloud's `/secure` prefix and are gated by `CLOUD_ML_KEM_MODE != off`
(`403` otherwise).

### `GET /secure/handshake`

Response:

```json
{
  "key_id": "cloud-mlkem768-1",
  "algorithm": "ML-KEM-768",
  "encapsulation_key": "<base64, 1184 bytes>",
  "fingerprint": "<sha256 hex digest of the raw encapsulation key>"
}
```

### `POST /secure/handshake`

Request:

```json
{
  "key_id": "cloud-mlkem768-1",
  "client_nonce": "<base64, 16 bytes>",
  "ciphertext": "<base64, 1088 bytes>",
  "mac": "<base64 HMAC-SHA256, or null if ML_KEM_PSK is unset>"
}
```

Response:

```json
{
  "session_id": "<opaque token>",
  "expires_at": 1789469207.78,
  "algorithm": "ML-KEM-768",
  "aead": "AES-256-GCM",
  "server_mac": "<base64 HMAC-SHA256, or null if ML_KEM_PSK is unset>"
}
```

### `POST /secure/data`

Request:

```json
{
  "session_id": "<opaque token from the handshake response>",
  "device_id": "sensor-001",
  "nonce": "<base64, 12 bytes = big-endian message counter>",
  "ciphertext": "<base64, AES-256-GCM ciphertext with 16-byte tag appended>"
}
```

The plaintext that `ciphertext` decrypts to is the same JSON body
`send_to_cloud` sends today: `{"device_id": ..., "temperature": ...}`.

Response (unchanged shape from today's plaintext `/data`):

```json
{"status": "stored"}
```

## Sequence diagram

```mermaid
sequenceDiagram
    participant GW as Gateway (initiator)
    participant CL as Cloud (responder)

    Note over GW,CL: Handshake (once per session, ~every 300s or on session loss)
    GW->>CL: GET /secure/handshake
    CL-->>GW: key_id, encapsulation_key, fingerprint
    GW->>GW: encapsulate(ek) -> (shared_secret, ciphertext)
    GW->>GW: derive session_key = HKDF(shared_secret, salt=client_nonce)
    GW->>CL: POST /secure/handshake (key_id, client_nonce, ciphertext, mac?)
    CL->>CL: decapsulate(ciphertext) -> shared_secret
    CL->>CL: derive session_key = HKDF(shared_secret, salt=client_nonce)
    CL->>CL: create session (session_id, session_key, expires_at)
    CL-->>GW: session_id, expires_at, server_mac?
    GW->>GW: verify server_mac (if ML_KEM_PSK set); cache session

    Note over GW,CL: Per reading (many times per session)
    GW->>GW: nonce = counter_to_nonce(counter++)
    GW->>GW: ciphertext = AES-256-GCM.encrypt(session_key, nonce, reading, aad)
    GW->>CL: POST /secure/data (session_id, device_id, nonce, ciphertext)
    CL->>CL: check session, check counter, AEAD-decrypt
    CL->>CL: save_sensor_data(reading)
    CL-->>GW: {"status": "stored"}

    Note over GW,CL: Cloud restarted, session forgotten
    GW->>CL: POST /secure/data (old session_id, ...)
    CL-->>GW: 404 unknown session_id
    GW->>GW: clear cached session
    GW->>CL: GET /secure/handshake (re-handshake, as above)
    GW->>CL: POST /secure/data (new session_id, retried reading)
    CL-->>GW: {"status": "stored"}
```

## Integration steps for the main agent

These are the only edits needed in files this task does not own. Nothing in
`cloud/app/crypto/` or `gateway/app/crypto/` needs to change for this.

### 1. `cloud/app/main.py`

Add the secure router and gate the existing plaintext endpoint:

```python
from app.crypto import router as secure_router
from app.crypto.mode import enforce_legacy_mode

app.include_router(secure_router)

@app.post("/data")
def receive_data(data: SensorData, _legacy_gate: None = Depends(enforce_legacy_mode)):
    ...  # existing body unchanged
```

This needs `from fastapi import Depends` added to the existing `from fastapi
import FastAPI` import line.

### 2. `gateway/app/cloud_client.py`

Dispatch on the mode switch, keeping the existing function name and return
contract so `gateway/app/main.py` needs no changes at all:

```python
from app.crypto import get_gateway_mode, send_secure

def send_to_cloud(sensor_data: dict):
    if get_gateway_mode() == "off":
        response = requests.post(CLOUD_URL, json=sensor_data, timeout=5)
        response.raise_for_status()
        return response.json()
    return send_secure(sensor_data)
```

`send_secure` raises the same `requests.exceptions.RequestException` family
`send_to_cloud` already raises today (see
`gateway/app/crypto/exceptions.py`), so `gateway/app/main.py`'s existing
`except Exception -> 502` handling needs no change.

Optional but recommended: increment a new metric on secure-channel failure,
mirroring the existing `CLOUD_FORWARD_FAILURES_TOTAL` pattern (add a
`KEM_HANDSHAKE_FAILURES_TOTAL` counter to `gateway/app/metrics.py` and
increment it in the `except` block around `send_secure`) -- this also
happens to be the exact counter name a concurrently-written test suite
(`tests/protected_path/test_protected_path_contract.py`) expects to exist;
see the decision record's "Relationship to the parallel verification suite"
for context. Not required for this package to function.

**Startup risk to test before relying on `off` as a safe default:** importing
`app.crypto` builds the cloud's `KeyManager`/`SessionStore` immediately
(see "Residual risks" -> "The mode switch guards behaviour, not import-time
failures"), so a `cryptography` wheel without `mlkem` on the target
platform, or an unwritable `CLOUD_ML_KEM_KEY_PATH`, crashes the cloud
service at startup even with `CLOUD_ML_KEM_MODE=off`. Verify the cloud
container starts cleanly with the new image and `CLOUD_ML_KEM_MODE=off`
before treating that as a safe rollback state.

### 3. `requirements.txt` (both `cloud/` and `gateway/`)

Append the one line from `requirements-crypto.txt`:

```
cryptography==50.0.1
```

`device/requirements.txt` needs no change.

### 4. `docker-compose.yml`

Add environment variables to the `cloud` and `gateway` services (values
below are a suggested starting rollout state -- see "Migration strategy"
for the order to actually flip them):

```yaml
  cloud:
    environment:
      CLOUD_ML_KEM_MODE: enabled
      ML_KEM_PSK: ${ML_KEM_PSK:-}
      CLOUD_ML_KEM_KEY_PATH: /data/ml-kem-key.der   # optional; needs a volume to persist
      CLOUD_ML_KEM_SESSION_TTL_SECONDS: "300"

  gateway:
    environment:
      CLOUD_URL: http://cloud:8001/data
      GATEWAY_ML_KEM_MODE: enabled
      ML_KEM_PSK: ${ML_KEM_PSK:-}
      GATEWAY_CLOUD_BASE_URL: http://cloud:8001
      GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT: ""       # set once CLOUD_ML_KEM_KEY_PATH is persisted
```

If `CLOUD_ML_KEM_KEY_PATH` is used, add a volume for it (e.g. a named
volume mounted at `/data` on the `cloud` service) so the key survives
container recreation; otherwise leave it unset and accept a fresh key (and
therefore a mandatory gateway re-handshake) on every cloud restart.

### 5. New environment variables

| Variable | Service | Default | Effect |
| --- | --- | --- | --- |
| `CLOUD_ML_KEM_MODE` | cloud | `off` | `off`: `/secure/*` returns 403, plaintext `/data` unchanged. `enabled`: both plaintext and `/secure/*` work. `required`: plaintext `/data` returns 403; `/secure/*` works. |
| `GATEWAY_ML_KEM_MODE` | gateway | `off` | `off`: send plaintext (today's behaviour). `enabled`/`required`: always use the secure channel (no plaintext fallback either way). |
| `ML_KEM_PSK` | both (same value) | unset | Pre-shared secret for mutual HMAC authentication of the handshake. Unset on either side = that side's MAC is skipped; the handshake is then unauthenticated. |
| `CLOUD_ML_KEM_KEY_PATH` | cloud | unset | Filesystem path to persist/load the cloud's ML-KEM-768 private key (PKCS8 DER). Unset = fresh ephemeral key pair every process start. |
| `CLOUD_ML_KEM_SESSION_TTL_SECONDS` | cloud | `300` | Session lifetime in seconds before the cloud considers it expired (`410`). |
| `GATEWAY_CLOUD_BASE_URL` | gateway | `http://localhost:8001` | Base URL (no path suffix) the gateway builds `/secure/handshake` and `/secure/data` against. Set to `http://cloud:8001` in Compose. |
| `GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT` | gateway | unset | Optional hex SHA-256 pin of the expected cloud encapsulation key; mismatches raise `PeerTrustError` before any data is sent. Only useful alongside a persisted `CLOUD_ML_KEM_KEY_PATH`. |

`GATEWAY_ML_KEM_REKEY_SKEW_SECONDS` is available as a constructor parameter
on `SecureCloudClient` (default 15s) but is not read from the environment
by this package; expose it as an env var in the integration patch above
only if operational experience shows the default needs tuning.
