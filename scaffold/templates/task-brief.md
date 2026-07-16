# Task Brief

<!-- Single task document. small tier: delete the Plan and Design Gate sections. -->

## Goal

## Context
<!-- Known facts; cite the two memory tiers / wiki instead of rediscovering. -->

## Scope
- backend:
- frontend:
- shared contract:

## Constraints

## Deliverables

## Acceptance Criteria
<!-- Every item must be verifiable by a command or file existence. -->
- [ ]

## Stop Conditions

## Plan (standard tier only)
<!-- Subtask split. One subtask = one worktree = one responsibility. -->
| subtask | workflow class | boundary (files it may touch) | depends on |
|---|---|---|---|

## Design Gate Checklist (standard tier only — orchestrator self-check, no review subagents)
<!-- All boxes checked = gate PASS, proceed to subtask split. Any unresolved box = revise Plan or escalate. -->
- [ ] subtask boundaries are responsibility-based; no two subtasks contend for the same source-of-truth file
- [ ] contract impact identified (API payload / endpoint / websocket / IPC / env); if any, a dedicated subtask owns the change and wiki sync is planned
- [ ] every subtask is verifiable by the check matrix (no "trust me" subtasks)
- [ ] no stop-rule triggers hidden in the plan (real credentials, auth semantics, IPC safety weakening)
- [ ] dependency order between subtasks is explicit
- gate result: PASS | FAIL | ESCALATE —

## Notes
