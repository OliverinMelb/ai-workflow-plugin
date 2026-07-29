---
name: workflow-init
description: Initialize or complete a repository's Codex workflow setup, including deterministic project checks, issue-tracker conventions, publication policy, domain-document layout, triage labels, and AGENTS.md or CLAUDE.md guidance. Use when workflow/config.json or its project_conventions block is missing, or when the user asks to set up Workflow or Matt-compatible project conventions.
---

# Workflow Init

Run once per repository and again only when the user intentionally changes project conventions.
Resolve the sibling `skills/codex-workflow/scripts/workflow.ps1` script.

## 1. Verification setup

If `workflow/config.json` is missing, preview and then initialize:

```powershell
workflow.ps1 init --dry-run
workflow.ps1 init
```

This detects conservative Python, Node, Maven, Gradle, or generic checks, never reads `.env`, never
overwrites existing configuration, and runs `doctor`.

## 2. Project conventions

If `project_conventions` is missing from `workflow/config.json`, inspect Git remotes, `.scratch/`,
agent files, domain documents, ADR directories, monorepo signals, and whether `triage` is installed.

Recommend local Markdown unless the user already uses a remote tracker and wants it recorded.
Remote tracker configuration does not authorize publishing: ordinary projects use publication
policy `explicit`; private/company workflows use `forbidden` and must use the local tracker.

Ask one question at a time only where the repository does not settle the choice. If neither
`AGENTS.md` nor `CLAUDE.md` exists, ask which file to create. Default to single-context domain
docs unless genuine monorepo signals exist.

Preview all generated files before writing:

```powershell
workflow.ps1 setup --tracker local --publication-policy explicit --domain-layout single --with-triage --agent-file AGENTS.md --dry-run
```

Show the preview to the user, accept edits, then rerun without `--dry-run`. Omit `--with-triage`
when triage is unavailable. For private/company repositories:

```powershell
workflow.ps1 setup --profile private --tracker local --publication-policy forbidden --domain-layout single --agent-file AGENTS.md --dry-run
```

The command creates `docs/agents/issue-tracker.md`, `docs/agents/domain.md`, optional
`docs/agents/triage-labels.md`, a managed block in the chosen agent file, and the
`project_conventions` config block. It refuses to overwrite existing convention documents or an
unmanaged `## Agent skills` section.

For a custom tracker, collect its fetch/read/list/create/update/comment/close and blocking workflow,
then pass it with `--tracker other --tracker-instructions "<workflow>"`. Use repeated
`--triage-label role=value` arguments when the repository already has non-default label names.

After initialization, summarize detected checks and conventions. Do not claim contract paths or
environment rules are complete when they remain empty.
