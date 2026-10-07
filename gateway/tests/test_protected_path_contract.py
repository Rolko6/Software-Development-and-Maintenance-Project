"""Carry PR #6's fail-closed/fresh-key requirements into v3's per-reading path."""
import base64
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey

from app import cloud_client


def test_consecutive_readings_use_fresh_kem_material(monkeypatch):
    private = MLKEM768PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    monkeypatch.setattr(cloud_client, "CLOUD_PUBLIC_KEY", public)
    post = Mock(return_value=Mock(json=lambda: {"status": "stored"}))
    monkeypatch.setattr(cloud_client.requests, "post", post)
    for _ in range(2):
        cloud_client.send_to_cloud({"device_id": "protected-device", "temperature": 22.5})
    envelopes = [call.kwargs["json"] for call in post.call_args_list]
    ciphertexts = [base64.b64decode(e["kem_ciphertext"]) for e in envelopes]
    assert ciphertexts[0] != ciphertexts[1]
    assert private.decapsulate(ciphertexts[0]) != private.decapsulate(ciphertexts[1])
    assert envelopes[0]["nonce"] != envelopes[1]["nonce"]


def test_key_establishment_failure_never_sends_plaintext(monkeypatch):
    def refuse(*args):
        raise RuntimeError("injected encapsulation failure")

    monkeypatch.setattr(cloud_client, "encapsulate", refuse)
    post = Mock()
    monkeypatch.setattr(cloud_client.requests, "post", post)
    with pytest.raises(RuntimeError, match="encapsulation failure"):
        cloud_client.send_to_cloud({"device_id": "protected-device", "temperature": 22.5})
    post.assert_not_called()
