# AI Workflow for Codex — Windows v1

这是 `ai-workflow` 的 Codex 原生 Windows 分支。它保留项目已有的
`workflow/config.json` 检查矩阵，同时将 Claude slash command 编排替换为
Codex skill、有限状态机、可复验的证据和显式隔离的 custom agents。

## 核心行为

- 状态机：`PLAN → EXECUTE → VERIFY → REVIEW → INTEGRATE → CLOSED`
- 失败进入 `FIX`；默认最多两轮，超限进入 `BLOCKED`
- `micro` 任务不创建任务包；workflow 不设置子代理数量上限
- 自动识别当前 checkout/worktree；并行写入代理必须显式分配独立 linked worktree
- `assign-writer` 验证并记录每个写入代理的 worktree、base SHA、owned paths 与集成顺序
- 验证绑定 Git HEAD、工作区指纹和配置哈希
- 任务开始前已有的脏文件不会被归因给当前任务
- 工作流自身的任务包和证据不会污染源码范围检查
- Windows Python 强制 UTF-8；`doctor` 动态检查代理与监听端口

## 目录

```text
.codex-plugin/plugin.json         Codex plugin manifest
skills/codex-workflow/            Skill、协议、配置说明和工作流引擎
codex-agents/                     Explorer、implementer、reviewer 示例
tests/test_workflow_cli.py        状态与证据闭环测试
```

## 安装

将仓库作为本地 Codex marketplace/plugin source 接入，或把
`.codex-plugin/` 与 `skills/codex-workflow/` 所在仓库添加到你的个人
marketplace。安装后的 skill 名称是 `$codex-workflow`。

如需使用示例 custom agents，把 `codex-agents/*.toml` 复制到：

```text
%USERPROFILE%\.codex\agents\
```

重新打开 Codex 会话后，在含有 `workflow/config.json` 的项目中输入：

```text
使用 $codex-workflow 完成这个任务
```

## 新项目自动初始化

在新 Git 项目根目录运行：

```powershell
workflow.ps1 init
```

也可以直接告诉 Codex：

```text
为当前仓库初始化 $codex-workflow，不修改业务代码。
```

`init` 会识别 Python、Node、Maven、Gradle 或通用仓库，生成保守的
`workflow/config.json`，随后自动执行 `doctor`。它不会读取 `.env` 的值，也不会覆盖
已有配置。先预览而不写入：

```powershell
workflow.ps1 init --dry-run
```

## 项目配置

现有 v1 配置可继续使用。建议增加：

```json
{
  "codex_workflow": {
    "version": 1,
    "default_tier": "small",
    "default_class": "app-change",
    "max_fix_loops": 2,
    "check_timeout_seconds": 900,
    "global_memory_dir": "C:/Users/<user>/.agents/workflow-memory"
  }
}
```

`default_class` 必须对应 `workflow_classes` 中的键。旧配置中的 `max_subagents`
仍可读取但会被忽略；并发数量由运行时决定。机器路径、代理端口和密钥
不得写死在公共配置中。

## 本地验证

```powershell
$python = "path\to\python.exe"
& $python -X utf8 -m unittest discover -s tests -v
& ".\skills\codex-workflow\scripts\workflow.ps1" doctor
```

生命周期测试覆盖：

- 新项目自动识别并初始化配置
- 已有配置拒绝覆盖
- 微任务跳过任务包
- 既有脏文件隔离
- 越界文件导致验证失败并进入 `FIX`
- 通过验证、review 和 close 后证据仍保持新鲜

## 与 Claude v1 的关系

本分支没有删除原有 `.claude-plugin/`、hooks、slash-command skills 或历史脚本。
它们不由 Codex workflow 调用，仅作为兼容内容和迁移参考。Codex 的入口以
`.codex-plugin/plugin.json` 和 `$codex-workflow` 为准。
