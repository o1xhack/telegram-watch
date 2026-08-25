"""Local GUI for editing tgwatch config."""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import webbrowser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import (
    ConfigError,
    MAX_CONTROL_GROUPS,
    MAX_TARGET_GROUPS,
    MAX_USERS_PER_TARGET,
    VALID_DISPLAY_TEMPLATES,
    load_config,
)
from .migration import migrate_config

try:  # pragma: no cover - Python 3.11+ always hits first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

logger = logging.getLogger(__name__)

KEEP_SECRET = "********"

_TIMEZONE_PRESET_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("UTC", "UTC"),
    ("China - Shanghai", "Asia/Shanghai"),
    ("China - Hong Kong", "Asia/Hong_Kong"),
    ("Japan - Tokyo", "Asia/Tokyo"),
    # Include a second Japan option when supported by the local tz database.
    ("Japan - Osaka (alias)", "Asia/Osaka"),
    ("Korea - Seoul", "Asia/Seoul"),
    ("US - Eastern (New York)", "America/New_York"),
    ("US - Central (Chicago)", "America/Chicago"),
    ("US - Pacific (Los Angeles)", "America/Los_Angeles"),
    ("Europe - UK (London)", "Europe/London"),
    ("Europe - Central (Paris)", "Europe/Paris"),
    ("Europe - Central (Berlin)", "Europe/Berlin"),
    ("Europe - Central (Madrid)", "Europe/Madrid"),
    ("Europe - Central (Rome)", "Europe/Rome"),
)


def _build_timezone_presets() -> list[dict[str, str]]:
    presets: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, value in _TIMEZONE_PRESET_CANDIDATES:
        if value in seen:
            continue
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            continue
        presets.append({"label": label, "value": value})
        seen.add(value)
    return presets

_TIME_FORMAT_UNITS: dict[str, list[dict[str, str]]] = {
    "year": [
        {"label": "4-digit (2026)", "value": "%Y"},
        {"label": "2-digit (26)", "value": "%y"},
    ],
    "month": [
        {"label": "Zero-padded (01)", "value": "%m"},
        {"label": "No padding (1)", "value": "%-m"},
        {"label": "Abbreviated (Jan)", "value": "%b"},
        {"label": "Full name (January)", "value": "%B"},
    ],
    "day": [
        {"label": "Zero-padded (01)", "value": "%d"},
        {"label": "No padding (1)", "value": "%-d"},
    ],
    "hour": [
        {"label": "24h zero-padded (14)", "value": "%H"},
        {"label": "12h zero-padded (02)", "value": "%I"},
        {"label": "24h no padding (2)", "value": "%-H"},
    ],
    "minute": [
        {"label": "Zero-padded (05)", "value": "%M"},
    ],
    "second": [
        {"label": "Zero-padded (09)", "value": "%S"},
    ],
    "timezone": [
        {"label": "Abbreviation (CST)", "value": "%Z"},
        {"label": "Offset (+0800)", "value": "%z"},
    ],
    "date_separator": [
        {"label": "Dot (.)", "value": "."},
        {"label": "Dash (-)", "value": "-"},
        {"label": "Slash (/)", "value": "/"},
    ],
}

_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>tgwatch GUI</title>
    <link rel="stylesheet" href="/app.css?v=2" />
  </head>
  <body>
    <div id="app"></div>
    <script src="/app.js?v=2"></script>
  </body>
</html>
"""

_CSS = """
:root {
  color-scheme: light;
  --bg: #f7f3ef;
  --panel: #ffffff;
  --ink: #1e1b16;
  --muted: #6b6158;
  --accent: #1b6f5a;
  --accent-2: #b4682d;
  --danger: #b83c3c;
  --border: #e4dcd2;
  --shadow: 0 20px 45px rgba(42, 32, 20, 0.12);
  --radius: 18px;
  --mono: "SF Mono", "JetBrains Mono", "Fira Code", monospace;
  --sans: "Avenir Next", "Avenir", "Helvetica Neue", "Segoe UI", sans-serif;
  --log-lines: 12;
  --log-lines-collapsed: 2;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: var(--sans);
  background: radial-gradient(circle at 20% 20%, #fef7ef 0%, #f6efe7 40%, #efe6db 100%);
  color: var(--ink);
}

@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

#app {
  max-width: 1100px;
  margin: 48px auto 80px;
  padding: 0 24px;
}

.header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 32px;
  animation: rise 0.6s ease both;
}

.header h1 {
  font-size: 28px;
  margin: 0;
  letter-spacing: -0.02em;
}

.header p {
  margin: 4px 0 0;
  color: var(--muted);
}

.hero {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  font-weight: 600;
}

.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.button {
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 12px 18px;
  border-radius: 999px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(27, 111, 90, 0.25);
}

.button.secondary {
  background: #fff;
  color: var(--accent);
  border: 1px solid var(--border);
  box-shadow: none;
}

.button.danger {
  background: var(--danger);
  color: #fff;
}

.button[disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}

.section {
  background: var(--panel);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  animation: rise 0.6s ease both;
}

.section h2 {
  margin: 0 0 12px;
  font-size: 20px;
}

.section p {
  margin: 0 0 16px;
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink);
  text-transform: none;
  letter-spacing: 0;
}

.checkbox input {
  margin: 0;
}

.field input,
.field select {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  font-size: 14px;
}

.field small {
  color: var(--muted);
}

.card-list {
  display: grid;
  gap: 16px;
}

.card {
  border-radius: 16px;
  border: 1px solid var(--border);
  padding: 16px;
  background: #fffaf4;
}

.card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card header h3 {
  margin: 0;
  font-size: 16px;
}

.inline-actions {
  display: flex;
  gap: 8px;
}

.list {
  display: grid;
  gap: 10px;
}

.list-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  align-items: center;
}

.list-row input {
  width: 100%;
}

.list-row .button {
  padding: 8px 12px;
  font-size: 12px;
}

.notice {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef1e9;
  color: var(--accent-2);
  border: 1px dashed rgba(180, 104, 45, 0.3);
  margin-bottom: 16px;
}

.notice .checkbox {
  margin-top: 10px;
}

.error {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fdecea;
  color: var(--danger);
  border: 1px solid rgba(184, 60, 60, 0.2);
  margin-bottom: 16px;
}

.lock-banner {
  padding: 18px;
  border-radius: 16px;
  border: 2px solid var(--danger);
  background: #fdecea;
  color: var(--danger);
  font-weight: 700;
  font-size: 20px;
  margin-bottom: 20px;
}

.lock-banner p {
  margin: 8px 0 0;
  font-size: 14px;
  font-weight: 500;
  color: #7f1d1d;
}

.warning-banner {
  padding: 18px;
  border-radius: 16px;
  border: 2px solid var(--accent-2);
  background: #fef1e9;
  color: var(--accent-2);
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 20px;
}

.warning-banner p {
  margin: 8px 0 0;
  font-size: 14px;
  font-weight: 500;
  color: #7a4a1a;
}

.status {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
}

.log-box {
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.4;
  background: #1b1916;
  color: #f5f1ec;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid rgba(27, 25, 22, 0.2);
  height: calc(var(--log-lines) * 1.4em + 24px);
  overflow-y: auto;
  white-space: pre-wrap;
}

.log-box.empty {
  background: #f3eee8;
  color: var(--muted);
  height: calc(var(--log-lines-collapsed) * 1.4em + 24px);
}

