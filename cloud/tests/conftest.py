import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey

# app.keys reads CLOUD_ML_KEM_PRIVATE_KEY at import time, so it must be set
# before anything imports app.main. Tests get the matching public key via
# the cloud_public_key fixture below to build valid encrypted requests.
_test_private_key = MLKEM768PrivateKey.generate()
_test_public_key = _test_private_key.public_key().public_bytes_raw()
os.environ["CLOUD_ML_KEM_PRIVATE_KEY"] = base64.b64encode(_test_private_key.private_bytes_raw()).decode()
os.environ["CLOUD_ALLOW_LEGACY_INGESTION"] = "false"


@pytest.fixture(scope="session")
def cloud_public_key():
    return _test_public_key


@pytest.fixture(autouse=True)
def isolated_cloud_storage(tmp_path, monkeypatch):
    """Give every test its own disposable SQLite database."""
    monkeypatch.setenv("CLOUD_DB_PATH", str(tmp_path / "readings.sqlite3"))
