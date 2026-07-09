# Stop Rules

## Task Sizing (route BEFORE creating any task packet)

- **Micro** (copy/style/docs/config tweak, single file, no logic or contract
  change): main session edits directly on the current task branch, runs the
  relevant checks, commits. NO task packet, NO subtask, NO worktree. The
  commit message is the record.
- **Small** (single file/module, no contract touchpoints): one task packet
  with brief.md only, one subtask, SKIP the design review gate, fast lane
  review. Worktree optional if the change is isolated.
- **Medium/large or any contract change**: full chain (packet, design gate,
  subtask worktrees, independent re-verification, full lane review).
- **Workflow-only changes** follow the same sizing; verification = workflow
  checker scripts.

When unsure between two tiers, pick the heavier one. Hooks apply to every
tier — micro tasks still get auto-checked on write.

## Review Lanes

Route every subtask into a lane before review:

**Fast lane** (all must hold):
- diff under ~50 changed lines, no new files outside the subtask scope
- zero contract touchpoints (no API payload, endpoint, websocket, IPC, or env changes)
- independent re-verification (`verify_subtask.ps1`) is PASS

Fast lane review = orchestrator checks the diff against acceptance criteria
directly; no full reviewer packet required. Record `review lane: fast` in the
task summary.

**Full lane** (any of the above fails): complete reviewer packet, independent
reviewer, human decision. Contract-change subtasks are ALWAYS full lane.

## Escalation Rules

Stop and escalate when any of these are true:

- the task needs real provider credentials to verify behavior
- a backend contract change is requested without clarity on the frontend impact
- a frontend Electron change would require weakening preload or IPC safety
- auth token handling or database semantics would change without explicit acceptance criteria
- the checker scripts surface multi-surface drift that cannot be classified confidently