.runner-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.runner-footnote {
  margin-top: 12px;
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .list-row {
    grid-template-columns: 1fr;
  }
  .inline-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
"""

_JS = """
// --- i18n ---
const _i18n = {
  en: {
    badge: "Local Configurator",
    title: "tgwatch GUI",
    subtitle: "Configure multi-group monitoring and control routing without editing files.",
    saveConfig: "Save Config",
    reload: "Reload",
    runner: "Runner",
    runnerDesc: "Start a one-shot fetch or keep the watcher running in the background. Closing the browser will not stop a running daemon.",
    onceWindow: "Once Window",
    onceWindowHelp: "Examples: 10m, 2h, 2026-02-01T10:30Z",
    onceTarget: "Once Target",
    allTargets: "All targets",
    onceTargetHelp: 'Choose a single target, or leave as "All targets".',
    oncePush: "Once Push",
    pushToControl: "Push to control chat",
    oncePushHelp: "Default is off; enable to push the once report.",
    daemonStatus: "Daemon Status",
    archiveRuntimeStatus: "Full Archive Status",
    archiveStatusActive: "Capturing",
    archiveStatusDisabled: "Disabled",
    archiveStatusStopped: "Daemon not running",
    archiveStatusDegraded: "Disabled: archive health degraded",
    archiveStatusUnverified: "Unavailable: restart daemon to verify",
    archiveStatusRestartRequired: "Restart daemon to apply configuration",
    runOnce: "Run once",
    runDaemon: "Run daemon",
    stopDaemon: "Stop daemon",
    stopGUI: "Stop GUI",
    guiFootnote: "Stopping the GUI will not stop a running daemon.",
    runLogs: "Run logs (live)",
    onceLogs: "Once logs",
    waitingLogs: "Waiting for logs...",
    noActiveRun: "No active run.",
    noRecentOnce: "No recent once run.",
    checkingStatus: "Checking status...",
    running: "Running",
    runningPid: "Running (pid {pid})",
    stalledPid: "Stalled (pid {pid})",
    archiveDisabledPid: "Running; archive disabled (pid {pid})",
    archiveUnverifiedPid: "Running; archive unverified (pid {pid})",
    notRunning: "Not running",
    runnerUnavailable: "Runner status unavailable.",
    sessionNotFound: "Session file not found. Please complete one terminal login first.",
    confirmRetention: "Please confirm retention_days={days} before starting run daemon.",
    failStartDaemon: "Failed to start run daemon: {msg}",
    failStopDaemon: "Failed to stop run daemon: {msg}",
    invalidSince: "Please enter a valid since window (e.g. 2h).",
    failStartOnce: "Failed to start once run: {msg}",
    guiStopped: "GUI stopped.",
    guiStoppedTitle: "GUI stopped",
    failStopGui: "Failed to stop GUI: {msg}",
    migrationFailed: "Migration failed: {msg}",
    sessionBannerTitle: "Session required before running",
    sessionBannerDesc: "Run this once in terminal to login:",
    retentionRequired: "Retention confirmation required:",
    retentionDesc: "retention_days is set to {days}. Confirm before starting run daemon.",
    retentionConfirmLabel: "I understand long retention may consume significant disk space.",
    confirmStart: "Confirm & Start Run",
    cancel: "Cancel",
    configLocked: "Configuration locked",
    configLockedDesc: "This config is outdated or invalid. Rewrite config.toml and reload the GUI.",
    migrateConfig: "Migrate Config",
    unableToLoad: "Unable to load GUI",
    loading: "Loading...",
    validationIssues: "Validation issues",
    telegramCreds: "Telegram Credentials",
    telegramCredsDesc: "Local-only. API hash is masked and kept on disk.",
    apiId: "API ID",
    apiHash: "API Hash",
    sessionFile: "Session File",
    enableSender: "Enable sender account (optional)",
    senderSession: "Sender Session File",
    targets: "Targets",
    targetsDesc: "Each target represents one monitored group or channel.",
    group: "Group {n}",
    addUser: "Add User",
    removeGroup: "Remove Group",
    name: "Name",
    targetChatId: "Target Chat ID",
    reportInterval: "Report Interval (min)",
    controlGroup: "Control Group",
    userId: "User ID",
    aliasOptional: "Alias (optional)",
    remove: "Remove",
    addGroup: "Add Group",
    controlGroups: "Control Groups",
    controlGroupsDesc: "Where summaries and commands are delivered.",
    control: "Control {n}",
    key: "Key",
    controlChatId: "Control Chat ID",
    forumMode: "Forum Mode",
    topicRouting: "Topic Routing",
    skipHtmlReport: "Skip HTML Report",
    mappedTargets: "Mapped targets: ",
    noneYet: "none yet",
    topicId: "Topic ID",
    addTopicMapping: "Add Topic Mapping",
    addControlGroup: "Add Control Group",
    storageReporting: "Storage & Reporting",
    dbPath: "DB Path",
    mediaDir: "Media Dir",
    fullArchiveSection: "Full Message Archive",
    fullArchiveHelp: "Optional local context archive. Disabled by default; when enabled it silently stores group context in separate SQLite shards.",
    fullArchiveEnabled: "Enable Full Archive",
    fullArchiveRoot: "Archive Root Dir",
    fullArchiveSourceChat: "Source Chat ID",
    fullArchiveScope: "Capture Scope",
    fullArchiveScopeWhole: "Whole Group",
    fullArchiveScopeTopics: "Selected Topics",
    fullArchiveTopicIds: "Topic IDs",
    fullArchiveTopicIdsHelp: "Comma-separated topic IDs. Required only when Full Archive is enabled and capture scope is Selected Topics.",
    fullArchiveShardPolicy: "Shard Policy",
    fullArchiveMaxMessages: "Max Messages / Shard",
    fullArchiveMaxSize: "Max Shard Size (MB)",
    fullArchiveBackfillLimit: "Backfill Limit",
    fullArchiveSourceBannerTitle: "Full archive source is not a configured target",
    fullArchiveSourceBannerDesc: "The archive can still run, but it may not recover context around tracked messages because this source chat is not one of the monitored target chats.",
    reportsDir: "Reports Dir",
    defaultSummaryInterval: "Default Summary Interval",
    timezone: "Timezone",
    timezoneHelp: "Saved as IANA timezone string (for example Asia/Shanghai).",
    retentionDays: "Retention Days",
    displayNotifications: "Display & Notifications",
    showIds: "Show IDs",
    barkKey: "Bark Key",
    optional: "optional",
    timeFormat: "Time Format",
    timeFormatCustom: "Time Format (custom)",
    switchToBuilder: "Switch to builder",
    editRawStrftime: "Edit as raw strftime string",
    dontDisplay: "Don\\u0027t display",
    year: "Year",
    month: "Month",
    day: "Day",
    dateSep: "Date Separator",
    hour: "Hour",
    minute: "Minute",
    second: "Second",
    unknownUser: "Unknown user ({id})",
    noAvailableUsers: "No available users",
    selectUser: "Select user",
    customTimezone: "Custom (keep existing) - {tz}",
    limitsText: "Limits: {targets} groups, {users} users per group, {controls} control groups.",
    select: "Select",
    realtimeBannerTitle: "Realtime mode (EXPERIMENTAL) is active",
    realtimeBannerDesc: "Messages are forwarded instantly. Rate limits: {perMin}/min, {perHr}/hr, {perDay}/day. Account restrictions are possible — monitor for FloodWait errors.",
    cloudSyncBannerTitle: "Your data files are inside a cloud sync directory",
    cloudSyncBannerDesc: "Cloud sync services can occasionally lock SQLite files, which may cause transient errors. WAL mode is enabled by default since v1.6.0 to mitigate this, but for maximum reliability consider moving data files outside the sync folder.",
    realtimeSectionTitle: "Realtime Push Mode — EXPERIMENTAL",
    realtimeSectionDesc: "Forward messages instantly instead of on a scheduled interval. Use with caution.",
    pushMode: "Push Mode",
    pushModeInterval: "Interval",
    pushModeRealtime: "Realtime (Experimental)",
    intervalModeStatus: "Using scheduled interval mode. Messages are batched into periodic summary reports.",
    realtimeWarningTitle: "Warning: You are enabling Realtime Push Mode",
    realtimeWarnExperimental: "This feature is <strong>experimental</strong> and behavior may change in future releases.",
    realtimeWarnRestrictions: "Sending messages too frequently risks <strong>Telegram account restrictions</strong> (temporary or permanent bans).",
    realtimeWarnRateProtection: "7-layer rate protection is enabled by default, but aggressive limits can still trigger FloodWait errors.",
    realtimeWarnDefaults: "Default limits: <strong>20 msgs/min</strong>, <strong>200 msgs/hr</strong>, <strong>1000 msgs/day</strong>.",
    realtimeWarnCircuitBreaker: "The circuit breaker will automatically pause sending if too many FloodWait errors are received.",
    realtimeWarnResponsibility: "You are responsible for monitoring logs and adjusting limits as needed.",
    realtimeRiskConfirm: "I understand the risks and want to enable realtime mode",
    confirmRealtimeMode: "Confirm Realtime Mode",
    rateLimitMinute: "Rate Limit / Minute",
    rateLimitMinuteHelp: "Max messages per minute (1\u201330)",
    rateLimitHour: "Rate Limit / Hour",
    rateLimitHourHelp: "Max messages per hour",
    rateLimitDay: "Rate Limit / Day",
    rateLimitDayHelp: "Max messages per day",
    minIntervalSec: "Min Interval (sec)",
    minIntervalSecHelp: "Minimum seconds between sends",
    mediaExtraDelay: "Media Extra Delay (sec)",
    mediaExtraDelayHelp: "Extra delay for media messages",
    warmupMinutes: "Warmup Minutes",
    warmupMinutesHelp: "Gradual ramp-up period after start",
    warmupRate: "Warmup Rate",
    warmupRateHelp: "Max msgs/min during warmup",
    rtReportInterval: "Report Interval (min)",
    rtReportIntervalHelp: "How often to send periodic summary reports",
    language: "Language",
    languageAuto: "Auto (detect from browser)",
    languageZh: "Chinese",
    languageEn: "English",
    heartbeatInterval: "Heartbeat Interval (hours)",
    heartbeatIntervalHelp: "Send 'still running' message after this many hours of inactivity. 0 = disabled, max 24.",
    checkUpdates: "Check for Updates",
    checkUpdatesHelp: "Automatically check GitHub for new releases every 24 hours.",
    messageTemplateSection: "Message Template",
    messageTemplateHelp: "Choose the layout for individual messages forwarded to the control chat. Applies in both interval mode (per-message forwards after each digest) and realtime mode (instant push). ID display, time format, and language preferences still apply on top of the chosen template.",
    template: "Template",
    templateNormal: "Normal",
    templateMinimal: "Minimal",
    templateNormalDesc: "Sender, time, and content on separate lines (default).",
    templateMinimalDesc: "Sender and content on one line; time on the second line.",
    templatePreview: "Preview",
    messageFieldsSection: "Message Fields",
    languageSection: "Language",
    notificationsSection: "Notifications",
  },
  zh: {
    badge: "本地配置器",
    title: "TG 监控面板",
    subtitle: "配置多群组监控和消息路由，无需手动编辑配置文件。",
    saveConfig: "保存配置",
    reload: "重新加载",
    runner: "运行控制",
    runnerDesc: "执行单次抓取或在后台持续运行监控。关闭浏览器不会停止正在运行的守护进程。",
    onceWindow: "时间窗口",
    onceWindowHelp: "示例：10m、2h、2026-02-01T10:30Z",
    onceTarget: "目标群组",
    allTargets: "全部目标",
    onceTargetHelp: "选择单个目标，或保持「全部目标」。",
    oncePush: "推送报告",
    pushToControl: "推送到控制群",
    oncePushHelp: "默认关闭；启用后将推送单次运行的报告。",
    daemonStatus: "守护进程状态",
    archiveRuntimeStatus: "全量归档实际状态",
    archiveStatusActive: "正在归档",
    archiveStatusDisabled: "未启用",
    archiveStatusStopped: "守护进程未运行",
    archiveStatusDegraded: "已停用：归档健康检查异常",
    archiveStatusUnverified: "无法确认：需重启守护进程",
    archiveStatusRestartRequired: "需重启守护进程以应用配置",
    runOnce: "单次运行",
    runDaemon: "启动守护进程",
    stopDaemon: "停止守护进程",
    stopGUI: "停止面板",
    guiFootnote: "停止面板不会停止正在运行的守护进程。",
    runLogs: "运行日志（实时）",
    onceLogs: "单次运行日志",
    waitingLogs: "等待日志...",
    noActiveRun: "当前没有运行中的任务。",
    noRecentOnce: "没有最近的单次运行记录。",
    checkingStatus: "正在检查状态...",
    running: "运行中",
    runningPid: "运行中 (pid {pid})",
    stalledPid: "已卡住 (pid {pid})",
    archiveDisabledPid: "运行中，但归档已停用 (pid {pid})",
    archiveUnverifiedPid: "运行中，但归档状态未确认 (pid {pid})",
    notRunning: "未运行",
    runnerUnavailable: "无法获取运行状态。",
    sessionNotFound: "未找到会话文件。请先在终端完成一次登录。",
    confirmRetention: "请在启动守护进程前确认 retention_days={days}。",
    failStartDaemon: "启动守护进程失败：{msg}",
    failStopDaemon: "停止守护进程失败：{msg}",
    invalidSince: "请输入有效的时间窗口（例如 2h）。",
    failStartOnce: "启动单次运行失败：{msg}",
    guiStopped: "面板已停止。",
    guiStoppedTitle: "面板已停止",
    failStopGui: "停止面板失败：{msg}",
    migrationFailed: "迁移失败：{msg}",
    sessionBannerTitle: "运行前需要先登录会话",
    sessionBannerDesc: "请在终端运行一次以完成登录：",
    retentionRequired: "需要确认数据保留设置：",
    retentionDesc: "retention_days 已设为 {days}，请在启动守护进程前确认。",
    retentionConfirmLabel: "我了解较长的保留时间可能会占用大量磁盘空间。",
    confirmStart: "确认并启动",
    cancel: "取消",
    configLocked: "配置已锁定",
    configLockedDesc: "当前配置已过期或无效，请重写 config.toml 并重新加载面板。",
    migrateConfig: "迁移配置",
    unableToLoad: "无法加载面板",
    loading: "加载中...",
    validationIssues: "验证问题",
    telegramCreds: "Telegram 凭证",
    telegramCredsDesc: "仅保存在本地。API Hash 已脱敏并保存在磁盘上。",
    apiId: "API ID",
    apiHash: "API Hash",
    sessionFile: "会话文件",
    enableSender: "启用发送账号（可选）",
    senderSession: "发送账号会话文件",
    targets: "监控目标",
    targetsDesc: "每个目标代表一个被监控的群组或频道。",
    group: "群组 {n}",
    addUser: "添加用户",
    removeGroup: "移除群组",
    name: "名称",
    targetChatId: "目标群组 ID",
    reportInterval: "汇报间隔（分钟）",
    controlGroup: "控制群组",
    userId: "用户 ID",
    aliasOptional: "别名（可选）",
    remove: "移除",
    addGroup: "添加群组",
    controlGroups: "控制群组",
    controlGroupsDesc: "汇总和命令发送到此处。",
    control: "控制 {n}",
    key: "标识",
    controlChatId: "控制群组 ID",
    forumMode: "论坛模式",
    topicRouting: "话题路由",
    skipHtmlReport: "跳过 HTML 报告",
    mappedTargets: "已映射目标：",
    noneYet: "暂无",
    topicId: "话题 ID",
    addTopicMapping: "添加话题映射",
    addControlGroup: "添加控制群组",
    storageReporting: "存储与报告",
    dbPath: "数据库路径",
    mediaDir: "媒体目录",
    fullArchiveSection: "全量消息归档",
    fullArchiveHelp: "可选的本地上下文归档。默认关闭；启用后会静默保存群组上下文到独立 SQLite 分片。",
    fullArchiveEnabled: "启用全量归档",
    fullArchiveRoot: "归档根目录",
    fullArchiveSourceChat: "来源群组 ID",
    fullArchiveScope: "采集范围",
    fullArchiveScopeWhole: "整个群组",
    fullArchiveScopeTopics: "指定话题",
    fullArchiveTopicIds: "话题 ID",
    fullArchiveTopicIdsHelp: "多个话题 ID 用逗号分隔。仅在启用全量归档且采集范围为指定话题时必填。",
    fullArchiveShardPolicy: "分片策略",
    fullArchiveMaxMessages: "每个分片最大消息数",
    fullArchiveMaxSize: "每个分片最大大小（MB）",
    fullArchiveBackfillLimit: "回填上限",
    fullArchiveSourceBannerTitle: "全量归档来源不是当前监控目标",
    fullArchiveSourceBannerDesc: "归档仍可运行，但这个来源群组不是当前 targets 中的监控群组，可能无法恢复 tracked 消息上下文。",
    reportsDir: "报告目录",
    defaultSummaryInterval: "默认汇总间隔",
    timezone: "时区",
    timezoneHelp: "保存为 IANA 时区字符串（例如 Asia/Shanghai）。",
    retentionDays: "数据保留天数",
    displayNotifications: "显示与通知",
    showIds: "显示 ID",
    barkKey: "Bark Key",
    optional: "可选",
    timeFormat: "时间格式",
    timeFormatCustom: "时间格式（自定义）",
    switchToBuilder: "切换到构建器",
    editRawStrftime: "编辑原始 strftime 格式",
    dontDisplay: "不显示",
    year: "年",
    month: "月",
    day: "日",
    dateSep: "日期分隔符",
    hour: "时",
    minute: "分",
    second: "秒",
    unknownUser: "未知用户 ({id})",
    noAvailableUsers: "没有可用用户",
    selectUser: "选择用户",
    customTimezone: "自定义（保持现有）- {tz}",
    limitsText: "限制：{targets} 个群组，每组 {users} 个用户，{controls} 个控制群组。",
    select: "选择",
    realtimeBannerTitle: "实时推送模式（实验性）已启用",
    realtimeBannerDesc: "消息将即时转发。速率限制：{perMin}/分钟、{perHr}/小时、{perDay}/天。可能触发账号限制——请关注 FloodWait 错误。",
    cloudSyncBannerTitle: "数据文件位于云同步目录中",
    cloudSyncBannerDesc: "云同步服务可能会偶尔锁定 SQLite 文件，从而导致临时错误。自 v1.6.0 起默认启用 WAL 模式以缓解此问题，但为获得最佳可靠性，建议将数据文件移出同步文件夹。",
    realtimeSectionTitle: "实时推送模式 — 实验性",
    realtimeSectionDesc: "即时转发消息，而非按计划周期汇总。请谨慎使用。",
    pushMode: "推送模式",
    pushModeInterval: "定时汇总",
    pushModeRealtime: "实时推送（实验性）",
    intervalModeStatus: "当前使用定时汇总模式。消息将按周期批量汇总后推送。",
    realtimeWarningTitle: "警告：您正在启用实时推送模式",
    realtimeWarnExperimental: "此功能为<strong>实验性</strong>，后续版本中行为可能发生变化。",
    realtimeWarnRestrictions: "发送消息过于频繁可能导致 <strong>Telegram 账号被限制</strong>（临时或永久封禁）。",
    realtimeWarnRateProtection: "默认启用 7 层速率保护，但过于激进的限制仍可能触发 FloodWait 错误。",
    realtimeWarnDefaults: "默认限制：<strong>20 条/分钟</strong>、<strong>200 条/小时</strong>、<strong>1000 条/天</strong>。",
    realtimeWarnCircuitBreaker: "熔断器会在收到过多 FloodWait 错误时自动暂停发送。",
    realtimeWarnResponsibility: "您有责任监控日志并根据需要调整限制。",
    realtimeRiskConfirm: "我了解相关风险并希望启用实时推送模式",
    confirmRealtimeMode: "确认启用实时模式",
    rateLimitMinute: "每分钟速率限制",
    rateLimitMinuteHelp: "每分钟最大消息数（1–30）",
    rateLimitHour: "每小时速率限制",
    rateLimitHourHelp: "每小时最大消息数",
    rateLimitDay: "每日速率限制",
    rateLimitDayHelp: "每天最大消息数",
    minIntervalSec: "最小发送间隔（秒）",
    minIntervalSecHelp: "两次发送之间的最短间隔",
    mediaExtraDelay: "媒体额外延迟（秒）",
    mediaExtraDelayHelp: "媒体消息的额外延迟",
    warmupMinutes: "预热时长（分钟）",
    warmupMinutesHelp: "启动后的逐步提速阶段",
    warmupRate: "预热速率",
    warmupRateHelp: "预热期间每分钟最大消息数",
    rtReportInterval: "汇报间隔（分钟）",
    rtReportIntervalHelp: "定期发送汇总报告的频率",
    language: "语言",
    languageAuto: "自动（跟随浏览器）",
    languageZh: "中文",
    languageEn: "English",
    heartbeatInterval: "心跳间隔（小时）",
    heartbeatIntervalHelp: "空闲超过此时间后发送「仍在运行」消息。0 表示关闭，最大 24。",
    checkUpdates: "自动检查更新",
    checkUpdatesHelp: "每 24 小时自动检查 GitHub 是否有新版本。",
    messageTemplateSection: "消息模板",
    messageTemplateHelp: "选择转发到控制群的单条消息版面样式。interval 模式（每次汇总后逐条转发）和 realtime 模式（即时推送）都生效。ID 显示、时间格式、语言设置会叠加在所选模板之上。",
    template: "模板",
    templateNormal: "标准",
    templateMinimal: "极简",
    templateNormalDesc: "发送者、时间、正文分行显示（默认）。",
    templateMinimalDesc: "发送者与正文同行显示，时间置于第二行。",
    templatePreview: "预览",
    messageFieldsSection: "消息字段",
    languageSection: "语言",
    notificationsSection: "通知",
  }
};

// Timezone label translations
const _tzLabels = {
  "UTC": "协调世界时 UTC",
  "China - Shanghai": "中国 - 上海",
  "China - Hong Kong": "中国 - 香港",
  "Japan - Tokyo": "日本 - 东京",
  "Japan - Osaka (alias)": "日本 - 大阪",
  "Korea - Seoul": "韩国 - 首尔",
  "US - Eastern (New York)": "美国 - 东部 (纽约)",
  "US - Central (Chicago)": "美国 - 中部 (芝加哥)",
  "US - Pacific (Los Angeles)": "美国 - 太平洋 (洛杉矶)",
  "Europe - UK (London)": "欧洲 - 英国 (伦敦)",
  "Europe - Central (Paris)": "欧洲 - 巴黎",
  "Europe - Central (Berlin)": "欧洲 - 柏林",
  "Europe - Central (Madrid)": "欧洲 - 马德里",
  "Europe - Central (Rome)": "欧洲 - 罗马",
};

// Time format unit label translations
const _tfLabels = {
  "4-digit (2026)": "四位数 (2026)",
  "2-digit (26)": "两位数 (26)",
  "Zero-padded (01)": "补零 (01)",
  "No padding (1)": "不补零 (1)",
  "Abbreviated (Jan)": "缩写 (Jan)",
  "Full name (January)": "全称 (January)",
  "Zero-padded (05)": "补零 (05)",
  "Zero-padded (09)": "补零 (09)",
  "24h zero-padded (14)": "24小时制补零 (14)",
  "12h zero-padded (02)": "12小时制补零 (02)",
  "24h no padding (2)": "24小时制不补零 (2)",
  "Abbreviation (CST)": "缩写 (CST)",
  "Offset (+0800)": "偏移量 (+0800)",
  "Dot (.)": "点 (.)",
  "Dash (-)": "短横线 (-)",
  "Slash (/)": "斜杠 (/)",
};

let _lang = localStorage.getItem("tgwatch_lang")
  || ((navigator.language || "en").startsWith("zh") ? "zh" : "en");

function _getStrings() { return _i18n[_lang] || _i18n.en; }

function t(key) {
  return _getStrings()[key] || _i18n.en[key] || key;
}

function tf(key, params) {
  let s = t(key);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.split("{" + k + "}").join(String(v));
    }
  }
  return s;
}

function tLabel(label) {
  if (_lang !== "zh") return label;
  return _tzLabels[label] || _tfLabels[label] || label;
}

const state = {
  data: null,
  errors: [],
  status: "",
  runner: null,
  runnerMessage: "",
  runnerSince: "2h",
  runnerTarget: "",
  runnerPush: false,
  runnerRetentionConfirmed: false,
  runnerRetentionPrompt: false,
  runnerLoading: false,
  locked: false,
  lockMessage: "",
  migrationStatus: "",
  timeFormatParts: null,
  timeFormatCustom: false,
  realtimeConfirmed: false
};
const runnerDefaults = {
  running: false,
  pid: null,
  full_archive: { configured: false, runtime_enabled: false, status: "disabled" },
  run_log: "",
  once_log: "",
  status: "",
  session_ready: true,
  requires_retention_confirm: false,
  retention_days: 30
};
const keepSecret = "********";
const LOG_MAX_LINES = 200;

const limitText = (limits) => tf("limitsText", {targets: limits.maxTargets, users: limits.maxUsersPerTarget, controls: limits.maxControlGroups});

const blankTarget = () => ({
  name: "",
  target_chat_id: "",
  summary_interval_minutes: "",
  control_group: "",
  tracked_users: [{ id: "", alias: "" }]
});

const blankControlGroup = () => ({
  key: "",
  control_chat_id: "",
  is_forum: false,
  topic_routing_enabled: false,
  skip_html_report: false,
  topic_target_map: [{ user_key: "", target_chat_id: "", user_id: "", topic_id: "" }]
});

const buildTargetUsers = (targets) => {
  const users = [];
  targets.forEach((target, tIdx) => {
    const name = target.name || `group-${tIdx + 1}`;
    const targetChatId = String(target.target_chat_id || "").trim();
    if (!targetChatId) return;
    (target.tracked_users || []).forEach((user) => {
      const id = String(user.id || "").trim();
      if (!id) return;
      const alias = String(user.alias || "").trim();
      const label = `${name} - ${id}${alias ? ` (${alias})` : ""}`;
      const key = `${targetChatId}|${id}`;
      users.push({ key, user_id: id, target_chat_id: targetChatId, label, targetName: name });
    });
  });
  return users;
};

const entryKey = (entry) => {
  if (!entry) return "";
  const key = String(entry.user_key || "").trim();
  if (key) return key;
  const targetChatId = String(entry.target_chat_id || "").trim();
  const userId = String(entry.user_id || "").trim();
  if (targetChatId && userId) return `${targetChatId}|${userId}`;
  return "";
};

const collectSelectedUsers = (controlGroups) => {
  const selected = new Set();
  controlGroups.forEach((group) => {
    if (!group.topic_routing_enabled) return;
    (group.topic_target_map || []).forEach((entry) => {
      const value = entryKey(entry);
      if (value) selected.add(value);
    });
  });
  return selected;
};

