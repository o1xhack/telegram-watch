# telegram-watch

[English](../README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

**文档版本：** `v1.0.4`

关注： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文频道](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## 关键特性

把嘈杂的 Telegram 群/频道变成私有、结构化的信号系统 —— **完全本地、无需 Bot**。

![telegram-watch GUI](assets/tgwatch-gui-v1.png)

- **多目标监控**：同时追踪多个群/频道，每个目标可独立配置用户名单、别名和汇总间隔。
- **控制群路由**：每个目标可绑定到指定控制群，方便按场景拆分工作流。
- **按目标 Topic 映射**：在论坛模式下按 `target_chat_id + user_id` 映射 Topic，同一用户在不同来源群可走不同 Topic。
- **GUI 优先配置**：凭据、目标、控制群、映射与存储都可在本地 GUI 里完成。
- **一键本地启动器**：启动流程为 Conda（`tgwatch`）优先，自动回退到 `venv`。
- **GUI 运行控制**：支持 Run once（可选单目标与 push）、Run daemon、Stop daemon，并可查看实时日志。
- **安全运行护栏**：启动前 session 检查、长保留窗口确认、以及界面内可见错误提示。
- **默认本地持久化**：消息归档到 SQLite，媒体快照落盘，自动生成 HTML 报告。
- **隐私优先设计**：不依赖云服务、不记录敏感密钥，运行时敏感文件默认不进 git。

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
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.0.4"
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

   一键方式：双击 `launch_tgwatch.command`（macOS）或 `launch_tgwatch.bat`（Windows）。启动器现在优先使用 Conda（环境名 `tgwatch`）：若检测到 Conda 则复用/创建 `tgwatch`，若没有 Conda 则回退 `.venv`。随后安装依赖、如缺失则复制 `config.toml`，并打开 GUI。macOS 启动器已兼容 bash；若在受限网络下 `pip/setuptools/wheel` 升级失败，会给出警告并继续尝试安装项目。

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

   - `config_version`（必须为 `1.0`）
   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（默认 `data/tgwatch.session`）
   - `[sender] session_file`（可选：用于桥接发送的第二账号 session，使主账号能收到通知）
   - `targets[].name`（可选标签；未填写时会显示为 `group-1`、`group-2` 等）
   - `targets[].target_chat_id`（目标群/频道 ID）
   - `targets[].tracked_user_ids`（需要跟踪的用户 ID 列表）
   - `targets[].summary_interval_minutes`（可选：每个目标群的报告频率）
   - `targets[].control_group`（可选；当存在多个控制群时必填）
   - `[targets.tracked_user_aliases]`（可选的 ID→别名映射）
   - `control_groups.<name>.control_chat_id`（接收报告与命令的控制群）
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_target_map.<target_chat_id>]`（可选：按用户分流到 TG Topic）
   - `storage.db_path` 与 `storage.media_dir`
   - `reporting.reports_dir` 与 `reporting.summary_interval_minutes`（默认报告频率）
   - `reporting.timezone`（如 `Asia/Shanghai`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（报告/媒体保留天数，默认 30；超过 180 时，CLI 会提示确认，GUI 会走界面内确认流程）
   - `[notifications] bark_key`（可选的 Bark Key，用于手机推送）
   - `[display] show_ids`（是否显示 ID，默认 true）与 `time_format`（strftime 格式字符串）控制控制群推送的姓名/时间展示

单一群组配置仍可使用旧版 `[target]` + `[control]` 写法。

### 单目标 Run once

`tgwatch once` 默认会跑所有目标群。若只想跑单个群，可传目标名称或 `target_chat_id`：

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

GUI 的 Run once 区域新增 **Push to control chat** 选项（默认关闭）。

### 迁移

如果从旧配置升级（缺少 `config_version`），tgwatch 会停止并提示迁移。

1. GUI 会锁定并显示 **Migrate Config** 按钮。
2. CLI 的 `run`/`once` 会红色提示并询问是否迁移。
3. 迁移会将 `config.toml` 重命名为 `config-old-0.1.toml`，并写入新的 `config.toml`（尽量迁移旧值）。

请在再次运行前检查新的 `config.toml`。`config-old-0.1.toml` 等备份文件已被 git 忽略。

### Bark Key 获取指南

1. 在手机上安装 Bark App，打开后点击右上角齿轮 → “复制设备码”，得到 `xxxxxxxxxxxxxxxxxxxxxxxx` 的 Key。
2. 在 `config.toml` 中填入：

   ```toml
   [notifications]
   bark_key = "你的BarkKey"
   ```

3. 启动 `tgwatch run ...`，报告/心跳/错误就会以 “Telegram Watch” 分组推送到 Bark。

详细步骤、如何获取群 ID/用户 ID、路径选择等请参考 [configuration.md](configuration.md)。

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

GUI 还提供 **Run once**、**Run daemon**、**Stop daemon** 按钮并显示运行日志。`Run daemon` 会启动后台进程，关闭浏览器不会停止运行；重新打开 GUI 会继续显示日志。若尚未生成 session 文件，请先在终端运行一次 `python -m tgwatch run --config config.toml` 完成登录，再使用 GUI 触发运行。
当 `retention_days > 180` 时，点击 **Run daemon** 会先出现界面内确认区。勾选风险确认后，**Confirm & Start Run** 才可点击。若操作失败，Runner 消息区会显示错误信息。

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

版本更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## License

MIT，详见 `LICENSE`。
