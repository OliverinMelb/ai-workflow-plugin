# Design Review Gate

Run this gate AFTER `plan.md` is written and BEFORE subtasks are created.
Splitting a bad plan multiplies the rework across every worktree.

## How To Run

Launch 2-3 parallel review agents, each with ONE lens below, each receiving
`brief.md`, `spec.md`, `plan.md`, and `workflow/context/invariants.md`.
Each reviewer answers: "what breaks if we build exactly this plan?"

Iterate at most 2 rounds. If the gate still fails, escalate to human.

## Lenses

### Lens 1: Architecture Boundaries
- Does the plan respect backend/frontend ownership (AGENTS.md)?
- Are proposed subtask boundaries responsibility-based, not directory-based?
- Would two subtasks need the same source-of-truth file in incompatible ways?

### Lens 2: Contract Impact
- Does any change alter API payloads, endpoint behavior, websocket messages,
  IPC channels, or env assumptions?
- If yes, is there a contract-change subtask that owns the alignment?
- Are `docs/wiki/api-reference.md` / `frontend-map.md` updates planned?

### Lens 3: Risk and Verification
- Can each subtask actually be verified by the matrix in
  `workflow/checks/verification.md`? (No "trust me" subtasks.)
- Any stop-rule triggers hiding in the plan (real credentials, auth semantics,
  IPC safety weakening)?
- Is the dependency order between subtasks explicit?

## Gate Record (fill in and keep in the task packet as `design-review.md`)

- plan version reviewed:
- round: 1 | 2
- lens 1 verdict: pass | fail —
- lens 2 verdict: pass | fail —
- lens 3 verdict: pass | fail —
- changes required to plan:
- gate result: PASS (proceed to subtask split) | FAIL (revise plan) | ESCALATE
