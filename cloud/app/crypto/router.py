"""FastAPI router implementing the cloud (responder) side of the ML-KEM
secure channel.

Integration: ``app.include_router(router)`` in cloud/app/main.py (see
docs/security/ml-kem-integration.md, "Integration steps for the main
agent"). Every route is gated by `enforce_secure_enabled` (403 when
CLOUD_ML_KEM_MODE=off).

Endpoints:
- GET  /secure/handshake  -- publish the current encapsulation key.
- POST /secure/handshake  -- accept a client's ML-KEM ciphertext, create a session.
- POST /secure/data       -- accept one AEAD-protected sensor reading.

`create_secure_router()` is a factory so tests can build an isolated router
(fresh KeyManager + SessionStore) instead of sharing the process-wide
singleton; the module-level `router` below is what real deployments use.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from . import wire
from .keys import KeyManager
from .mode import enforce_secure_enabled, get_psk
from .schemas import (
    HandshakeInfo,
    HandshakeRequest,
    HandshakeResponse,
    SecureDataRequest,
    SecureDataResponse,
)
from .sessions import SessionStore
from ..models import SensorData
from ..storage import save_sensor_data

logger = logging.getLogger(__name__)

_psk_warned = False


def _warn_if_unauthenticated(psk: Optional[bytes]) -> None:
    global _psk_warned
    if psk is None and not _psk_warned:
        logger.warning(
            "ML_KEM_PSK is not set: ML-KEM handshakes are unauthenticated and "
            "the gateway<->cloud link is vulnerable to an active "
            "machine-in-the-middle. See docs/security/ml-kem-integration.md "
            "(Peer/key trust)."
        )
        _psk_warned = True


def _decode_b64(value: str, field_name: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"malformed base64 in field '{field_name}'"
        ) from exc


def create_secure_router(
    key_manager: Optional[KeyManager] = None,
    session_store: Optional[SessionStore] = None,
) -> APIRouter:
    # NOTE: deliberately `is None` rather than truthiness (`x or default`):
    # a freshly constructed, empty SessionStore defines __len__() == 0 and
    # is therefore falsy, which would silently discard a caller-provided
    # empty store and replace it with a different one.
    if key_manager is None:
        key_manager = KeyManager(key_path=os.environ.get("CLOUD_ML_KEM_KEY_PATH"))
    if session_store is None:
        ttl_seconds = float(os.environ.get("CLOUD_ML_KEM_SESSION_TTL_SECONDS", "300"))
        session_store = SessionStore(ttl_seconds=ttl_seconds)

    router = APIRouter(
        prefix="/secure",
        tags=["ml-kem"],
        dependencies=[Depends(enforce_secure_enabled)],
    )

    @router.get("/handshake", response_model=HandshakeInfo)
    def handshake_info() -> HandshakeInfo:
        return HandshakeInfo(
            key_id=key_manager.key_id,
            algorithm=wire.KEM_ALGORITHM,
            encapsulation_key=base64.b64encode(key_manager.public_key_bytes).decode("ascii"),
            fingerprint=key_manager.fingerprint,
        )

    @router.post("/handshake", response_model=HandshakeResponse)
    def do_handshake(body: HandshakeRequest) -> HandshakeResponse:
        if body.key_id != key_manager.key_id:
            raise HTTPException(
                status_code=404,
                detail="unknown key_id; fetch GET /secure/handshake again",
            )

        client_nonce = _decode_b64(body.client_nonce, "client_nonce")
        ciphertext = _decode_b64(body.ciphertext, "ciphertext")
        mac = _decode_b64(body.mac, "mac") if body.mac else None

        if len(client_nonce) != wire.CLIENT_NONCE_LEN:
            raise HTTPException(status_code=400, detail="invalid client_nonce length")
        if len(ciphertext) != wire.CIPHERTEXT_LEN:
            raise HTTPException(status_code=400, detail="invalid ciphertext length")

        psk = get_psk()
        _warn_if_unauthenticated(psk)
        fingerprint_bytes = bytes.fromhex(key_manager.fingerprint)

        if psk is not None:
            expected = wire.compute_mac(
                psk, b"client", body.key_id.encode("utf-8"), client_nonce, fingerprint_bytes, ciphertext
            )
            if mac is None or not wire.constant_time_equal(expected, mac):
                raise HTTPException(status_code=401, detail="handshake authentication failed")

        try:
            shared_secret = key_manager.decapsulate(ciphertext)
        except ValueError as exc:
            # Wrong-length/malformed ciphertext. Content tampering does NOT
            # raise here (FIPS 203 implicit rejection) -- it surfaces later
            # as an AEAD failure on the first /secure/data call.
            raise HTTPException(
                status_code=400, detail="ciphertext rejected by ML-KEM decapsulation"
            ) from exc

        session_key = wire.derive_session_key(shared_secret, client_nonce, body.key_id)
        session = session_store.create(session_key)

        server_mac_b64 = None
        if psk is not None:
            server_mac = wire.compute_mac(
                psk,
                b"server",
                body.key_id.encode("utf-8"),
                client_nonce,
                fingerprint_bytes,
                ciphertext,
                session.session_id.encode("utf-8"),
            )
            server_mac_b64 = base64.b64encode(server_mac).decode("ascii")

        return HandshakeResponse(
            session_id=session.session_id,
            expires_at=session.expires_at,
            algorithm=wire.KEM_ALGORITHM,
            aead=wire.AEAD_ALGORITHM,
            server_mac=server_mac_b64,
        )

    @router.post("/data", response_model=SecureDataResponse)
    def receive_secure_data(body: SecureDataRequest) -> SecureDataResponse:
        nonce = _decode_b64(body.nonce, "nonce")
        ciphertext = _decode_b64(body.ciphertext, "ciphertext")

        if len(nonce) != wire.NONCE_LEN:
            raise HTTPException(status_code=400, detail="invalid nonce length")

        session, error = session_store.get(body.session_id)
        if error == "unknown":
            raise HTTPException(status_code=404, detail="unknown session_id; re-handshake required")
        if error == "expired":
            raise HTTPException(status_code=410, detail="session expired; re-handshake required")

        counter = wire.nonce_to_counter(nonce)
        if not session_store.check_counter(body.session_id, counter):
            raise HTTPException(status_code=409, detail="replayed or out-of-order counter")

        aad = wire.build_aad(body.session_id, body.device_id, nonce)
        try:
            plaintext = wire.aead_decrypt(session.key, nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise HTTPException(status_code=400, detail="ciphertext authentication failed") from exc

        if not session_store.commit_counter(body.session_id, counter):
            # Lost a race with a concurrent request for the same session.
            raise HTTPException(status_code=409, detail="replayed or out-of-order counter")

        try:
            reading = json.loads(plaintext.decode("utf-8"))
            sensor_data = SensorData(**reading)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail="decrypted payload failed validation"
            ) from exc

        if sensor_data.device_id != body.device_id:
            # Defense in depth only: build_aad already binds device_id, so a
            # mismatch here would already have failed as InvalidTag above
            # unless the *original* sender itself encrypted inconsistent
            # values.
            raise HTTPException(
                status_code=400, detail="device_id mismatch between envelope and payload"
            )

        save_sensor_data(sensor_data.model_dump())
        return SecureDataResponse(status="stored")

    return router


router = create_secure_router()
