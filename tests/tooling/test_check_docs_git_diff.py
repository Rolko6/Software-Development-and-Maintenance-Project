"""Regression tests for check_git_diff in .github/scripts/check_docs.py.

`git diff --check` exits 2 when it finds whitespace errors and writes them to
stdout. The checker originally accepted only exit codes 0 and 1, so a real
finding was reported as "could not run (unknown error)" and then discarded by
an early return -- the docs-check job stayed green on exactly the input it
exists to catch. This was found by CI on its first real run, not by a test.

The module lives under .github/scripts/, which is not an importable package,
so it is loaded by path.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / ".github" / "scripts" / "check_docs.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_check_docs", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_docs = _load_checker()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", ".")
    (tmp_path / "a.txt").write_text("clean line\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_reports_the_actual_whitespace_finding(repo: Path):
    (repo / "a.txt").write_text("clean line\ntrailing space here \n")

    violations: list = []
    check_docs.check_git_diff(repo, None, violations)

    assert violations, "a trailing-space change must produce a violation"

    messages = " ".join(v.message for v in violations)

    assert "trailing whitespace" in messages
    assert "could not run" not in messages


def test_clean_tree_produces_no_violations(repo: Path):
    violations: list = []
    check_docs.check_git_diff(repo, None, violations)

    assert violations == []


def test_a_genuine_git_failure_is_still_reported(repo: Path):
    violations: list = []
    check_docs.check_git_diff(repo, "no-such-ref-xyz", violations)

    assert violations, "an unresolvable ref must still be reported"
    assert "could not run" in " ".join(v.message for v in violations)
