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

## Ownership

Record explicit `owned_paths` for every write-capable task. A path owns itself and descendants. Changes outside owned paths fail verification unless they are unchanged pre-existing dirty files recorded at task start.

Parallel write streams are allowed only when:

- their owned paths do not overlap;
- neither depends on the other's uncommitted result;
- shared contracts are unchanged or assigned to one owner;
- integration order is explicit.

Use the current Codex-managed worktree as the task workspace. Do not create one worktree per subtask by default.

## Delegation

Delegate read-heavy exploration, test analysis, or independent review. Keep ambiguous scope decisions and integration in the main thread.

The configured `max_subagents` is a hard cap on the tier allowance. A cognitive skill cannot
override it. Use one write-capable implementer at a time; reserve any additional allowance for
read-only exploration or review.

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
- overlapping writes: stop one stream and integrate sequentially.
- detached HEAD: continue working and verifying; create a branch only when the user authorizes integration or persistence.

## Lessons

At closure, promote only reusable failures:

- machine/environment facts -> shared `environment.md`;
- cross-project failure patterns -> shared `lessons.md`;
- project-specific patterns -> project `workflow/context/lessons.md`.

Merge with an existing lesson ID instead of appending duplicates. Prefer a deterministic doctor check over prose when a failure can be detected mechanically.
