# Planning orchestration

## Invocation contract

One explicit `$codex-workflow` invocation owns the bounded lifecycle from alignment through
closure. Do not ask the user to chain `grill-with-docs`, `to-spec`, `to-tickets`, or `implement`
before this workflow. Borrow their core practices inside PLAN while keeping the Codex workflow
authoritative for state, worktrees, subagents, verification, and review.

The wrappers remain explicit because they are also useful as standalone, user-directed artifact
workflows. Never change their invocation metadata as a side effect of using this workflow.

## PLAN loop

1. Establish repository facts, constraints, and current behavior.
2. List only decisions that cannot be safely resolved from evidence.
3. For user-owned decisions, ask one focused question at a time. Explain the concrete trade-off,
   press on ambiguous answers, and record the chosen resolution.
4. Stabilize domain terms and durable decisions when inconsistent language would leak into code.
5. Route remaining uncertainty:
   - public factual gap -> research;
   - one runnable design or state question -> prototype;
   - hard failure without a tight loop -> diagnosis.
6. Write the smallest implementation-grade spec. Include goal, non-goals, existing behavior,
   proposed behavior, affected contracts, constraints, acceptance criteria, and verification.
7. Decide whether the task is multi-session. If yes, create vertical tracer-bullet tickets rather
   than horizontal layer tickets. Every ticket needs acceptance criteria; `blocked_by` expresses
   sequencing.
8. Mark the plan ready only when no unresolved decisions remain.

## Ticket execution

Treat each unblocked ticket as a fresh bounded implementation packet. Preserve the shared spec and
decisions, but avoid carrying speculative conversation history. Prefer one write-capable agent at
a time unless tickets are genuinely independent and own disjoint paths.

Ticket publication is separate from ticket creation. Local task artifacts are authorized by the
workflow invocation; creating or modifying GitHub, Linear, Jira, or another external tracker
requires explicit user authorization.

## Escape hatch

If the requested outcome is too broad to produce a credible bounded spec or tracer bullet, stop
at PLAN and recommend explicit `wayfinder`. Resume the workflow after its map is accepted.
