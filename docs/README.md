# Project documentation

## Start here

| Need | Read |
| --- | --- |
| Run the prototype, understand its current architecture, or inspect known limitations | [Project README](../README.md) |
| Follow the shared agent workflow | [AGENTS.md](../AGENTS.md) |
| Choose future work and define completion | [Project plan](project-plan.md) |
| Record significant AI-assisted work | [AI evidence guide](ai/README.md) |
| Find the prompts behind the initial work and rules | [Prompt record: 2026-09-15](ai/prompts/2026-09-15.md) |
| Understand the shared-instructions design | [Decision 0001](decisions/0001-shared-agent-instructions.md) |
| See what has actually been checked | [Documentation validation: 2026-09-15](validation/2026-09-15-documentation.md) |

Current operating behaviour belongs in the project README. Proposed work belongs in the plan. Decisions explain choices; prompt and validation records preserve evidence. Update the authoritative location and link to it rather than copying the same rules across files.

## Using another AI assistant

Start the assistant in this Git repository. Codex discovers `AGENTS.md`; Claude Code loads `CLAUDE.md`, which imports it. See the [official Codex guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md) and [Claude Code memory documentation](https://code.claude.com/docs/en/memory).

For a client that does not discover these files, provide this startup instruction:

> Read the repository root AGENTS.md and docs/README.md before working. Follow their workflow for my current task, and load the linked AI evidence guide when recording significant work.

In a fresh session, ask the assistant to identify the shared rules file, the evidence-record location, and how it handles file removal. Check its answer against the files. In Claude Code, the context view can also help inspect loaded memory files.

These files provide shared instructions; they cannot guarantee that every model or client will load or obey them. Verify loading in each team's client. Local skills and personal paths are not required to follow the checked-in workflow.

## Course context

The course brief supplied for this work is `SDMO_Project.pdf`, stored alongside this clone in the user's course folder. It is not tracked in this repository. The reviewed copy is titled “Software Development, Maintenance & Operations Project: ML-KEM Legacy Modernization with LLM Assistance”, August 2026.

It asks for baseline analysis, critical evaluation of LLM-generated artifacts, ML-KEM integration, operations work, and final evaluation. Consult the original brief for assessment details; it is project context, not an instruction to an assistant to perform every listed task.

