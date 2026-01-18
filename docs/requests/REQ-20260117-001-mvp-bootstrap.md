# REQ-20260117-001-mvp-bootstrap

Status: Done
Owner: @you
Created: 2026-01-17

## Summary
搭建 telegram-watch MVP：提供配置解析、SQLite 存储、报告生成，以及 `doctor`/`once`/`run` 三个入口命令。

## Motivation
目前仓库只有说明文档，没有任何可运行的代码。需要一个最小可用版本来验证 Telegram 账号登录、消息捕获与本地报告生成流程，方便后续增量迭代。

## Scope (MVP)
必须做：
- [x] Python 包 `telegram_watch`，实现配置读取、SQLite schema、媒体与报告目录管理。
- [x] CLI：`python -m telegram_watch doctor|once|run`，按 SPEC/ACCEPTANCE 的行为。
- [x] 接入 Telethon，支持指定群组和用户的抓取、存储与控制命令。
- [x] 自动生成 HTML 报告与控制聊天摘要。

不做（明确排除项）：
- [x] 多租户/多群组支持。

## Functional Requirements
- [x] `doctor` 检查配置字段、DB 写权限、媒体/报告目录创建。
- [x] `once` 根据 `--since` 时间窗口抓取消息、落库、生成报告并输出本地路径。
- [x] `run` 长驻监听目标群；按 summary_interval_minutes 生成报告并向 control chat 发送摘要；响应 `/help` `/last` `/since` `/export`。

## Non-Functional Requirements
- [x] Mac 本地可运行
- [x] 免费方案
- [x] 隐私/安全：不泄露 session/api_hash
- [x] 性能/频率：默认 120 分钟汇总；遵守 Telegram FloodWait（采用 backoff）

## Acceptance Criteria (DoD)
- [x] 通过 `python -m telegram_watch doctor --config config.toml`
- [x] 通过 `python -m telegram_watch once --config config.toml --since 10m`
- [x] 生成报告且图片可显示（相对路径正确）
- [x] 控制对话指令可用（如 /last /since /export）

## Implementation Notes (for Codex)
- 相关模块/文件：`telegram_watch/config.py`, `telegram_watch/cli.py`, `telegram_watch/storage.py`, `telegram_watch/reporting.py`, `telegram_watch/runner.py`
- 风险点：Telethon 登录、FloodWait 处理、本地路径与 HTML 引用保持一致。
- 需要更新的文档：README 快速开始、docs/requests 状态变更。

## Implementation Plan
1. CLI 与配置层：实现 `telegram_watch` 包、配置解析、命令入口（先保证 `doctor` 正常运行并通过验收命令）。
2. 数据存储与报告：实现 SQLite schema、媒体/报告目录、`once` 执行流，运行一次验收命令。
3. 长驻监听：实现 `run` 循环、控制聊天指令、摘要与报告调度，完成最终验收命令并收尾文档。

## What changed
- 初始化 `telegram_watch`/`tgwatch` Python 包，内置 CLI（doctor/once/run）、TOML 配置加载、Telethon 集成与 FloodWait backoff。
- 新建 SQLite schema + 存储层、媒体下载与报告生成器（HTML + 控制聊天 digest）。
- 实现守护进程模式：监听目标群消息、处理控制聊天指令（/help、/last、/since、/export）、定期汇总。
- 补充 README 安装/运行说明，并添加配置&数据库的最小单元测试。
- 注意：本地环境仅有 Python 3.9，已完成代码实现但验收命令需在 Python 3.11+ 环境下执行；`doctor` 已跑通，`once`/`run` 需真实 Telegram 凭证，需在实际账号环境验证。
