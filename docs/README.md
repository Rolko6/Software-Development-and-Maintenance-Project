# Project documentation

## Start here

| Need | Read |
| --- | --- |
| Run the prototype, understand its current architecture, or inspect known limitations | [Project README](../README.md) |
| Follow the shared agent workflow | [AGENTS.md](../AGENTS.md) |
| Choose future work and define completion | [Project plan](project-plan.md) |
| Record significant AI-assisted work | [AI evidence guide](ai/README.md) |
| Find the prompts behind the initial work and rules | [Prompt record: 2026-09-15](ai/prompts/2026-09-15.md) |
| See what each release contains, why, and how to evaluate it | [v1.0.0 record](ai/prompts/v1.0.0.md), [v2.0.0 record](ai/prompts/v2.0.0.md) |
| Find the prompt behind the v2.0.0 release | [Prompt record: 2026-09-24](ai/prompts/2026-09-24.md) |
| Understand the shared-instructions design | [Decision 0001](decisions/0001-shared-agent-instructions.md) |
| Understand how ML-KEM key establishment is designed and what it protects | [ML-KEM integration design](security/ml-kem-integration.md) |
| Understand why that cryptographic library and protocol were chosen | [Decision 0002](decisions/0002-ml-kem-key-establishment.md) |
| Run the CI pipeline, or reproduce a failing job locally | [CI guide](operations/ci.md) |
| Deploy to a shared test environment | [Deployment runbook](operations/deployment.md) |
| Scrape metrics and query delivery or handshake failures | [Monitoring guide](operations/monitoring.md) |
| Understand what the ML-KEM tests do and do not prove | [ML-KEM verification](testing/ml-kem-verification.md) |
| See what has actually been checked | [Documentation validation: 2026-09-15](validation/2026-09-15-documentation.md) |
| See the measured plaintext baseline and how to reproduce it | [Baseline validation: 2026-09-15](validation/2026-09-15-baseline.md) |
| See which reliability gap each fix closes, and its regression test | [Reliability validation: 2026-09-15](validation/2026-09-15-reliability.md) |
| See the container evidence, the ML-KEM checks and the plaintext-vs-secured comparison | [Integration validation: 2026-09-15](validation/2026-09-15-integration.md) |
| Understand how baseline and secured measurements are kept comparable | [Measurement method: 2026-09-15](validation/2026-09-15-measurement-method.md) |
| See what has actually been checked for the device module restructuring | [Device modularization validation: 2026-09-15](validation/2026-09-15-device-modularization.md) |
| See what has actually been checked for the automated tests and CI/CD | [Tests and CI/CD validation: 2026-09-15](validation/2026-09-15-tests-and-ci.md) |

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
