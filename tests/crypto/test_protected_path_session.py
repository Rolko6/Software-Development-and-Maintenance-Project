"""Protected-path contract, ported to the session-based ML-KEM design.

tests/protected_path/test_protected_path_contract.py states what the
gateway-to-cloud link has to satisfy, but it was written against a proposed
sessionless ``gateway/app/kem.py`` that was never built, so it skips. The
implemented design (docs/decisions/0002-ml-kem-key-establishment.md) runs one
ML-KEM handshake per session in gateway/app/crypto and cloud/app/crypto and
then AES-256-GCM-encrypts each reading under the derived session key. Both the
contract's docstring and ADR 0002 expect that contract to be rewritten for a
session design. This module is that rewrite. Each test's docstring names the
contract test it ports. The assertions keep the original strength. Where the
session design changes what can be observed, the docstring says so.

Ported here:

  a. test_parameter_set_is_the_one_the_group_agreed_on
  b. test_key_material_has_the_sizes_of_the_declared_parameter_set
  c. test_recorded_traffic_does_not_reveal_the_reading (the device-id
     assertion is kept as a strict xfail; see below)
  d. test_recorded_traffic_carries_ml_kem_material
  e. test_the_ml_kem_secret_changes_the_session_key
  g1. test_failed_key_establishment_fails_closed (the "nothing sent" half)

Not ported. Each of these needs a decision from Stanley/Tiago, and a
production change, before it can be tested:

  c (device id). The original asserts the device id never appears in clear.
     In this design ``device_id`` travels in clear in every /secure/data body
     as routing and AEAD associated data (wire.build_aad). The assertion is
     kept below as ``xfail(strict=True)``, so it turns into a failure the day
     the design stops sending the device id in clear.
  f. test_a_classical_secret_alone_is_not_accepted. ``wire.derive_session_key``
     has no length guard: an empty or short ML-KEM secret goes into HKDF
     without complaint. Adding a 32-byte guard changes production code in both
     wire copies.
  g2. The counter half of test_failed_key_establishment_fails_closed.
     ``GATEWAY_HANDSHAKE_FAILED_TOTAL`` is defined in gateway/app/metrics.py
     but nothing increments it, so there is nothing to assert.

Harness notes:

* Services load under the ``_gateway_app`` / ``_cloud_app`` aliases from
  conftest.py. The cloud side is the real secure router behind FastAPI's
  TestClient. The gateway side is the real SecureCloudClient with an injected
  transport that records every JSON body in both directions.
* The cloud session clock is pinned (see ``frozen_cloud_clock``). The recorded
  handshake response contains ``expires_at`` as a float, and a real clock value
  can contain the digits "22.5" by chance. Pinning it keeps the
  "reading not in traffic" assertion deterministic without excluding any field
  from the recording.
* gateway/app/cloud_client.py registers Prometheus collectors on import, and
  tests/reliability imports the gateway under another alias in the same
  process. To avoid a duplicate-timeseries error, cloud_client is loaded
  against a no-op stand-in for ``.metrics``. Nothing here asserts on metrics
  (g2 is not ported).
* ``cloud_client._send_secure`` imports ``app.crypto`` absolutely, and that
  name does not exist under the test aliases. The fail-closed tests replace
  ``_send_secure`` with the real SecureCloudClient's ``send_secure`` on a
  recording transport, so the real ``send_to_cloud`` dispatch and retry loop
  run against the real client.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import types

import pytest
import requests

from .conftest import (
    cloud_keys_module,
    cloud_sessions_module,
    cloud_storage_module,
    cloud_wire_module,
    gateway_client_module,
    gateway_wire_module,
    make_transport,
)

ACCEPTED_PARAMETER_SETS = {"ML-KEM-768", "ML-KEM-1024"}

# FIPS 203 Table 3 sizes in bytes, for the parameter sets this project accepts.
# The decapsulation key size (768: 2400, 1024: 3168) is left out on purpose:
# KeyManager never exposes the decapsulation key, so this port cannot observe
# it. See test_key_material_has_the_sizes_of_the_declared_parameter_set.
ARTIFACT_SIZES = {
    "ML-KEM-768": {"ek": 1184, "ct": 1088, "ss": 32},
    "ML-KEM-1024": {"ek": 1568, "ct": 1568, "ss": 32},
}

DEVICE_ID = "contract-sensor-001"
READING = {"device_id": DEVICE_ID, "temperature": 22.5}

WIRE_MODULES = pytest.mark.parametrize(
    "wire",
    [gateway_wire_module, cloud_wire_module],
    ids=["gateway-wire", "cloud-wire"],
)


# --- Harness ----------------------------------------------------------------


class RecordingTransport:
    """Every JSON body that crosses the gateway-cloud link, in both
    directions, as an eavesdropper would store it."""

    def __init__(self, test_client):
        self._get, self._post = make_transport(test_client)
        self.exchanges = []  # (method, url, request_body | None, response_body | None)

    @staticmethod
    def _response_body(response):
        try:
            return response.json()
        except ValueError:
            return None

    def http_get(self, url, timeout):
        response = self._get(url, timeout)
        self.exchanges.append(("GET", url, None, self._response_body(response)))
        return response

    def http_post(self, url, json_body, timeout):
        response = self._post(url, json_body, timeout)
        self.exchanges.append(("POST", url, json_body, self._response_body(response)))
        return response

    def recorded_bytes(self) -> bytes:
        chunks = []
        for _method, url, request_body, response_body in self.exchanges:
            chunks.append(url.encode())
            for body in (request_body, response_body):
                if body is not None:
                    chunks.append(json.dumps(body).encode())
        return b"\n".join(chunks)

    def posts_to(self, suffix):
        return [e for e in self.exchanges if e[0] == "POST" and e[1].endswith(suffix)]


@pytest.fixture()
def frozen_cloud_clock(monkeypatch):
    """Pin the cloud session store's clock so ``expires_at`` is a fixed
    value (2000000300.0) that cannot contain the reading's digits by
    chance. The value is later than today, so the gateway's real clock
    still sees the session as fresh."""
    monkeypatch.setattr(
        cloud_sessions_module, "time", types.SimpleNamespace(time=lambda: 2_000_000_000.0)
    )


@pytest.fixture()
def recorder(test_client, frozen_cloud_clock):
    return RecordingTransport(test_client)


@pytest.fixture()
def recorded_client(recorder, monkeypatch):
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    monkeypatch.delenv("GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT", raising=False)
    return gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001",
        http_get=recorder.http_get,
        http_post=recorder.http_post,
    )


class _NoopMetric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


def _load_gateway_cloud_client():
    name = "_gateway_app.cloud_client"
    if name in sys.modules:
        return sys.modules[name]

    metrics_name = "_gateway_app.metrics"
    stub = types.ModuleType(metrics_name)
    for metric in (
        "GATEWAY_CLOUD_REQUEST_DURATION_SECONDS",
        "GATEWAY_CLOUD_RETRIES_EXHAUSTED_TOTAL",
        "GATEWAY_CLOUD_RETRY_ATTEMPTS_TOTAL",
    ):
        setattr(stub, metric, _NoopMetric())

    previous = sys.modules.get(metrics_name)
    sys.modules[metrics_name] = stub
    try:
        return importlib.import_module(name)
    finally:
        if previous is None:
            sys.modules.pop(metrics_name, None)
        else:
            sys.modules[metrics_name] = previous


class PlaintextPostRecorder:
    """Stands in for ``requests.post`` in cloud_client. It answers 200, so a
    plaintext fallback would look like a success and be caught."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, timeout=None, **kwargs):
        self.calls.append((url, json))

        class Response:
            status_code = 200
            text = '{"status": "stored"}'

            @staticmethod
            def json():
                return {"status": "stored"}

        return Response()


