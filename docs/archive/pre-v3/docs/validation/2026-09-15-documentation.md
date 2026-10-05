> Historical pre-v3 documentation, recovered from [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/validation/2026-09-15-documentation.md). Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../../../../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Documentation validation — 2026-09-15

Scope: README, shared agent instructions, and the documentation/evidence structure created for [P002 and P003](../ai/prompts/2026-09-15-yyy-tom.md).

## Evidence already observed

| Check | Result | Scope |
| --- | --- | --- |
| Source inspection | Completed | Endpoints, ports, payloads, counters, storage, and device loop compared with README claims. |
| `docker compose config --quiet` | Passed during P002 | Compose configuration parses; does not prove image builds or service readiness. |
| `git diff --check` | Passed during P002 | README diff had no whitespace errors. |
| Instruction-format documentation | Consulted during P003 | Official Codex discovery guidance and Claude Code import documentation support the chosen file layout. |

## P003 final file checks

The following checks passed during P003:

| Check | Observed result |
| --- | --- |
| Local Markdown file and section links | 40 links/anchors resolved across all 9 Markdown files, including untracked files. |
| Claude import | Root `CLAUDE.md` contains exactly one standalone `@AGENTS.md` import; its target exists. |
| Markdown fences and whitespace | Balanced code fences and no trailing whitespace across those 9 files. |
| `git diff --check` | Passed. |
| Working-tree scope | Modified README; added AGENTS.md, CLAUDE.md, and docs. Application source and Compose configuration unchanged by P003. |

Link, fence, and import checks were performed with a temporary inline Python script; no application test harness was added.

## Not run

- Container builds, startup, endpoint requests, outage/recovery checks, and latency measurements.
- Automated application tests; the inspected baseline contains no test suite.
- Fresh Codex or Claude Code sessions to verify instruction discovery and adherence.

## Reproducing the documentation check

From the repository root, inspect the Markdown links to local files and section headings, confirm `CLAUDE.md` imports the existing root `AGENTS.md`, and run `git diff --check`. Include newly created files in link/whitespace inspection because untracked files do not appear in the normal Git diff.

The runtime baseline remains a separate task using the manual checks in the [README](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/README.md).
