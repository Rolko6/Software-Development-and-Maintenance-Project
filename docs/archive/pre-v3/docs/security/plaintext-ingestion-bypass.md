> Historical pre-v3 documentation, recovered from the uncommitted local checkout on 2026-10-05. Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../../../../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Plaintext cloud-ingestion bypass

Recorded: 2026-10-05. Status: **Confirmed by source inspection and existing unit
tests; remediation proposed, not implemented.** Request:
[P012](../../../../ai/prompts/2026-10-05-yyy-tom.md#p012-record-the-plaintext-ingestion-bypass-and-suggest-a-fix).
Inspected revision: `b297b28fd7ed31177babdebe7a7dcbc3481fbd90`.

## Finding and impact

The default [Compose configuration](../../../../../docker-compose.yml) sets
`CLOUD_ML_KEM_MODE=enabled` and publishes cloud port 8001 without a loopback
restriction. The real [cloud POST /data route](../../../../../cloud/app/main.py) calls
`enforce_legacy_mode`, but that [gate](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/b297b28fd7ed31177babdebe7a7dcbc3481fbd90/cloud/app/crypto/mode.py) rejects
plaintext only in `required` mode. In `enabled` mode a reachable caller can submit
valid sensor JSON directly to `POST /data` and store it without ML-KEM encryption,
AEAD integrity protection, or the secure handshake's PSK authentication.
Network access and a payload passing sensor validation are sufficient; the
legacy route has no caller authentication dependency.

This bypasses the gateway→cloud protection requirement and permits fabricated
readings through the legacy cloud endpoint. It does not break ML-KEM or AES-GCM.
The gateway itself already forwards securely in `enabled` and `required` modes
and has no plaintext fallback after secure delivery fails.

The plaintext device→gateway hop is a separate boundary. The device sends to
`POST /device-data`; the gateway encrypts before sending to `POST /secure/data`.
Keeping that device compatible does not require accepting plaintext at the cloud.

There is also a configuration risk: absent cloud mode defaults to `off`, and
unknown values in `get_cloud_mode()` normalize to `off`. The cloud entry point
has separate mode handling. A typo can therefore leave legacy ingestion open.
Startup and request gating need one consistent validated policy.

## Recommended fix

1. Make `required` the default cloud mode in the secured Compose deployment.
   Set the gateway to `required` too so the deployment intent is explicit.
   The existing cloud gate already returns HTTP `403` for plaintext in this mode;
   there is no need to change the legacy device payload.
2. Default absent application mode variables to `required` on both services.
   Reject empty and unknown values at startup with a clear configuration error.
   Use the validated mode consistently for router mounting, legacy gating,
   forwarding, and metrics. Preserve `off` and `enabled` only when explicitly
   selected for isolated baseline or migration runs.
3. Keep the rejection at the cloud ingestion boundary. Network restrictions
   help reduce exposure but do not replace rejecting plaintext in the service.
   Do not recover from key, handshake, or encrypted-send failures by enabling
   plaintext ingestion or forwarding.
4. Update Compose comments, the README, deployment guidance, and mode tests to
   match the new default. Current comments incorrectly connect plaintext cloud
   ingestion to the legacy device's compatibility. Document that recreating the
   cloud clears in-memory readings and that deployments with old plaintext
   gateways must upgrade those gateways before enforcing `required`.

The immediate configuration mitigation is to explicitly select
`CLOUD_ML_KEM_MODE=required` while keeping gateway secure forwarding enabled.
That is already supported by the current code; this task has not applied it
to a running stack.

## Alternatives

| Approach | Benefit | Trade-off |
| --- | --- | --- |
| **Recommend: required by default with strict mode validation** | Closes the default bypass using the existing gate and preserves explicit baseline/migration experiments | Changes the default deployment contract for older plaintext gateways |
| Remove cloud plaintext POST /data entirely | Removes the legacy ingestion surface | Breaks baseline and mixed-gateway migration workflows |
| Keep enabled behind an isolated migration deployment | Supports genuinely unupgraded gateways | Plaintext ingestion remains possible there; isolation does not enforce encrypted ingestion |

## Acceptance criteria for implementation

- Under the default secured configuration, valid direct plaintext `POST /data`
  returns HTTP `403` and the probe's unique device ID is absent from storage.
  Exercise the real cloud app, including routing variants such as `/data/`,
  rather than relying only on a dummy route with the same dependency.
- The unchanged device→gateway payload still reaches cloud storage through
  `POST /secure/data`. Cloud logs show no plaintext forwarding.
- Missing mode variables select `required`; empty and unknown values fail
  startup without serving an accepting plaintext route. Both application entry
  points and mode helpers obey the same policy.
- Explicit baseline/migration modes retain their documented behaviour in
  isolated test deployments; tests select those modes explicitly.
- Failed key establishment, tampered ciphertext, expired sessions, and cloud
  unavailability never trigger plaintext forwarding or plaintext storage.
- Documentation checks, mode tests, relevant service tests, and container
  integration checks pass, with observed outcomes recorded.

## Verification performed for this record

- Repository was clean before editing. Inspected Compose, the cloud entry point
  and gate, the gateway forwarding branch, and existing mode tests.
- Executed `.venv/bin/python -m pytest tests/crypto/test_mode_switch.py -q`:
  **7 passed**, with one dependency deprecation warning. These tests confirm
  `enabled` accepts plaintext and `required` rejects it through a
  `FakeCloudApp` using the real gate. They do not execute the real cloud entry
  point or prove the proposed default changes.
- Executed `docker compose config --quiet`: exit 0, with Docker Compose
  v5.1.3. This validates the current configuration only.
- Executed `.venv/bin/python .github/scripts/check_docs.py`: 31 Markdown files
  and 216 local links checked; no violations. `git diff --check`: exit 0.
- The [2026-09-15 integration record](../validation/2026-09-15-integration.md)
  already records live `enabled` plaintext acceptance and `required` rejection.
  That is historical evidence, not a new runtime check.
- No live stack was reconfigured, and no end-to-end check was run for this
  documentation task. Implementation and its acceptance checks remain open.

Compose validation was checked through Context7 (`/docker/compose`) against
Docker's [config implementation](https://github.com/docker/compose/blob/main/cmd/compose/config.go):
`config --quiet` is validation only. Project-specific mode semantics come
from the repository source, not from Docker documentation.

## Residual risks

Enforcing the encrypted cloud path does not authenticate the legacy device or
stop a reachable caller from submitting fabricated readings to the gateway's
plaintext endpoint for encryption. Gateway ingress needs its own authentication
or network controls if device identity is required. The visible development PSK,
unprotected read API, device→gateway exposure, and other
[protocol limitations](ml-kem-integration.md) also remain separate work.
