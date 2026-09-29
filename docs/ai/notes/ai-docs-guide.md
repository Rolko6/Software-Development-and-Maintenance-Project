# Guide: AI records, version files and release notes

Stanley's working rules for documenting AI-assisted work, agreed with Claude Code.

**Opt-in only.** This file applies only when the user explicitly asks, in that session, to follow it. Otherwise it is reference material and the normal repository rules apply. When it is invoked, it replaces the prompt-record rules in [AGENTS.md](../../../AGENTS.md), [CLAUDE.md](../../../CLAUDE.md) and the [AI evidence guide](../README.md) (the dated `YYYY-MM-DD-<person>.md` files); everything else in those files still applies.

## Why

The course brief asks for the prompts used for *significant* tasks, a *representative selection* of outputs, and for each generated artifact what was accepted, modified or rejected, why, how problems were found, and what risk remains. A reader should be able to check that quickly. A log of every prompt hides the important decisions among routine ones.

## Where things go

| Content | Location |
| --- | --- |
| Significant prompts of one release | `docs/ai/prompts/vX.Y.Z.md` (one file per version) |
| Working lists, reviews, evaluations, this guide | `docs/ai/notes/` |
| Release description to paste into a GitHub Release | `local/vX.Y.Z-release.md` (untracked) |

Do not create dated per-person prompt files. Existing ones stay as they are.

## What to record

- Record a prompt only if it produced or changed something that ships (code, tests, CI, configuration, documentation others rely on) or changed a design decision.
- Do not record analysis, questions, brainstorming, or routine typo and formatting fixes. When analysis leads to a change, record the prompt behind that change, with the change.
- If a follow-up prompt corrects an earlier output (for example after a CI failure), record it as its own entry and link the two.

## Version files are written in version order

Each `vX.Y.Z.md` reads as if it was written when that version was finished, and the files read in version order tell the story of the project.

- **Order by version, not by date.** Do not write dates (no "Period", "Recorded" or "observed on …"). Dates on these files are misleading, because a file may be written after a later version already exists.
- **No hindsight.** A file only knows what was known at its version. It may refer back to earlier versions, never forward.
  - Allowed: plans and decisions made at the time ("ML-KEM is planned for v2.0.0", "deferred to a later version").
  - Not allowed: outcomes from later versions ("this was fixed in v2.0.0", "the folder we ended up using").
- **Problems found in an earlier version** are recorded in the file of the version where they were found or fixed ("v2.0.0 fixed these problems in the v1.0.0 code"), not added to the earlier file.
- **A version under work** may be updated until it is released. After release, its file is closed. Later findings go in the next version's file.
- Do not edit a teammate's version file without asking them.

## Version file structure

```markdown
# Prompt record — vX.Y.Z

**Contributors:** name(s)\
**Tool:** assistant and model(s)\
**Purpose:** one or two sentences on what this version set out to do.

## Summary

| # | Artifact | Decision | Problems found |
| --- | --- | --- | --- |

## 1. Entry title
(entry format below)

## Known limitations
What this version still does not do, as known at this version.
```

## Entry format

1. **Person:** who gave the prompt.
2. **Prompt:** verbatim, or clearly marked as an excerpt or summary.
3. **Background** (optional): why the prompt was needed.
4. **What AI did:** a short description of the output.
5. **Decision:** accepted, modified or rejected, and the reason.
6. **How it was checked:** the check actually run and its result.
7. **What that check did not prove:** the limits of the check.
8. **Remaining risk:** anything still open, with a link to [pending-tasks.md](pending-tasks.md) where relevant.

## Release description (GitHub Release text)

Kept in `local/vX.Y.Z-release.md` and pasted into the GitHub Release. Same no-hindsight rule. Structure:

1. One-paragraph summary.
2. What changed (grouped: features, fixes, CI, docs).
3. Upgrade notes (breaking changes, new configuration, or "none").
4. Verification (which checks passed).
5. Known issues (what is open, planned for the next version without promising a version number unless it is decided).
6. Links: the version file and the pull request(s).

## Honesty rules

- Never write "accepted as written" without saying how it was checked.
- Do not claim a human review, a decision or a check that did not happen. If something is unknown, say so or ask.
- A failed first attempt that was then fixed is evidence of review; record it, do not hide it.
