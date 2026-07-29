# workflow/config.json v1

The Codex engine remains compatible with existing `components`, `checks`, `workflow_classes`, `python`, `contract_touchpoints`, and `env_consistency` fields.

## Automatic initialization

From a new Git repository, run:

```powershell
workflow.ps1 init
```

The command inspects repository metadata such as `pyproject.toml`, `package.json`, `pom.xml`,
Gradle build files, test directories, and wrapper scripts. It does not inspect `.env` values.
It creates a conservative starting configuration and immediately runs `doctor`.

- Use `init --dry-run` to print the proposed JSON without writing.
- Use `init --project-name "<name>"` to override the repository-folder project name.
- Existing `workflow/config.json` files are never overwritten.
- Generated contract and environment sections are intentionally minimal; extend them only with
  verified project facts.

Add this optional block for Codex routing:

```json
{
  "codex_workflow": {
    "version": 1,
    "default_tier": "small",
    "default_class": "app-change",
    "max_fix_loops": 2,
    "max_subagents": 2,
    "check_timeout_seconds": 900,
    "global_memory_dir": "C:/Users/admin/.agents/workflow-memory"
  }
}
```

Keep model names out of project workflow configuration. Configure role models in Codex custom-agent TOML files.

`max_subagents` is a hard project cap. The task receives the lower of this value and its tier
allowance. Set it to `0` to keep all work in the main thread.

## Checks

```json
{
  "checks": {
    "app": [
      {
        "name": "tests",
        "dir": "",
        "cmd": "npm",
        "args": ["test"],
        "timeout_seconds": 900
      }
    ]
  },
  "workflow_classes": {
    "app-change": ["app"]
  }
}
```

For `cmd: "python"`, the engine resolves the configured project venv first. Commands run without a shell, with UTF-8 Python environment variables set.

## Contract checks

`contract_touchpoints.surface_markers` identifies risky paths. When a changed path matches, every configured `structural_checks` rule is evaluated.

`env_consistency.rules` checks that required markers remain in configuration or code files. Never put secret values in workflow configuration.
