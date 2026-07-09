---
name: workflow-init
description: 在一个新项目里初始化 ai-workflow 多代理工作流：脚手架 workflow/ 目录并引导填写 config.json。当用户说"给这个项目接入 workflow / 初始化工作流 / init workflow"时使用。已存在 workflow/config.json 的项目不要重复初始化。
---

# workflow-init：为当前项目脚手架 workflow 层

引擎脚本在 plugin 里，本 skill 只在项目里铺"数据"骨架。全程在**项目仓库根目录**操作。

## 步骤

1. 前置检查：项目必须是 git 仓库；若 `workflow/config.json` 已存在，停止并告知用户已初始化。
2. 脚手架目录（从 plugin scaffold 拷贝）：
   ```powershell
   New-Item -ItemType Directory -Force workflow\templates, workflow\checks, workflow\state, workflow\tasks, workflow\context, workflow\reports
   Copy-Item "${CLAUDE_PLUGIN_ROOT}/scaffold/templates/*" workflow\templates\
   Copy-Item "${CLAUDE_PLUGIN_ROOT}/scaffold/checks/*" workflow\checks\
   Copy-Item "${CLAUDE_PLUGIN_ROOT}/scaffold/state/worktree-registry.json" workflow\state\
   ```
3. 生成 `workflow/config.json`：以 `${CLAUDE_PLUGIN_ROOT}/scaffold/config.example.json` 为模板，但**每个值都必须按本项目实际情况重写**，不能照抄示例（示例来自 ai_helper 项目）。逐项调查后填写：
   - `project_name`、`memory.pointers`（本项目的 wiki/规则文档路径）
   - `components`：读项目目录结构确定组件（python-venv 组件填 probe_imports；node 组件填 probe_modules 和 install_env）
   - `checks` + `workflow_classes`：问用户或从 package.json/pyproject/CI 配置推断验证命令；**注意检查间的顺序依赖**（如 build-before-test）
   - `auto_check`：选一个最快的单文件检查（如 ruff）
   - `contract_touchpoints` / `env_consistency`：没有明确契约面时可先填空数组，后续补
4. 创建 `workflow/context/lessons.md`（空骨架，说明"闭环时追加"）和 `workflow/README.md`（一句话指向 plugin README）。
5. `git config core.longpaths true`（Windows worktree 长路径保护）。
6. 运行验证：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.ps1"
   ```
   bootstrap 必须跑通（幂等预备环境）。再开新会话时 SessionStart hook 应显示项目记忆横幅。
7. 提醒用户把项目的 CLAUDE.md 指向 workflow 协议和 config。

## 完成标准（缺一不可）
- [ ] workflow/config.json 存在且为本项目定制（非示例照抄）
- [ ] bootstrap.ps1 运行通过
- [ ] workflow/templates、state/worktree-registry.json 就位