@pytest.fixture()
def gateway_cloud_client(monkeypatch, recorded_client):
    """gateway/app/cloud_client.py in secure mode, dispatching to the real
    SecureCloudClient on the recording transport, with backoff removed."""
    cloud_client = _load_gateway_cloud_client()
    monkeypatch.setattr(cloud_client, "ML_KEM_MODE", "required")
    monkeypatch.setattr(cloud_client, "CLOUD_URL", "http://cloud.test/data")
    monkeypatch.setattr(cloud_client, "CLOUD_FORWARD_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(cloud_client, "CLOUD_FORWARD_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(cloud_client, "CLOUD_FORWARD_TOTAL_BUDGET_SECONDS", 4.0)
    monkeypatch.setattr(cloud_client, "_send_secure", recorded_client.send_secure)

    plaintext_posts = PlaintextPostRecorder()
    # cloud_client calls requests.post through its module-level `requests`
    # import, which is this same module object.
    assert cloud_client.requests is requests
    monkeypatch.setattr(requests, "post", plaintext_posts)
    return cloud_client, plaintext_posts


# --- a. parameter set ---------------------------------------------------------


def test_parameter_set_is_the_one_the_group_agreed_on(test_client):
    """Ports test_parameter_set_is_the_one_the_group_agreed_on.

    A silent drop to ML-KEM-512 would still pass every round-trip test. Both
    wire copies must declare an accepted set and agree with each other, and
    the cloud must advertise that same set on GET /secure/handshake.
    """
    assert gateway_wire_module.KEM_ALGORITHM in ACCEPTED_PARAMETER_SETS
    assert cloud_wire_module.KEM_ALGORITHM in ACCEPTED_PARAMETER_SETS
    assert gateway_wire_module.KEM_ALGORITHM == cloud_wire_module.KEM_ALGORITHM

    response = test_client.get("/secure/handshake")
    assert response.status_code == 200
    assert response.json()["algorithm"] == gateway_wire_module.KEM_ALGORITHM


# --- b. sizes -----------------------------------------------------------------


@WIRE_MODULES
def test_wire_size_constants_match_the_declared_parameter_set(wire):
    """Ports test_key_material_has_the_sizes_of_the_declared_parameter_set
    (the declared-constants half).

    The size constants each side validates against must be the FIPS 203
    sizes of the declared parameter set, not left over from another set.
    """
    expected = ARTIFACT_SIZES[wire.KEM_ALGORITHM]
    assert wire.EK_LEN == expected["ek"]
    assert wire.CIPHERTEXT_LEN == expected["ct"]
    assert wire.SHARED_SECRET_LEN == expected["ss"]


def test_key_material_has_the_sizes_of_the_declared_parameter_set():
    """Ports test_key_material_has_the_sizes_of_the_declared_parameter_set.

    Checks that the declared name matches the real algorithm. The cloud's
    KeyManager provides the encapsulation key. The gateway's ML-KEM binding
    (the ``mlkem`` module that gateway/app/crypto/client.py encapsulates with)
    produces the ciphertext and secret. KeyManager decapsulates, and the
    secret must round-trip.

    Not ported: the decapsulation-key size assertion. KeyManager keeps the
    decapsulation key private and exposes no bytes for it, so its size cannot
    be observed through the implemented interface.
    """
    expected = ARTIFACT_SIZES[gateway_wire_module.KEM_ALGORITHM]
    key_manager = cloud_keys_module.KeyManager()

    ek = key_manager.public_key_bytes
    assert len(ek) == expected["ek"]

    public_key = gateway_client_module.mlkem.MLKEM768PublicKey.from_public_bytes(ek)
    secret, ciphertext = public_key.encapsulate()

    assert len(ciphertext) == expected["ct"]
    assert len(secret) == expected["ss"] == 32
    assert key_manager.decapsulate(ciphertext) == secret


# --- c. recorded traffic hides the reading ------------------------------------


def test_recorded_traffic_does_not_reveal_the_reading(recorded_client, recorder, cloud_app):
    """Ports test_recorded_traffic_does_not_reveal_the_reading (temperature
    and field-name assertions).

    The harvest-now-decrypt-later case. Every request and response body of
    the handshake and the data exchange is recorded. The reading's value and
    field name must not appear anywhere in them. The cloud must still store
    the reading, so the test cannot pass because nothing was sent.
    """
    recorded_client.send_secure(dict(READING))

    assert recorder.posts_to("/secure/handshake"), "no handshake was recorded"
    assert recorder.posts_to("/secure/data"), "no data request was recorded"
    assert list(cloud_storage_module.stored_data) == [READING]

    traffic = recorder.recorded_bytes()
    assert b"22.5" not in traffic, "temperature appears in cleartext"
    assert b"temperature" not in traffic, "field names leak the payload shape"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Open design question, pending Stanley/Tiago decision: device id "
        "travels in cleartext as routing/associated data in every "
        "/secure/data body (wire.build_aad). If the design changes, this "
        "strict xfail fails and the marker must be removed."
    ),
)
def test_recorded_traffic_does_not_reveal_the_device_id(recorded_client, recorder, cloud_app):
    """Ports test_recorded_traffic_does_not_reveal_the_reading (device-id
    assertion), unchanged."""
    recorded_client.send_secure(dict(READING))

    assert recorder.posts_to("/secure/data"), "no data request was recorded"
    assert DEVICE_ID.encode() not in recorder.recorded_bytes(), "device id appears in cleartext"


