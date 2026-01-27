# 更新日誌

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> 條目按時間由新到舊排列，最新版本在最上方。每條變更都會標註對應的需求編號。

## 0.2.0 — 2026-01-25
- 新增可選的論壇 Topic（主題）路由，可將指定使用者映射到控制群的對應 Topic，同時保留預設 General 主題的推送行為（REQ-20260125-002-topic-routing）。
- 修復控制群引用 blockquote 出現多餘空行的問題（REQ-20260125-003-reply-blockquote-regression）。
- 刷新 README 的亮點與功能列表，補充 Topic 路由等能力說明（REQ-20260125-004-readme-refresh）。
- 將已完成的需求文件歸檔到 `docs/requests/Done/`，保持活躍需求清單簡潔（REQ-20260125-005-archive-done-requests）。
- 修復心跳排程，使 run 模式下的 “Watcher is still running” 能依空閒間隔重複送出（REQ-20260125-006-heartbeat-repeat）。
- 啟用 Topic 路由時，依使用者拆分 HTML 報告並送至對應 Topic（REQ-20260125-007-topic-report-split）。
- 更新 README 安裝 tag 與設定提示以符合 v0.2.0（REQ-20260125-008-readme-release-tag）。

## 0.1.2 — 2026-01-24
- 修復 run 模式彙整迴圈未傳遞 activity tracker 與 Bark 標籤，恢復 Bark/控制群通知與 “Watcher is still running” 心跳流（REQ-20260124-024-run-notify-regression）。
- 新增非同步回歸測試，確保 run 彙整仍會傳遞 tracker/bark 上下文（REQ-20260124-024-run-notify-regression）。

## 0.1.1 — 2026-01-24
- 引入發布管理流程：每個需求選擇語意化版本號、更新 changelog，並在 README 中連結日誌（REQ-20260124-023-versioning-log）。

## 0.1.0 — 2026-01-23
- 交付 telegram-watch MVP：基於 Telethon 的監看器，支援登入、使用者篩選、SQLite 持久化、媒體歸檔與 HTML 報告推送至控制群（REQ-20260117-001-mvp-bootstrap）。
- 新增 `doctor`/`once`/`run` 三個 CLI 命令，FloodWait 處理、Bark 通知、保留清理與引用上下文擷取（REQ-20260117-001-mvp-bootstrap）。
- 發佈完整設定指南（README + `docs/configuration.md`），涵蓋 API 憑證、Chat ID、本機路徑與隱私說明（REQ-20260117-002-config-docs）。
