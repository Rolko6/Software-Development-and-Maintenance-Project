"""Executable contract for the gateway's ML-KEM integration.

A conformant ML-KEM library in the dependency list protects nothing. What
matters is whether the gateway-to-cloud link actually uses it, and whether an
attacker who records today's traffic and decrypts it in fifteen years gets
anything. That is the threat ML-KEM exists to address, so these tests are
written from the recorder's point of view: capture the bytes the gateway
sends and look for the reading in them.

The integration does not exist yet (project plan work package 3), so this
module skips. The skip is conditional on the module under test being absent,
not on a failure being hidden: nothing here is marked xfail, and the crypto
layer never skips.

These tests assume one further design point, and it is a proposal like the
rest: that every forwarded reading carries the ML-KEM ciphertext, so each
message is independently decryptable and a lost message costs nothing. A design
that establishes a session once and then symmetric-encrypts readings under the
derived key is equally reasonable and would need
`test_recorded_traffic_carries_ml_kem_material` rewritten to look for a session
identifier instead. Decide that in work package 3, then change the test.

Interface assumed below, proposed by these tests rather than decided:

    gateway/app/kem.py
        PARAMETER_SET: str
        generate_keypair() -> tuple[bytes, bytes]                # (ek, dk)
        encapsulate(peer_ek: bytes) -> tuple[bytes, bytes]       # (secret, ct)
        decapsulate(dk: bytes, ct: bytes) -> bytes               # secret
        derive_session_key(*, ml_kem_secret: bytes,
                           classical_secret: bytes | None = None,
                           context: bytes = b"") -> bytes

    gateway/app/metrics.py
        KEM_HANDSHAKE_FAILURES_TOTAL: prometheus_client.Counter

If work package 3 settles on different names, change this file with the
implementation and say so in the decision record. Do not delete a test to make
the suite pass.
"""

import json
import sys

import pytest

from support import GATEWAY_ROOT


# The gateway imports itself as the top-level package `app`, exactly as it does
# inside its container. The cloud service does the same, so this path is added
# here rather than in tests/conftest.py: only this module needs it, and a
# session-wide insert would shadow the other services' packages.
if GATEWAY_ROOT not in sys.path:
    sys.path.insert(0, GATEWAY_ROOT)

kem = pytest.importorskip(
    "app.kem",
    reason=(
        "gateway/app/kem.py does not exist yet: ML-KEM integration is project "
        "plan work package 3. These tests define what it has to satisfy."
    ),
)

from app import cloud_client  # noqa: E402


READING = {"device_id": "contract-sensor-001", "temperature": 22.5}

# FIPS 203 Table 2, for the parameter sets this project would accept.
ARTIFACT_SIZES = {
    "ML-KEM-768": {"ek": 1184, "dk": 2400, "ct": 1088},
    "ML-KEM-1024": {"ek": 1568, "dk": 3168, "ct": 1568},
}


class CapturedRequest:
    """Whatever the gateway put on the wire, as an eavesdropper would see it."""

    def __init__(self):
        self.body = b""

    def record(self, url, **kwargs):
        if kwargs.get("json") is not None:
            self.body = json.dumps(kwargs["json"]).encode()
        elif kwargs.get("data") is not None:
            payload = kwargs["data"]
            self.body = payload if isinstance(payload, bytes) else str(payload).encode()

        class Response:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"status": "stored"}

        return Response()


@pytest.fixture
def wire(monkeypatch):
    captured = CapturedRequest()
    monkeypatch.setattr(cloud_client.requests, "post", captured.record)
    return captured


def test_parameter_set_is_the_one_the_group_agreed_on():
    """A silent drop to ML-KEM-512 would still pass every round-trip test."""
    assert kem.PARAMETER_SET in {"ML-KEM-768", "ML-KEM-1024"}