# --- d. recorded traffic carries ML-KEM material ------------------------------


def test_recorded_traffic_carries_ml_kem_material(recorded_client, recorder, cloud_app):
    """Ports test_recorded_traffic_carries_ml_kem_material, rewritten for a
    session design as that test's module docstring asks.

    Absence of plaintext is not presence of ML-KEM. The recorded handshake
    must carry an ML-KEM ciphertext of the declared set's size. The
    handshake response must name that KEM, so a captured exchange can be
    attributed without the source. Every recorded data message must belong to
    the session that ML-KEM handshake established.
    """
    recorded_client.send_secure(dict(READING))
    recorded_client.send_secure({"device_id": DEVICE_ID, "temperature": 23.0})

    handshakes = recorder.posts_to("/secure/handshake")
    data_messages = recorder.posts_to("/secure/data")
    assert len(handshakes) == 1
    assert len(data_messages) == 2

    _method, _url, handshake_request, handshake_response = handshakes[0]
    algorithm = handshake_response["algorithm"]

    assert algorithm in ACCEPTED_PARAMETER_SETS
    assert algorithm == cloud_wire_module.KEM_ALGORITHM

    ciphertext = base64.b64decode(handshake_request["ciphertext"], validate=True)
    assert len(ciphertext) == ARTIFACT_SIZES[algorithm]["ct"]

    session_id = handshake_response["session_id"]
    assert session_id
    for _method, _url, data_request, _data_response in data_messages:
        assert data_request["session_id"] == session_id


