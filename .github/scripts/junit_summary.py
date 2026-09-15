#!/usr/bin/env python3
"""Render a JUnit XML report as a small Markdown summary.

Used by .github/workflows/ci.yml to publish a pytest summary to
$GITHUB_STEP_SUMMARY (job summaries: docs.github.com/en/actions/reference/
workflows-and-actions/workflow-commands, "Adding a job summary"), but has
no dependency on GitHub Actions and can be run anywhere:

    python .github/scripts/junit_summary.py --title "Unit tests: cloud" \
        cloud/unit-report.xml

Only the standard library is used deliberately: this script must run with
whatever interpreter pytest just ran under, without an extra install step.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _collect_testsuites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    return list(root.iter("testsuite"))


def render_summary(report_path: Path, title: str) -> str:
    if not report_path.is_file():
        return (
            f"### {title}\n\n"
            f"**No JUnit report found at `{report_path}`.** "
            "The test run likely failed before pytest could write a report; "
            "check the preceding step's log.\n"
        )

    try:
        tree = ET.parse(report_path)
    except ET.ParseError as error:
        return f"### {title}\n\n**Could not parse `{report_path}`:** {error}\n"

    suites = _collect_testsuites(tree.getroot())
    if not suites:
        return f"### {title}\n\nNo `<testsuite>` element found in `{report_path}`.\n"

    tests = failures = errors = skipped = 0
    time = 0.0
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        time += float(suite.get("time", 0.0))

    passed = tests - failures - errors - skipped
    status = "PASSED" if failures == 0 and errors == 0 else "FAILED"

    lines = [
        f"### {title}: {status}",
        "",
        "| Tests | Passed | Failed | Errors | Skipped | Time (s) |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {tests} | {passed} | {failures} | {errors} | {skipped} | {time:.2f} |",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to a JUnit XML report")
    parser.add_argument(
        "--title", default="Test results", help="Heading to use for this summary block"
    )
    args = parser.parse_args(argv)

    print(render_summary(args.report, args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
