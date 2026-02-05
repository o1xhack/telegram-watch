# 更新日誌

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> 條目按時間由新到舊排列，最新版本在最上方。每條變更都會標註對應的需求編號。

## 1.0.0 — 2026-02-04
- 交付多目標監控與控制群路由，並提供本機 GUI 與控制群映射體驗優化（REQ-20260202-001-multi-admin-monitoring，REQ-20260203-001-config-gui-design，REQ-20260204-003-gui-control-mapping-ux）。
- 新增一鍵啟動腳本與 GUI 執行控制（run/once、背景日誌、Stop GUI），並修復 GUI 啟動崩潰（REQ-20260203-002-gui-launcher-and-runner，REQ-20260204-001-gui-launcher-loglevel-fix，REQ-20260204-002-gui-stop-button）。
- 強制 config_version = 1.0，按 target_chat_id + user_id 的 Topic 映射，並加入應用內遷移流程（REQ-20260204-004-topic-mapping-per-target，REQ-20260204-006-config-migration-flow）。
- 補齊遷移與預設命名相關測試，並更新文件說明（REQ-20260205-001-audit-tests-docs）。
- 簡化遷移流程，只保留 `config-old-0.1.toml` 備份（REQ-20260205-002-drop-config-sample）。
- 新增 run once 單一目標過濾（CLI/GUI 可選單一群組）（REQ-20260205-003-once-target-filter）。
- 將 `config-old-*.toml` 遷移備份加入 git 忽略（REQ-20260205-004-ignore-old-configs）。
- GUI 增加 run once 推送開關與日誌顯示上限（REQ-20260205-005-gui-once-push-toggle）。
- GUI 新增啟動前保護：缺少 session 時顯示醒目提示並禁用 Run/Once，`retention_days > 180` 改為介面確認，避免終端 y/n 卡住（REQ-20260205-006-gui-run-guards）。
- 優化 GUI retention 互動：Run daemon 保持可點擊，點擊後進入確認流程（勾選後確認按鈕才可用）再啟動長保留執行（REQ-20260205-007-gui-retention-click-confirm-flow）。
- GUI 新增 `Stop daemon` 控制，並修復 run 啟動後 retention 確認框不消失的問題，可直接在 Runner 面板管理 daemon 生命週期（REQ-20260205-008-gui-run-stop-and-confirm-dismiss）。

## 0.3.0 — 2026-01-29
- 新增雙帳號橋接：由發送端帳號推送控制群訊息，使主帳號恢復通知（REQ-20260129-002-bridge-implementation）。
- 雙帳號登入時補充主帳號/發送帳號提示，避免混淆（REQ-20260129-003-sender-login-prompt）。
- 雙帳號登入提示改為使用者友好文字，並在終端明確區分主帳號/發送帳號（REQ-20260129-004-friendly-login-prompts）。

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
