# 更新日志

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> 条目按时间从新到旧排列，最新版本在最上方。每条变更都会标注对应的需求编号。

## 0.5.0 — 2026-02-03
- 支持多目标监控，可按目标群设置报告间隔，并配置控制群路由（REQ-20260202-001-multi-admin-monitoring）。
- 新增本地 GUI，用于配置多群组监控、控制群路由与上限（REQ-20260203-001-config-gui-design）。

## 0.3.0 — 2026-01-29
- 新增双账号桥接：由发送端账号推送控制群消息，使主账号恢复通知（REQ-20260129-002-bridge-implementation）。
- 双账号登录时补充主账号/发送账号提示，避免混淆（REQ-20260129-003-sender-login-prompt）。
- 双账号登录提示改为用户友好文本，并在终端明确区分主账号/发送账号（REQ-20260129-004-friendly-login-prompts）。

## 0.2.0 — 2026-01-25
- 增加可选的论坛 Topic（主题）路由，可将指定用户映射到控制群的对应 Topic，同时保留默认 General 主题的推送行为（REQ-20260125-002-topic-routing）。
- 修复控制群引用 blockquote 出现多余空行的问题（REQ-20260125-003-reply-blockquote-regression）。
- 刷新 README 的亮点与功能列表，补充 Topic 路由等能力说明（REQ-20260125-004-readme-refresh）。
- 将已完成的需求文档归档到 `docs/requests/Done/`，保持活跃需求列表简洁（REQ-20260125-005-archive-done-requests）。
- 修复心跳调度逻辑，使 run 模式下的 “Watcher is still running” 能按空闲间隔重复发送（REQ-20260125-006-heartbeat-repeat）。
- 在启用 Topic 路由时，按用户拆分 HTML 报告并发送到对应 Topic（REQ-20260125-007-topic-report-split）。
- 更新 README 安装 tag 与配置提示以匹配 v0.2.0（REQ-20260125-008-readme-release-tag）。

## 0.1.2 — 2026-01-24
- 修复 run 模式汇总循环未传递 activity tracker 与 Bark 标签的问题，恢复 Bark/控制群通知与 “Watcher is still running” 心跳流（REQ-20260124-024-run-notify-regression）。
- 新增异步回归测试，确保 run 汇总继续传递 tracker/bark 上下文（REQ-20260124-024-run-notify-regression）。

## 0.1.1 — 2026-01-24
- 引入发布管理流程：每个需求选择语义化版本号、更新 changelog，并在 README 中链接日志（REQ-20260124-023-versioning-log）。

## 0.1.0 — 2026-01-23
- 交付 telegram-watch MVP：基于 Telethon 的监听器，支持登录、用户筛选、SQLite 持久化、媒体归档与 HTML 报告推送到控制群（REQ-20260117-001-mvp-bootstrap）。
- 增加 `doctor`/`once`/`run` 三个 CLI 命令，FloodWait 处理、Bark 通知、保留清理，以及引用上下文抓取（REQ-20260117-001-mvp-bootstrap）。
- 发布详尽的配置指南（README + `docs/configuration.md`），覆盖 API 凭据、Chat ID、本地路径与隐私说明（REQ-20260117-002-config-docs）。
