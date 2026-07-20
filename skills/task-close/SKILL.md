---
name: task-close
description: 关闭一个 ai-workflow 任务（闭环步骤，强制）：合并子任务分支、回写 summary、两层记忆分拣（全局/项目 lessons）、更新项目 wiki 与需求史、清理 worktree。任务验收通过准备收尾时使用；没走完本清单的任务不算完成。
---

# task-close：闭环（没有门禁的步骤必然被跳过——这就是门禁）

背景教训：曾有三个任务包 summary 全空，项目记忆层等于死亡。本清单每一项都要落盘验证。

## 清单（按序执行，缺一不可）

1. **合并**：合并前核对每个子任务 `.verify.md` 的 candidate_sha 等于待合分支 HEAD（不一致 = 验证后又改过，先重跑 /task-verify）。然后把子任务分支合回 task 分支/main（按用户约定）；合并后在主 checkout 重跑该任务涉及的检查矩阵确认无冲突破坏。

2. **summary.md 回写**：填 `workflow/tasks/<task-id>/summary.md`——交付了什么、验证证据（引用 .verify.md）、遗留 follow-ups。禁止留模板原文。

3. **两层记忆分拣**（判据：换一个项目还成立吗？）：
   - 全局教训 → 追加 `~/.claude/workflow-memory/lessons.md`（环境事实 → `environment.md`）；注意全局层条数上限（约 30 条，超了先合并淘汰）
   - 项目教训 → 追加项目 `workflow/context/lessons.md`
   - 没有新教训就明确写"无新教训"，不许静默跳过

4. **wiki/文档同步**：本次改动若触碰端点、payload、IPC、env、行为 → 更新 config.memory.pointers 指向的对应文档；需求史文档（如有）追加一行。

5. **清理**：`git worktree remove` 已合并的子任务 worktree、删除子任务分支；registry 里的条目保留（历史记录）。

6. **提交**：任务包产物（brief/summary/verify 证据）随代码一起提交。

7. **会话卫生**：close 完成后建议用户开新会话跑下一个任务——长会话每轮重复携带全部历史计费，且 prompt cache TTL 只有 5 分钟，间隔一长就是全量重读。

## 完成标准
- [ ] summary.md 非空且含验证证据引用
- [ ] 记忆分拣有明确结论（写了什么/为什么没写）
- [ ] 无残留 worktree（除非用户要求保留）
