"""ML-KEM secure-channel responder package for the cloud service.

Exposes `router` (a FastAPI APIRouter, ready for `app.include_router(...)`)
and `enforce_legacy_mode` (a dependency for gating the existing plaintext
POST /data endpoint once CLOUD_ML_KEM_MODE=required). See
docs/security/ml-kem-integration.md for the full design and the exact
integration patch.
"""

from .keys import KeyManager
from .mode import enforce_legacy_mode, enforce_secure_enabled, get_cloud_mode, get_psk
from .router import create_secure_router, router
from .sessions import SessionStore

__all__ = [
    "router",
    "create_secure_router",
    "enforce_legacy_mode",
    "enforce_secure_enabled",
    "get_cloud_mode",
    "get_psk",
    "KeyManager",
    "SessionStore",
]
