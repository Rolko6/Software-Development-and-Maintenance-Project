"""Assurance checks on the ML-KEM implementation itself, not the algorithm.

Conformance tests show that the code computes ML-KEM. They say nothing about
whether this particular implementation is safe to deploy. Those are different
questions, and the second one is where a prototype usually goes wrong: a
correct algorithm in a library that leaks timing gives an attacker a practical
break with no quantum computer involved.

These tests pin the facts a reviewer would otherwise have to rediscover, and
fail when the ML-KEM dependency changes so that the assurance review is redone
instead of inherited.
"""

import os
import re

import pytest

from support import REPO_ROOT


RISK_RECORD = os.path.join(REPO_ROOT, "docs", "testing", "ml-kem-verification.md")

# Implementations the group has actually looked at, with the limitation that
# review found. Adding an entry is a deliberate act: record the reasoning in
# the risk record and in the project plan before changing this table.
REVIEWED_IMPLEMENTATIONS = {
    "kyber-py": {
        "version": "1.2.0",
        "constant_time": False,
        "suitable_for_deployment": False,
        "reason": (
            "Pure-Python educational implementation. Its own documentation "
            "states it must not be used for cryptographic applications and is "
            "not written to resist side-channel attack."
        ),
    },
}


def installed_version(distribution):
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def test_the_ml_kem_dependency_is_one_that_was_reviewed():
    """Fail when the library or its version changes under the suite.

    The known-answer tests drive `_keygen_internal` and `_encaps_internal`,
    which are private. Pinning the version is what keeps that dependency
    honest, and a swap to a different library invalidates the review recorded
    below rather than inheriting it.
    """
    for distribution, review in REVIEWED_IMPLEMENTATIONS.items():
        found = installed_version(distribution)

        assert found is not None, (
            f"{distribution} is not installed; "
            "install tests/../requirements-dev.txt"
        )

        assert found == review["version"], (
            f"{distribution} {found} is installed but only {review['version']} "
            "has been reviewed. Redo the assurance review and update "
            "REVIEWED_IMPLEMENTATIONS and the risk record."
        )


def test_the_library_still_declares_itself_unsuitable_for_deployment():
    """Detect the day this stops being true, rather than assuming it never will.

    The check asserts the state the review was based on. If upstream changes
    its position, this test fails and the group re-reads the disclaimer instead
    of carrying an outdated conclusion into the report.
    """
    from importlib.metadata import metadata

    description = metadata("kyber-py").get_payload() or ""

    assert re.search(
        r"under no circumstances should this be used for cryptographic",
        description,
        re.IGNORECASE,
    ), (
        "kyber-py no longer carries its 'not for cryptographic applications' "
        "caution. Re-read the upstream disclaimer and update the risk record."
    )

    assert re.search(r"not constant time", description, re.IGNORECASE), (
        "kyber-py no longer documents the constant-time gap; re-review it."
    )


def test_side_channel_risk_is_recorded_rather_than_tested():
    """No test in this repository establishes side-channel resistance.

    Timing behaviour is not measurable reliably on shared CI hardware, and a
    pure-Python implementation would fail such a measurement anyway. The
    project's own rules require residual risks to be written down, so the
    record is what this test checks for.
    """
    assert os.path.exists(RISK_RECORD), (
        f"missing residual-risk record at {os.path.relpath(RISK_RECORD, REPO_ROOT)}"
    )

    with open(RISK_RECORD) as handle:
        # Collapse whitespace so that a wrapped line does not hide a phrase.
        text = re.sub(r"\s+", " ", handle.read().lower())

    for topic in ("constant time", "side channel", "residual risk"):
        assert topic in text, f"risk record does not discuss {topic!r}"


@pytest.mark.parametrize("distribution", sorted(REVIEWED_IMPLEMENTATIONS))
def test_no_reviewed_implementation_is_marked_deployment_ready(distribution):
    """Guard against a table edit that quietly promotes a prototype library.

    Marking an implementation deployment-ready requires evidence this suite
    cannot produce — a constant-time implementation and, ideally, a CAVP
    validation certificate. Recording that decision belongs in the project
    plan, where a reviewer will see it.
    """
    review = REVIEWED_IMPLEMENTATIONS[distribution]

    if review["suitable_for_deployment"]:
        pytest.fail(
            f"{distribution} is marked deployment-ready. Link the CAVP "
            "certificate or constant-time evidence in the risk record and "
            "delete this guard deliberately."
        )

    assert review["reason"], "record why the implementation is not deployable"