const mapTargetsToControl = (targets, controlGroups, key) => {
  if (controlGroups.length === 1) {
    return targets.map((target, idx) => target.name || `group-${idx + 1}`);
  }
  return targets
    .filter((target) => String(target.control_group || "") === String(key || ""))
    .map((target, idx) => target.name || `group-${idx + 1}`);
};

const buildUserOptions = (targetUsers, selectedUsers, currentValue) => {
  const available = new Set(selectedUsers);
  if (currentValue) {
    available.delete(currentValue);
  }
  const options = [];
  const seen = new Set();
  targetUsers.forEach((user) => {
    if (available.has(user.key)) return;
    const label = user.label;
    const value = user.key;
    if (seen.has(value)) return;
    seen.add(value);
    options.push(`<option value="${value}">${label}</option>`);
  });
  if (currentValue && !targetUsers.some((user) => user.key === currentValue)) {
    options.unshift(`<option value="${currentValue}">${tf("unknownUser", {id: currentValue})}</option>`);
  }
  if (!options.length) {
    options.push(`<option value="">${t("noAvailableUsers")}</option>`);
  } else {
    options.unshift(`<option value="">${t("selectUser")}</option>`);
  }
  return options.join("");
};

const buildTimezoneOptions = (presets, currentValue) => {
  const selected = String(currentValue || "UTC").trim() || "UTC";
  const options = [];
  const seen = new Set();
  (presets || []).forEach((entry) => {
    if (!entry || !entry.value) return;
    const value = String(entry.value);
    const label = String(entry.label || entry.value);
    if (seen.has(value)) return;
    seen.add(value);
    options.push(
      `<option value="${value}" ${value === selected ? "selected" : ""}>${tLabel(label)} (${value})</option>`
    );
  });
  if (!seen.has(selected)) {
    options.unshift(
      `<option value="${selected}" selected>${tf("customTimezone", {tz: selected})}</option>`
    );
  }
  if (!options.length) {
    options.push(`<option value="UTC" ${selected === "UTC" ? "selected" : ""}>UTC (UTC)</option>`);
  }
  return options.join("");
};

// --- Time Format Builder helpers ---

const _TF_KNOWN_CODES = {
  year: ["%Y", "%y"],
  month: ["%m", "%-m", "%b", "%B"],
  day: ["%d", "%-d"],
  hour: ["%H", "%I", "%-H"],
  minute: ["%M"],
  second: ["%S"],
};
const _TF_DATE_SEPS = [".", "-", "/"];
const _TF_TZ_CODES = ["%Z", "%z"];

function parseTimeFormat(fmt) {
  if (!fmt || typeof fmt !== "string") return null;
  let s = fmt.trim();
  let tz = "";
  for (const code of _TF_TZ_CODES) {
    const suffix = " (" + code + ")";
    if (s.endsWith(suffix)) {
      tz = code;
      s = s.slice(0, -suffix.length);
      break;
    }
  }
  // Split into date part and time part at the space boundary.
  // Heuristic: time part starts with a known hour code.
  let datePart = "";
  let timePart = "";
  const spaceIdx = s.indexOf(" ");
  if (spaceIdx === -1) {
    // Single segment — decide if it is date or time.
    if (_TF_KNOWN_CODES.hour.some((c) => s.startsWith(c))) {
      timePart = s;
    } else {
      datePart = s;
    }
  } else {
    datePart = s.slice(0, spaceIdx);
    timePart = s.slice(spaceIdx + 1);
  }

  // Parse date
  let year = "", month = "", day = "", dateSep = ".";
  if (datePart) {
    let sep = "";
    for (const candidate of _TF_DATE_SEPS) {
      if (datePart.includes(candidate)) { sep = candidate; break; }
    }
    dateSep = sep || ".";
    const dateCodes = sep ? datePart.split(sep) : [datePart];
    // Identify each code
    const identified = [];
    for (const code of dateCodes) {
      if (!code) continue;
      let found = false;
      for (const [unit, codes] of Object.entries(_TF_KNOWN_CODES)) {
        if (["year", "month", "day"].includes(unit) && codes.includes(code)) {
          identified.push({ unit, code });
          found = true;
          break;
        }
      }
      if (!found) return null; // unrecognised code
    }
    for (const item of identified) {
      if (item.unit === "year") year = item.code;
      else if (item.unit === "month") month = item.code;
      else if (item.unit === "day") day = item.code;
    }
  }

  // Parse time
  let hour = "", minute = "", second = "";
  if (timePart) {
    const timeCodes = timePart.split(":");
    const tIdentified = [];
    for (const code of timeCodes) {
      if (!code) continue;
      let found = false;
      for (const [unit, codes] of Object.entries(_TF_KNOWN_CODES)) {
        if (["hour", "minute", "second"].includes(unit) && codes.includes(code)) {
          tIdentified.push({ unit, code });
          found = true;
          break;
        }
      }
      if (!found) return null;
    }
    for (const item of tIdentified) {
      if (item.unit === "hour") hour = item.code;
      else if (item.unit === "minute") minute = item.code;
      else if (item.unit === "second") second = item.code;
    }
  }

  return { year, month, day, dateSep, hour, minute, second, timezone: tz };
}

function composeTimeFormat(parts) {
  const dateCodes = [parts.year, parts.month, parts.day].filter(Boolean);
  const timeCodes = [parts.hour, parts.minute, parts.second].filter(Boolean);
  let result = "";
  if (dateCodes.length) {
    result = dateCodes.join(parts.dateSep || ".");
  }
  if (timeCodes.length) {
    if (result) result += " ";
    result += timeCodes.join(":");
  }
  if (parts.timezone) {
    if (result) result += " ";
    result += "(" + parts.timezone + ")";
  }
  return result || "%Y.%m.%d %H:%M:%S (%Z)";
}

function buildTimeFormatDropdown(unitName, presets, currentValue, fieldId) {
  const options = ['<option value="">' + t("dontDisplay") + '</option>'];
  (presets || []).forEach((entry) => {
    const sel = entry.value === currentValue ? "selected" : "";
    options.push('<option value="' + entry.value + '" ' + sel + '>' + tLabel(entry.label) + "</option>");
  });
  return '<select id="' + fieldId + '" data-tf-unit="' + unitName + '">' + options.join("") + "</select>";
}

function buildTemplatePreview(template, showIds) {
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const sender = showIds ? "Alice (123456)" : "Alice";
  const reply = showIds ? "Bob (789012)" : "Bob";
  const time = "2026.01.24 15:30:45 (UTC+8)";
  const msg = "MSG 999";
  const body = "Hello world";
  const replyText = "Are you coming tonight?";
  const boxCSS = "font-family: var(--mono, ui-monospace, monospace); font-size: 13px; padding: 12px; border-radius: 6px; border: 1px solid var(--border, #ddd); background: var(--code-bg, #fafafa); line-height: 1.6; margin-top: 12px;";
  const quoteCSS = "border-left: 3px solid var(--muted, #bbb); padding-left: 8px; margin: 4px 0; color: var(--muted, #666);";
  let html;
  if (template === "minimal") {
    html = '<strong>' + esc(sender) + '</strong>: ' + esc(body)
         + '<br>Time: ' + esc(time) + ' \u2014 ' + esc(msg)
         + '<div style="' + quoteCSS + '">\u21a9 Reply to ' + esc(reply) + ' at ' + esc(time) + '</div>'
         + '<div style="' + quoteCSS + '">' + esc(replyText) + '</div>';
  } else {
    html = '<strong>' + esc(sender) + '</strong>'
         + '<br>Time: ' + esc(time) + ' \u2014 ' + esc(msg)
         + '<br><strong>Content:</strong> ' + esc(body)
         + '<div style="' + quoteCSS + '">\u21a9 Reply to ' + esc(reply) + ' at ' + esc(time) + '</div>'
         + '<div style="' + quoteCSS + '">' + esc(replyText) + '</div>';
  }
  return '<div style="' + boxCSS + '">' + html + '</div>';
}

function timeFormatPreview(parts) {
  const sample = {
    "%Y": "2026", "%y": "26",
    "%m": "01", "%-m": "1", "%b": "Jan", "%B": "January",
    "%d": "05", "%-d": "5",
    "%H": "14", "%I": "02", "%-H": "2",
    "%M": "05", "%S": "09",
    "%Z": "CST", "%z": "+0800"
  };
  const fmt = composeTimeFormat(parts);
  let result = fmt;
  // Replace longest codes first to avoid partial matches (e.g. %-m before %m).
  const codes = Object.keys(sample).sort((a, b) => b.length - a.length);
  for (const code of codes) {
    result = result.split(code).join(sample[code]);
  }
  return result;
}

const runnerStatusText = (runner) => {
  if (!runner) return t("checkingStatus");
  if (runner.running) {
    if (runner.stalled) {
      return runner.pid ? tf("stalledPid", {pid: runner.pid}) : t("stalledPid");
    }
    if (runner.full_archive && runner.full_archive.configured) {
      if (runner.full_archive.status === "degraded" || runner.full_archive.status === "restart_required") {
        return runner.pid ? tf("archiveDisabledPid", {pid: runner.pid}) : t("archiveStatusDegraded");
      }
      if (runner.full_archive.status === "unverified") {
        return runner.pid ? tf("archiveUnverifiedPid", {pid: runner.pid}) : t("archiveStatusUnverified");
      }
    }
    return runner.pid ? tf("runningPid", {pid: runner.pid}) : t("running");
  }
  return t("notRunning");
};

const fullArchiveStatusText = (runner) => {
  const archive = runner && runner.full_archive;
  if (!archive) return t("archiveStatusDisabled");
  const labels = {
    active: "archiveStatusActive",
    disabled: "archiveStatusDisabled",
    stopped: "archiveStatusStopped",
    degraded: "archiveStatusDegraded",
    unverified: "archiveStatusUnverified",
    restart_required: "archiveStatusRestartRequired"
  };
  return t(labels[archive.status] || "archiveStatusUnverified");
};

const runnerMessageText = () => {
  if (state.runner && state.runner.status) return state.runner.status;
  if (state.runnerMessage) return state.runnerMessage;
  return "";
};

const trimLogLines = (text) => {
  if (!text) return "";
  const lines = text.split("\\n");
  if (lines.length <= LOG_MAX_LINES) return text;
  return lines.slice(lines.length - LOG_MAX_LINES).join("\\n");
};

function updateRunnerUI() {
  const runner = state.runner || runnerDefaults;
  const statusEl = document.getElementById("runner-status");
  if (!statusEl) return;
  statusEl.textContent = runnerStatusText(runner);
  const archiveStatusEl = document.getElementById("full-archive-status");
  if (archiveStatusEl) {
    archiveStatusEl.textContent = fullArchiveStatusText(runner);
  }

  const runLogEl = document.getElementById("run-log");
  if (runLogEl) {
    const runLogText = runner.running ? trimLogLines(runner.run_log || "") : "";
    if (runner.running && runLogText) {
      runLogEl.textContent = runLogText;
      runLogEl.classList.remove("empty");
    } else if (runner.running) {
      runLogEl.textContent = t("waitingLogs");
      runLogEl.classList.add("empty");
    } else {
      runLogEl.textContent = t("noActiveRun");
      runLogEl.classList.add("empty");
    }
  }

  const onceLogEl = document.getElementById("once-log");
  if (onceLogEl) {
    const onceLogText = trimLogLines(runner.once_log || "");
    if (onceLogText) {
      onceLogEl.textContent = onceLogText;
      onceLogEl.classList.remove("empty");
    } else {
      onceLogEl.textContent = t("noRecentOnce");
      onceLogEl.classList.add("empty");
    }
  }

  const messageEl = document.getElementById("runner-message");
  const message = runnerMessageText();
  if (messageEl) {
    if (message) {
      messageEl.textContent = message;
      messageEl.style.display = "block";
    } else {
      messageEl.textContent = "";
      messageEl.style.display = "none";
    }
  }

  const runButton = document.querySelector('[data-action="run-daemon"]');
  if (runButton) {
    const sessionReady = Boolean(runner.session_ready);
    runButton.disabled = Boolean(runner.running || !sessionReady);
  }
  const stopButton = document.querySelector('[data-action="run-daemon-stop"]');
  if (stopButton) {
    stopButton.disabled = !Boolean(runner.running);
  }
  const onceButton = document.querySelector('[data-action="run-once"]');
  if (onceButton) {
    onceButton.disabled = !Boolean(runner.session_ready);
  }
  const retentionConfirmButton = document.querySelector('[data-action="run-daemon-confirm"]');
  if (retentionConfirmButton) {
    retentionConfirmButton.disabled = !Boolean(state.runnerRetentionConfirmed);
  }
  const retentionCheckbox = document.getElementById("run-retention-confirm");
  if (retentionCheckbox) {
    retentionCheckbox.checked = Boolean(state.runnerRetentionConfirmed);
  }
}

function applyLockState() {
  const locked = Boolean(state.locked);
  const banner = document.getElementById("lock-banner");
  if (banner) {
    banner.style.display = locked ? "block" : "none";
  }
  document.querySelectorAll("#app input, #app select, #app button, #app textarea").forEach((el) => {
    if (el.dataset.allowLocked) return;
    el.disabled = locked;
  });
}

async function loadRunnerStatus() {
  if (state.runnerLoading) return;
  state.runnerLoading = true;
  try {
    const res = await fetch("/api/runner/status");
    const payload = await res.json();
    state.runner = payload;
    if (!payload.requires_retention_confirm) {
      state.runnerRetentionConfirmed = false;
      state.runnerRetentionPrompt = false;
    }
    if (payload.running) {
      state.runnerRetentionConfirmed = false;
      state.runnerRetentionPrompt = false;
    }
    updateRunnerUI();
  } catch (err) {
    state.runnerMessage = t("runnerUnavailable");
    updateRunnerUI();
  } finally {
    state.runnerLoading = false;
  }
}

async function startRun() {
  const runner = state.runner || runnerDefaults;
  if (!runner.session_ready) {
    state.runnerMessage = t("sessionNotFound");
    updateRunnerUI();
    return;
  }
  if (runner.requires_retention_confirm) {
    if (!state.runnerRetentionPrompt) {
      state.runnerRetentionPrompt = true;
      state.runnerRetentionConfirmed = false;
      state.runnerMessage = "";
      render();
      updateRunnerUI();
      return;
    }
    if (!state.runnerRetentionConfirmed) {
      state.runnerMessage = tf("confirmRetention", {days: runner.retention_days});
      updateRunnerUI();
      return;
    }
  }
  await startRunConfirmed();
}

async function startRunConfirmed() {
  const runner = state.runner || runnerDefaults;
  if (runner.requires_retention_confirm && !state.runnerRetentionConfirmed) {
    return;
  }
  try {
    state.runnerMessage = "";
    updateRunnerUI();
    const res = await fetch("/api/runner/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_retention: state.runnerRetentionConfirmed })
    });
    const payload = await res.json();
    state.runnerMessage = payload.status || "";
    if (payload.ok) {
      state.runnerRetentionPrompt = false;
      state.runnerRetentionConfirmed = false;
      render();
    }
    await loadRunnerStatus();
    updateRunnerUI();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.runnerMessage = tf("failStartDaemon", {msg: message});
    updateRunnerUI();
  }
}

async function stopRun() {
  try {
    state.runnerMessage = "";
    updateRunnerUI();
    const res = await fetch("/api/runner/stop", { method: "POST" });
    const payload = await res.json();
    state.runnerMessage = payload.status || "";
    await loadRunnerStatus();
    updateRunnerUI();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.runnerMessage = tf("failStopDaemon", {msg: message});
    updateRunnerUI();
  }
}

async function startOnce() {
  const sinceInput = document.getElementById("once-since");
  const targetInput = document.getElementById("once-target");
  const pushInput = document.getElementById("once-push");
  const since = sinceInput ? sinceInput.value.trim() : "";
  const target = targetInput ? targetInput.value.trim() : state.runnerTarget;
  const push = pushInput ? pushInput.checked : state.runnerPush;
  if (!since) {
    state.runnerMessage = t("invalidSince");
    updateRunnerUI();
    return;
  }
  try {
    state.runnerMessage = "";
    updateRunnerUI();
    const res = await fetch("/api/runner/once", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ since, target, push })
    });
    const payload = await res.json();
    state.runnerMessage = payload.status || "";
    await loadRunnerStatus();
    updateRunnerUI();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.runnerMessage = tf("failStartOnce", {msg: message});
    updateRunnerUI();
  }
}

function startRunnerPolling() {
  loadRunnerStatus();
  window.setInterval(loadRunnerStatus, 2000);
}

async function stopGui() {
  try {
    const res = await fetch("/api/gui/stop", { method: "POST" });
    const payload = await res.json();
    const app = document.getElementById("app");
    const message = payload && payload.status ? payload.status : t("guiStopped");
    app.innerHTML = `<div class="section"><h2>${t("guiStoppedTitle")}</h2><p>${message}</p></div>`;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.status = tf("failStopGui", {msg: message});
    render();
  }
}

async function migrateConfig() {
  try {
    const res = await fetch("/api/config/migrate", { method: "POST" });
    const payload = await res.json();
    state.migrationStatus = payload.status || "";
    await loadConfig();
    render();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.migrationStatus = tf("migrationFailed", {msg: message});
    render();
  }
}

function setByPath(obj, path, value) {
  const parts = path.split(".");
  let cursor = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    cursor = cursor[key];
  }
  cursor[parts[parts.length - 1]] = value;
}

