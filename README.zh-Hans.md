# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

关注： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文频道](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## 关键特性

把嘈杂的 Telegram 群/频道变成个人可查询的信号源 —— **完全本地、无需 Bot**。

- **只看重要的人**：在大群里只追踪少量高信号账号（按用户 ID 订阅）。
- **控制群仪表盘**：在控制聊天（收藏消息或你控制的私密群）接收消息与摘要，并用简单指令按需查询（`/last`、`/since`、`/export`，仅你本人账号可用）。
- **定时 HTML 摘要 + 消息流**：HTML 报告包含上下文与媒体快照，并逐条推送每条消息到控制群；每条消息都带可点击的 `MSG` 链接回到原消息。
- **证据留存**：消息与引用文本存入 SQLite，媒体快照保存在磁盘，便于回溯与导出。
- **自动分流**：可选把不同用户分流到各自 Topic（论坛模式），未配置回到 General。
- **长期稳定**：保留清理、心跳/错误提示、FloodWait 退避，适配真实群运行。
- **默认隐私优先**：完全本地运行，不上传、不依赖第三方采集。
- **可选推送镜像**：如需手机提醒，可用 Bark 同步摘要/心跳/错误。

适用场景：社区运营、研究人员、交易者或任何需要 **信号提取 + 本地归档** 的人。

以下章节介绍安装、配置与使用。

## 依赖

- macOS，Python 3.11+
- 在 [my.telegram.org](https://my.telegram.org/) 获取的 Telegram API ID / hash（必须是用户账号）
- 本地存储，无需任何云服务
- 如果需要长期运行守护模式，建议使用可以常开联网的 Mac（如 Mac mini 等）

## 安装

当前尚未发布到 PyPI，需要通过 Git 安装（标签版）或本地可编辑安装。

### 第一步：安装包（推荐：标签版）

**推荐（稳定且可复现）：安装标签版**

> 只想运行 `tgwatch` 并固定版本时选择它。

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.3.1"
python -m tgwatch --help
```

**开发用：可编辑安装**

> 本地改代码时使用。

```bash
pip install -e .
python -m tgwatch --help
```

### 第二步：创建 Python 环境（二选一）

可用系统自带 `venv` 或 Conda，只要 Python ≥ 3.11 即可。

#### 方式 A：`python -m venv`（推荐）

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

#### 方式 B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

> 提示：运行命令前只需激活一种环境（`.venv` 或 `conda`）。命令行前缀应显示 `(.venv)` 或 `(tgwatch)`。

### 第三步：继续完成相同流程

安装完成并激活环境后：

1) 复制 `config.example.toml` → `config.toml`
2) 运行 `tgwatch doctor`
3) 运行 `tgwatch once --since 2h --push` 做测试
4) 运行 `tgwatch run` 进入守护模式

## 配置

1. 复制示例配置：

   ```bash
   cp config.example.toml config.toml
   ```

   提示：可使用本地 GUI 配置（默认 `http://127.0.0.1:8765`）：

   ```bash
   tgwatch gui
   ```

2. 启动本地 GUI（推荐）进行配置：

   ```bash
   tgwatch gui
   ```

   仍可直接编辑 `config.toml`，但不推荐，容易出错。

3. 若选择手动编辑文件，请填写以下字段：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（默认 `data/tgwatch.session`）
   - `[sender] session_file`（可选：用于桥接发送的第二账号 session，使主账号能收到通知）
   - `targets[].name`（每个目标群的名称/标签）
   - `targets[].target_chat_id`（目标群/频道 ID）
   - `targets[].tracked_user_ids`（需要跟踪的用户 ID 列表）
   - `targets[].summary_interval_minutes`（可选：每个目标群的报告频率）
   - `targets[].control_group`（可选；当存在多个控制群时必填）
   - `[targets.tracked_user_aliases]`（可选的 ID→别名映射）
   - `control_groups.<name>.control_chat_id`（接收报告与命令的控制群）
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_user_map]`（可选：按用户分流到 TG Topic）
   - `storage.db_path` 与 `storage.media_dir`
   - `reporting.reports_dir` 与 `reporting.summary_interval_minutes`（默认报告频率）
   - `reporting.timezone`（如 `Asia/Shanghai`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（报告/媒体保留天数，默认 30，超过 180 会提示确认）
   - `[notifications] bark_key`（可选的 Bark Key，用于手机推送）
   - `[display] show_ids`（是否显示 ID，默认 true）与 `time_format`（strftime 格式字符串）控制控制群推送的姓名/时间展示

单一群组配置仍可使用旧版 `[target]` + `[control]` 写法。

### Bark Key 获取指南

1. 在手机上安装 Bark App，打开后点击右上角齿轮 → “复制设备码”，得到 `xxxxxxxxxxxxxxxxxxxxxxxx` 的 Key。
2. 在 `config.toml` 中填入：

   ```toml
   [notifications]
   bark_key = "你的BarkKey"
   ```

3. 启动 `tgwatch run ...`，报告/心跳/错误就会以 “Telegram Watch” 分组推送到 Bark。

详细步骤、如何获取群 ID/用户 ID、路径选择等请参考 [docs/configuration.md](docs/configuration.md)。

> ⚠️ 不要将 `config.toml`、会话文件、`data/`、`reports/` 等敏感内容提交到版本管理。

## 使用

所有命令均可通过 `python -m tgwatch ...` 或 `tgwatch ...` 执行，记得传入 `--config`。

### Doctor

检查配置、目录权限与 SQLite 架构：

```bash
python -m tgwatch doctor --config config.toml
```

### GUI（本地配置界面）

启动本地 UI 来管理目标群与控制群（会自动打开浏览器）：

```bash
tgwatch gui
```

### Once（单次报告）

抓取最近窗口的消息（如 2 小时）、写入数据库并为每个目标群生成 `reports/YYYY-MM-DD/HHMM/index.html`：

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

- 持续监听每个目标群，跟踪用户消息会被写入（文本、引用、媒体快照）。
- 在各目标群的 `summary_interval_minutes` 窗口结束时（或全局默认），生成 HTML 报告并推送到对应控制群，同时逐条发送该窗口内的跟踪消息。
- 报告内的图片默认以内联 Base64 存储；若文件读取失败，会退回相对路径。
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
- Flood-wait 退避应用于 Telegram API 调用（发送、下载、实体解析）。

## Changelog

版本更新记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## License

MIT，详见 `LICENSE`。
