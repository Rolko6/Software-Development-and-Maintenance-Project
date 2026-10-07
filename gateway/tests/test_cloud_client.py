import base64
import json
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey

from app.cloud_client import send_to_cloud


@patch("app.cloud_client.requests.post")
def test_send_to_cloud_encrypts_the_payload(mock_post, monkeypatch):
    # Gateway never holds cloud's private key, so to verify the envelope is
    # genuinely decryptable, generate our OWN keypair, point cloud_client at
    # its public half, and decrypt with the matching private half.
    private_key = MLKEM768PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    monkeypatch.setattr("app.cloud_client.CLOUD_PUBLIC_KEY", public_key)

    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "stored"})

    send_to_cloud({"device_id": "sensor-1", "temperature": 22.5})

    sent_json = mock_post.call_args.kwargs["json"]
    assert set(sent_json.keys()) == {"kem_ciphertext", "nonce", "ciphertext"}

    kem_ciphertext = base64.b64decode(sent_json["kem_ciphertext"])
    nonce = base64.b64decode(sent_json["nonce"])
    ciphertext = base64.b64decode(sent_json["ciphertext"])

    shared_secret = private_key.decapsulate(kem_ciphertext)
    plaintext = AESGCM(shared_secret).decrypt(nonce, ciphertext, None)
    payload = json.loads(plaintext)

    assert payload["device_id"] == "sensor-1"
    assert payload["temperature"] == 22.5
    assert "timestamp" in payload


@patch("app.cloud_client.requests.post")
def test_send_to_cloud_posts_to_secure_endpoint_by_default(mock_post):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "stored"})

    send_to_cloud({"device_id": "sensor-1", "temperature": 22.5})

    called_url = mock_post.call_args.args[0]
    assert called_url.endswith("/data/secure")
