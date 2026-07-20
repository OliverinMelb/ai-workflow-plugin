---
name: task-new
description: 按 ai-workflow 协议开始一个新任务：分级路由(trivial/small/standard)、创建任务包、填写 brief。当用户提出一个新的开发需求且项目有 workflow/config.json 时使用。trivial 级(单文件改动、文案、配置)不建包，直接做。
---

# task-new：任务分级 + 建任务包

## 第一步：分级路由（先判级，再决定流程重量）

**默认 small；升 standard 必须说明触发了哪条标准。**

- **trivial**：2-3 个文件以内的小改、文案、配置，无契约变更、无新依赖 → **不建任务包**，直接实现 + 跑该文件所属组件的检查，结束。
- **small**（默认档）：影响面清晰、无契约变更 → 建任务包（只需 brief + summary），在 task 分支直接做，跳过设计门。
- **standard**：仅当满足以下任一条才升级——①契约变更（API payload / endpoint / websocket / IPC / env 语义）；②确实需要多个子任务并行 worktree。流程：brief（单文件，含 Plan 段和 Design Gate Checklist 段）→ 子任务拆分。

判级拿不准时向用户报告你的判断和理由，倾向低一级（流程越重越贵）。

## 第二步：建包（small/standard）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/new_task.ps1" -Title "<英文短标题>" -Workflow <workflow-class> -NoWorktree
```

- Title 用短英文（生成的 task_id 有 MAX_PATH 风险，见全局环境记忆）。
- workflow-class 从项目 workflow/config.json 的 workflow_classes 里选。
- small 级加 `-NoWorktree` 后自己开 task 分支；standard 级由 task-assign 为每个子任务开 worktree。

## 第三步：填 brief.md（唯一任务文档）

覆盖模板占位内容，必须包含：Goal、Context（已知事实，引用两层记忆避免重新踩坑）、Deliverables、**可验收的 Acceptance Criteria**（每条都要能被命令或文件存在性验证）、Stop Conditions。small 级删除 Plan 和 Design Gate Checklist 两段。

standard 级填 brief 前先过**方案门**：需求存在设计空间时，一次性给出 2-3 个候选方案（各带取舍）和你的推荐，让用户**确认一次**（不要多轮追问、不要逐段确认），把选定方案和落选原因写进 brief 的 Options Considered 段；确实只有一种做法时写明"无设计空间"即可。然后在 brief 内继续填 **Plan 段**（子任务拆分表）并自查 **Design Gate Checklist 段**，全勾后才能拆子任务。不再单独建 spec.md / plan.md / design-review.md；仅当契约变更复杂到 brief 装不下时才另建 spec.md，且不派发独立评审子代理（checklist 自查即设计门）。

## 完成标准
- [ ] 分级判断已明示给用户
- [ ] small/standard：任务包目录存在且 brief 已填（非模板原文）
