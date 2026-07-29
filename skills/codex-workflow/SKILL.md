---
name: codex-workflow
description: Route, plan, implement, verify, review, resume, or close bounded repository work with cognitive-skill selection, native-worktree awareness, controlled subagent delegation, deterministic checks, finite fix loops, and auditable task evidence. Use for non-trivial coding work, hard bugs, design questions that may need research or a prototype, or whenever a repository contains workflow/config.json.
---

# Codex Workflow

Keep the main thread responsible for scope, decisions, integration, and final verification. Use scripts for repeatable checks and use subagents only when their work is independent and bounded.

## Cognitive routing

Before creating a task packet, classify what is missing:

- unresolved user decisions -> use `grilling`; add `domain-modeling` when domain language or a durable decision is involved;
- missing public facts -> use `research`;
- a runnable state, logic, or UI question -> use `prototype`;
- a hard bug without a tight reproduction -> use `diagnosing-bugs`;
- clear, bounded implementation -> start the workflow directly.

During execution, use `tdd` for behavior changes and `codebase-design` for interface or seam decisions.
After deterministic verification, use `code-review` for separate Standards and Spec judgments.

These are model-invoked disciplines. Do not implicitly invoke Matt's user-invoked orchestrators
such as `grill-with-docs`, `to-spec`, `to-tickets`, or `wayfinder`; recommend them when appropriate
and continue only after the user invokes them. Read
[references/cognitive-routing.md](references/cognitive-routing.md) for routing, delegation, and
fallback rules.

## Command

Resolve `scripts/workflow.ps1` relative to this skill directory and run it from the target repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skill-dir>\scripts\workflow.ps1 <command> <args>
```

For a new Git repository without `workflow/config.json`, initialize it first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skill-dir>\scripts\workflow.ps1 init
```

`init` detects conservative Python, Node, Maven, or Gradle checks from repository metadata, writes
only `workflow/config.json`, refuses to overwrite an existing configuration, and then runs
`doctor`. It never reads `.env` values. Use `init --dry-run` to inspect the generated JSON without
writing.

Start every non-micro workflow with `doctor`.

## Route the task

- `micro`: one small docs, copy, style, or config edit with no behavior or contract change. Do not create a task packet or subagent.
- `small`: one component and no contract change. Create a task; use zero or one subagent only when exploration materially helps.
- `medium`: multiple files or meaningful behavior. Create a task; prefer one implementer and let the main thread independently verify.
- `contract`: API, schema, environment semantics, security boundary, trading behavior, or cross-component change. Create a task; use full verification and one read-only reviewer.

Never create a nested worktree when Codex already placed the chat in one. Use another worktree only for an independent parallel write stream with disjoint owned paths. Keep dependent slices sequential in the same workspace.

## Run the state machine

1. Initialize once when configuration is missing:

   ```powershell
   workflow.ps1 init
   ```

2. Diagnose:

   ```powershell
   workflow.ps1 doctor
   ```

3. Start:

   ```powershell
   workflow.ps1 start --title "<task>" --tier medium --workflow-class <class> --owned-path <path> --skill <discipline> --source-ref <issue-or-spec>
   ```

4. Complete the plan, record acceptance criteria in the generated `brief.md`, then:

   ```powershell
   workflow.ps1 transition <task-id> --to EXECUTE
   ```

   If routing changes while still in PLAN or BLOCKED, record it:

   ```powershell
   workflow.ps1 route <task-id> --skill research --source-ref <artifact> --routing-note "<why>"
   ```

5. Implement within owned paths. Do not require a commit before verification.

6. Independently verify from the main thread:

   ```powershell
   workflow.ps1 verify <task-id>
   ```

7. Review only after verification passes. For a pass:

   ```powershell
   workflow.ps1 review <task-id> --verdict pass
   ```

   For actionable findings:

   ```powershell
   workflow.ps1 review <task-id> --verdict fix --finding "<finding>"
   ```

   Return fixes to the same implementer context when practical. The script enforces the configured fix-loop limit.

8. After integration, run verification again if the workspace changed, pass review, then close:

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
