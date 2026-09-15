"""In-memory session store for ML-KEM-derived AEAD keys.

A session is created at the end of a successful handshake and identifies an
AES-256-GCM key plus a strictly-increasing message counter (see wire.py's
counter-as-nonce scheme). Sessions expire after a fixed TTL; there is no
persistence, so a cloud process restart forgets every session -- this is
intentional (see docs/security/ml-kem-integration.md, "Failure behaviour")
and is handled by the gateway re-handshaking automatically on 404/410.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class Session:
    session_id: str
    key: bytes
    created_at: float
    expires_at: float
    last_counter: int = -1


class SessionStore:
    """Thread-safe. FastAPI's sync `def` endpoints run on a threadpool, so
    every mutation is taken under a single lock; counter validation is
    split into a read-only `check_counter` and a commit-on-success
    `commit_counter` so that a request with an unauthenticated (not yet
    AEAD-verified) counter can never advance the replay window -- otherwise
    an attacker could send a bogus ciphertext with a huge counter purely to
    get later legitimate messages rejected as "replays" (a counter-poisoning
    DoS). Only a request whose ciphertext successfully decrypts commits its
    counter.
    """

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: Dict[str, Session] = {}

    def create(self, key: bytes) -> Session:
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            session_id = secrets.token_urlsafe(18)
            session = Session(
                session_id=session_id,
                key=key,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Tuple[Optional[Session], Optional[str]]:
        """Returns (session, None) on success, or (None, "unknown"/"expired")."""
        now = time.time()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None, "unknown"
            if session.expires_at <= now:
                del self._sessions[session_id]
                return None, "expired"
            return session, None

    def check_counter(self, session_id: str, counter: int) -> bool:
        """Read-only freshness check -- does not mutate state."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            return counter > session.last_counter

    def commit_counter(self, session_id: str, counter: int) -> bool:
        """Atomically advances last_counter after the ciphertext has been
        authenticated. Returns False if the session vanished or the counter
        is no longer fresh (e.g. a concurrent request already advanced it)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if counter <= session.last_counter:
                return False
            session.last_counter = counter
            return True

    def _sweep_locked(self, now: float) -> None:
        expired = [sid for sid, s in self._sessions.items() if s.expires_at <= now]
        for sid in expired:
            del self._sessions[sid]

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
