"""Gateway-side cached session state.

Deliberately in-process memory only -- never persisted to disk. That is
what makes the counter-as-nonce scheme in wire.py safe across gateway
restarts: a fresh process starts with no cached session, so its first
`send_secure` call always performs a fresh handshake (a fresh HKDF salt,
hence a fresh AES-256-GCM key) before it ever encrypts anything, so the
counter resetting to 0 never collides with a nonce used under the same key
by a previous process. Persisting this dataclass to disk (e.g. to survive a
gateway restart without re-handshaking) would break that invariant and must
not be done without also durably and atomically persisting `counter`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClientSession:
    session_id: str
    key: bytes
    expires_at: float
    counter: int = -1  # last counter successfully sent; next message uses counter + 1