function render() {
  const app = document.getElementById("app");
  if (!state.data) {
    const errorBlock = state.errors.length
      ? `<div class="error"><strong>${t("unableToLoad")}</strong><ul>${state.errors
          .map((e) => `<li>${e}</li>`)
          .join("")}</ul></div>`
      : "";
    app.innerHTML = `<div class="section"><h2>${t("loading")}</h2>${errorBlock}</div>`;
    return;
  }
  const data = state.data;
  const limits = data.limits;
  const targets = data.targets;
  const controlGroups = data.control_groups;
  const targetUsers = buildTargetUsers(targets);
  const selectedUsers = collectSelectedUsers(controlGroups);
  const timezonePresets = data.reporting_timezone_presets || [];
  const selectedOnceTarget = state.runnerTarget || "";
  const oncePushChecked = state.runnerPush;

  const errorBlock = state.errors.length
    ? `<div class="error"><strong>${t("validationIssues")}</strong><ul>${state.errors.map(e => `<li>${e}</li>`).join("")}</ul></div>`
    : "";

  const noticeParts = [];
  if (state.status) noticeParts.push(state.status);
  if (state.migrationStatus) noticeParts.push(state.migrationStatus);
  const statusBlock = noticeParts.length ? `<div class="notice">${noticeParts.join("<br />")}</div>` : "";
  const lockBanner = state.locked
    ? `<div class="lock-banner" id="lock-banner">
        ${t("configLocked")}
        <p>${state.lockMessage || t("configLockedDesc")}</p>
        <div style="margin-top:12px;">
          <button class="button danger" data-action="migrate-config" data-allow-locked="true">${t("migrateConfig")}</button>
        </div>
      </div>`
    : "";

  const controlOptions = controlGroups
    .map((group, idx) => `<option value="${group.key}">${group.key || `control-${idx + 1}`}</option>`)
    .join("");
  const defaultControlLabel = controlGroups.length === 1
    ? `default (${controlGroups[0].key || "control-1"})`
    : t("select");

  const runner = state.runner || runnerDefaults;
  const runnerMessage = runnerMessageText();
  const runLog = runner.running ? runner.run_log : "";
  const onceLog = runner.once_log || "";
  const sessionBanner = !runner.session_ready
    ? `<div class="lock-banner" style="margin-bottom:16px;">
        ${t("sessionBannerTitle")}
        <p>${t("sessionBannerDesc")} <code>python -m tgwatch run --config config.toml</code></p>
      </div>`
    : "";
  const retentionNotice = runner.requires_retention_confirm && state.runnerRetentionPrompt
    ? `<div class="notice">
        <strong>${t("retentionRequired")}</strong>
        ${tf("retentionDesc", {days: runner.retention_days})}
        <label class="checkbox">
          <input type="checkbox" id="run-retention-confirm" ${state.runnerRetentionConfirmed ? "checked" : ""} />
          ${t("retentionConfirmLabel")}
        </label>
        <div class="actions" style="margin-top:10px;">
          <button class="button secondary" data-action="run-daemon-confirm" ${state.runnerRetentionConfirmed ? "" : "disabled"}>${t("confirmStart")}</button>
          <button class="button secondary" data-action="run-daemon-cancel">${t("cancel")}</button>
        </div>
      </div>`
    : "";
  const realtimeBanner = data.realtime && data.realtime.push_mode === "realtime" && state.realtimeConfirmed
    ? `<div class="warning-banner">
        \\u26A0\\uFE0F ${t("realtimeBannerTitle")}
        <p>${tf("realtimeBannerDesc", {perMin: data.realtime.rate_limit_per_minute, perHr: data.realtime.rate_limit_per_hour, perDay: data.realtime.rate_limit_per_day})}</p>
      </div>`
    : "";
  const cloudSyncBanner = data.cloud_sync_warning
    ? `<div class="warning-banner">
        \\u26A0\\uFE0F ${t("cloudSyncBannerTitle")} (${data.cloud_sync_warning})
        <p>${t("cloudSyncBannerDesc")}</p>
      </div>`
    : "";
  const fullArchiveSourceBanner = data.full_archive_source_warning
    ? `<div class="warning-banner">
        \\u26A0\\uFE0F ${t("fullArchiveSourceBannerTitle")}
        <p>${t("fullArchiveSourceBannerDesc")}</p>
      </div>`
    : "";

  app.innerHTML = `
    <div class="header">
      <div class="hero">
        <span class="badge">${t("badge")}</span>
        <h1>${t("title")}</h1>
        <p>${t("subtitle")}</p>
        <div class="status">${limitText(limits)}</div>
      </div>
      <div class="actions">
        <button class="button" data-action="save">${t("saveConfig")}</button>
        <button class="button secondary" data-action="reload" data-allow-locked="true">${t("reload")}</button>
        <button class="button secondary" data-action="toggle-lang" data-allow-locked="true">${_lang === "zh" ? "EN" : "中文"}</button>
      </div>
    </div>
    ${cloudSyncBanner}
    ${fullArchiveSourceBanner}
    ${statusBlock}
    ${errorBlock}
    ${lockBanner}

    <section class="section" id="runner-section">
      <h2>${t("runner")}</h2>
      <p>${t("runnerDesc")}</p>
      ${sessionBanner}
      ${retentionNotice}
      ${realtimeBanner}
      <div class="runner-grid">
        <div class="field">
          <label>${t("onceWindow")}</label>
          <input id="once-since" value="${state.runnerSince}" placeholder="2h" />
          <small>${t("onceWindowHelp")}</small>
        </div>
        <div class="field">
          <label>${t("onceTarget")}</label>
          <select id="once-target">
            ${(() => {
              const options = [];
              options.push(
                `<option value="" ${selectedOnceTarget === "" ? "selected" : ""}>${t("allTargets")}</option>`
              );
              targets.forEach((target, idx) => {
                const label = target.name || `group-${idx + 1}`;
                const value = String(target.target_chat_id || "").trim();
                if (value) {
                  options.push(
                    `<option value="${value}" ${value === selectedOnceTarget ? "selected" : ""}>${label} (${value})</option>`
                  );
                } else {
                  options.push(
                    `<option value="${label}" ${label === selectedOnceTarget ? "selected" : ""}>${label} (name)</option>`
                  );
                }
              });
              return options.join("");
            })()}
          </select>
          <small>${t("onceTargetHelp")}</small>
        </div>
        <div class="field">
          <label>${t("oncePush")}</label>
          <label class="checkbox">
            <input type="checkbox" id="once-push" ${oncePushChecked ? "checked" : ""} />
            ${t("pushToControl")}
          </label>
          <small>${t("oncePushHelp")}</small>
        </div>
        <div class="field">
          <label>${t("daemonStatus")}</label>
          <div class="status" id="runner-status">${runnerStatusText(runner)}</div>
        </div>
        <div class="field">
          <label>${t("archiveRuntimeStatus")}</label>
          <div class="status" id="full-archive-status">${fullArchiveStatusText(runner)}</div>
        </div>
      </div>
      <div class="actions" style="margin-top:16px;">
        <button class="button" data-action="run-once">${t("runOnce")}</button>
        <button class="button secondary" data-action="run-daemon">${t("runDaemon")}</button>
        <button class="button secondary" data-action="run-daemon-stop" disabled>${t("stopDaemon")}</button>
        <button class="button danger" data-action="stop-gui" data-allow-locked="true">${t("stopGUI")}</button>
      </div>
      <div class="runner-footnote">${t("guiFootnote")}</div>
      <div class="notice" id="runner-message" style="${runnerMessage ? "" : "display:none;"}">${runnerMessage}</div>
      <div class="grid" style="margin-top:16px;">
        <div>
          <div class="status">${t("runLogs")}</div>
          <pre class="log-box ${runner.running && runLog ? "" : "empty"}" id="run-log">${runner.running ? (runLog || t("waitingLogs")) : t("noActiveRun")}</pre>
        </div>
        <div>
          <div class="status">${t("onceLogs")}</div>
          <pre class="log-box ${onceLog ? "" : "empty"}" id="once-log">${onceLog || t("noRecentOnce")}</pre>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>${t("telegramCreds")}</h2>
      <p>${t("telegramCredsDesc")}</p>
      <div class="grid">
        <div class="field">
          <label>${t("apiId")}</label>
          <input data-field="telegram.api_id" value="${data.telegram.api_id}" placeholder="123456" />
        </div>
        <div class="field">
          <label>${t("apiHash")}</label>
          <input type="password" data-field="telegram.api_hash" value="${data.telegram.api_hash}" placeholder="${keepSecret}" />
        </div>
        <div class="field">
          <label>${t("sessionFile")}</label>
          <input data-field="telegram.session_file" value="${data.telegram.session_file}" placeholder="data/tgwatch.session" />
        </div>
      </div>
      <div class="field" style="margin-top:16px;">
        <label><input type="checkbox" data-field="sender.enabled" ${data.sender.enabled ? "checked" : ""}/> ${t("enableSender")}</label>
      </div>
      ${data.sender.enabled ? `
      <div class="grid" style="margin-top:12px;">
        <div class="field">
          <label>${t("senderSession")}</label>
          <input data-field="sender.session_file" value="${data.sender.session_file}" placeholder="data/tgwatch_sender.session" />
        </div>
      </div>` : ""}
    </section>

    <section class="section">
      <h2>${t("targets")}</h2>
      <p>${t("targetsDesc")}</p>
      <div class="card-list">
        ${targets.map((target, idx) => `
        <div class="card">
          <header>
            <h3>${tf("group", {n: idx + 1})}</h3>
            <div class="inline-actions">
              <button class="button secondary" data-action="add-user" data-target-index="${idx}" ${target.tracked_users.length >= limits.maxUsersPerTarget ? "disabled" : ""}>${t("addUser")}</button>
              <button class="button danger" data-action="remove-target" data-target-index="${idx}">${t("removeGroup")}</button>
            </div>
          </header>
          <div class="grid">
            <div class="field">
              <label>${t("name")}</label>
              <input data-field="targets.${idx}.name" value="${target.name}" placeholder="group-${idx + 1}" />
            </div>
            <div class="field">
              <label>${t("targetChatId")}</label>
              <input data-field="targets.${idx}.target_chat_id" value="${target.target_chat_id}" placeholder="-100..." />
            </div>
            <div class="field">
              <label>${t("reportInterval")}</label>
              <input data-field="targets.${idx}.summary_interval_minutes" value="${target.summary_interval_minutes}" placeholder="${t("optional")}" />
            </div>
            <div class="field">
              <label>${t("controlGroup")}</label>
              <select data-field="targets.${idx}.control_group">
                <option value="">${defaultControlLabel}</option>
                ${controlOptions}
              </select>
            </div>
          </div>
          <div class="list" style="margin-top:16px;">
            ${target.tracked_users.map((user, uidx) => `
            <div class="list-row">
              <input data-field="targets.${idx}.tracked_users.${uidx}.id" value="${user.id}" placeholder="${t("userId")}" />
              <input data-field="targets.${idx}.tracked_users.${uidx}.alias" value="${user.alias}" placeholder="${t("aliasOptional")}" />
              <button class="button secondary" data-action="remove-user" data-target-index="${idx}" data-user-index="${uidx}">${t("remove")}</button>
            </div>`).join("")}
          </div>
        </div>`).join("")}
      </div>
      <div style="margin-top:16px;">
        <button class="button secondary" data-action="add-target" ${targets.length >= limits.maxTargets ? "disabled" : ""}>${t("addGroup")}</button>
      </div>
    </section>

    <section class="section">
      <h2>${t("controlGroups")}</h2>
      <p>${t("controlGroupsDesc")}</p>
      <div class="card-list">
        ${controlGroups.map((group, idx) => `
        <div class="card">
          <header>
            <h3>${tf("control", {n: idx + 1})}</h3>
            <div class="inline-actions">
              <button class="button danger" data-action="remove-control" data-control-index="${idx}">${t("remove")}</button>
            </div>
          </header>
          <div class="grid">
            <div class="field">
              <label>${t("key")}</label>
              <input data-field="control_groups.${idx}.key" value="${group.key}" placeholder="main" />
            </div>
            <div class="field">
              <label>${t("controlChatId")}</label>
              <input data-field="control_groups.${idx}.control_chat_id" value="${group.control_chat_id}" placeholder="-100..." />
            </div>
            <div class="field">
              <label>${t("forumMode")}</label>
              <select data-field="control_groups.${idx}.is_forum">
                <option value="false" ${group.is_forum ? "" : "selected"}>false</option>
                <option value="true" ${group.is_forum ? "selected" : ""}>true</option>
              </select>
            </div>
            <div class="field">
              <label>${t("topicRouting")}</label>
              <select data-field="control_groups.${idx}.topic_routing_enabled">
                <option value="false" ${group.topic_routing_enabled ? "" : "selected"}>false</option>
                <option value="true" ${group.topic_routing_enabled ? "selected" : ""}>true</option>
              </select>
            </div>
            <div class="field">
              <label>${t("skipHtmlReport")}</label>
              <select data-field="control_groups.${idx}.skip_html_report">
                <option value="false" ${group.skip_html_report ? "" : "selected"}>false</option>
                <option value="true" ${group.skip_html_report ? "selected" : ""}>true</option>
              </select>
            </div>
          </div>
          <div class="status" style="margin-top:12px;">
            ${t("mappedTargets")}${(() => {
              const mapped = mapTargetsToControl(targets, controlGroups, group.key);
              return mapped.length ? mapped.join(", ") : t("noneYet");
            })()}
          </div>
          ${group.topic_routing_enabled ? `
          <div class="list" style="margin-top:16px;">
            ${group.topic_target_map.map((entry, eidx) => `
            <div class="list-row">
              <select data-field="control_groups.${idx}.topic_target_map.${eidx}.user_key">
                ${buildUserOptions(targetUsers, selectedUsers, entryKey(entry))}
              </select>
              <input data-field="control_groups.${idx}.topic_target_map.${eidx}.topic_id" value="${entry.topic_id}" placeholder="${t("topicId")}" />
              <button class="button secondary" data-action="remove-topic" data-control-index="${idx}" data-topic-index="${eidx}">${t("remove")}</button>
            </div>`).join("")}
          </div>
          <div style="margin-top:12px;">
            <button class="button secondary" data-action="add-topic" data-control-index="${idx}">${t("addTopicMapping")}</button>
          </div>` : ""}
        </div>`).join("")}
      </div>
      <div style="margin-top:16px;">
        <button class="button secondary" data-action="add-control" ${controlGroups.length >= limits.maxControlGroups ? "disabled" : ""}>${t("addControlGroup")}</button>
      </div>
    </section>

    <section class="section">
      <h2>${t("storageReporting")}</h2>
      <div class="grid">
        <div class="field">
          <label>${t("dbPath")}</label>
          <input data-field="storage.db_path" value="${data.storage.db_path}" />
        </div>
        <div class="field">
          <label>${t("mediaDir")}</label>
          <input data-field="storage.media_dir" value="${data.storage.media_dir}" />
        </div>
        <div class="field">
          <label>${t("reportsDir")}</label>
          <input data-field="reporting.reports_dir" value="${data.reporting.reports_dir}" />
        </div>
        <div class="field">
          <label>${t("defaultSummaryInterval")}</label>
          <input data-field="reporting.summary_interval_minutes" value="${data.reporting.summary_interval_minutes}" />
        </div>
        <div class="field">
          <label>${t("timezone")}</label>
          <select data-field="reporting.timezone">
            ${buildTimezoneOptions(timezonePresets, data.reporting.timezone)}
          </select>
          <small>${t("timezoneHelp")}</small>
        </div>
        <div class="field">
          <label>${t("retentionDays")}</label>
          <input data-field="reporting.retention_days" value="${data.reporting.retention_days}" />
        </div>
      </div>

      <h3 style="margin-top:24px;margin-bottom:8px;font-size:15px;font-weight:600;">${t("fullArchiveSection")}</h3>
      <p style="margin-top:0;margin-bottom:10px;font-size:13px;color:var(--muted,#666);">${t("fullArchiveHelp")}</p>
      <div class="grid">
        <div class="field">
          <label>${t("fullArchiveEnabled")}</label>
          <select data-field="full_archive.enabled">
            <option value="false" ${data.full_archive.enabled ? "" : "selected"}>false</option>
            <option value="true" ${data.full_archive.enabled ? "selected" : ""}>true</option>
          </select>
        </div>
        <div class="field">
          <label>${t("fullArchiveRoot")}</label>
          <input data-field="full_archive.root_dir" value="${data.full_archive.root_dir}" />
        </div>
        <div class="field">
          <label>${t("fullArchiveSourceChat")}</label>
          <input data-field="full_archive.source_chat_id" value="${data.full_archive.source_chat_id || ""}" />
        </div>
        <div class="field">
          <label>${t("fullArchiveScope")}</label>
          <select data-field="full_archive.capture_scope">
            <option value="whole_group" ${data.full_archive.capture_scope !== "topics" ? "selected" : ""}>${t("fullArchiveScopeWhole")}</option>
            <option value="topics" ${data.full_archive.capture_scope === "topics" ? "selected" : ""}>${t("fullArchiveScopeTopics")}</option>
          </select>
        </div>
        <div class="field">
          <label>${t("fullArchiveTopicIds")}</label>
          <input data-field="full_archive.topic_ids" value="${data.full_archive.topic_ids}" />
          <small>${t("fullArchiveTopicIdsHelp")}</small>
        </div>
        <div class="field">
          <label>${t("fullArchiveShardPolicy")}</label>
          <select data-field="full_archive.shard_policy">
            <option value="monthly" ${data.full_archive.shard_policy === "monthly" ? "selected" : ""}>monthly</option>
          </select>
        </div>
        <div class="field">
          <label>${t("fullArchiveMaxMessages")}</label>
          <input data-field="full_archive.max_messages_per_shard" value="${data.full_archive.max_messages_per_shard}" />
        </div>
        <div class="field">
          <label>${t("fullArchiveMaxSize")}</label>
          <input data-field="full_archive.max_shard_size_mb" value="${data.full_archive.max_shard_size_mb}" />
        </div>
        <div class="field">
          <label>${t("fullArchiveBackfillLimit")}</label>
          <input data-field="full_archive.backfill_limit_messages" value="${data.full_archive.backfill_limit_messages}" />
        </div>
      </div>
    </section>

    <section class="section">
      <h2>${t("displayNotifications")}</h2>

      <h3 style="margin-top:8px;margin-bottom:4px;font-size:15px;font-weight:600;">${t("messageTemplateSection")}</h3>
      <p style="margin-top:0;margin-bottom:10px;font-size:13px;color:var(--muted,#666);">${t("messageTemplateHelp")}</p>
      <div class="grid">
        <div class="field">
          <label>${t("template")}</label>
          <select data-field="display.template">
            <option value="normal" ${data.display.template !== "minimal" ? "selected" : ""}>${t("templateNormal")}</option>
            <option value="minimal" ${data.display.template === "minimal" ? "selected" : ""}>${t("templateMinimal")}</option>
          </select>
          <small>${data.display.template === "minimal" ? t("templateMinimalDesc") : t("templateNormalDesc")}</small>
        </div>
      </div>
      <label style="font-weight:600;margin-top:12px;display:block;">${t("templatePreview")}</label>
      ${buildTemplatePreview(data.display.template, data.display.show_ids)}

      <h3 style="margin-top:24px;margin-bottom:8px;font-size:15px;font-weight:600;">${t("messageFieldsSection")}</h3>
      <div class="grid">
        <div class="field">
          <label>${t("showIds")}</label>
          <select data-field="display.show_ids">
            <option value="true" ${data.display.show_ids ? "selected" : ""}>true</option>
            <option value="false" ${data.display.show_ids ? "" : "selected"}>false</option>
          </select>
        </div>
      </div>
      ${(() => {
        const tfUnits = data.display_time_format_units || {};
        if (state.timeFormatCustom || !state.timeFormatParts) {
          return '<div style="margin-top:16px;"><div class="field"><label>' + t("timeFormatCustom") + '</label><input data-field="display.time_format" value="' + (data.display.time_format || "") + '" /><small><a href="#" data-action="tf-switch-builder">' + t("switchToBuilder") + '</a></small></div></div>';
        }
        const p = state.timeFormatParts;
        const hasMultiDate = [p.year, p.month, p.day].filter(Boolean).length > 1;
        return '<div style="margin-top:16px;"><label style="font-weight:600;margin-bottom:8px;display:block;">' + t("timeFormat") + '</label>'
          + '<div class="grid">'
          + '<div class="field"><label>' + t("year") + '</label>' + buildTimeFormatDropdown("year", tfUnits.year, p.year, "tf-year") + '</div>'
          + '<div class="field"><label>' + t("month") + '</label>' + buildTimeFormatDropdown("month", tfUnits.month, p.month, "tf-month") + '</div>'
          + '<div class="field"><label>' + t("day") + '</label>' + buildTimeFormatDropdown("day", tfUnits.day, p.day, "tf-day") + '</div>'
          + (hasMultiDate ? '<div class="field"><label>' + t("dateSep") + '</label>' + buildTimeFormatDropdown("dateSep", tfUnits.date_separator, p.dateSep, "tf-datesep") + '</div>' : '')
          + '<div class="field"><label>' + t("hour") + '</label>' + buildTimeFormatDropdown("hour", tfUnits.hour, p.hour, "tf-hour") + '</div>'
          + '<div class="field"><label>' + t("minute") + '</label>' + buildTimeFormatDropdown("minute", tfUnits.minute, p.minute, "tf-minute") + '</div>'
          + '<div class="field"><label>' + t("second") + '</label>' + buildTimeFormatDropdown("second", tfUnits.second, p.second, "tf-second") + '</div>'
          + '<div class="field"><label>' + t("timezone") + '</label>' + buildTimeFormatDropdown("timezone", tfUnits.timezone, p.timezone, "tf-timezone") + '</div>'
          + '</div>'
          + '<div style="margin-top:12px;"><small>Preview: <strong style="font-family:var(--mono);color:var(--accent);">' + timeFormatPreview(p) + '</strong></small>'
          + '&nbsp;&nbsp;<small>Format: <code style="font-size:12px;color:var(--muted);">' + composeTimeFormat(p) + '</code></small></div>'
          + '<small><a href="#" data-action="tf-switch-custom">' + t("editRawStrftime") + '</a></small>'
          + '</div>';
      })()}

      <h3 style="margin-top:24px;margin-bottom:8px;font-size:15px;font-weight:600;">${t("languageSection")}</h3>
      <div class="grid">
        <div class="field">
          <label>${t("language")}</label>
          <select data-field="display.language">
            <option value="auto" ${data.display.language === "auto" ? "selected" : ""}>${t("languageAuto")}</option>
            <option value="zh" ${data.display.language === "zh" ? "selected" : ""}>${t("languageZh")}</option>
            <option value="en" ${data.display.language === "en" ? "selected" : ""}>${t("languageEn")}</option>
          </select>
        </div>
      </div>

      <h3 style="margin-top:24px;margin-bottom:8px;font-size:15px;font-weight:600;">${t("notificationsSection")}</h3>
      <div class="grid">
        <div class="field">
          <label>${t("barkKey")}</label>
          <input data-field="notifications.bark_key" value="${data.notifications.bark_key}" placeholder="${t("optional")}" />
        </div>
        <div class="field">
          <label>${t("heartbeatInterval")}</label>
          <input type="number" data-field="notifications.heartbeat_interval_hours" value="${data.notifications.heartbeat_interval_hours}" placeholder="2" min="0" max="24" />
          <small>${t("heartbeatIntervalHelp")}</small>
        </div>
        <div class="field">
          <label>${t("checkUpdates")}</label>
          <select data-field="notifications.check_updates">
            <option value="true" ${data.notifications.check_updates ? "selected" : ""}>true</option>
            <option value="false" ${data.notifications.check_updates ? "" : "selected"}>false</option>
          </select>
          <small>${t("checkUpdatesHelp")}</small>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>${t("realtimeSectionTitle")}</h2>
      <p>${t("realtimeSectionDesc")}</p>
      <div class="grid">
        <div class="field">
          <label>${t("pushMode")}</label>
          <select id="realtime-push-mode" data-field="realtime.push_mode">
            <option value="interval" ${data.realtime.push_mode !== "realtime" ? "selected" : ""}>${t("pushModeInterval")}</option>
            <option value="realtime" ${data.realtime.push_mode === "realtime" ? "selected" : ""}>${t("pushModeRealtime")}</option>
          </select>
        </div>
      </div>
      ${(() => {
        if (data.realtime.push_mode !== "realtime" && !state.realtimeConfirmed) {
          return '<div class="status" style="margin-top:12px;">' + t("intervalModeStatus") + '</div>';
        }
        if (data.realtime.push_mode === "realtime" && !state.realtimeConfirmed) {
          return '<div class="notice" style="margin-top:12px;">'
            + '<strong>' + t("realtimeWarningTitle") + '</strong>'
            + '<ul style="margin:8px 0 8px 16px;padding:0;font-size:13px;color:#7a4a1a;">'
            + '<li>' + t("realtimeWarnExperimental") + '</li>'
            + '<li>' + t("realtimeWarnRestrictions") + '</li>'
            + '<li>' + t("realtimeWarnRateProtection") + '</li>'
            + '<li>' + t("realtimeWarnDefaults") + '</li>'
            + '<li>' + t("realtimeWarnCircuitBreaker") + '</li>'
            + '<li>' + t("realtimeWarnResponsibility") + '</li>'
            + '</ul>'
            + '<label class="checkbox">'
            + '<input type="checkbox" id="realtime-risk-confirm" />'
            + t("realtimeRiskConfirm")
            + '</label>'
            + '<div class="actions" style="margin-top:10px;">'
            + '<button class="button secondary" data-action="realtime-confirm" disabled>' + t("confirmRealtimeMode") + '</button>'
            + '<button class="button secondary" data-action="realtime-cancel">' + t("cancel") + '</button>'
            + '</div>'
            + '</div>';
        }
        return '<div class="grid" style="margin-top:16px;">'
          + '<div class="field"><label>' + t("rateLimitMinute") + '</label>'
          + '<input data-field="realtime.rate_limit_per_minute" value="' + data.realtime.rate_limit_per_minute + '" placeholder="20" />'
          + '<small>' + t("rateLimitMinuteHelp") + '</small></div>'
          + '<div class="field"><label>' + t("rateLimitHour") + '</label>'
          + '<input data-field="realtime.rate_limit_per_hour" value="' + data.realtime.rate_limit_per_hour + '" placeholder="200" />'
          + '<small>' + t("rateLimitHourHelp") + '</small></div>'
          + '<div class="field"><label>' + t("rateLimitDay") + '</label>'
          + '<input data-field="realtime.rate_limit_per_day" value="' + data.realtime.rate_limit_per_day + '" placeholder="1000" />'
          + '<small>' + t("rateLimitDayHelp") + '</small></div>'
          + '<div class="field"><label>' + t("minIntervalSec") + '</label>'
          + '<input data-field="realtime.min_interval_sec" value="' + data.realtime.min_interval_sec + '" placeholder="3.0" />'
          + '<small>' + t("minIntervalSecHelp") + '</small></div>'
          + '<div class="field"><label>' + t("mediaExtraDelay") + '</label>'
          + '<input data-field="realtime.media_extra_delay_sec" value="' + data.realtime.media_extra_delay_sec + '" placeholder="2.0" />'
          + '<small>' + t("mediaExtraDelayHelp") + '</small></div>'
          + '<div class="field"><label>' + t("warmupMinutes") + '</label>'
          + '<input data-field="realtime.warmup_minutes" value="' + data.realtime.warmup_minutes + '" placeholder="5.0" />'
          + '<small>' + t("warmupMinutesHelp") + '</small></div>'
          + '<div class="field"><label>' + t("warmupRate") + '</label>'
          + '<input data-field="realtime.warmup_rate" value="' + data.realtime.warmup_rate + '" placeholder="5" />'
          + '<small>' + t("warmupRateHelp") + '</small></div>'
          + '<div class="field"><label>' + t("rtReportInterval") + '</label>'
          + '<input data-field="realtime.report_interval_minutes" value="' + data.realtime.report_interval_minutes + '" placeholder="120" />'
          + '<small>' + t("rtReportIntervalHelp") + '</small></div>'
          + '</div>';
      })()}
    </section>
  `;

  document.querySelectorAll("select[data-field]").forEach((select) => {
    const field = select.dataset.field;
    const value = getByPath(state.data, field);
    select.value = String(value);
  });
  applyLockState();
}

