# Codex workflow protocol

## State machine

```text
PLAN -> EXECUTE -> VERIFY -> REVIEW -> INTEGRATE -> VERIFY -> REVIEW -> INTEGRATE -> CLOSED
                       |         |
                       +-> FIX <-+

Any active state -> BLOCKED
BLOCKED -> PLAN | EXECUTE | FIX
```

`verify` moves passing work to `REVIEW` and failing work to `FIX`. `review --verdict fix` consumes one fix-loop allowance. `review --verdict pass` moves fresh verified work to `INTEGRATE`. `close` requires fresh passing evidence while in `INTEGRATE`.

## Cognitive gate

Before `PLAN -> EXECUTE`, resolve product decisions, missing facts, runnable design questions, and
bug reproduction using `references/cognitive-routing.md`. Record selected disciplines, source
artifacts, and short routing notes in the task packet. Cognitive skills inform the workflow; they
do not own task state, delegation, worktrees, integration, or closure.

New task packets also carry an enforced planning record. `PLAN -> EXECUTE` requires `status=ready`,
`grilling_status=confirmed`, at least one acceptance criterion, and no unresolved decisions.
Medium and contract tasks require a repository-local spec. Multi-session tasks additionally
require tracer-bullet tickets with ticket-level acceptance criteria and a valid acyclic
`blocked_by` graph. Legacy task packets with schema version 1 remain resumable; schema version 2
cannot omit its planning record. A schema version 2 planning record that predates
`grilling_status` is treated as pending and can be resumed by completing the checkpoint.

Use `plan --confirm-grilling` only after the user explicitly confirms the final shared-
understanding summary. Opening or resolving decisions, changing decisions, acceptance criteria,
the spec reference, multi-session status, or tickets resets confirmation to `pending`.

Passing verification binds evidence to the semantic planning record and the registered spec
content hash. Changing either after verification makes the evidence stale and requires a new
verification run.

## Ownership

Record explicit `owned_paths` for every write-capable task. A path owns itself and descendants. Changes outside owned paths fail verification unless they are unchanged pre-existing dirty files recorded at task start.

Parallel write streams are allowed only when:

- their owned paths do not overlap;
- neither depends on the other's uncommitted result;
- shared contracts are unchanged or assigned to one owner;
- integration order is explicit.

Use the current Codex-managed worktree as the integration workspace. Read-only agents and a sole
write-capable agent may share it. Before multiple write-capable agents run concurrently, the main
thread must create or assign a dedicated linked worktree to each writer. Never assume agent spawn
provides worktree isolation.

## Delegation

Delegate read-heavy exploration, test analysis, or independent review. Keep ambiguous scope decisions and integration in the main thread.

The workflow does not impose a subagent count limit; concurrency is governed by runtime capacity
and whether useful work can be split into independent bounded outcomes. Legacy
`codex_workflow.max_subagents` configuration is accepted but ignored.

Read-only agents may share the integration worktree. For every concurrent write-capable agent,
record an absolute worktree path, branch or detached state, base SHA, disjoint `owned_paths`, and
integration order before spawning it. The assigned prompt must require all commands and writes to
stay in that worktree. If isolation cannot be established or ownership overlaps, serialize those
writers.

Use `workflow.ps1 assign-writer` to validate and store each writer assignment in
`task.delegation.writers`. The command accepts only a clean linked worktree from the same Git
common directory whose HEAD matches the task base SHA. Worktree creation remains an explicit
main-thread action through the native Codex facility or the approved Git fallback.

Give each subagent:

- one concrete outcome;
- exact read and write boundaries;
- acceptance criteria;
- required checks;
- a concise return format.

Reuse the same implementer for fixes to avoid reloading project context. Do not create an LLM health-checker for normal runs; use `status`, state transitions, timeouts, and verification evidence.

## Recovery

- `BLOCKED`: record the blocker in task history, resolve it, then transition to the appropriate state.
- stale evidence: rerun `verify`; never override freshness for closure.
- failing check: fix in the same workspace, then rerun the whole configured matrix.
- overlapping writes or a writer in the wrong worktree: stop the affected streams and integrate sequentially.
- detached HEAD: continue working and verifying; create a branch only when the user authorizes integration or persistence.

## Lessons

At closure, promote only reusable failures:

- machine/environment facts -> shared `environment.md`;
- cross-project failure patterns -> shared `lessons.md`;
- project-specific patterns -> project `workflow/context/lessons.md`.

Merge with an existing lesson ID instead of appending duplicates. Prefer a deterministic doctor check over prose when a failure can be detected mechanically.
