# Branch cleanup before the documentation merge — 2026-10-05

The user requested branch renaming and cleanup before merging [PR #16](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/16). Remote branches were reduced from 17 to 12. Five merged branches were removed; three branches with unique history were renamed. The documentation PR remains open and unmerged.

## Renamed branches with retained history

| Previous name | Current name | Unchanged tip |
| --- | --- | --- |
| `add-claude-github-actions-1790067039896` | [`legacy/claude-review-workflow`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/legacy/claude-review-workflow) | `acece0f` |
| `feat/secure-channel-hardening` | [`legacy/security-hardening-v2`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/legacy/security-hardening-v2) | `4f2b22d` |
| `roland/simplify-v1.0.0` | [`archive/v3-rewrite-source`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/v3-rewrite-source) | `4bc9010` |

The rewritten source branch had only a README difference from current v3 main, but its commit history was imported rather than merged normally. It was therefore retained under `archive/v3-rewrite-source`. The security and Claude-workflow branches also contain unique work and were kept under `legacy/`, not discarded or treated as part of current v3.

## Cleared merged branches

All five tips were verified as ancestors of fetched `origin/main`. Their former PRs were merged. A matching archive tag was pushed and verified before each obsolete branch ref was removed.

| Removed branch | Saved archive tag | Tip |
| --- | --- | --- |
| `docs/p008-outcome` | [`archive/2026-10-05/docs/p008-outcome`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/2026-10-05/docs/p008-outcome) | `172ef46` |
| `feat/ds18b20-device` | [`archive/2026-10-05/feat/ds18b20-device`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/2026-10-05/feat/ds18b20-device) | `e5ea58e` |
| `feat/project-plan-work-packages` | [`archive/2026-10-05/feat/project-plan-work-packages`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/2026-10-05/feat/project-plan-work-packages) | `18ed206` |
| `fix/check-docs-exit-code` | [`archive/2026-10-05/fix/check-docs-exit-code`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/2026-10-05/fix/check-docs-exit-code) | `a4e7385` |
| `test-ci-pr` | [`archive/2026-10-05/test-ci-pr`](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/tree/archive/2026-10-05/test-ci-pr) | `6b4b797` |

All three renamed tips also have `archive/2026-10-05/<old-branch-name>` tags. The tags preserve the complete reachable history, not just the contents of the tip. Original release tags were left unchanged.

## Kept branches and open pull requests

`main`, `develop`, `release/1.0.0`, `release/2.0.0` and `release/3.0.0` retained their exact tips. `develop` is still the older implementation's base because three open PRs target it; it was not reset to v3 main.

| Open PR | Head retained | Base retained |
| --- | --- | --- |
| [#16](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/16) | `codex/restore-project-documentation` | `main` |
| [#14](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/14) | `tom/issue4-remaining-metrics` | `develop` |
| [#13](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/13) | `tom/ci-deploy-evaluation` | `develop` |
| [#6](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/6) | `ci/root-suites` | `develop` |

No open PR branch was renamed or deleted, and no PR was closed, retargeted or merged. The original dirty checkout remains on `ci/root-suites`; its edits were preserved. Local remote-tracking refs were refreshed and pruned to reflect the renamed/removed remote branches. Local release and active PR branches were kept.

## Recovery and verification

A verified local bundle of all refs was created before cleanup at `.trash/2026-10-05__git-branch-cleanup.bundle` in the recovery worktree. It is ignored and remains on disk; no permanent file deletion or purge occurred. The eight archive tags are also available remotely, so recovery does not depend on this machine.

To restore a removed branch without switching the current checkout, create its old name from its matching archive tag, for example:

```bash
git branch docs/p008-outcome archive/2026-10-05/docs/p008-outcome
git push origin docs/p008-outcome
```

These are recovery instructions, not commands executed during cleanup.

- Executed: ancestry and branch-tip checks, all-ref bundle creation/verification, archive-tag push and remote verification, GitHub branch-rename API for the three non-PR branches, conditional atomic deletion of the five merged refs, and fetch/prune of stale tracking refs.
- Deletions used explicit expected-tip leases; a concurrent update would reject the atomic deletion rather than discard new commits. Rename API responses were checked for unchanged tips.
- Verified remotely: 12 remaining branches, all renamed tips unchanged, all kept branch tips unchanged, and all four open PR head/base pairs unchanged.
- Verified locally: original checkout HEAD and all pre-existing file hashes unchanged before the prompt log was extended. Human phase documents, application code and workflows remain unchanged relative to v3 main.
- Complete before/after evidence: [branch manifest](2026-10-05-branch-cleanup.json). Prompt and final documentation checks: [P017](../ai/prompts/2026-10-05-yyy-tom.md#p017-rename-historical-branches-and-clear-merged-branches-before-pr-16).
- Sources: Context7 official [Git push](https://git-scm.com/docs/git-push), [Git branch](https://git-scm.com/docs/git-branch), and [GitHub branch rename API](https://docs.github.com/en/rest/branches/branches#rename-a-branch). Git 2.39.5 (Apple Git-154), GitHub CLI 2.92.0.

## Subsequent develop update

After this cleanup snapshot, the user asked to update develop. It was fast-forwarded to v3 main, with its old tip preserved as `legacy/develop-v2` and PRs #6/#13/#14 retargeted there. See the [develop synchronization record](2026-10-05-develop-sync.md) for the current state; the tables above record the earlier cleanup outcome.