function getByPath(obj, path) {
  return path.split(".").reduce((acc, key) => acc[key], obj);
}

function bindEvents() {
  document.addEventListener("input", (event) => {
    const target = event.target;
    if (target.id === "once-since") {
      state.runnerSince = target.value;
      return;
    }
    if (target.id === "once-target") {
      state.runnerTarget = target.value;
      return;
    }
    if (target.id === "once-push") {
      state.runnerPush = target.checked;
      return;
    }
    if (target.id === "run-retention-confirm") {
      state.runnerRetentionConfirmed = target.checked;
      updateRunnerUI();
      return;
    }
    if (target.id === "realtime-risk-confirm") {
      const confirmBtn = document.querySelector('[data-action="realtime-confirm"]');
      if (confirmBtn) confirmBtn.disabled = !target.checked;
      return;
    }
    if (!target.dataset.field) return;
    const field = target.dataset.field;
    let value = target.type === "checkbox" ? target.checked : target.value;
    if (target.tagName === "SELECT") {
      value = target.value === "true" ? true : target.value === "false" ? false : target.value;
    }
    setByPath(state.data, field, value);
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target.dataset && target.dataset.tfUnit) {
      const unit = target.dataset.tfUnit;
      if (state.timeFormatParts) {
        state.timeFormatParts[unit] = target.value;
        const composed = composeTimeFormat(state.timeFormatParts);
        state.data.display.time_format = composed;
        render();
      }
      return;
    }
    if (target.id === "realtime-push-mode") {
      const newMode = target.value;
      if (newMode === "realtime") {
        state.data.realtime.push_mode = "realtime";
        state.realtimeConfirmed = false;
        render();
      } else {
        state.data.realtime.push_mode = "interval";
        state.realtimeConfirmed = false;
        render();
      }
      return;
    }
    if (target.dataset && target.dataset.field === "display.language") {
      const val = target.value;
      if (val === "auto") {
        _lang = (navigator.language || "en").startsWith("zh") ? "zh" : "en";
      } else {
        _lang = val;
      }
      localStorage.setItem("tgwatch_lang", _lang);
      document.documentElement.lang = _lang === "zh" ? "zh-CN" : "en";
      document.title = t("title");
      render();
      return;
    }
    if (target.id === "once-target") {
      state.runnerTarget = target.value;
      return;
    }
    if (target.id === "once-push") {
      state.runnerPush = target.checked;
      return;
    }
    if (target.id === "run-retention-confirm") {
      state.runnerRetentionConfirmed = target.checked;
      updateRunnerUI();
      return;
    }
    if (!target.dataset.field) return;
    const field = target.dataset.field;
    if (
      field === "sender.enabled" ||
      field === "display.template" ||
      field === "display.show_ids" ||
      field.startsWith("targets.") ||
      field.endsWith(".key") ||
      field.endsWith(".topic_routing_enabled") ||
      field.endsWith(".is_forum") ||
      field.endsWith(".skip_html_report") ||
      field.endsWith(".control_group") ||
      field.includes(".topic_target_map.")
    ) {
      render();
    }
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    const action = target.dataset.action;
    if (!action) return;

    if (action === "add-target") {
      state.data.targets.push(blankTarget());
      render();
      return;
    }
    if (action === "remove-target") {
      const index = Number(target.dataset.targetIndex);
      state.data.targets.splice(index, 1);
      render();
      return;
    }
    if (action === "add-user") {
      const index = Number(target.dataset.targetIndex);
      state.data.targets[index].tracked_users.push({ id: "", alias: "" });
      render();
      return;
    }
    if (action === "remove-user") {
      const tIndex = Number(target.dataset.targetIndex);
      const uIndex = Number(target.dataset.userIndex);
      state.data.targets[tIndex].tracked_users.splice(uIndex, 1);
      render();
      return;
    }
    if (action === "add-control") {
      state.data.control_groups.push(blankControlGroup());
      render();
      return;
    }
    if (action === "remove-control") {
      const index = Number(target.dataset.controlIndex);
      state.data.control_groups.splice(index, 1);
      render();
      return;
    }
    if (action === "add-topic") {
      const index = Number(target.dataset.controlIndex);
      state.data.control_groups[index].topic_target_map.push({
        user_key: "",
        target_chat_id: "",
        user_id: "",
        topic_id: ""
      });
      render();
      return;
    }
    if (action === "remove-topic") {
      const cIndex = Number(target.dataset.controlIndex);
      const tIndex = Number(target.dataset.topicIndex);
      state.data.control_groups[cIndex].topic_target_map.splice(tIndex, 1);
      render();
      return;
    }
    if (action === "save") {
      saveConfig();
      return;
    }
    if (action === "reload") {
      loadConfig();
      return;
    }
    if (action === "toggle-lang") {
      _lang = _lang === "zh" ? "en" : "zh";
      localStorage.setItem("tgwatch_lang", _lang);
      if (state.data) {
        state.data.display.language = _lang;
      }
      document.documentElement.lang = _lang === "zh" ? "zh-CN" : "en";
      document.title = t("title");
      render();
      return;
    }
    if (action === "run-once") {
      startOnce();
      return;
    }
    if (action === "run-daemon") {
      startRun();
      return;
    }
    if (action === "run-daemon-confirm") {
      startRunConfirmed();
      return;
    }
    if (action === "run-daemon-stop") {
      stopRun();
      return;
    }
    if (action === "run-daemon-cancel") {
      state.runnerRetentionPrompt = false;
      state.runnerRetentionConfirmed = false;
      state.runnerMessage = "";
      render();
      updateRunnerUI();
      return;
    }
    if (action === "stop-gui") {
      stopGui();
      return;
    }
    if (action === "migrate-config") {
      migrateConfig();
      return;
    }
    if (action === "realtime-confirm") {
      state.realtimeConfirmed = true;
      render();
      return;
    }
    if (action === "realtime-cancel") {
      state.data.realtime.push_mode = "interval";
      state.realtimeConfirmed = false;
      render();
      return;
    }
    if (action === "tf-switch-builder") {
      event.preventDefault();
      const parsed = parseTimeFormat(state.data.display.time_format || "");
      if (parsed) {
        state.timeFormatParts = parsed;
      } else {
        state.timeFormatParts = {
          year: "%Y", month: "%m", day: "%d", dateSep: ".",
          hour: "%H", minute: "%M", second: "%S", timezone: "%Z"
        };
        state.data.display.time_format = composeTimeFormat(state.timeFormatParts);
      }
      state.timeFormatCustom = false;
      render();
      return;
    }
    if (action === "tf-switch-custom") {
      event.preventDefault();
      state.timeFormatCustom = true;
      state.timeFormatParts = null;
      render();
      return;
    }
  });
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const payload = await res.json();
    state.data = payload.data;
    state.errors = payload.errors || [];
    state.status = payload.status || "";
    state.locked = Boolean(payload.locked);
    state.lockMessage = payload.lock_message || "";
    if (payload.data.display.language && payload.data.display.language !== "auto") {
      _lang = payload.data.display.language;
      localStorage.setItem("tgwatch_lang", _lang);
      document.documentElement.lang = _lang === "zh" ? "zh-CN" : "en";
      document.title = t("title");
    }
    if (payload.data && payload.data.realtime && payload.data.realtime.push_mode === "realtime") {
      state.realtimeConfirmed = true;
    } else {
      state.realtimeConfirmed = false;
    }
    const parsedTf = parseTimeFormat((payload.data && payload.data.display && payload.data.display.time_format) || "");
    if (parsedTf) {
      state.timeFormatParts = parsedTf;
      state.timeFormatCustom = false;
    } else {
      state.timeFormatParts = null;
      state.timeFormatCustom = true;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.errors = [`Failed to load config: ${message}`];
    state.status = "";
    state.locked = true;
    state.lockMessage = "GUI failed to load config. Reload the page or restart the GUI.";
  }
  render();
  updateRunnerUI();
}

