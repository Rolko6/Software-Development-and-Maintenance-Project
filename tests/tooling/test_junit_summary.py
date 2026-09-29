"""Tests for .github/scripts/junit_summary.py, which enforces the root-suite
skip and xfail budgets in CI.

A skip or xfail is a pass as far as pytest's exit code is concerned, so the
budget check in this script is the only thing that turns an unexpected one
into a red job. These tests pin that behaviour.

The module lives under .github/scripts/, which is not an importable package,
so it is loaded by path.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "junit_summary.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_junit_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


junit_summary = _load_script()

# Shaped like pytest's own --junitxml output: one pass, one real skip, one
# xfail (which pytest records as <skipped type="pytest.xfail">).
REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="2" tests="3" time="0.1">
<testcase classname="t" name="test_ok" time="0.01"/>
<testcase classname="t" name="test_skip" time="0.01"><skipped type="pytest.skip" message="waiting on a decision">t.py:1: waiting on a decision</skipped></testcase>
<testcase classname="t" name="test_known" time="0.01"><skipped type="pytest.xfail" message="known deviation"/></testcase>
</testsuite></testsuites>
"""

ALL_SKIPPED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="1" tests="1" time="0.1">
<testcase classname="" name="t" time="0.01"><skipped message="collection skipped">('/abs/t.py', 57, 'Skipped: module waits on a decision')</skipped></testcase>
</testsuite></testsuites>
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(text)
    return path


def test_skips_and_xfails_are_counted_separately(tmp_path):
    assert junit_summary.count_skipped_and_xfailed(_write(tmp_path, REPORT)) == (1, 1)


def test_summary_names_each_skip_and_xfail_with_its_reason(tmp_path):
    text = junit_summary.render_summary(_write(tmp_path, REPORT), "demo")
    assert "| skipped | `t::test_skip` |" in text
    assert "waiting on a decision" in text
    assert "| xfail | `t::test_known` | known deviation |" in text


def test_within_budget_exits_zero(tmp_path):
    report = str(_write(tmp_path, REPORT))
    assert junit_summary.main(["--max-skipped", "1", "--max-xfailed", "1", report]) == 0


def test_one_skip_over_budget_fails(tmp_path):
    report = str(_write(tmp_path, REPORT))
    assert junit_summary.main(["--max-skipped", "0", "--max-xfailed", "1", report]) == 1


def test_one_xfail_over_budget_fails(tmp_path):
    report = str(_write(tmp_path, REPORT))
    assert junit_summary.main(["--max-skipped", "1", "--max-xfailed", "0", report]) == 1


def test_missing_report_fails_a_budget_check(tmp_path):
    assert junit_summary.main(["--max-skipped", "0", str(tmp_path / "absent.xml")]) == 1


def test_without_a_budget_the_script_only_reports(tmp_path):
    assert junit_summary.main([str(_write(tmp_path, REPORT))]) == 0
    assert junit_summary.main([str(tmp_path / "absent.xml")]) == 0


def test_a_suite_where_nothing_passed_is_not_shown_as_passed(tmp_path):
    text = junit_summary.render_summary(_write(tmp_path, ALL_SKIPPED), "demo")
    assert "NO TESTS PASSED" in text
    assert ": PASSED" not in text


def test_a_module_level_skip_shows_its_reason_not_the_tuple(tmp_path):
    text = junit_summary.render_summary(_write(tmp_path, ALL_SKIPPED), "demo")
    assert "| module waits on a decision |" in text
    assert "/abs/t.py" not in text
