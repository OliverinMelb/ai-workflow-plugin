---
name: codex-workflow
description: Run a bounded Codex coding workflow with task sizing, native-worktree awareness, limited subagent delegation, deterministic environment diagnosis, independent verification, finite review/fix loops, and auditable task closure. Use when the user asks to plan, implement, verify, review, resume, or close non-trivial repository work using the workflow protocol, or when a repository contains workflow/config.json.
---

# Codex Workflow

Keep the main thread responsible for scope, decisions, integration, and final verification. Use scripts for repeatable checks and use subagents only when their work is independent and bounded.

## Command

Resolve `scripts/workflow.ps1` relative to this skill directory and run it from the target repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skill-dir>\scripts\workflow.ps1 <command> <args>
```

Start every non-micro workflow with `doctor`.

## Route the task

- `micro`: one small docs, copy, style, or config edit with no behavior or contract change. Do not create a task packet or subagent.
- `small`: one component and no contract change. Create a task; use zero or one subagent only when exploration materially helps.
- `medium`: multiple files or meaningful behavior. Create a task; prefer one implementer and let the main thread independently verify.
- `contract`: API, schema, environment semantics, security boundary, trading behavior, or cross-component change. Create a task; use full verification and one read-only reviewer.

Never create a nested worktree when Codex already placed the chat in one. Use another worktree only for an independent parallel write stream with disjoint owned paths. Keep dependent slices sequential in the same workspace.

## Run the state machine

1. Diagnose:

   ```powershell
   workflow.ps1 doctor
   ```

2. Start:

   ```powershell
   workflow.ps1 start --title "<task>" --tier medium --workflow-class <class> --owned-path <path>
   ```

3. Complete the plan, record acceptance criteria in the generated `brief.md`, then:

   ```powershell
   workflow.ps1 transition <task-id> --to EXECUTE
   ```

4. Implement within owned paths. Do not require a commit before verification.

5. Independently verify from the main thread:

   ```powershell
   workflow.ps1 verify <task-id>
   ```

6. Review only after verification passes. For a pass:

   ```powershell
   workflow.ps1 review <task-id> --verdict pass
   ```

   For actionable findings:

   ```powershell
   workflow.ps1 review <task-id> --verdict fix --finding "<finding>"
   ```

   Return fixes to the same implementer context when practical. The script enforces the configured fix-loop limit.

7. After integration, run verification again if the workspace changed, pass review, then close:

   ```powershell
   workflow.ps1 close <task-id>
   ```

Read [references/protocol.md](references/protocol.md) when deciding delegation, ownership, review, or recovery. Read [references/config.md](references/config.md) when creating or changing `workflow/config.json`.

## Agent budget

- Micro: 0 subagents.
- Small: at most 1.
- Medium: at most 1 active implementer; optional read-only explorer first.
- Contract: at most 1 implementer and 1 reviewer.
- Maximum review/fix loops: 2 by default.
- Do not let workflow subagents spawn more subagents.

Use `workflow-explorer` for read-only scans, `workflow-implementer` for a bounded write scope, and `workflow-reviewer` for independent read-only review when those custom agents are available.

## Evidence rules

- Preserve pre-existing dirty files and record them at task start.
- Bind verification to the current HEAD, dirty fingerprint, config hash, commands, durations, and outputs.
- Treat verification as stale after any workspace change.
- Run project checks from `workflow/config.json`; automatically run structural contract and environment checks when relevant.
- Do not claim a model, token count, or verification result that the runtime did not expose.
- Do not merge, commit, delete branches, remove worktrees, deploy, or publish unless the user explicitly authorizes that action.
