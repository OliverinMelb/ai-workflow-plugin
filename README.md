# ai-workflow plugin

> **`codex-win` 分支**：Codex/Windows v1 已加入本分支。Codex 用户先阅读
> [README-CODEX.md](README-CODEX.md)；原有 Claude Code v1 文件保留用于兼容和历史对照。

可复用的多 worktree 代理工作流引擎（Claude Code plugin）。

> **状态：early（v1.0）**。在 2 个真实项目（FastAPI+Electron、Nuxt）上完成
> 移植验收，但只在 1 台机器上跑过——假设它有坑，欢迎 issue。
>
> **环境要求**：Windows（NTFS junction / PowerShell 5.1+）、git、
> Claude Code。引擎目前是 Windows 专用；跨平台移植在路线图上，
> 有需求请开 issue。
>
> **安装**：`/plugin marketplace add <本仓库>` 后 install，
> 在自己的项目里跑 `/workflow-init` 接入。License: MIT。

设计原则：

- **引擎带"怎么做"，项目仓库带"做了什么"**：脚本/hooks/agents 在 plugin 里，
  任务包、worktree 注册表、教训、以及一切项目特定事实留在各项目仓库。
- **项目特定事实唯一来源是各项目的 `workflow/config.json`**：组件目录、
  检查矩阵、检查器规则、记忆指针。移植到新项目 = 装 plugin + 写一份 config。
- **两层记忆**：`~/.claude/workflow-memory/`（机器事实 + 跨项目教训，
  `~/.claude/CLAUDE.md` 索引）；项目层在各仓库 wiki/lessons。判据：
  换一个项目仍成立 → 全局，否则 → 项目。

## 当前内容（v1.0）

> v1.0 收束记录：P3 移植验收于 2026-07-09 在第二个项目（Nuxt 技术栈）通过——
> 全流程（init 检查/分级建包/实现/独立复验/Playwright 行为验收/闭环）零次翻阅
> 首个项目；摩擦项已修（small 级直验 `-WorktreePath`、复验并发预检、maker
> check 目录纪律）。

- `hooks/hooks.json` + `scripts/hooks/`：
  - `guard_worktree_scope`（PreToolUse）：worktree 写入边界硬门禁
  - `auto_check`（PostToolUse）：按 config 规则对刚写入的文件做快速检查
  - `session_start`（SessionStart）：注入项目 + 全局两层记忆指针
  - 三者都在**没有 `workflow/config.json` 的项目里静默跳过**
- `scripts/`：全部编排引擎（new_task / new_subtask / assign_worktree /
  render_subagent_prompt / verify_subtask / assemble_reviewer_packet /
  bootstrap / 三个检查器 / register_worktree）。项目根一律从 cwd 经 git
  解析（`_lib.ps1` / `_lib.py`）：状态类脚本用主 checkout 根，检查器用
  所在树的根（worktree 感知——修复了老版本"在 worktree 跑检查器却检查
  主 checkout"的隐性 bug）。
- `skills/`：五个流程 skill
  - `/workflow-init`：新项目脚手架（scaffold/ 拷贝 + config 引导）
  - `/task-new`：分级路由（trivial 不建包）+ 建任务包
  - `/task-assign`：子任务 → worktree（自动 bootstrap）→ 渲染提示词 → 派发
  - `/task-verify`：独立复验 + fast/full lane 判定
  - `/task-close`：闭环清单（summary/两层记忆分拣/wiki/清理）
- `agents/`：通用 `implementer` / `reviewer`（项目特化版优先）
- `scaffold/`：workflow-init 的铺骨架素材（templates/checks/registry/
  config.example.json）

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

Git 证据模型：任务/子任务创建时记录 `base_sha`（brief 与 registry），受审变更集
= `base_sha...candidate_sha` 的已提交范围（实现代理必须 commit；未提交内容在
packet 里单列为 WARNING，不算候选）。verify 证据绑定 candidate_sha / dirty 指纹
/ config hash；组包时 candidate_sha 与 worktree HEAD 不一致直接拒绝
（-AllowStale 可越过但会标注 STALE）。summary 由实现代理写在 worktree 根
（不提交），verify 收集进任务包——实现代理不跨 worktree 边界写主 checkout。

e2e 检查组约定：Playwright spec 作为普通检查进 config checks，挂到需要行为
验收的 workflow class（模板见 config.example.json 的 e2e 组）。浏览器写
`channel: 'chrome'` 用本地系统 Chrome 兜底——镜像环境下 `playwright install`
常下不动 Chromium（quick-creative-V2 已验证）。需要应用在跑的 spec 用
playwright config 的 webServer 起停，别依赖手动 dev 进程（并发假阴性）。

## 后续方向（v1.0 之后，按需）

- 跨平台：引擎目前是 PowerShell 5.1 / Windows 专用；出现非 Windows 项目时
  评估移植成 python
- bootstrap 组件类型扩展：目前只有 python-venv / node（npm）；pnpm/yarn/
  go/docker 组件出现时按需加