async function saveConfig() {
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.data)
    });
    const payload = await res.json();
    state.errors = payload.errors || [];
    state.status = payload.status || "";
    if (payload.data) {
      state.data = payload.data;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    state.errors = [`Failed to save config: ${message}`];
    state.status = "";
  }
  render();
  updateRunnerUI();
}

document.documentElement.lang = _lang === "zh" ? "zh-CN" : "en";
document.title = t("title");
bindEvents();
render();
loadConfig();
startRunnerPolling();
"""


_RUN_LOG_TAIL_BYTES = 12000
_RUN_HEALTH_STALE_SECONDS = 90.0


class _RunnerManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.runtime_dir = config_path.parent / "data" / "gui"
        self.run_pid_path = self.runtime_dir / "run.pid"
        self.run_log_path = self.runtime_dir / "run.log"
        self.run_health_path = self.runtime_dir / "run.health.json"
        self.once_log_path = self.runtime_dir / "once.log"
        self.lock = threading.Lock()

    def status_payload(self) -> dict[str, Any]:
        self._ensure_runtime_dir()
        running, pid = self._current_run()
        run_log = self._tail(self.run_log_path) if running else ""
        once_log = self._tail(self.once_log_path) if self.once_log_path.exists() else ""
        config_ok, session_ready, retention_days, requires_retention_confirm, message = (
            self._config_health()
        )
        health, stalled_reason = self._runner_health(pid) if running else ({}, None)
        full_archive = self._full_archive_status(running=running, health=health)
        archive_problem = running and full_archive["status"] in {
            "degraded",
            "restart_required",
            "unverified",
        }
        if stalled_reason:
            message = f"Run daemon appears stalled (pid {pid}): {stalled_reason}"
        elif full_archive["status"] == "degraded":
            message = (
                "Full Archive live capture is disabled because archive health is "
                "degraded. Run archive-status and archive-repair --dry-run before "
                "restarting the daemon."
            )
        elif full_archive["status"] == "unverified":
            message = (
                "Full Archive runtime status is unavailable; restart the daemon "
                "to verify live capture."
            )
        elif full_archive["status"] == "restart_required":
            message = (
                "Full Archive configuration changed after startup; restart the "
                "daemon to apply it."
            )
        return {
            "running": running,
            "pid": pid,
            "healthy": running and stalled_reason is None and not archive_problem,
            "stalled": stalled_reason is not None,
            "health": health,
            "full_archive": full_archive,
            "run_log": run_log,
            "once_log": once_log,
            "status": message or "",
            "config_ok": config_ok,
            "session_ready": session_ready,
            "retention_days": retention_days,
            "requires_retention_confirm": requires_retention_confirm,
        }

    def _full_archive_status(
        self,
        *,
        running: bool,
        health: dict[str, Any],
    ) -> dict[str, Any]:
        config, _ = self._load_config()
        archive_config = getattr(config, "full_archive", None)
        configured = bool(getattr(archive_config, "enabled", False))
        reported = health.get("full_archive")
        if not isinstance(reported, dict):
            return {
                "configured": configured,
                "runtime_enabled": None if configured and running else False,
                "status": (
                    "unverified"
                    if configured and running
                    else "stopped" if configured else "disabled"
                ),
            }

        daemon_configured = reported.get("configured")
        runtime_enabled = reported.get("runtime_enabled")
        if not isinstance(daemon_configured, bool) or not isinstance(runtime_enabled, bool):
            return {
                "configured": configured,
                "runtime_enabled": None,
                "status": "unverified",
            }
        if configured != daemon_configured:
            status = "restart_required"
        elif configured:
            reported_fingerprint = reported.get("config_fingerprint")
            current_fingerprint = getattr(archive_config, "runtime_fingerprint", None)
            if not isinstance(reported_fingerprint, str):
                status = "unverified"
                runtime_enabled = None
            elif reported_fingerprint != current_fingerprint:
                status = "restart_required"
            elif runtime_enabled:
                status = "active"
            else:
                status = "degraded" if running else "stopped"
        elif runtime_enabled:
            status = "active"
        else:
            status = "disabled"
        return {
            "configured": configured,
            "runtime_enabled": runtime_enabled,
            "status": status,
        }

    def start_run(self, *, confirm_retention: bool = False) -> dict[str, Any]:
        with self.lock:
            running, pid = self._current_run()
            if running:
                return {"ok": True, "status": f"Run already active (pid {pid})."}
            config, message = self._load_config()
            if message:
                return {"ok": False, "status": message}
            session_ok, session_msg = self._session_ready(config)
            if not session_ok:
                return {"ok": False, "status": session_msg}
            if self._retention_confirm_required(config) and not confirm_retention:
                return {
                    "ok": False,
                    "status": (
                        "Retention confirmation required. "
                        "Please confirm retention risk in GUI before starting run daemon."
                    ),
                }
            self._ensure_runtime_dir()
            self.run_health_path.unlink(missing_ok=True)
            self._write_log_header(self.run_log_path, "Starting run daemon.")
            proc = self._spawn_process(
                [
                    "-m",
                    "tgwatch",
                    "run",
                    "--config",
                    str(self.config_path),
                    "--yes-retention",
                ],
                log_path=self.run_log_path,
            )
            self.run_pid_path.write_text(str(proc.pid), encoding="utf-8")
            return {"ok": True, "status": f"Run started (pid {proc.pid})."}

    def stop_run(self) -> dict[str, Any]:
        with self.lock:
            running, pid = self._current_run()
            if not running or pid is None:
                return {"ok": True, "status": "Run daemon is not active."}
            if not self._terminate_run_process(pid):
                return {"ok": False, "status": f"Failed to stop run daemon (pid {pid})."}
            self.run_pid_path.unlink(missing_ok=True)
            self.run_health_path.unlink(missing_ok=True)
            self._write_log_header(self.run_log_path, f"Stopped run daemon (pid {pid}).")
            return {"ok": True, "status": f"Run stopped (pid {pid})."}

    def start_once(
        self,
        since: str,
        target: str | None = None,
        push: bool = False,
    ) -> dict[str, Any]:
        if not since:
            return {"ok": False, "status": "since is required"}
        config, message = self._load_config()
        if message:
            return {"ok": False, "status": message}
        session_ok, session_msg = self._session_ready(config)
        if not session_ok:
            return {"ok": False, "status": session_msg}
        if target:
            target_key = target.strip()
            if target_key not in config.target_by_name:
                try:
                    target_chat_id = int(target_key)
                except (TypeError, ValueError):
                    return {"ok": False, "status": f"Unknown target: {target}"}
                if target_chat_id not in config.target_by_chat_id:
                    return {"ok": False, "status": f"Unknown target: {target}"}
        self._ensure_runtime_dir()
        header = f"Starting once (since {since})"
        args = ["-m", "tgwatch", "once", "--config", str(self.config_path), "--since", since]
        if target:
            args.extend(["--target", target])
            header += f" target={target}"
        if push:
            args.append("--push")
            header += " push=true"
        self._write_log_header(self.once_log_path, f"{header}.")
        self._spawn_process(
            args,
            log_path=self.once_log_path,
        )
        status = f"Once started (since {since})."
        if target:
            status = f"Once started (since {since}, target {target})."
        if push:
            status = status.replace(").", ", push enabled).")
        return {"ok": True, "status": status}

    def _ensure_runtime_dir(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def _current_run(self) -> tuple[bool, int | None]:
        pid = self._read_pid()
        if pid is None:
            return False, None
        if self._pid_is_running(pid) and self._pid_matches_run_daemon(pid):
            return True, pid
        if self._pid_is_running(pid):
            logger.warning("Ignoring PID %s from run.pid because it does not match tgwatch run daemon.", pid)
        self.run_pid_path.unlink(missing_ok=True)
        self.run_health_path.unlink(missing_ok=True)
        return False, None

    def _runner_health(
        self,
        pid: int | None,
    ) -> tuple[dict[str, Any], str | None]:
        if pid is None:
            return {}, None
        try:
            raw = json.loads(self.run_health_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            try:
                pid_age = time.time() - self.run_pid_path.stat().st_mtime
            except OSError:
                pid_age = 0.0
            if pid_age > _RUN_HEALTH_STALE_SECONDS:
                return {}, "health heartbeat is missing"
            return {}, None
        if not isinstance(raw, dict) or raw.get("pid") != pid:
            return {}, "health heartbeat belongs to a different process"
        last_tick = self._parse_health_timestamp(raw.get("last_tick"))
        if last_tick is None:
            return raw, "health heartbeat timestamp is invalid"
        tick_age = (datetime.now(timezone.utc) - last_tick).total_seconds()
        if tick_age > _RUN_HEALTH_STALE_SECONDS:
            return raw, f"event-loop heartbeat is {int(tick_age)}s old"
        pending = raw.get("sqlite_pending")
        pending_since = self._parse_health_timestamp(raw.get("sqlite_pending_since"))
        if isinstance(pending, int) and pending > 0 and pending_since is not None:
            last_success = self._parse_health_timestamp(raw.get("sqlite_last_success"))
            last_progress = max(
                timestamp
                for timestamp in (pending_since, last_success)
                if timestamp is not None
            )
            pending_age = (datetime.now(timezone.utc) - last_progress).total_seconds()
            if pending_age > _RUN_HEALTH_STALE_SECONDS:
                return raw, f"SQLite made no progress for {int(pending_age)}s"
        return raw, None

    @staticmethod
    def _parse_health_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _read_pid(self) -> int | None:
        if not self.run_pid_path.exists():
            return None
        try:
            value = int(self.run_pid_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None
        return value if value > 0 else None

    def _pid_is_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            return self._pid_exists_windows(pid)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _pid_exists_windows(self, pid: int) -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False
        return str(pid) in result.stdout

    def _pid_matches_run_daemon(self, pid: int) -> bool:
        """Best-effort identity check to avoid killing unrelated reused PIDs."""
        if os.name == "nt":
            # Windows tasklist output does not reliably include command args in this flow.
            return True
        command = self._pid_command(pid)
        if not command:
            return False
        argv = self._split_command(command)
        if not argv:
            return False
        has_config = self._command_uses_config(argv)
        has_run = self._command_is_tgwatch_run(argv)
        return has_run and has_config

    def _split_command(self, command: str) -> list[str]:
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()

    def _command_is_tgwatch_run(self, argv: list[str]) -> bool:
        if not argv:
            return False
        for idx, token in enumerate(argv):
            if token == "-m" and idx + 2 < len(argv):
                if argv[idx + 1] == "tgwatch" and argv[idx + 2] == "run":
                    return True
            if Path(token).name == "tgwatch" and idx + 1 < len(argv):
                if argv[idx + 1] == "run":
                    return True
        return False

    def _command_uses_config(self, argv: list[str]) -> bool:
        expected = self.config_path.resolve()
        for idx, token in enumerate(argv):
            value: str | None = None
            if token == "--config" and idx + 1 < len(argv):
                value = argv[idx + 1]
            elif token.startswith("--config="):
                value = token.partition("=")[2]
            if value is None:
                continue
            normalized = self._normalize_config_arg(value)
            if normalized is not None and normalized == expected:
                return True
        return False

    def _normalize_config_arg(self, value: str) -> Path | None:
        path = Path(value).expanduser()
        if not path.is_absolute():
            return None
        return path.resolve()

    def _pid_command(self, pid: int) -> str:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _terminate_run_process(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                return False
            return result.returncode == 0 or not self._pid_is_running(pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not self._pid_is_running(pid)
        for _ in range(10):
            if not self._pid_is_running(pid):
                return True
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return not self._pid_is_running(pid)
        for _ in range(10):
            if not self._pid_is_running(pid):
                return True
            time.sleep(0.1)
        return not self._pid_is_running(pid)

    def _load_config(self) -> tuple[Any | None, str | None]:
        if not self.config_path.exists():
            return None, f"Config not found: {self.config_path.name}"
        try:
            return load_config(self.config_path), None
        except ConfigError as exc:
            return None, str(exc)

    def _session_ready(self, config: Any) -> tuple[bool, str | None]:
        if not config.telegram.session_file.exists():
            return False, "Session file not found. Run `python -m tgwatch run --config ...` once in a terminal."
        return True, None

    def _retention_confirm_required(self, config: Any) -> bool:
        retention_days = getattr(config.reporting, "retention_days", 30)
        return int(retention_days) > 180

    def _config_health(self) -> tuple[bool, bool, int, bool, str | None]:
        config, message = self._load_config()
        if message:
            return False, False, 30, False, message
        retention_days = int(getattr(config.reporting, "retention_days", 30))
        requires_retention_confirm = self._retention_confirm_required(config)
        session_ok, session_msg = self._session_ready(config)
        if not session_ok:
            return True, False, retention_days, requires_retention_confirm, session_msg
        return True, True, retention_days, requires_retention_confirm, None

    def _spawn_process(self, args: list[str], *, log_path: Path) -> subprocess.Popen:
        self._ensure_runtime_dir()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [sys.executable, *args]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
        try:
            if os.name == "nt":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                return subprocess.Popen(
                    cmd,
                    cwd=str(self.config_path.parent),
                    stdout=log_handle,
                    stderr=log_handle,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    creationflags=flags,
                )
            return subprocess.Popen(
                cmd,
                cwd=str(self.config_path.parent),
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log_handle.close()

    def _write_log_header(self, path: Path, message: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== {message} ===\n")

    def _tail(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > _RUN_LOG_TAIL_BYTES:
                    handle.seek(-_RUN_LOG_TAIL_BYTES, os.SEEK_END)
                data = handle.read()
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")


def run_gui(config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the local GUI server."""
    config_path = config_path.expanduser().resolve()
    server = _GuiServer((host, port), _GuiHandler, config_path=config_path)
    url = f"http://{host}:{port}"
    logger.info("GUI running at %s", url)
    print(f"GUI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url, new=2)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Failed to open browser: %s", exc)
    server.serve_forever()


class _GuiServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, *, config_path: Path):
        super().__init__(server_address, handler_cls)
        self.config_path = config_path
        self.runner = _RunnerManager(config_path)


