# Verification Matrix

## Two Layers of Verification

1. **Maker checks**: the implementing subagent runs the matrix below inside its
   worktree and records results in its subtask summary. This is self-report.
2. **Independent re-verification**: before the reviewer packet is assembled, the
   orchestrator (or reviewer) re-runs the same matrix via
   `workflow/scripts/verify_subtask.ps1 -TaskId <id> -SubtaskId <id>`.
   Self-reported results are never trusted as review evidence; only the
   `subtask-summaries/<subtask-id>.verify.md` evidence file counts.

A subtask is not review-ready until its independent re-verification is PASS.

## Backend Only
Run from `ai_helper_backend`:
- `python -m pytest`
- `python -m ruff check .`

## Frontend Only
Run from `ai_helper_frontend`:
- `npm run test`
- `npm run typecheck`
- `npm run build`

## Contract Change
Run both backend and frontend checks, then:
- `python workflow/scripts/check_contract_touchpoints.py`
- `python workflow/scripts/check_env_consistency.py`

## Workflow-Only Change
Run from repo root:
- `python workflow/scripts/check_env_consistency.py`
- `python workflow/scripts/check_contract_touchpoints.py`
