"""Rebuild `ml_kem_acvp.json` from the upstream NIST ACVP vector files.

The committed subset is small enough to review; the upstream files are several
megabytes. Run this script to regenerate or refresh the subset:

    curl -sSLO "https://raw.githubusercontent.com/usnistgov/ACVP-Server/<commit>/gen-val/json-files/ML-KEM-keyGen-FIPS203/internalProjection.json"
    mv internalProjection.json keygen.json
    curl -sSLO "https://raw.githubusercontent.com/usnistgov/ACVP-Server/<commit>/gen-val/json-files/ML-KEM-encapDecap-FIPS203/internalProjection.json"
    mv internalProjection.json encapdecap.json
    python tests/vectors/extract_acvp_subset.py <dir-with-those-two-files> <commit>

Every value in the output is copied verbatim from the upstream files. Nothing is
computed locally: a known-answer test that generates its own answers proves
nothing.
"""

import json
import os
import sys

SETS = ("ML-KEM-512", "ML-KEM-768", "ML-KEM-1024")

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_kem_acvp.json")


def groups(document, **match):
    return [
        group
        for group in document["testGroups"]
        if all(group.get(key) == value for key, value in match.items())
    ]


def pick(tests, count, key=None, value=None):
    selected = [t for t in tests if key is None or t.get(key) == value]
    return selected[:count]


def build(source_dir, commit, retrieved):
    keygen = json.load(open(os.path.join(source_dir, "keygen.json")))
    encapdecap = json.load(open(os.path.join(source_dir, "encapdecap.json")))

    out = {
        "_provenance": {
            "source": "NIST ACVP-Server public test vectors (gen-val/json-files)",
            "repository": "https://github.com/usnistgov/ACVP-Server",
            "commit": commit,
            "files": [
                "gen-val/json-files/ML-KEM-keyGen-FIPS203/internalProjection.json",
                "gen-val/json-files/ML-KEM-encapDecap-FIPS203/internalProjection.json",
            ],
            "retrieved": retrieved,
            "standard": "NIST FIPS 203 (ML-KEM)",
            "note": (
                "Subset extracted verbatim; no value was generated locally. "
                "Regenerate with tests/vectors/extract_acvp_subset.py."
            ),
            "hex_encoding": (
                "All key material is uppercase hex, exactly as published upstream; compare case-insensitively."
            ),
        },
        "keyGen": [],
        "encap": [],
        "decap": [],
        "encapsulationKeyCheck": [],
        "decapsulationKeyCheck": [],
    }

    for parameter_set in SETS:
        group = groups(keygen, testType="AFT", parameterSet=parameter_set)[0]
        for test in group["tests"][:2]:
            out["keyGen"].append(
                {
                    "parameterSet": parameter_set,
                    "tcId": test["tcId"],
                    "d": test["d"],
                    "z": test["z"],
                    "ek": test["ek"],
                    "dk": test["dk"],
                }
            )

        group = groups(
            encapdecap,
            testType="AFT",
            parameterSet=parameter_set,
            function="encapsulation",
        )[0]
        for test in group["tests"][:2]:
            out["encap"].append(
                {
                    "parameterSet": parameter_set,
                    "tcId": test["tcId"],
                    "ek": test["ek"],
                    "m": test["m"],
                    "k": test["k"],
                    "c": test["c"],
                }
            )

        group = groups(
            encapdecap,
            testType="VAL",
            parameterSet=parameter_set,
            function="decapsulation",
        )[0]
        for reason, count in (("valid decapsulation", 1), ("modified ciphertext", 2)):
            for test in pick(group["tests"], count, "reason", reason):
                out["decap"].append(
                    {
                        "parameterSet": parameter_set,
                        "tcId": test["tcId"],
                        "reason": test["reason"],
                        "dk": test["dk"],
                        "c": test["c"],
                        "k": test["k"],
                    }
                )

        group = groups(
            encapdecap,
            testType="VAL",
            parameterSet=parameter_set,
            function="encapsulationKeyCheck",
        )[0]
        for passed in (True, False):
            for test in pick(group["tests"], 1, "testPassed", passed):
                out["encapsulationKeyCheck"].append(
                    {
                        "parameterSet": parameter_set,
                        "tcId": test["tcId"],
                        "reason": test["reason"],
                        "testPassed": test["testPassed"],
                        "ek": test["ek"],
                    }
                )

        group = groups(
            encapdecap,
            testType="VAL",
            parameterSet=parameter_set,
            function="decapsulationKeyCheck",
        )[0]
        for passed in (True, False):
            for test in pick(group["tests"], 1, "testPassed", passed):
                out["decapsulationKeyCheck"].append(
                    {
                        "parameterSet": parameter_set,
                        "tcId": test["tcId"],
                        "reason": test["reason"],
                        "testPassed": test["testPassed"],
                        "dk": test["dk"],
                    }
                )

    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: extract_acvp_subset.py <source-dir> <commit> [retrieved-date]"
        )

    document = build(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "unrecorded",
    )

    with open(OUTPUT, "w") as handle:
        json.dump(document, handle, indent=1, sort_keys=False)
        handle.write("\n")

    print(f"wrote {OUTPUT}")
    for section, cases in document.items():
        if section != "_provenance":
            print(f"  {section}: {len(cases)} cases")
