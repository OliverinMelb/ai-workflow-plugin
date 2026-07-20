---
name: task-assign
description: 为 ai-workflow 任务的一个子任务分配 worktree 并启动实现子代理：建子任务 spec、开 worktree（自动 bootstrap 零安装就绪）、渲染子代理提示词、派发 implementer。当任务包已建好需要开始实现某个子任务时使用。
---

# task-assign：子任务 → worktree → 子代理

one subtask, one worktree 是硬约束（hook 强制）。默认串行处理；**可选并行**：若多个子任务的文件面互不相交（看 brief 的 Plan 段 boundary 列）且无依赖关系，可先逐个完成步骤 1-3，再在同一条消息里并行派发多个 implementer（worktree + hook 已保证隔离）。并行省时间但多花 token，按当下更缺哪个选。

## 步骤

1. 若子任务 spec 还不存在，先建：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/new_subtask.ps1" -TaskId <task-id> -Title "<短英文标题>" -Workflow <class>
   ```
   然后把 spec 填实：目标、**Files To Modify（精确路径清单）**、边界（允许/禁止触碰的文件）、验收标准（每条带验证命令+预期输出，禁占位语）。

2. 分配 worktree（自动注册 + bootstrap，完成后 worktree 零安装可跑全部检查）：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/assign_worktree.ps1" -TaskId <task-id> -SubtaskId <subtask-id> -Workflow <class>
   ```

3. 渲染子代理启动提示词（检查清单由 config 自动生成，不要手写）：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/render_subagent_prompt.ps1" -TaskId <task-id> -SubtaskId <subtask-id> -OutFile prompts\<subtask-id>.md
   ```

4. 用 Agent 工具派发：优先用项目 `.claude/agents/` 里的特化 implementer（如 implementer-backend），没有则用 plugin 的通用 `implementer`。提示词全文使用渲染产物。

5. 子代理返回后：**不信自查报告**，直接进入 /task-verify。它的 summary 写在
   worktree 根的 `subtask-summary.md`（不提交），由 verify 收集进任务包——实现
   代理不跨 worktree 边界回写主 checkout。

## 完成标准
- [ ] worktree 已注册进 workflow/state/worktree-registry.json
- [ ] 子代理拿到的是渲染产物（不是手写提示词）
