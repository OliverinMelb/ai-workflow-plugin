---
name: task-verify
description: 对 ai-workflow 子任务做独立复验：在其 worktree 里重跑该 workflow class 的完整检查矩阵并产出证据文件，然后判定走 fast/full review lane。子任务实现完成后必须调用；永远不要接受子代理的自查报告作为验证结果。
---

# task-verify：独立复验 + 判定 review lane

原则：**验证必须由编排方重跑，证据必须落盘**。子代理说"测试全过"不算数。

## 步骤

1. 独立复验（从项目根运行；矩阵按 config 的 workflow class 展开）：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/verify_subtask.ps1" -TaskId <task-id> -SubtaskId <subtask-id>
   ```
   产出 `workflow/tasks/<task-id>/subtask-summaries/<subtask-id>.verify.md`，exit 0 = 全过。

2. FAIL 处理：读证据文件里的失败输出，把失败信息回给实现子代理修复（同一 worktree），修完重跑本步骤。**不要自己在主 checkout 里修**。

3. 全 PASS 后判 review lane（参照项目 workflow/checks/stop-rules.md，若有）：
   - **fast lane**：改动小、无契约面、检查全过 → 编排方自查 diff 即可合并
   - **full lane**：契约变更 / 多子任务 / 触碰 stop-rule 边缘 → 组装 reviewer packet 并派发 reviewer 子代理：
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_reviewer_packet.ps1" -TaskId <task-id>
     ```
     reviewer 用项目特化版或 plugin 通用 `reviewer` agent；它只验证不实现。

4. 向用户报告：overall 结果、证据文件路径、选择的 lane 和理由。

## 完成标准
- [ ] .verify.md 证据文件存在且是本次运行产出
- [ ] lane 判定及理由已明示
