#!/usr/bin/env python3
"""Reproduce the repository's documentation validation check.

This is a runnable implementation of the check described in
docs/validation/2026-09-15-documentation.md ("Reproducing the documentation
check"): validate relative Markdown links and section anchors across all
tracked Markdown files (including untracked ones, since untracked files do
not show up in a normal `git diff`), confirm the root CLAUDE.md contains
exactly one standalone `@AGENTS.md` import whose target exists, check
balanced code fences and no trailing whitespace, and run `git diff --check`.

Run it from anywhere inside the repository:

    python .github/scripts/check_docs.py
    python .github/scripts/check_docs.py --diff-ref origin/main

Exits non-zero and prints every violation found; exits 0 with a short
summary when the repository is clean. Uses only the standard library plus
`git`, so it needs no dependency installation to run locally or in CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
IMPORT_RE = re.compile(r"^@AGENTS\.md\s*$")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class Violation:
    def __init__(self, path: str, line: int | None, message: str):
        self.path = path
        self.line = line
        self.message = message

    def __str__(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: {self.message}"


def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def find_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def list_markdown_files(repo_root: Path) -> list[Path]:
    patterns = ["*.md", "*.markdown"]
    names: set[str] = set()

    tracked = run_git(repo_root, "ls-files", "--", *patterns)
    names.update(line for line in tracked.stdout.splitlines() if line)

    untracked = run_git(
        repo_root, "ls-files", "--others", "--exclude-standard", "--", *patterns
    )
    names.update(line for line in untracked.stdout.splitlines() if line)

    return sorted(repo_root / name for name in names)


def slugify(heading: str, seen_counts: dict[str, int]) -> str:
    # GitHub's heading-anchor algorithm: lowercase, drop characters other
    # than word characters/hyphens/spaces, spaces (and underscores are kept
    # but spaces) become hyphens, then de-duplicate with -1, -2, ...
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    count = seen_counts.get(slug, 0)
    seen_counts[slug] = count + 1
    if count:
        slug = f"{slug}-{count}"
    return slug


def strip_fences(lines: list[str]) -> tuple[list[bool], int]:
    """Return a per-line "inside a fenced code block" mask, and the number
    of fence-marker lines seen (used for the balance check).
    """

    in_fence = False
    mask = []
    fence_count = 0
    for line in lines:
        is_fence_marker = bool(FENCE_RE.match(line))
        if is_fence_marker:
            fence_count += 1
        mask.append(in_fence)
        if is_fence_marker:
            in_fence = not in_fence
    return mask, fence_count


def parse_headings(lines: list[str], fence_mask: list[bool]) -> dict[str, int]:
    seen_counts: dict[str, int] = {}
    slugs: dict[str, int] = {}
    for i, line in enumerate(lines):
        if fence_mask[i]:
            continue
        match = HEADING_RE.match(line)
        if match:
            slug = slugify(match.group(2), seen_counts)
            slugs.setdefault(slug, i + 1)
    return slugs


def check_file(
    path: Path,
    repo_root: Path,
    headings_by_file: dict[Path, dict[str, int]],
    violations: list[Violation],
) -> int:
    rel = str(path.relative_to(repo_root))
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # Drop the trailing empty element from the final newline so line numbers
    # line up with a 1-indexed editor view.
    if lines and lines[-1] == "":
        lines = lines[:-1]

    fence_mask, fence_count = strip_fences(lines)
    if fence_count % 2 != 0:
        violations.append(
            Violation(rel, None, f"unbalanced code fences ({fence_count} fence markers)")
        )

    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped != stripped.rstrip(" \t") :
            violations.append(Violation(rel, i + 1, "trailing whitespace"))

    links_checked = 0
    for i, line in enumerate(lines):
        if fence_mask[i]:
            continue
        for match in LINK_RE.finditer(line):
            target = match.group(1).strip()
            # Drop an optional " title" suffix: [text](path "title")
            if " " in target and not target.startswith("<"):
                first, _, rest = target.partition(" ")
                if rest.strip().startswith(('"', "'")):
                    target = first
            target = target.strip("<>")

            if not target or SCHEME_RE.match(target):
                continue  # external link (http(s):, mailto:, tel:, ...)

            links_checked += 1
            path_part, _, anchor_part = target.partition("#")
            path_part = urllib.parse.unquote(path_part)

            if path_part:
                target_path = (path.parent / path_part).resolve()
                if not target_path.exists():
                    violations.append(
                        Violation(rel, i + 1, f"broken link target: {target}")
                    )
                    continue
            else:
                target_path = path  # "#anchor" within the same file

            if anchor_part:
                target_headings = headings_by_file.get(target_path)
                if target_headings is None and target_path.suffix.lower() in (
                    ".md",
                    ".markdown",
                ):
                    # File exists but wasn't in our Markdown file list (e.g.
                    # it is git-ignored); read it directly for its headings.
                    try:
                        other_lines = target_path.read_text(encoding="utf-8").split(
                            "\n"
                        )
                        other_mask, _ = strip_fences(other_lines)
                        target_headings = parse_headings(other_lines, other_mask)
                    except OSError:
                        target_headings = {}
                if target_headings is not None and anchor_part not in target_headings:
                    violations.append(
                        Violation(
                            rel,
                            i + 1,
                            f"broken section anchor '#{anchor_part}' in {target}",
                        )
                    )

    return links_checked


def check_claude_import(repo_root: Path, violations: list[Violation]) -> None:
    claude_md = repo_root / "CLAUDE.md"
    if not claude_md.is_file():
        violations.append(Violation("CLAUDE.md", None, "file is missing"))
        return

    lines = claude_md.read_text(encoding="utf-8").split("\n")
    matches = [i + 1 for i, line in enumerate(lines) if IMPORT_RE.match(line)]

    if len(matches) != 1:
        violations.append(
            Violation(
                "CLAUDE.md",
                None,
                f"expected exactly one standalone '@AGENTS.md' import line, found {len(matches)}",
            )
        )
        return

    if not (repo_root / "AGENTS.md").is_file():
        violations.append(
            Violation("CLAUDE.md", matches[0], "import target AGENTS.md does not exist")
        )


def check_git_diff(
    repo_root: Path, diff_ref: str | None, violations: list[Violation]
) -> None:
    args = ["diff", "--check"]
    if diff_ref:
        args.append(diff_ref)
    result = run_git(repo_root, *args)
    # `git diff --check` exits 2 when it FINDS whitespace errors, writing them
    # to stdout; 0 when clean. Treating 2 as a failure-to-run meant every real
    # finding was reported as "could not run (unknown error)" and then dropped
    # by the early return below -- the check silently passed on exactly the
    # input it exists to catch. Anything outside 0/1/2 is a genuine failure.
    if result.returncode not in (0, 1, 2):
        violations.append(
            Violation(
                "git diff --check",
                None,
                f"could not run ({result.stderr.strip() or 'unknown error'})",
            )
        )
        return
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            violations.append(Violation("git diff --check", None, line))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diff-ref",
        default=None,
        help=(
            "Optional ref/SHA to diff against for the git diff --check step "
            "(e.g. the PR base branch). Defaults to a bare 'git diff --check' "
            "against the working tree, matching local reproduction."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = find_repo_root()
    md_files = list_markdown_files(repo_root)

    violations: list[Violation] = []
    headings_by_file: dict[Path, dict[str, int]] = {}

    # Headings must be known for every file before link-checking anchors
    # that point *into* another Markdown file.
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        mask, _ = strip_fences(lines)
        headings_by_file[path] = parse_headings(lines, mask)

    total_links = 0
    for path in md_files:
        total_links += check_file(path, repo_root, headings_by_file, violations)

    check_claude_import(repo_root, violations)
    check_git_diff(repo_root, args.diff_ref, violations)

    print(f"Checked {len(md_files)} Markdown file(s), {total_links} local link(s).")
    if violations:
        print(f"{len(violations)} violation(s) found:\n")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("No violations found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
