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
<!-- Every item: verify command + expected output (not just "verifiable").
     No placeholder language ("add appropriate error handling" etc). -->
- [ ]

## Stop Conditions

## Options Considered (standard tier only)
<!-- Filled BEFORE the rest of the brief when the requirement has design
     space: present 2-3 approaches with trade-offs + a recommendation to the
     user ONCE, get one confirmation, record the outcome here. Skip only when
     there is genuinely one way to do it (say so). -->
- chosen: <approach> -- why:
- rejected: <approach> -- why not:

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
