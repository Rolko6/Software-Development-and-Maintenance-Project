"""Carry PR #6's fail-closed/fresh-key requirements into v3's per-reading path."""
import base64
from unittest.mock import Mock

import pytest
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app import cloud_client


def test_consecutive_readings_use_fresh_kem_material(monkeypatch):
    public, private = ML_KEM_768.keygen()
    monkeypatch.setattr(cloud_client, "CLOUD_PUBLIC_KEY", public)
    post = Mock(return_value=Mock(json=lambda: {"status": "stored"}))
    monkeypatch.setattr(cloud_client.requests, "post", post)
    for _ in range(2):
        cloud_client.send_to_cloud({"device_id": "protected-device", "temperature": 22.5})
    envelopes = [call.kwargs["json"] for call in post.call_args_list]
    ciphertexts = [base64.b64decode(e["kem_ciphertext"]) for e in envelopes]
    assert ciphertexts[0] != ciphertexts[1]
    assert ML_KEM_768.decaps(private, ciphertexts[0]) != ML_KEM_768.decaps(private, ciphertexts[1])
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
