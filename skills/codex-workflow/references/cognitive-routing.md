# Cognitive routing

Use this reference before implementation to select the smallest useful thinking discipline.
The workflow remains the authority for task state, subagents, worktrees, ownership, verification,
review, integration, and closure.

## Routing table

| Signal | Model-invoked discipline | Exit condition |
| --- | --- | --- |
| Product or design decisions are unresolved | `grilling` | The user has answered one decision at a time and acceptance criteria are clear |
| Domain terms conflict or a durable trade-off is being made | `domain-modeling` with `grilling` | Vocabulary and any justified ADR are resolved |
| A public technical fact is missing | `research` | A primary-source artifact answers the blocking question |
| State, logic, or UI must be experienced to decide | `prototype` | The disposable prototype answers one named question |
| A hard bug lacks a tight feedback loop | `diagnosing-bugs` | One command reproduces the failure |
| Behavior is ready to implement | `tdd` | Red-green slices satisfy the acceptance criteria |
| A module boundary or test seam is unclear | `codebase-design` | The interface and ownership boundary are explicit |
| Verified work needs independent judgment | `code-review` | Standards and Spec judgments both pass |

If a listed skill is unavailable, apply the same discipline in the main thread and record that
fallback in `--routing-note`.

## Invocation boundary

Model-invoked skills may be selected automatically when their descriptions match the task.
User-invoked orchestrators (`grill-with-docs`, `to-spec`, `to-tickets`, `implement`, `wayfinder`)
must not be invoked implicitly. Recommend the appropriate orchestrator and wait for explicit user
invocation when the work needs it.

## Delegation and worktrees

The workflow, not a cognitive skill, decides whether to create a subagent. Cognitive skills may
request research, implementation, or review, but the configured agent budget and owned paths win.
Subagents must not spawn subagents.

Reuse the current Codex-managed worktree. Read-only explorers and reviewers share it. Use at most
one write-capable implementer by default. Create another worktree only for an explicitly independent
parallel write stream with disjoint owned paths and a declared integration order.

## Audit

Record the selected disciplines and their artifacts at task start:

```powershell
workflow.ps1 start --title "<task>" --tier medium --workflow-class <class> `
  --owned-path <path> --skill diagnosing-bugs --source-ref issue:123
```

Append discoveries before execution:

```powershell
workflow.ps1 route <task-id> --skill research `
  --source-ref research/api-contract.md --routing-note "Verified the public API contract."
```

The task's `cognitive_routing` object and `COGNITIVE_ROUTE` history events are the audit record.
