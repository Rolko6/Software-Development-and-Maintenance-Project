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


def _is_xfail(element: ET.Element) -> bool:
    # pytest's JUnit writer records an expected failure (xfail) as a
    # <skipped type="pytest.xfail"> element. It is a known, tracked deviation
    # rather than a test that did not run, so it is counted apart from skips.
    return element.tag == "skipped" and element.get("type") == "pytest.xfail"


def _count_xfailed(suites: list[ET.Element]) -> int:
    return sum(
        1
        for suite in suites
        for case in suite.iter("testcase")
        if (element := case.find("skipped")) is not None and _is_xfail(element)
    )


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

    xfailed = _count_xfailed(suites)
    skipped -= xfailed
    passed = tests - failures - errors - skipped - xfailed
    if failures or errors:
        status = "FAILED"
    elif passed <= 0:
        # Nothing actually ran (all skipped, or nothing collected). That is
        # not a pass, even though pytest exits 0 for it.
        status = "NO TESTS PASSED"
    else:
        status = "PASSED"

    lines = [
        f"### {title}: {status}",
        "",
        "| Tests | Passed | Failed | Errors | Skipped | Expected failures | Time (s) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        f"| {tests} | {passed} | {failures} | {errors} | {skipped} | {xfailed} | {time:.2f} |",
        "",
    ]
    lines.extend(_detail_lines(suites))
    return "\n".join(lines)


def _detail_lines(suites: list[ET.Element]) -> list[str]:
    """List every failed, errored and skipped test with its message.

    A skip is a pass as far as the job's exit code is concerned, so naming
    each one (and its reason) here is what keeps a skip from going unnoticed.
    """
    rows: list[str] = []
    for suite in suites:
        for case in suite.iter("testcase"):
            for outcome in ("failure", "error", "skipped"):
                element = case.find(outcome)
                if element is None:
                    continue
                name = f"{case.get('classname', '')}::{case.get('name', '')}"
                label = "xfail" if _is_xfail(element) else outcome
                # pytest puts a skip's reason in the element text when the
                # message attribute is only "collection skipped".
                message = element.get("message") or ""
                if outcome == "skipped" and element.text and not _is_xfail(element):
                    message = element.text
                    # A module-level skip's text is a tuple repr,
                    # "('/abs/path.py', 57, 'Skipped: reason')"; keep the reason.
                    marker = "Skipped: "
                    if marker in message:
                        message = message.split(marker, 1)[1].rstrip("')\n ")
                message = message.replace("|", "\\|")
                message = " ".join(message.split())[:300]
                rows.append(f"| {label} | `{name}` | {message} |")
    if not rows:
        return []
    return ["| Outcome | Test | Message |", "| --- | --- | --- |", *rows, ""]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to a JUnit XML report")
    parser.add_argument(
        "--title", default="Test results", help="Heading to use for this summary block"
    )
    parser.add_argument(
        "--max-skipped",
        type=int,
        default=None,
        help=(
            "Exit 1 if the report records more skipped tests than this "
            "(expected failures are counted by --max-xfailed instead). "
            "Without it the script only reports and always exits 0."
        ),
    )
    parser.add_argument(
        "--max-xfailed",
        type=int,
        default=None,
        help="Exit 1 if the report records more expected failures (xfail) than this.",
    )
    args = parser.parse_args(argv)

    print(render_summary(args.report, args.title))
    if args.max_skipped is None and args.max_xfailed is None:
        return 0
    counts = count_skipped_and_xfailed(args.report)
    if counts is None:
        print(f"**Skip budget not checked:** no readable report at `{args.report}`.")
        return 1
    status = 0
    for kind, count, budget in (
        ("skipped", counts[0], args.max_skipped),
        ("expected failures", counts[1], args.max_xfailed),
    ):
        if budget is not None and count > budget:
            print(
                f"**Budget exceeded:** {count} {kind}, at most {budget} allowed. "
                "A new skip or xfail needs a recorded reason and a matching "
                "change to the budget in ci.yml."
            )
            status = 1
    return status


def count_skipped_and_xfailed(report_path: Path) -> tuple[int, int] | None:
    """(skipped, xfailed) in a JUnit report, or None if it cannot be read."""
    try:
        root = ET.parse(report_path).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = _collect_testsuites(root)
    xfailed = _count_xfailed(suites)
    return sum(int(suite.get("skipped", 0)) for suite in suites) - xfailed, xfailed


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
