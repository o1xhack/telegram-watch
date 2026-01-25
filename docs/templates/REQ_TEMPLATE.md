# REQ-YYYYMMDD-###-slug
# 命名规则：`YYYYMMDD` 必须使用需求实际创建当天的日期，`###` 为当日递增编号。

Status: Draft
Owner: @you
Created: YYYY-MM-DD  # 与文件名中的日期一致

## Summary
一句话描述要做什么（非技术语言）。

## Release Impact
- 预计版本号：`x.y.z -> x.y.z`
- 预告 changelog 文案（英文）：`...`

## Motivation
为什么要做？解决什么痛点？

## Scope (MVP)
必须做：
- [ ] 
- [ ] 

不做（明确排除项）：
- [ ] 

## Functional Requirements
- [ ] 输入/触发方式（用户怎么用）
- [ ] 输出/结果（会生成什么、发到哪里）
- [ ] 数据要求（时间、引用、图片/文件等）

## Non-Functional Requirements
- [ ] Mac 本地可运行
- [ ] 免费方案
- [ ] 隐私/安全：不泄露 session/api_hash
- [ ] 性能/频率：例如每 2 小时汇总

## Acceptance Criteria (DoD)
- [ ] 通过 `python -m telegram_watch doctor --config config.toml`
- [ ] 通过 `python -m telegram_watch once --config config.toml --since 10m`
- [ ] 生成报告且图片可显示（相对路径正确）
- [ ] 控制对话指令可用（如 /last /since /export）

## Implementation Notes (for Codex)
- 相关模块/文件：
- 风险点：
- 需要更新的文档：
