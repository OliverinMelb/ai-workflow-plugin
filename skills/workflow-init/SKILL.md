---
name: workflow-init
description: Initialize Codex workflow configuration for a new Git repository. Use when the user asks to initialize, set up, or add workflow support and workflow/config.json is missing.
---

# Workflow Init

Run from the target Git repository. Resolve the sibling
`skills/codex-workflow/scripts/workflow.ps1` script from this plugin and execute:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <codex-workflow-skill>\scripts\workflow.ps1 init
```

The command:

- discovers the Git root;
- detects conservative Python, Node, Maven, Gradle, or generic checks;
- creates only `workflow/config.json`;
- never reads `.env` values;
- refuses to overwrite an existing configuration;
- automatically runs `doctor`.

Use `init --dry-run` when the user wants to inspect the proposed configuration first. After
initialization, summarize the detected stack and checks. Do not claim the configuration is
production-complete when contract paths or environment rules remain empty.
