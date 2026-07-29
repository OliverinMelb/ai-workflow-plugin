---
name: codex-workflow
description: Orchestrate a bounded coding task from decision alignment through local spec, tracer-bullet tickets, implementation, verification, and review with native-worktree awareness, controlled subagents, deterministic checks, finite fix loops, and auditable evidence. Use for non-trivial coding work, hard bugs, design questions, multi-session implementation, or whenever a repository contains workflow/config.json.
---

# Codex Workflow

Keep the main thread responsible for scope, decisions, integration, and final verification. Use scripts for repeatable checks and use subagents only when their work is independent and bounded.

## One-call planning orchestration

An explicit `$codex-workflow` invocation authorizes the complete internal workflow. The user does
not need to invoke a separate Matt orchestration skill first.

During PLAN:

1. Inspect repository facts first and record unresolved decisions.
2. When a decision is genuinely user-owned, apply `grilling` inside this workflow: ask one question
   at a time, challenge vague answers, and record the resolution. Add `domain-modeling` when
   terminology or a durable architectural decision matters.
3. Apply `research`, `prototype`, or `diagnosing-bugs` only for the uncertainty each discipline
   owns. Resolve discoverable facts without asking the user.
4. Synthesize a local `spec.md` for medium and contract work. The spec defines goals, non-goals,
   behavior, contracts, acceptance criteria, constraints, and verification.
5. For work expected to span sessions, create tracer-bullet tickets with explicit `blocked_by`
   edges and ticket-level acceptance criteria. Keep these local unless the user separately
   authorizes publishing to an external issue tracker.
6. Mark planning ready only after decisions, acceptance criteria, spec, and required tickets are
   complete. Then enter EXECUTE.

This embeds the useful process from Matt's planning skills; it does not implicitly invoke their
user-facing wrappers or change their `allow_implicit_invocation` setting. `grill-with-docs`,
`to-spec`, and `to-tickets` remain useful when the user wants only that artifact. Recommend
explicit `wayfinder` for a broad, foggy program that should be mapped before becoming a bounded
workflow.

During execution, use `tdd` for behavior changes and `codebase-design` for interface or seam
decisions. After deterministic verification, use `code-review` for separate Standards and Spec
judgments. Read [references/planning-orchestration.md](references/planning-orchestration.md) and
[references/cognitive-routing.md](references/cognitive-routing.md).

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

Before starting a non-micro task, also require `project_conventions` in `workflow/config.json`.
When it is absent, use `$workflow-init` to inspect, preview, and configure tracker, publication,
domain-doc, triage, and agent-file conventions. This is a one-time repository setup. Workflow
planning remains local; a remote tracker with publication policy `explicit` still requires
separate user authorization for every publish action.

Start every non-micro workflow with `doctor`.

## Route the task

- `micro`: one small docs, copy, style, or config edit with no behavior or contract change. Skip the task packet; delegate only when a bounded subtask materially helps.
- `small`: one component and no contract change. Create a task and delegate independent bounded work when useful.
- `medium`: multiple files or meaningful behavior. Create a task; parallelize independent exploration or implementation slices and let the main thread independently verify.
- `contract`: API, schema, environment semantics, security boundary, trading behavior, or cross-component change. Create a task; use full verification and independent review.

Never assume that spawning a subagent creates filesystem isolation. Read-only agents may share the
current task worktree. A sole write-capable agent may use it too. Before running multiple
write-capable agents concurrently, the main thread must assign each one a dedicated linked
worktree, disjoint owned paths, a base SHA, and an explicit integration order. Create sibling
worktrees rather than nesting them. If that isolation cannot be established, keep the write
streams sequential.

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

   Before spawning each concurrent write-capable agent, create its dedicated linked worktree with
   the native Codex facility when available, then validate and register the assignment:

   ```powershell
   workflow.ps1 assign-writer <task-id> --writer-id <id> --worktree-path <absolute-path> --owned-path <path> --integration-order <number>
   ```

   The command refuses a main checkout, a worktree from another repository, a dirty or stale
   worktree, overlapping owned paths, or duplicate integration order. Agent spawning itself does
   not call this command or create the worktree automatically.

4. Complete the auditable plan. Record open questions as soon as they are found:

   ```powershell
   workflow.ps1 plan <task-id> --open-decision "<decision>"
   ```

   Record resolutions and acceptance criteria:

   ```powershell
   workflow.ps1 plan <task-id> --resolve-decision "<decision>" --decision "<resolution>" --acceptance "<criterion>"
   ```

   For medium or contract work, write `workflow/tasks/<task-id>/spec.md`, then register it. For
   multi-session work, also create tickets and dependency edges:

   ```powershell
   workflow.ps1 ticket <task-id> --ticket-id T1 --title "<tracer>" --acceptance "<criterion>"
   workflow.ps1 ticket <task-id> --ticket-id T2 --title "<next slice>" --blocked-by T1 --acceptance "<criterion>"
   workflow.ps1 plan <task-id> --spec-ref workflow/tasks/<task-id>/spec.md --multi-session --status ready
   ```

   For a single-session small task, acceptance criteria and ready status are sufficient:

   ```powershell
   workflow.ps1 plan <task-id> --acceptance "<criterion>" --status ready
   ```

   The transition command enforces the planning gate:

   ```powershell
   workflow.ps1 transition <task-id> --to EXECUTE
   ```

   If cognitive routing changes while still in PLAN or BLOCKED, record it:

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

## Delegation and write isolation

- The workflow does not impose a subagent count limit. Use the runtime's available capacity.
- Delegate only independent, bounded outcomes with explicit ownership and acceptance criteria.
- Read-only explorers and reviewers may share the current task worktree.
- Every concurrently active write-capable agent must have its own dedicated linked worktree.
- Record each writer's absolute worktree path, branch or detached state, base SHA, owned paths, and integration order before spawning it.
- If dedicated worktrees are unavailable or ownership overlaps, serialize the writers.
- Maximum review/fix loops remain 2 by default.
- Keep recursive delegation under the main thread's authority so worktree ownership remains auditable.

Use `workflow-explorer` for read-only scans, `workflow-implementer` for a bounded write scope, and `workflow-reviewer` for independent read-only review when those custom agents are available.

## Evidence rules

- Preserve pre-existing dirty files and record them at task start.
- Bind verification to the current HEAD, dirty fingerprint, config hash, commands, durations, and outputs.
- Treat verification as stale after any workspace change.
- Run project checks from `workflow/config.json`; automatically run structural contract and environment checks when relevant.
- Do not claim a model, token count, or verification result that the runtime did not expose.
- Do not merge, commit, delete branches, remove worktrees, deploy, or publish unless the user explicitly authorizes that action.