def test_key_material_has_the_sizes_of_the_declared_parameter_set():
    """Cheap confirmation that the declared name matches the real algorithm."""
    ek, dk = kem.generate_keypair()

    expected = ARTIFACT_SIZES[kem.PARAMETER_SET]

    assert len(ek) == expected["ek"]
    assert len(dk) == expected["dk"]

    secret, ciphertext = kem.encapsulate(ek)

    assert len(ciphertext) == expected["ct"]
    assert len(secret) == 32
    assert kem.decapsulate(dk, ciphertext) == secret


def test_recorded_traffic_does_not_reveal_the_reading(wire):
    """The harvest-now-decrypt-later case, stated as a test.

    An attacker who stores this body today must not be able to read the
    temperature from it at all, let alone after building a quantum computer.
    Searching for the literal values catches the common integration mistake of
    attaching an encrypted blob beside the untouched plaintext.
    """
    cloud_client.send_to_cloud(dict(READING))

    assert wire.body, "no request was captured"

    assert b"22.5" not in wire.body, "temperature appears in cleartext"
    assert b"contract-sensor-001" not in wire.body, "device id appears in cleartext"
    assert b"temperature" not in wire.body, "field names leak the payload shape"


def test_recorded_traffic_carries_ml_kem_material(wire):
    """Absence of plaintext is not presence of ML-KEM.

    A body could be empty, base64-wrapped, or protected by something classical
    and still pass the previous test. This one looks for key-encapsulation
    material of the right size.
    """
    cloud_client.send_to_cloud(dict(READING))

    envelope = json.loads(wire.body)

    assert envelope.get("kem") == kem.PARAMETER_SET, (
        "the envelope should name the KEM it used, so a captured packet can be "
        "attributed without access to the source"
    )

    ciphertext = bytes.fromhex(envelope["kem_ciphertext"])

    assert len(ciphertext) == ARTIFACT_SIZES[kem.PARAMETER_SET]["ct"]


def test_the_ml_kem_secret_changes_the_session_key():
    """The kill switch: prove ML-KEM is load-bearing, not decorative.

    In a hybrid construction it is easy to derive the session key from the
    classical secret and pass the ML-KEM secret to a KDF that ignores it. The
    result round-trips, interoperates, and offers no post-quantum protection at
    all. Changing only the ML-KEM input must change the output.
    """
    classical = b"\x01" * 32
    context = b"gateway-cloud-v1"

    first = kem.derive_session_key(
        ml_kem_secret=b"\xaa" * 32, classical_secret=classical, context=context
    )
    second = kem.derive_session_key(
        ml_kem_secret=b"\xbb" * 32, classical_secret=classical, context=context
    )

    assert first != second, "session key ignores the ML-KEM secret"
    assert len(first) >= 32


def test_a_classical_secret_alone_is_not_accepted():
    """Refuse to derive a session key with no post-quantum input.

    A hybrid design that tolerates a missing ML-KEM secret silently degrades to
    classical security on the day encapsulation starts failing.
    """
    with pytest.raises((ValueError, TypeError)):
        kem.derive_session_key(
            ml_kem_secret=b"", classical_secret=b"\x01" * 32, context=b"x"
        )


def test_failed_key_establishment_fails_closed(wire, monkeypatch):
    """When ML-KEM fails, send nothing rather than falling back to plaintext.

    Work package 5 also asks for cryptographic failures to be observable, so
    the failure has to reach a counter and not just a log line.
    """
    from app import metrics

    def refuse(_peer_ek):
        raise ValueError("simulated key establishment failure")

    monkeypatch.setattr(kem, "encapsulate", refuse)

    before = metrics.KEM_HANDSHAKE_FAILURES_TOTAL._value.get()

    with pytest.raises(Exception):
        cloud_client.send_to_cloud(dict(READING))

    assert b"22.5" not in wire.body, "plaintext sent after key establishment failed"

    after = metrics.KEM_HANDSHAKE_FAILURES_TOTAL._value.get()

    assert after == before + 1, "key establishment failure was not counted"
