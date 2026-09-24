# Decision 0001: One shared agent instructions file

- Date: 2026-09-15
- Status: implemented under the user's request; human review of the wording not recorded.
- Origin: [P003](../ai/prompts/2026-09-15-yyy-tom.md#p003-shared-rules-and-prompt-records).

## Context

The group wants AI assistants working in this repository to follow the same process and preserve crucial prompts as project evidence. Separate copies of the same rules would drift.

## Decision

Keep shared rules in root `AGENTS.md`. Root `CLAUDE.md` imports it using `@AGENTS.md`. Other clients can be explicitly instructed to read it. Keep evidence-record details in `docs/ai/README.md`, reached whenever significant work requires a record.

Use one documentation index, keep current runtime documentation in the README, and store proposals, decisions, and historical evidence in their own files. Archive prompts as data rather than importing their text into the active rules.

This applies the user-invoked writing-great-skills guidance: one source of truth, short entry points, conditional links to detail, and checkable completion criteria. The skill is a design reference used for this change, not an installed repository dependency.

## Alternatives considered

- Duplicate the rules in both tool files: easy to read independently, but every rule change requires synchronized edits.
- Put all rules and history into each entry point: more context to load, with a greater risk of treating an old request as a current instruction.

## Consequences and verification

Shared edits happen in one place. Prompt history remains auditable. Assistants still depend on their client's file loading and instruction adherence; these Markdown files do not enforce tool permissions.

Static file and import checks are recorded in [validation](../validation/2026-09-15-documentation.md). Fresh Codex and Claude sessions have not been launched to verify discovery in this task.

## Sources

- [Codex AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Claude Code imports and instruction memory](https://code.claude.com/docs/en/memory)
- User-supplied writing-great-skills skill and glossary, read from the user's local skill directory on 2026-09-15.
