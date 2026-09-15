"""ML-KEM-768 key pair generation, persistence, and lifecycle for the cloud
responder.

Generation: a fresh key pair is generated with the process's CSPRNG
(``cryptography``'s ``MLKEM768PrivateKey.generate()``, backed by OpenSSL) the
first time no persisted key is found.

Loading / persistence: if ``CLOUD_ML_KEM_KEY_PATH`` is set, the private key
is stored on disk (PKCS8 DER, unencrypted -- protect the file with filesystem
permissions / a mounted secret volume) and reloaded on the next start, so the
cloud's encapsulation key -- and therefore its fingerprint -- stays stable
across restarts. This lets an operator pin the fingerprint on the gateway
side (``GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT``) meaningfully. If the
variable is unset (the default), a new ephemeral key pair is generated on
every process start; this is fine functionally (the gateway always
re-handshakes against whatever key is currently published, and never caches
a session across a cloud restart -- see the design doc's failure-behaviour
section) but means the fingerprint is not stable and cannot be usefully
pinned.

Rotation: this module does not implement scheduled rotation. Rotate by
restarting the cloud process with ``CLOUD_ML_KEM_KEY_PATH`` unset (fresh
ephemeral key) or by deleting the persisted key file before restart. Existing
*sessions* are unaffected by rotating the long-term key -- session keys are
derived once at handshake time and cached independently -- only *future*
handshakes pick up the new key. Automatic/scheduled rotation is a documented
residual gap (see docs/security/ml-kem-integration.md).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import mlkem

from . import wire

DEFAULT_KEY_ID = "cloud-mlkem768-1"


class KeyManager:
    """Owns the cloud's long-term ML-KEM-768 decapsulation key."""

    def __init__(self, key_path: Optional[str] = None, key_id: str = DEFAULT_KEY_ID):
        self.key_id = key_id
        self._private_key = self._load_or_generate(key_path)
        public_key = self._private_key.public_key()
        self._public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        if len(self._public_bytes) != wire.EK_LEN:  # pragma: no cover - defensive
            raise RuntimeError(
                f"unexpected ML-KEM-768 encapsulation key length: {len(self._public_bytes)}"
            )
        self.fingerprint = wire.fingerprint(self._public_bytes)

    @staticmethod
    def _load_or_generate(key_path: Optional[str]):
        if not key_path:
            return mlkem.MLKEM768PrivateKey.generate()

        path = Path(key_path)
        if path.exists():
            data = path.read_bytes()
            return serialization.load_der_private_key(data, password=None)

        key = mlkem.MLKEM768PrivateKey.generate()
        der = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(der)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - best effort on unusual filesystems
            pass
        return key

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_bytes

    def decapsulate(self, ciphertext: bytes) -> bytes:
        """Recover the shared secret for a client-supplied ciphertext.

        Per FIPS 203, ML-KEM decapsulation uses *implicit rejection*: a
        ciphertext of the correct length that has been tampered with does
        not raise here -- it silently yields an unrelated (wrong) shared
        secret. Detecting tampering is therefore the AEAD layer's job (the
        first /secure/data call under the resulting session will fail with
        InvalidTag -> HTTP 400), not this method's. A wrong-length
        ciphertext does raise ValueError; callers should map that to a 400.
        """
        return self._private_key.decapsulate(ciphertext)
