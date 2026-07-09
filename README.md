# ai-workflow plugin

可复用的多 worktree 代理工作流引擎（Claude Code plugin）。设计原则：

- **引擎带"怎么做"，项目仓库带"做了什么"**：脚本/hooks/agents 在 plugin 里，
  任务包、worktree 注册表、教训、以及一切项目特定事实留在各项目仓库。
- **项目特定事实唯一来源是各项目的 `workflow/config.json`**：组件目录、
  检查矩阵、检查器规则、记忆指针。移植到新项目 = 装 plugin + 写一份 config。
- **两层记忆**：`~/.claude/workflow-memory/`（机器事实 + 跨项目教训，
  `~/.claude/CLAUDE.md` 索引）；项目层在各仓库 wiki/lessons。判据：
  换一个项目仍成立 → 全局，否则 → 项目。

## 当前内容（v0.1，P1 阶段）

- `hooks/hooks.json` + `scripts/hooks/`：
  - `guard_worktree_scope`（PreToolUse）：worktree 写入边界硬门禁
  - `auto_check`（PostToolUse）：按 config 规则对刚写入的文件做快速检查
  - `session_start`（SessionStart）：注入项目 + 全局两层记忆指针
  - 三者都在**没有 `workflow/config.json` 的项目里静默跳过**
- `agents/`：通用 `implementer` / `reviewer`（项目可用自己的
  `.claude/agents/` 特化版覆盖，特化版优先）

编排脚本（new_task / assign_worktree / verify_subtask / bootstrap /
render_subagent_prompt / checkers）目前仍在首个消费项目（ai_helper）的
`workflow/scripts/` 里，P2 做 skills 时随包装一起迁入，避免过渡期双份漂移。

## 安装（本地目录 marketplace）

用户级 `~/.claude/settings.json`：

```json
{
  "extraKnownMarketplaces": {
    "ai-workflow-local": {
      "source": { "source": "directory", "path": "<本仓库绝对路径>" }
    }
  },
  "enabledPlugins": { "ai-workflow@ai-workflow-local": true }
}
```

## workflow/config.json schema（消费项目必备）

```jsonc
{
  "project_name": "...",
  "memory": {
    "pointers": ["会话启动时注入的项目记忆指针,一行一条"],
    "global_memory_dir": "~/.claude/workflow-memory"
  },
  "python": { "venv": "<相对路径>/.venv" },       // cmd:"python" 的解析锚点
  "components": {                                  // bootstrap 用
    "<名>": { "dir": "...", "type": "python-venv", "probe_imports": ["pytest"] },
    "<名>": { "dir": "...", "type": "node", "probe_modules": ["typescript"],
              "install_env": { "KEY": "value" } }
  },
  "checks": { "<组>": [ { "name": "...", "dir": "...", "cmd": "python|npm|...",
                           "args": ["..."] } ] },
  "workflow_classes": { "<类>": ["<组>", "..."] }, // 类 → 检查组
  "auto_check": { "path_contains": "...", "extension": ".py",
                  "cmd": "python", "args": ["-m", "ruff", "check"] },
  "contract_touchpoints": { "surface_markers": ["..."],
                            "structural_checks": [ { "file": "...",
                              "must_contain": ["..."], "error": "..." } ] },
  "env_consistency": { "rules": [ { "file": "...", "must_contain": "...",
                                     "error": "..." } ] }
}
```

约定：检查里 `cmd: "python"` 由引擎解析为 项目 venv > `WORKFLOW_PYTHON`
（用户级 settings env）> PATH，并验证可运行（Windows Store 别名会 exit 9009）。

## 路线图

- P2：五个 skills（workflow-init / task-new / task-assign / task-verify /
  task-close），编排脚本迁入并由 skills 包装
- P3：第二个项目移植验收（收束标准：新项目 ≤30 分钟人工介入走完最小闭环，
  零次翻阅首个项目）