class _GuiHandler(BaseHTTPRequestHandler):
    server_version = "tgwatch-gui/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send_response(HTTPStatus.OK, _HTML, "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._send_response(HTTPStatus.OK, _CSS, "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_response(HTTPStatus.OK, _JS, "text/javascript; charset=utf-8")
            return
        if path == "/api/config":
            self._handle_get_config()
            return
        if path == "/api/runner/status":
            self._handle_runner_status()
            return
        if path == "/api/gui/stop":
            self._handle_gui_stop()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            self._handle_post_config()
            return
        if path == "/api/runner/run":
            self._handle_runner_run()
            return
        if path == "/api/runner/once":
            self._handle_runner_once()
            return
        if path == "/api/runner/stop":
            self._handle_runner_stop()
            return
        if path == "/api/gui/stop":
            self._handle_gui_stop()
            return
        if path == "/api/config/migrate":
            self._handle_migrate_config()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        msg = format % args
        # Suppress noisy status-poll logs (every 2s) to DEBUG.
        if "/api/runner/status" in msg:
            logger.debug("GUI %s - %s", self.address_string(), msg)
        else:
            logger.info("GUI %s - %s", self.address_string(), msg)

    def _handle_get_config(self) -> None:
        errors: list[str] = []
        locked = False
        lock_message = ""
        try:
            raw = _load_raw_config(self.server.config_path)
        except ConfigError as exc:
            raw = {}
            message = str(exc)
            errors.append(message)
            locked = True
            lock_message = message
        data = _normalize_config(raw)
        if self.server.config_path.exists():
            if not lock_message:
                try:
                    load_config(self.server.config_path)
                except ConfigError as exc:
                    message = str(exc)
                    errors.append(message)
                    locked = True
                    lock_message = message
        else:
            locked = True
            lock_message = (
                "config.toml not found. Copy config.example.toml and fill it, "
                "then reload the GUI."
            )
        data["cloud_sync_warning"] = _detect_cloud_sync(
            data.get("telegram", {}).get("session_file", ""),
            data.get("storage", {}).get("db_path", ""),
            self.server.config_path.parent,
        )
        payload = {
            "data": data,
            "errors": errors,
            "status": "",
            "locked": locked,
            "lock_message": lock_message,
        }
        self._send_json(HTTPStatus.OK, payload)

    def _handle_post_config(self) -> None:
        try:
            payload = self._read_json()
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"errors": ["Invalid JSON"]})
            return
        try:
            raw_existing = _load_raw_config(self.server.config_path)
        except ConfigError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"errors": [str(exc)]})
            return
        errors, normalized = _validate_payload(payload, raw_existing)
        if errors:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"errors": errors, "data": _normalize_config(raw_existing)},
            )
            return
        toml_text = _render_toml(normalized, raw_existing)
        tmp_path = self.server.config_path.with_suffix(".tmp")
        tmp_path.write_text(toml_text, encoding="utf-8")
        try:
            load_config(tmp_path)
        except ConfigError as exc:
            tmp_path.unlink(missing_ok=True)
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"errors": [str(exc)], "data": _normalize_config(raw_existing)},
            )
            return
        tmp_path.replace(self.server.config_path)
        data = _normalize_config(_load_raw_config(self.server.config_path))
        self._send_json(HTTPStatus.OK, {"errors": [], "status": "Saved.", "data": data})

    def _handle_migrate_config(self) -> None:
        result = migrate_config(self.server.config_path)
        if not result.ok:
            self._send_json(HTTPStatus.BAD_REQUEST, {"status": result.status})
            return
        status = f"Migrated. Backup: {result.backup_path.name}. Review config.toml before running."
        self._send_json(HTTPStatus.OK, {"status": status})

    def _handle_runner_status(self) -> None:
        payload = self.server.runner.status_payload()
        self._send_json(HTTPStatus.OK, payload)

    def _handle_runner_run(self) -> None:
        try:
            request_payload = self._read_json()
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"status": "Invalid JSON"})
            return
        confirm_retention = bool(request_payload.get("confirm_retention", False))
        payload = self.server.runner.start_run(confirm_retention=confirm_retention)
        status = HTTPStatus.OK if payload.get("ok", True) else HTTPStatus.BAD_REQUEST
        self._send_json(status, payload)

    def _handle_runner_once(self) -> None:
        try:
            payload = self._read_json()
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"status": "Invalid JSON"})
            return
        since = str(payload.get("since", "")).strip()
        target = str(payload.get("target", "")).strip() or None
        push = bool(payload.get("push", False))
        response = self.server.runner.start_once(since, target, push)
        status = HTTPStatus.OK if response.get("ok", True) else HTTPStatus.BAD_REQUEST
        self._send_json(status, response)

    def _handle_runner_stop(self) -> None:
        payload = self.server.runner.stop_run()
        status = HTTPStatus.OK if payload.get("ok", True) else HTTPStatus.BAD_REQUEST
        self._send_json(status, payload)

    def _handle_gui_stop(self) -> None:
        self._send_json(
            HTTPStatus.OK,
            {"status": "GUI stopped. The run daemon (if running) stays active."},
        )
        shutdown_thread = threading.Thread(target=self.server.shutdown, daemon=True)
        shutdown_thread.start()

    def _send_response(self, status: HTTPStatus, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))


_CLOUD_SYNC_PATTERNS: list[tuple[str, list[str]]] = [
    ("Dropbox", ["/Dropbox/"]),
    ("iCloud", ["/Library/Mobile Documents/", "/iCloud/"]),
    ("OneDrive", ["/OneDrive/"]),
    ("Google Drive", ["/Google Drive/", "/GoogleDrive/"]),
]


def _detect_cloud_sync(
    session_file: str,
    db_path: str,
    config_dir: Path,
) -> str:
    """Return comma-separated cloud service names if data paths sit inside
    a known cloud sync directory, or empty string if none detected."""
    paths_to_check: list[str] = []
    for rel in (session_file, db_path):
        if not rel:
            continue
        resolved = str((config_dir / rel).resolve())
        paths_to_check.append(resolved)
    if not paths_to_check:
        return ""
    detected: list[str] = []
    for service, patterns in _CLOUD_SYNC_PATTERNS:
        for p in paths_to_check:
            if any(pat in p for pat in patterns):
                detected.append(service)
                break
    return ", ".join(detected)


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path.name}: {exc}") from exc


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    telegram = raw.get("telegram", {})
    sender_raw = raw.get("sender", {}) if isinstance(raw.get("sender"), dict) else {}
    reporting = raw.get("reporting", {})
    storage = raw.get("storage", {})
    display = raw.get("display", {})
    notifications = raw.get("notifications", {})
    realtime = raw.get("realtime", {})
    full_archive = raw.get("full_archive", {})

    api_hash = telegram.get("api_hash")
    data = {
        "config_version": raw.get("config_version", ""),
        "limits": {
            "maxTargets": MAX_TARGET_GROUPS,
            "maxUsersPerTarget": MAX_USERS_PER_TARGET,
            "maxControlGroups": MAX_CONTROL_GROUPS,
        },
        "telegram": {
            "api_id": telegram.get("api_id", ""),
            "api_hash": KEEP_SECRET if api_hash else "",
            "session_file": telegram.get("session_file", "data/tgwatch.session"),
        },
        "sender": {
            "enabled": bool(sender_raw),
            "session_file": sender_raw.get("session_file", "data/tgwatch_sender.session"),
        },
        "storage": {
            "db_path": storage.get("db_path", "data/tgwatch.sqlite3"),
            "media_dir": storage.get("media_dir", "data/media"),
        },
        "full_archive": {
            "enabled": bool(full_archive.get("enabled", False)),
            "root_dir": full_archive.get("root_dir", "data/full_archive"),
            "source_chat_id": full_archive.get("source_chat_id", ""),
            "capture_scope": str(full_archive.get("capture_scope", "whole_group")).strip().lower(),
            "topic_ids": _format_topic_ids_for_gui(full_archive.get("topic_ids", [])),
            "shard_policy": str(full_archive.get("shard_policy", "monthly")).strip().lower(),
            "max_messages_per_shard": full_archive.get("max_messages_per_shard", 500000),
            "max_shard_size_mb": full_archive.get("max_shard_size_mb", 1024),
            "backfill_limit_messages": full_archive.get("backfill_limit_messages", 10000),
        },
        "reporting": {
            "reports_dir": reporting.get("reports_dir", "reports"),
            "summary_interval_minutes": reporting.get("summary_interval_minutes", 120),
            "timezone": reporting.get("timezone", "UTC"),
            "retention_days": reporting.get("retention_days", 30),
        },
        "reporting_timezone_presets": _build_timezone_presets(),
        "display": {
            "show_ids": display.get("show_ids", True),
            "time_format": display.get("time_format", "%Y.%m.%d %H:%M:%S (%Z)"),
            "language": display.get("language", "auto"),
            "template": display.get("template", "normal"),
        },
        "display_time_format_units": _TIME_FORMAT_UNITS,
        "notifications": {
            "bark_key": notifications.get("bark_key", ""),
            "heartbeat_interval_hours": notifications.get("heartbeat_interval_hours", 2),
            "check_updates": notifications.get("check_updates", True),
        },
        "realtime": {
            "push_mode": str(realtime.get("push_mode", "interval")).strip().lower(),
            "rate_limit_per_minute": realtime.get("rate_limit_per_minute", 20),
            "rate_limit_per_hour": realtime.get("rate_limit_per_hour", 200),
            "rate_limit_per_day": realtime.get("rate_limit_per_day", 1000),
            "min_interval_sec": realtime.get("min_interval_sec", 3.0),
            "media_extra_delay_sec": realtime.get("media_extra_delay_sec", 2.0),
            "warmup_minutes": realtime.get("warmup_minutes", 5.0),
            "warmup_rate": realtime.get("warmup_rate", 5),
            "report_interval_minutes": realtime.get("report_interval_minutes", 120),
        },
    }

    targets_raw = []
    if "targets" in raw:
        targets_raw = raw.get("targets", []) or []
    elif "target" in raw:
        targets_raw = [raw.get("target", {})]
    targets: list[dict[str, Any]] = []
    for idx, target in enumerate(targets_raw, start=1):
        if not isinstance(target, dict):
            continue
        aliases = target.get("tracked_user_aliases", {}) or {}
        tracked_users = []
        for user_id in target.get("tracked_user_ids", []) or []:
            alias = aliases.get(user_id) or aliases.get(str(user_id)) or ""
            tracked_users.append({"id": str(user_id), "alias": alias})
        if not tracked_users:
            tracked_users = [{"id": "", "alias": ""}]
        targets.append(
            {
                "name": target.get("name") or f"group-{idx}",
                "target_chat_id": target.get("target_chat_id", ""),
                "summary_interval_minutes": target.get("summary_interval_minutes", ""),
                "control_group": target.get("control_group", ""),
                "tracked_users": tracked_users,
            }
        )
    if not targets:
        targets = [blank_target()]
    data["targets"] = targets
    data["full_archive_source_warning"] = _full_archive_source_warning(data)

    control_groups_raw: dict[str, Any] = {}
    if "control_groups" in raw:
        control_groups_raw = raw.get("control_groups", {}) or {}
    elif "control" in raw:
        control_groups_raw = {"default": raw.get("control", {})}
    control_groups: list[dict[str, Any]] = []
    for key, group in control_groups_raw.items():
        if not isinstance(group, dict):
            continue
        topic_map = []
        topic_target_raw = group.get("topic_target_map", {}) or {}
        if isinstance(topic_target_raw, dict):
            for target_id, user_map in topic_target_raw.items():
                if not isinstance(user_map, dict):
                    continue
                for user_id, topic_id in user_map.items():
                    target_text = str(target_id)
                    user_text = str(user_id)
                    topic_map.append(
                        {
                            "user_key": f"{target_text}|{user_text}",
                            "target_chat_id": target_text,
                            "user_id": user_text,
                            "topic_id": str(topic_id),
                        }
                    )
        if not topic_map:
            topic_map = [{"user_key": "", "target_chat_id": "", "user_id": "", "topic_id": ""}]
        control_groups.append(
            {
                "key": str(key),
                "control_chat_id": group.get("control_chat_id", ""),
                "is_forum": bool(group.get("is_forum", False)),
                "topic_routing_enabled": bool(group.get("topic_routing_enabled", False)),
                "skip_html_report": bool(group.get("skip_html_report", False)),
                "topic_target_map": topic_map,
            }
        )
    if not control_groups:
        control_groups = [blank_control_group()]
    data["control_groups"] = control_groups
    return data


def _full_archive_source_warning(data: dict[str, Any]) -> bool:
    full_archive = data.get("full_archive", {})
    if not _parse_gui_bool(full_archive.get("enabled", False)):
        return False
    source_chat_id = _try_int(full_archive.get("source_chat_id", ""))
    if source_chat_id is None:
        return False
    target_ids = {
        target_id
        for target in data.get("targets", [])
        if (target_id := _try_int(target.get("target_chat_id", ""))) is not None
    }
    return source_chat_id not in target_ids


def blank_target() -> dict[str, Any]:
    return {
        "name": "",
        "target_chat_id": "",
        "summary_interval_minutes": "",
        "control_group": "",
        "tracked_users": [{"id": "", "alias": ""}],
    }


def blank_control_group() -> dict[str, Any]:
    return {
        "key": "",
        "control_chat_id": "",
        "is_forum": False,
        "topic_routing_enabled": False,
        "skip_html_report": False,
        "topic_target_map": [
            {"user_key": "", "target_chat_id": "", "user_id": "", "topic_id": ""}
        ],
    }


