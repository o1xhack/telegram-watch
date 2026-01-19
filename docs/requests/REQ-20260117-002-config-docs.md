# REQ-20260117-002-config-docs

Status: Done
Owner: @you
Created: 2026-01-17

## Summary
Document and guide users through filling out `config.toml` so they can run `tgwatch once/run` without guesswork.

## Motivation
New users need clearer instructions for gathering Telegram API credentials, chat IDs, and local paths before the watcher can connect. Without explicit documentation they may be blocked on onboarding.

## Scope (MVP)
必须做：
- [ ] 解释 `telegram.api_id`, `telegram.api_hash`, `telegram.session_file`
- [ ] 说明 `target_chat_id`, `tracked_user_ids`, `control_chat_id` 的来源和格式
- [ ] 描述本地存储路径的推荐默认值与可写性要求

不做（明确排除项）：
- [ ] 实现自动化获取聊天 ID 的脚本

## Functional Requirements
- [ ] 输入/触发方式（用户怎么用）：阅读文档或 README 获取配置指导
- [ ] 输出/结果（会生成什么、发到哪里）：更新的文档提供字段说明、示例和操作步骤
- [ ] 数据要求（时间、引用、图片/文件等）：涵盖 API ID/hash、会话文件、目标/控制聊天 ID、跟踪用户 ID、本地路径配置

## Non-Functional Requirements
- [ ] Mac 本地可运行
- [ ] 免费方案
- [ ] 隐私/安全：不泄露 session/api_hash
- [ ] 性能/频率：例如每 2 小时汇总

## Acceptance Criteria (DoD)
- [x] 文档解释 `telegram.*`, `target.*`, `control.*`, `storage.*`, `reporting.*` 字段的来源、格式与默认值
- [x] README 指向详细配置指南
- [x] 配置指南提醒用户保持隐私并提供验证命令

## Implementation Notes (for Codex)
- 相关模块/文件：`README.md`, `docs/` onboarding guides
- 风险点：避免记录真实凭证，指导需强调隐私
- 需要更新的文档：主 README 或独立配置指南

## Plan
1. Audit existing README/config example to understand current guidance and missing pieces.
2. Draft a dedicated configuration section or doc covering credential acquisition, chat IDs, and local paths with safe defaults.
3. Cross-reference config fields to ensure completeness, then update request status when acceptance steps verified.

## What changed
- 新增 `docs/configuration.md`，逐字段讲解 API 凭证、聊天/用户 ID 获取方式与本地路径要求。
- 在 README 的配置步骤中链接到完整指南，帮助新用户快速发现文档。
