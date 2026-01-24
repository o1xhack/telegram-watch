# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

关注： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文频道](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## 亮点

全程在本地运行的 Telegram 监听工具，基于 Telethon 打造。主要特性：

- **用户级监听**：使用你的 Telegram 用户账户（非 Bot）登录，实时关注指定超级群/频道中的一组用户。
- **信息完整采集**：同步保存文本、引用上下文、媒体快照到 SQLite 与本地媒体目录。
- **自动化报告**：按自定义窗口（5~120 分钟等）生成 HTML 报告，推送到控制群后依次发送窗口内的所有跟踪消息，`MSG` 链接可一键回到 Telegram 原消息。
- **内联媒体**：报告中的图片以 Base64 形式内嵌，即使在 Telegram 或手机中直接打开 HTML 也能看到图片。
- **心跳与告警**：连续 2 小时无活动则发送 “Watcher is still running”；若程序异常退出，会把错误摘要推送到控制群，同时保留终端日志。
- **保留策略**：通过 `reporting.retention_days`（默认 30 天）定期清理旧报告/媒体；设置超过 180 天会在启动前提示确认。
- **可选 Bark 推送**：配置 Bark Key 后，报告/心跳/错误都会以 “Telegram Watch” 分组推送到手机。

以下章节介绍安装、配置与常用命令。

## 依赖

- macOS，Python 3.11+
- 在 [my.telegram.org](https://my.telegram.org/) 获取的 Telegram API ID / hash（必须是用户账号）
- 本地存储，无需任何云服务

## 安装

可选择系统自带的 `venv` 或 Conda，确保 Python ≥ 3.11。

### 方式 A：`python -m venv`

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
```

### 方式 B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -e .
```

> 提示：运行命令前只需激活一种环境（`.venv` 或 `conda`）。命令行前缀应显示 `(.venv)` 或 `(tgwatch)`。

## 配置

1. 复制示例配置：

   ```bash
   cp config.example.toml config.toml
   ```

2. 编辑 `config.toml`，填写以下字段：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（默认 `data/tgwatch.session`）
   - `target.target_chat_id`（目标群/频道 ID）
   - `target.tracked_user_ids`（需要跟踪的用户 ID 列表）
   - `[target.tracked_user_aliases]`（可选的 ID→别名映射）
   - `control.control_chat_id`（接收报告与命令的控制群）
   - `storage.db_path` 与 `storage.media_dir`
   - `reporting.reports_dir` 与 `reporting.summary_interval_minutes`（报告频率）
   - `reporting.timezone`（如 `Asia/Shanghai`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（报告/媒体保留天数，默认 30，超过 180 会提示确认）
   - `[notifications] bark_key`（可选的 Bark Key，用于手机推送）

### Bark Key 获取指南

1. 在手机上安装 Bark App，打开后点击右上角齿轮 → “复制设备码”，得到 `xxxxxxxxxxxxxxxxxxxxxxxx` 的 Key。
2. 在 `config.toml` 中填入：

   ```toml
   [notifications]
   bark_key = "你的BarkKey"
   ```

3. 启动 `tgwatch run ...`，报告/心跳/错误就会以 “Telegram Watch” 分组推送到 Bark。

详细步骤、如何获取群 ID/用户 ID、路径选择等请参考 `docs/configuration.md`。

> ⚠️ 不要将 `config.toml`、会话文件、`data/`、`reports/` 等敏感内容提交到版本管理。

## 使用

所有命令均可通过 `python -m tgwatch ...` 或 `tgwatch ...` 执行，记得传入 `--config`。

### Doctor

检查配置、目录权限与 SQLite 架构：

```bash
python -m tgwatch doctor --config config.toml
```

### Once（单次报告）

抓取最近窗口的消息（如 2 小时）、写入数据库并生成 `reports/YYYY-MM-DD/HHMM/index.html`：

```bash
python -m tgwatch once --config config.toml --since 2h
# 加上 --push 可立即把报告与消息推送到控制群，方便调试
python -m tgwatch once --config config.toml --since 2h --push
```

### Run（守护模式）

首次运行需在终端输入 Telegram 验证码：

```bash
python -m tgwatch run --config config.toml
```

运行时：

- 持续监听目标群，实时写入文本、引用、媒体。
- 在每个 `summary_interval_minutes` 窗口结束时，生成 HTML 报告并推送到控制群，同时逐条发送该窗口内的跟踪消息。
- HTML 报告的图片以内联 Base64 存储，可直接在 Telegram 中预览。
- 控制群支持以下命令（仅限你本人发起）：
  - `/help`
  - `/last <user_id|@username> [N]`
  - `/since <10m|2h|ISO>`
  - `/export <10m|2h|ISO>`

## 测试

```bash
pytest
```

## 隐私与安全

- 完全在你的 Mac 上运行，不使用云端。
- 不写入 API hash、手机号或聊天内容到日志。
- `config.toml`、会话文件、数据目录均已加入 `.gitignore`。
- Telethon 带有 Flood-wait 退避机制，登录、下载、推送更稳定。

## License

MIT，详见 `LICENSE`。