def _validate_payload(payload: dict[str, Any], raw_existing: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []

    telegram = payload.get("telegram", {}) or {}
    api_id_raw = str(telegram.get("api_id", "")).strip()
    api_hash_raw = str(telegram.get("api_hash", "")).strip()
    session_file = str(telegram.get("session_file", "data/tgwatch.session")).strip()

    if not api_id_raw:
        errors.append("telegram.api_id is required")
    if api_hash_raw in {"", KEEP_SECRET}:
        api_hash_raw = str(raw_existing.get("telegram", {}).get("api_hash", "")).strip()
    if not api_hash_raw:
        errors.append("telegram.api_hash is required")

    sender = payload.get("sender", {}) or {}
    sender_enabled = bool(sender.get("enabled", False))
    sender_session = str(sender.get("session_file", "")).strip()
    if sender_enabled and not sender_session:
        errors.append("sender.session_file is required when sender is enabled")
    if sender_enabled and sender_session and sender_session == session_file:
        errors.append("sender.session_file must differ from telegram.session_file")

    targets_raw = payload.get("targets", []) or []
    control_raw = payload.get("control_groups", []) or []

    if not targets_raw:
        errors.append("At least one target group is required")
    if len(targets_raw) > MAX_TARGET_GROUPS:
        errors.append(f"Targets cannot exceed {MAX_TARGET_GROUPS}")
    if not control_raw:
        errors.append("At least one control group is required")
    if len(control_raw) > MAX_CONTROL_GROUPS:
        errors.append(f"Control groups cannot exceed {MAX_CONTROL_GROUPS}")

    control_groups: list[dict[str, Any]] = []
    control_keys: list[str] = []
    for idx, raw in enumerate(control_raw, start=1):
        key = str(raw.get("key", "")).strip()
        if not key:
            errors.append(f"Control group #{idx} requires a key")
        if key in control_keys:
            errors.append(f"Duplicate control group key: {key}")
        control_keys.append(key)
        chat_id = _coerce_int(raw.get("control_chat_id"), f"control_groups[{key}].control_chat_id", errors)
        is_forum = bool(raw.get("is_forum", False))
        skip_html_report = bool(raw.get("skip_html_report", False))
        topic_enabled = bool(raw.get("topic_routing_enabled", False))
        topic_map_entries = raw.get("topic_target_map", []) or []
        topic_map = []
        if topic_enabled:
            for entry in topic_map_entries:
                user_key = str(entry.get("user_key", "")).strip()
                target_chat_id = None
                user_id = None
                if user_key:
                    parts = user_key.split("|", 1)
                    if len(parts) == 2:
                        target_chat_id = _coerce_int(
                            parts[0], f"control_groups[{key}].topic_target_map.target_chat_id", errors
                        )
                        user_id = _coerce_int(
                            parts[1], f"control_groups[{key}].topic_target_map.user_id", errors
                        )
                    else:
                        errors.append(f"control_groups[{key}] topic map user selection is invalid")
                else:
                    target_chat_id = _coerce_int(
                        entry.get("target_chat_id"),
                        f"control_groups[{key}].topic_target_map.target_chat_id",
                        errors,
                    )
                    user_id = _coerce_int(
                        entry.get("user_id"),
                        f"control_groups[{key}].topic_target_map.user_id",
                        errors,
                    )
                topic_id = _coerce_int(
                    entry.get("topic_id"), f"control_groups[{key}].topic_target_map.topic_id", errors
                )
                if target_chat_id is not None and user_id is not None and topic_id is not None:
                    topic_map.append(
                        {"target_chat_id": target_chat_id, "user_id": user_id, "topic_id": topic_id}
                    )
        else:
            # Keep existing mappings without strict validation while routing is disabled.
            for entry in topic_map_entries:
                user_key = str(entry.get("user_key", "")).strip()
                target_chat_id = None
                user_id = None
                if user_key:
                    parts = user_key.split("|", 1)
                    if len(parts) == 2:
                        target_chat_id = _try_int(parts[0])
                        user_id = _try_int(parts[1])
                else:
                    target_chat_id = _try_int(entry.get("target_chat_id"))
                    user_id = _try_int(entry.get("user_id"))
                topic_id = _try_int(entry.get("topic_id"))
                if target_chat_id is not None and user_id is not None and topic_id is not None:
                    topic_map.append(
                        {"target_chat_id": target_chat_id, "user_id": user_id, "topic_id": topic_id}
                    )
        if topic_enabled and not is_forum:
            errors.append(f"control_groups[{key}] topic routing requires forum mode")
        if topic_enabled and not topic_map:
            errors.append(f"control_groups[{key}] topic routing requires at least one mapping")
        control_groups.append(
            {
                "key": key,
                "control_chat_id": chat_id,
                "is_forum": is_forum,
                "topic_routing_enabled": topic_enabled,
                "skip_html_report": skip_html_report,
                "topic_target_map": topic_map,
            }
        )

    default_control = control_keys[0] if len(control_keys) == 1 else None

    targets: list[dict[str, Any]] = []
    mapped_users: dict[str, dict[int, set[int]]] = {key: {} for key in control_keys}
    for idx, raw in enumerate(targets_raw, start=1):
        name = str(raw.get("name", "")).strip()
        if not name:
            name = f"group-{idx}"
        chat_id = _coerce_int(raw.get("target_chat_id"), f"targets[{idx}].target_chat_id", errors)
        interval_raw = str(raw.get("summary_interval_minutes", "")).strip()
        interval = None
        if interval_raw:
            interval = _coerce_int(interval_raw, f"targets[{idx}].summary_interval_minutes", errors)
            if interval is not None and interval <= 0:
                errors.append(f"targets[{idx}].summary_interval_minutes must be > 0")
        control_group = str(raw.get("control_group", "")).strip() or default_control
        if not control_group:
            errors.append(f"targets[{idx}] must map to a control_group")
        if control_group and control_group not in control_keys:
            errors.append(f"targets[{idx}] references unknown control_group '{control_group}'")
        tracked_users_raw = raw.get("tracked_users", []) or []
        if not tracked_users_raw:
            errors.append(f"targets[{idx}].tracked_users cannot be empty")
        if len(tracked_users_raw) > MAX_USERS_PER_TARGET:
            errors.append(f"targets[{idx}] cannot exceed {MAX_USERS_PER_TARGET} users")
        tracked_ids: list[int] = []
        aliases: dict[int, str] = {}
        for uidx, entry in enumerate(tracked_users_raw, start=1):
            user_id = _coerce_int(entry.get("id"), f"targets[{idx}].tracked_users[{uidx}].id", errors)
            if user_id is None:
                continue
            if user_id in tracked_ids:
                errors.append(f"targets[{idx}] has duplicate user_id {user_id}")
                continue
            tracked_ids.append(user_id)
            alias = str(entry.get("alias", "")).strip()
            if alias:
                aliases[user_id] = alias
            if control_group and chat_id is not None:
                mapped_users.setdefault(control_group, {}).setdefault(chat_id, set()).add(user_id)
        targets.append(
            {
                "name": name,
                "target_chat_id": chat_id,
                "tracked_user_ids": tracked_ids,
                "tracked_user_aliases": aliases,
                "summary_interval_minutes": interval,
                "control_group": control_group,
            }
        )

    seen_topics: set[tuple[str, int, int]] = set()
    for group in control_groups:
        if not group["topic_routing_enabled"]:
            continue
        allowed_by_target = mapped_users.get(group["key"], {})
        for entry in group["topic_target_map"]:
            target_chat_id = entry["target_chat_id"]
            user_id = entry["user_id"]
            key = (group["key"], target_chat_id, user_id)
            if key in seen_topics:
                errors.append(
                    f"control_groups[{group['key']}] has duplicate topic mapping for "
                    f"{target_chat_id}:{user_id}"
                )
            seen_topics.add(key)
            allowed = allowed_by_target.get(target_chat_id, set())
            if not allowed:
                errors.append(
                    f"control_groups[{group['key']}] topic map references unknown target {target_chat_id}"
                )
                continue
            if user_id not in allowed:
                errors.append(
                    f"control_groups[{group['key']}] topic map includes unknown user {user_id} "
                    f"for target {target_chat_id}"
                )

    reporting = payload.get("reporting", {}) or {}
    storage = payload.get("storage", {}) or {}
    full_archive = payload.get("full_archive", {}) or {}
    display = payload.get("display", {}) or {}
    notifications = payload.get("notifications", {}) or {}
    realtime_raw = payload.get("realtime", {}) or {}

    push_mode = str(realtime_raw.get("push_mode", "interval")).strip().lower()
    if push_mode not in ("interval", "realtime"):
        errors.append("realtime.push_mode must be 'interval' or 'realtime'")
        push_mode = "interval"

    rt_rate_min = _coerce_int(
        realtime_raw.get("rate_limit_per_minute", 20),
        "realtime.rate_limit_per_minute",
        errors,
    ) or 20
    rt_rate_hour = _coerce_int(
        realtime_raw.get("rate_limit_per_hour", 200),
        "realtime.rate_limit_per_hour",
        errors,
    ) or 200
    rt_rate_day = _coerce_int(
        realtime_raw.get("rate_limit_per_day", 1000),
        "realtime.rate_limit_per_day",
        errors,
    ) or 1000
    rt_warmup_rate = _coerce_int(
        realtime_raw.get("warmup_rate", 5),
        "realtime.warmup_rate",
        errors,
    ) or 5
    rt_report_interval = _coerce_int(
        realtime_raw.get("report_interval_minutes", 120),
        "realtime.report_interval_minutes",
        errors,
    ) or 120

    rt_min_interval = _try_float(realtime_raw.get("min_interval_sec", 3.0))
    if rt_min_interval is None or rt_min_interval <= 0:
        rt_min_interval = 3.0
    rt_media_extra = _try_float(realtime_raw.get("media_extra_delay_sec", 2.0))
    if rt_media_extra is None or rt_media_extra <= 0:
        rt_media_extra = 2.0
    rt_warmup_min = _try_float(realtime_raw.get("warmup_minutes", 5.0))
    if rt_warmup_min is None or rt_warmup_min <= 0:
        rt_warmup_min = 5.0

    full_archive_enabled = _parse_gui_bool(full_archive.get("enabled", False))
    full_archive_scope = str(full_archive.get("capture_scope", "whole_group")).strip().lower()
    if full_archive_scope not in ("whole_group", "topics"):
        errors.append("full_archive.capture_scope must be 'whole_group' or 'topics'")
        full_archive_scope = "whole_group"
    full_archive_shard_policy = str(full_archive.get("shard_policy", "monthly")).strip().lower()
    if full_archive_shard_policy != "monthly":
        errors.append("full_archive.shard_policy currently supports only 'monthly'")
        full_archive_shard_policy = "monthly"
    full_archive_source_chat_id = _try_int(full_archive.get("source_chat_id", ""))
    full_archive_topic_ids = _parse_topic_ids_for_gui(
        full_archive.get("topic_ids", ""),
        errors,
    )
    if full_archive_enabled and full_archive_source_chat_id is None:
        errors.append("full_archive.source_chat_id is required when enabled")
    if full_archive_enabled and full_archive_source_chat_id == 0:
        errors.append("full_archive.source_chat_id must not be 0")
    if full_archive_enabled and full_archive_scope == "topics" and not full_archive_topic_ids:
        errors.append("full_archive.topic_ids is required when capture_scope is 'topics'")
    full_archive_max_messages = _coerce_int(
        full_archive.get("max_messages_per_shard", 500000),
        "full_archive.max_messages_per_shard",
        errors,
    ) or 500000
    if full_archive_max_messages <= 0:
        errors.append("full_archive.max_messages_per_shard must be > 0")
        full_archive_max_messages = 500000
    full_archive_max_size = _coerce_int(
        full_archive.get("max_shard_size_mb", 1024),
        "full_archive.max_shard_size_mb",
        errors,
    ) or 1024
    if full_archive_max_size <= 0:
        errors.append("full_archive.max_shard_size_mb must be > 0")
        full_archive_max_size = 1024
    full_archive_backfill_limit = _coerce_int(
        full_archive.get("backfill_limit_messages", 10000),
        "full_archive.backfill_limit_messages",
        errors,
    )
    if full_archive_backfill_limit is None:
        full_archive_backfill_limit = 10000
    if full_archive_backfill_limit < 0:
        errors.append("full_archive.backfill_limit_messages must be >= 0")
        full_archive_backfill_limit = 10000

    normalized = {
        "config_version": 1.0,
        "telegram": {
            "api_id": _coerce_int(api_id_raw, "telegram.api_id", errors) or 0,
            "api_hash": api_hash_raw,
            "session_file": session_file or "data/tgwatch.session",
        },
        "sender": {
            "enabled": sender_enabled,
            "session_file": sender_session,
        },
        "targets": targets,
        "control_groups": control_groups,
        "storage": {
            "db_path": str(storage.get("db_path", "data/tgwatch.sqlite3")).strip(),
            "media_dir": str(storage.get("media_dir", "data/media")).strip(),
        },
        "full_archive": {
            "enabled": full_archive_enabled,
            "root_dir": str(full_archive.get("root_dir", "data/full_archive")).strip()
            or "data/full_archive",
            "source_chat_id": full_archive_source_chat_id,
            "capture_scope": full_archive_scope,
            "topic_ids": full_archive_topic_ids,
            "shard_policy": full_archive_shard_policy,
            "max_messages_per_shard": full_archive_max_messages,
            "max_shard_size_mb": full_archive_max_size,
            "backfill_limit_messages": full_archive_backfill_limit,
        },
        "reporting": {
            "reports_dir": str(reporting.get("reports_dir", "reports")).strip(),
            "summary_interval_minutes": _coerce_int(
                reporting.get("summary_interval_minutes", 120),
                "reporting.summary_interval_minutes",
                errors,
            )
            or 120,
            "timezone": str(reporting.get("timezone", "UTC")).strip() or "UTC",
            "retention_days": _coerce_int(
                reporting.get("retention_days", 30),
                "reporting.retention_days",
                errors,
            )
            or 30,
        },
        "display": {
            "show_ids": bool(display.get("show_ids", True)),
            "time_format": str(display.get("time_format", "%Y.%m.%d %H:%M:%S (%Z)")).strip()
            or "%Y.%m.%d %H:%M:%S (%Z)",
            "language": str(display.get("language", "auto")).strip().lower()
            if str(display.get("language", "auto")).strip().lower() in ("auto", "zh", "en")
            else "auto",
            "template": str(display.get("template", "normal")).strip().lower()
            if str(display.get("template", "normal")).strip().lower() in VALID_DISPLAY_TEMPLATES
            else "normal",
        },
        "notifications": {
            "bark_key": str(notifications.get("bark_key", "")).strip(),
            "heartbeat_interval_hours": max(
                0,
                _coerce_int(
                    notifications.get("heartbeat_interval_hours", 2),
                    "notifications.heartbeat_interval_hours",
                    errors,
                )
                or 2,
            ),
            "check_updates": bool(notifications.get("check_updates", True)),
        },
        "realtime": {
            "push_mode": push_mode,
            "rate_limit_per_minute": rt_rate_min,
            "rate_limit_per_hour": rt_rate_hour,
            "rate_limit_per_day": rt_rate_day,
            "min_interval_sec": rt_min_interval,
            "media_extra_delay_sec": rt_media_extra,
            "warmup_minutes": rt_warmup_min,
            "warmup_rate": rt_warmup_rate,
            "report_interval_minutes": rt_report_interval,
        },
    }

    return errors, normalized


def _coerce_int(value: Any, label: str, errors: list[str]) -> int | None:
    if value is None:
        errors.append(f"{label} is required")
        return None
    if isinstance(value, str):
        value = value.strip()
    if value == "":
        errors.append(f"{label} is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be an integer")
        return None


def _parse_gui_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _try_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    if value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_topic_ids_for_gui(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return ""


def _parse_topic_ids_for_gui(value: Any, errors: list[str]) -> list[int]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        errors.append("full_archive.topic_ids must be a comma-separated list of integers")
        return []
    topic_ids: list[int] = []
    for item in raw_items:
        if item in ("", None):
            continue
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            errors.append("full_archive.topic_ids must be a comma-separated list of integers")
            return []
        if parsed <= 1:
            errors.append(
                "full_archive.topic_ids values must be Telegram forum topic IDs > 1; "
                "use whole_group for General"
            )
            return []
        topic_ids.append(parsed)
    return topic_ids


def _render_toml(config: dict[str, Any], raw_existing: dict[str, Any]) -> str:
    lines: list[str] = []
    config_version = config.get("config_version", 1.0)
    lines.append(f"config_version = {config_version}")
    telegram = config["telegram"]
    api_hash = telegram["api_hash"]
    if api_hash in {"", KEEP_SECRET}:
        api_hash = str(raw_existing.get("telegram", {}).get("api_hash", ""))
    lines.extend(
        [
            "[telegram]",
            f"api_id = {telegram['api_id']}",
            f"api_hash = {toml_string(api_hash)}",
            f"session_file = {toml_string(telegram['session_file'])}",
        ]
    )

    sender = config["sender"]
    if sender.get("enabled"):
        lines.extend(
            [
                "",
                "[sender]",
                f"session_file = {toml_string(sender.get('session_file', ''))}",
            ]
        )

    for target in config["targets"]:
        lines.extend(
            [
                "",
                "[[targets]]",
                f"name = {toml_string(target['name'])}",
                f"target_chat_id = {target['target_chat_id']}",
                f"tracked_user_ids = {toml_list(target['tracked_user_ids'])}",
            ]
        )
        if target.get("summary_interval_minutes"):
            lines.append(f"summary_interval_minutes = {target['summary_interval_minutes']}")
        if target.get("control_group"):
            lines.append(f"control_group = {toml_string(target['control_group'])}")
        aliases = target.get("tracked_user_aliases", {})
        if aliases:
            lines.append("")
            lines.append("[targets.tracked_user_aliases]")
            for user_id, alias in aliases.items():
                lines.append(f"{user_id} = {toml_string(alias)}")

    for group in config["control_groups"]:
        key = group["key"]
        quoted_key = toml_string(str(key))
        lines.extend(
            [
                "",
                f"[control_groups.{quoted_key}]",
                f"control_chat_id = {group['control_chat_id']}",
                f"is_forum = {toml_bool(group['is_forum'])}",
                f"topic_routing_enabled = {toml_bool(group['topic_routing_enabled'])}",
                f"skip_html_report = {toml_bool(group.get('skip_html_report', False))}",
            ]
        )
        topic_map = group.get("topic_target_map", [])
        if topic_map:
            by_target: dict[int, list[dict[str, Any]]] = {}
            for entry in topic_map:
                target_id = entry.get("target_chat_id")
                if target_id is None:
                    continue
                by_target.setdefault(int(target_id), []).append(entry)
            for target_id, entries in by_target.items():
                lines.append("")
                lines.append(
                    f"[control_groups.{quoted_key}.topic_target_map.{toml_string(str(target_id))}]"
                )
                for entry in entries:
                    lines.append(f"{entry['user_id']} = {entry['topic_id']}")

    storage = config["storage"]
    full_archive = config.get("full_archive", {})
    reporting = config["reporting"]
    display = config["display"]
    notifications = config["notifications"]
    realtime = config.get("realtime", {})

    full_archive_lines = [
        "[full_archive]",
        f"enabled = {toml_bool(_parse_gui_bool(full_archive.get('enabled', False)))}",
        f"root_dir = {toml_string(str(full_archive.get('root_dir', 'data/full_archive')))}",
    ]
    if full_archive.get("source_chat_id") not in (None, ""):
        full_archive_lines.append(f"source_chat_id = {full_archive.get('source_chat_id')}")
    full_archive_lines.extend(
        [
            f"capture_scope = {toml_string(str(full_archive.get('capture_scope', 'whole_group')))}",
            f"topic_ids = {toml_list(full_archive.get('topic_ids', []))}",
            f"shard_policy = {toml_string(str(full_archive.get('shard_policy', 'monthly')))}",
            f"max_messages_per_shard = {full_archive.get('max_messages_per_shard', 500000)}",
            f"max_shard_size_mb = {full_archive.get('max_shard_size_mb', 1024)}",
            f"backfill_limit_messages = {full_archive.get('backfill_limit_messages', 10000)}",
        ]
    )

    lines.extend(
        [
            "",
            "[storage]",
            f"db_path = {toml_string(storage['db_path'])}",
            f"media_dir = {toml_string(storage['media_dir'])}",
            "",
            *full_archive_lines,
            "",
            "[reporting]",
            f"reports_dir = {toml_string(reporting['reports_dir'])}",
            f"summary_interval_minutes = {reporting['summary_interval_minutes']}",
            f"timezone = {toml_string(reporting['timezone'])}",
            f"retention_days = {reporting['retention_days']}",
            "",
            "[display]",
            f"template = {toml_string(display.get('template', 'normal'))}",
            f"show_ids = {toml_bool(display['show_ids'])}",
            f"time_format = {toml_string(display['time_format'])}",
            f"language = {toml_string(display.get('language', 'auto'))}",
            "",
            "[notifications]",
            f"bark_key = {toml_string(notifications.get('bark_key', ''))}",
            f"heartbeat_interval_hours = {notifications.get('heartbeat_interval_hours', 2)}",
            f"check_updates = {toml_bool(notifications.get('check_updates', True))}",
            "",
            "[realtime]",
            f"push_mode = {toml_string(realtime.get('push_mode', 'interval'))}",
            f"rate_limit_per_minute = {realtime.get('rate_limit_per_minute', 20)}",
            f"rate_limit_per_hour = {realtime.get('rate_limit_per_hour', 200)}",
            f"rate_limit_per_day = {realtime.get('rate_limit_per_day', 1000)}",
            f"min_interval_sec = {realtime.get('min_interval_sec', 3.0)}",
            f"media_extra_delay_sec = {realtime.get('media_extra_delay_sec', 2.0)}",
            f"warmup_minutes = {realtime.get('warmup_minutes', 5.0)}",
            f"warmup_rate = {realtime.get('warmup_rate', 5)}",
            f"report_interval_minutes = {realtime.get('report_interval_minutes', 120)}",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def toml_string(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', "\\\"")
    return f'"{value}"'


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def toml_list(values: list[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"
