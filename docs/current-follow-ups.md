# Current follow-up proposals — 2026-10-05

These are proposals for the rewritten v3 implementation. The source findings were checked during earlier chats against an older checkout and, for storage, the v3 source. The prompt history is preserved in [P012 and P013](ai/prompts/2026-10-05-yyy-tom.md). No runtime or deployment change was implemented in the documentation recovery.

## Persist readings across restarts

The v3 cloud uses `stored_data = []` in `cloud/app/storage.py`; both legacy `/data` and decrypted `/data/secure` submissions call `save_sensor_data`. Each cloud-process restart creates a fresh empty list. Earlier v2 used a bounded in-memory collection, which also lost data on restart.

P013 proposes SQLite for a single-cloud course deployment, with the database directory mounted from a named volume, committed writes before success responses, response ordering preserved, write failures reported, and a deliberate retention policy. The earlier v2 1,000-reading cap must not be silently assumed for v3, which is currently unbounded. Verify the exact submitted reading survives both a process restart and container recreation, and cover both submission routes. This remains unimplemented; prior lost readings cannot be recovered from the in-memory store.

## Close plaintext cloud ingestion

The v3 cloud still accepts plaintext `POST /data` with a warning and increments `legacy_data_received_total`; its protected endpoint is `POST /data/secure`. This bypass exists even while the gateway encrypts its forwarded readings.

The [recovered finding](archive/pre-v3/docs/security/plaintext-ingestion-bypass.md) applies to the earlier mode-based implementation, where `CLOUD_ML_KEM_MODE=required` can reject plaintext. V3 does not have that mode gate. Its fix therefore needs to reject or disable direct plaintext ingestion in the secured deployment, rather than copy the old environment-variable instructions. The legacy device can continue posting to the gateway. Verify rejection without storing a reading and continued delivery through the encrypted gateway path. Migration requirements and endpoint authentication need an explicit decision before implementation.

## Re-evaluate earlier security and operations work against v3

The historical security branch contained nonce handling, configuration guards, metrics fixes, healthchecks, alert rules and live security evidence. Recovering its documents does not port those production changes into v3. Likewise, the old CI fault-injection and deployment results do not verify the current workflow. The applicable CI and measurement work is now implemented in [replacement PR #17](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/17), targeting active v3 develop; it remains pending review/merge. Use the [version comparison](recovery/2026-10-05-documentation-recovery.md) to choose a baseline before adapting those checks.