# --- e. the ML-KEM secret determines the session key --------------------------


@WIRE_MODULES
def test_the_ml_kem_secret_changes_the_session_key(wire):
    """Ports test_the_ml_kem_secret_changes_the_session_key.

    The kill switch: prove ML-KEM is load-bearing, not decorative. With the
    nonce and key id held fixed, changing only the ML-KEM shared secret must
    change the derived session key. Both wire copies are checked, because the
    gateway and the cloud each derive the key themselves.
    """
    client_nonce = b"\x01" * wire.CLIENT_NONCE_LEN
    key_id = "cloud-mlkem768-1"

    first = wire.derive_session_key(b"\xaa" * 32, client_nonce, key_id)
    second = wire.derive_session_key(b"\xbb" * 32, client_nonce, key_id)

    assert first != second, "session key ignores the ML-KEM secret"
    assert len(first) >= 32


# --- g1. fail closed ----------------------------------------------------------


class _RefusingMLKEM:
    """Stands in for the ``mlkem`` module gateway/app/crypto/client.py uses:
    loading the cloud's encapsulation key fails, so ML-KEM key establishment
    cannot happen."""

    class MLKEM768PublicKey:
        @staticmethod
        def from_public_bytes(_data):
            raise ValueError("simulated key establishment failure")


def _break_mlkem(monkeypatch, _client):
    monkeypatch.setattr(gateway_client_module, "mlkem", _RefusingMLKEM)


def _cloud_unreachable_during_handshake(monkeypatch, client):
    def refuse(url, timeout):
        raise requests.exceptions.ConnectionError("simulated: cloud unreachable")

    monkeypatch.setattr(client, "_http_get", refuse)


@pytest.mark.parametrize(
    "break_key_establishment",
    [_break_mlkem, _cloud_unreachable_during_handshake],
    ids=["ml-kem-key-loading-fails", "handshake-unreachable-with-retries"],
)
def test_failed_key_establishment_fails_closed(
    break_key_establishment, gateway_cloud_client, recorded_client, recorder, cloud_app, monkeypatch
):
    """Ports test_failed_key_establishment_fails_closed (the fail-closed half;
    the metrics half is g2, not ported).

    When ML-KEM key establishment fails, gateway/app/cloud_client.py's
    send_to_cloud must raise. It must not fall back to a plaintext POST, on
    the first attempt or on any retry. The reading must not appear in
    anything that crossed the wire, and the cloud must store nothing.
    """
    cloud_client, plaintext_posts = gateway_cloud_client
    break_key_establishment(monkeypatch, recorded_client)

    with pytest.raises(Exception):
        cloud_client.send_to_cloud(dict(READING))

    assert plaintext_posts.calls == [], "plaintext sent after key establishment failed"
    assert recorder.posts_to("/secure/data") == [], "data sent without a session"
    assert b"22.5" not in recorder.recorded_bytes(), "reading reached the wire"
    assert list(cloud_storage_module.stored_data) == [], "cloud stored a reading"
