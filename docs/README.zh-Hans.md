# telegram-watch

[English](../README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

[![Release](https://img.shields.io/github/v/release/o1xhack/telegram-watch?style=for-the-badge&label=release&color=7c3aed)](https://github.com/o1xhack/telegram-watch/releases/latest)
[![Stars](https://img.shields.io/github/stars/o1xhack/telegram-watch?style=for-the-badge&label=stars&color=7c3aed)](https://github.com/o1xhack/telegram-watch/stargazers)
[![License](https://img.shields.io/github/license/o1xhack/telegram-watch?style=for-the-badge&label=license&color=7c3aed)](../LICENSE)

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-o1xhack-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/o1xhack)

**文档版本：** `v1.0.7`（release `v1.7.0`）

关注： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文频道](https://t.me/lalabeng) · [Telegram 中文频道](https://t.me/o1xinsight)

## 关键特性

把嘈杂的 Telegram 群/频道变成私有、结构化的信号系统 —— **完全本地、无需 Bot**。

![telegram-watch GUI](assets/tgwatch-gui-v1.png)

- **多目标监控**：同时追踪多个群/频道，每个目标可独立配置用户名单、别名和汇总间隔。
- **控制群路由**：每个目标可绑定到指定控制群，方便按场景拆分工作流。
- **按目标 Topic 映射**：在论坛模式下按 `target_chat_id + user_id` 映射 Topic，同一用户在不同来源群可走不同 Topic。
- **GUI 优先配置**：凭据、目标、控制群、映射与存储都可在本地 GUI 里完成——根据浏览器语言自动切换中文或英文界面。
- **一键本地启动器**：启动流程为 Conda（`tgwatch`）优先，自动回退到 `venv`。
- **GUI 运行控制**：支持 Run once（可选单目标与 push）、Run daemon、Stop daemon，并可查看实时日志。
- **安全运行护栏**：启动前 session 检查、长保留窗口确认、以及界面内可见错误提示。
- **自动重连**：daemon 模式在临时网络故障时自动重连（指数退避），恢复后向控制群发送通知。
- **默认本地持久化**：消息归档到 SQLite，媒体快照落盘，自动生成 HTML 报告。
- **即时推送模式** *（实验性）*：被追踪用户的消息到达后立即转发至控制群组，内置 7 层速率防护体系，防止账号受限。
- **隐私优先设计**：不依赖云服务、不记录敏感密钥，运行时敏感文件默认不进 git。

适用场景：社区运营、研究人员、交易者或任何需要 **信号提取 + 本地归档** 的人。

## 快速开始

5 步上手。你需要：**macOS + Python 3.11+** 以及一个 Telegram 用户账号。

### 1. 获取 Telegram API 凭据

前往 [my.telegram.org](https://my.telegram.org/)，用手机号登录，创建应用以获取 **API ID** 和 **API Hash**。

### 2. 克隆仓库

克隆稳定 release 版本（推荐）：

```bash
git clone --branch v1.7.0 https://github.com/o1xhack/telegram-watch.git
cd telegram-watch
```

> 也可以克隆 `main` 获取最新代码：`git clone https://github.com/o1xhack/telegram-watch.git`

### 3. 双击启动器

在 Finder 中双击 **`launch_tgwatch.command`**，它会自动：
- 创建 Python 环境（有 Conda 用 Conda `tgwatch`，否则用 `.venv`）
- 安装所有依赖
- 若缺失则复制 `config.example.toml` → `config.toml`
- 在浏览器中打开 GUI

### 4. 在 GUI 中配置

GUI 打开后（`http://127.0.0.1:8765`）：
1. 在 Telegram 区域填入 **API ID** 和 **API Hash**
2. 添加一个或多个 **Target**（要监控的群/频道及跟踪用户 ID）
3. 添加一个 **Control Group**（报告和消息推送的目标群）
4. 点击 **Save**

### 5. 首次登录（终端）

首次运行需在终端输入 Telegram 验证码：

```bash
# 如果用了启动器，先激活同一环境：
# Conda: conda activate tgwatch
# venv:  source .venv/bin/activate

python -m tgwatch run --config config.toml
```

按提示输入手机号和验证码。连接成功后守护进程即开始运行。按 `Ctrl+C` 停止，或以后直接在 GUI 中使用 **Run daemon** / **Stop daemon**。

> **提示**：首次登录后，后续启动/停止都可以在 GUI 中完成，无需再用终端。

## 手动安装

<details>
<summary>面向开发者，或不想用启动器时使用</summary>

### 创建 Python 环境（二选一）

#### 方式 A：venv（推荐）

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

#### 方式 B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

### 安装包

**可编辑安装（开发用）：**

```bash
pip install -e .
```

**标签版安装（稳定、版本固定）：**

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.8.0"
```

### 配置与运行

```bash
cp config.example.toml config.toml
tgwatch gui          # 在 GUI 中编辑配置，或手动编辑 config.toml
tgwatch doctor       # 验证配置
tgwatch once --since 2h --push   # 测试运行
tgwatch run          # 启动守护模式
```

</details>

## 配置

**推荐使用 GUI**（`tgwatch gui` 或启动器）—— 覆盖所有设置项且不易出错。

如需手动编辑 `config.toml`，完整字段说明见 [configuration.md](configuration.md)。关键字段：

| 区块 | 字段 | 说明 |
|------|------|------|
| `telegram` | `api_id`、`api_hash` | Telegram API 凭据 |
| `telegram` | `session_file` | Session 路径（默认 `data/tgwatch.session`） |
| `sender` | `session_file` | 可选的第二账号 session |
| `targets[]` | `target_chat_id`、`tracked_user_ids` | 监控目标 |
| `targets[]` | `name`、`tracked_user_aliases` | 可选标签与别名 |
| `targets[]` | `summary_interval_minutes`、`control_group` | 每目标覆盖项 |
| `control_groups.<name>` | `control_chat_id` | 报告推送目标 |
| `control_groups.<name>` | `is_forum`、`topic_routing_enabled`、`topic_target_map` | Topic 路由 |
| `control_groups.<name>` | `skip_html_report` | 跳过 HTML 文件，仅发逐条消息 |
| `reporting` | `reports_dir`、`summary_interval_minutes`、`timezone`、`retention_days` | 报告设置 |
| `storage` | `db_path`、`media_dir` | 本地存储路径 |
| `notifications` | `bark_key` | 可选 Bark 手机推送 |
| `display` | `show_ids`、`time_format` | 显示格式 |
| `realtime` | `push_mode` | `"interval"`（默认）或 `"realtime"`（实验性） |
| `realtime` | `rate_limit_per_minute`、`rate_limit_per_hour`、`rate_limit_per_day` | 速率防护限制 |

单一群组配置仍可使用旧版 `[target]` + `[control]` 写法。

### 单目标 Run once

`tgwatch once` 默认跑所有目标群。若只跑单个群，传目标名称或 `target_chat_id`：

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

### 旧配置迁移

从旧配置升级（缺少 `config_version`）时，tgwatch 会停止并提示迁移。

1. GUI 会锁定并显示 **Migrate Config** 按钮。
2. CLI 的 `run`/`once` 会红色提示并询问是否迁移。
3. 迁移会将 `config.toml` 重命名为 `config-old-0.1.toml`，并写入新 `config.toml`（尽量迁移旧值）。

### Bark 推送

1. 手机安装 Bark App，点齿轮 → 复制设备码。
2. 在配置中填入 `[notifications]` → `bark_key = "你的Key"`（或在 GUI 中设置）。
3. 报告、心跳、错误会以"Telegram Watch"分组推送到 Bark。

### 即时推送模式 *（实验性）*

默认情况下，tgwatch 会收集消息并定期汇总发送（"interval"模式）。**即时模式**会在消息到达的一刹那将其转发至控制群组。

1. 在 GUI 中找到 **Realtime Push Mode** 区块，切换为 **Realtime (Experimental)**。
2. 确认风险提示对话框（超出速率限制可能导致账号受限）。
3. 如有需要可调整速率防护参数 — 默认值已偏保守。

即时模式内置 **7 层速率防护**：滑动窗口限流（20 条/分钟）、随机抖动间隔（3 秒 ± 1 秒）、媒体额外延迟（+2 秒）、每小时/每日上限（200/时、1000/天）、FloodWait 指数退避、熔断器（自动暂停 30 分钟 + Bark 告警）、启动冷却期（5 分钟 @ 5 条/分钟）。详见[配置指南](configuration.zh-Hans.md)。

> ⚠️ 不要将 `config.toml`、会话文件、`data/`、`reports/` 等敏感内容提交到版本管理。

## 使用

所有命令：`python -m tgwatch <cmd>` 或 `tgwatch <cmd>`，始终传入 `--config config.toml`。

### Doctor

检查配置、目录权限与 SQLite 架构：

```bash
tgwatch doctor --config config.toml
```

### GUI（本地配置界面）

启动本地 UI（默认 `http://127.0.0.1:8765`）：

```bash
tgwatch gui
```

GUI 提供 **Run once**、**Run daemon**、**Stop daemon** 按钮并显示运行日志。`Run daemon` 会启动后台进程，关闭浏览器不会停止运行；重新打开 GUI 会继续显示日志。

### Once（单次报告）

抓取最近窗口的消息、写入数据库并生成 HTML 报告：

```bash
tgwatch once --config config.toml --since 2h
# 加上 --push 可立即推送到控制群
tgwatch once --config config.toml --since 2h --push
```

### Run（守护模式）

首次运行需在终端输入 Telegram 验证码：

```bash
tgwatch run --config config.toml
```

运行时：
- 持续监听每个目标群，跟踪用户消息会被写入（文本、引用、媒体快照）。
- 按各目标群的汇总间隔生成 HTML 报告并推送到对应控制群，同时逐条推送消息。
- 控制群支持命令（仅限你本人发起）：`/help`、`/last`、`/since`、`/export`。

## GitHub Actions（自动每日抓取）

可以通过 GitHub Actions 定时运行 `tgwatch once` —— 无需本地守护进程。Fork 本仓库，配置两个 GitHub Secret 即可。

### 所需 GitHub Secrets

| Secret | 内容 | 如何生成 |
|--------|------|----------|
| `TGWATCH_CONFIG_TOML` | `config.toml` 的完整内容 | 直接复制粘贴文件内容 |
| `TELEGRAM_SESSION_BASE64` | Base64 编码的 session 文件 | 见下方步骤 |

### 配置步骤

1. **本地登录一次**以生成 session 文件：

   ```bash
   pip install -e .
   cp config.example.toml config.toml
   # 填入 api_id、api_hash、target_chat_id、tracked_user_ids 等
   tgwatch once --config config.toml --since 1m
   # 按提示输入手机号和验证码
   ```

2. **编码 session 文件**：

   ```bash
   # macOS
   base64 -i data/tgwatch.session
   # Linux
   base64 data/tgwatch.session
   ```

3. **添加 Secrets**：在 fork 仓库的 Settings → Secrets and variables → Actions → New repository secret。
   - `TGWATCH_CONFIG_TOML`：粘贴 `config.toml` 内容
   - `TELEGRAM_SESSION_BASE64`：粘贴 base64 输出

4. **完成。** 工作流每天 UTC 02:00 自动运行。也可在 Actions 页面手动触发，自定义时间窗口（如 `48h`）。

### 工作原理

- 工作流从 Secrets 中还原 `config.toml` 和 session 文件
- 运行 `tgwatch once --since 24h` 抓取最近 24 小时的消息
- 将 HTML 报告和 SQLite 数据库上传为 GitHub Actions Artifact（保留 30 天）
- 每次运行后清理敏感文件

### 注意事项

- **Session 失效**：如果在 Telegram「活跃会话」中撤销了该 session，工作流会报错。重新在本地执行步骤 1–3 即可。
- **隐私**：配置和 session 文件通过 Secret 注入，不会提交到仓库。Artifact 仅对仓库协作者可见。
- **无 AI 总结**：当前工作流仅采集原始消息并生成 HTML 报告。基于 LLM 的智能总结为后续规划功能。

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
