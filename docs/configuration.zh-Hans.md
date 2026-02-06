# 配置指南

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

**文档版本：** `v1.0.0`

`tgwatch` 会从 `config.toml` 读取所有运行参数。该文件应仅保存在本机，禁止提交或分享。按以下步骤填写所有字段后再运行 `python -m tgwatch ...`。

## 1. 复制示例配置

```bash
cp config.example.toml config.toml
```

一键方式：双击 `launch_tgwatch.command`（macOS）或 `launch_tgwatch.bat`（Windows）。启动器优先使用 Conda（环境名 `tgwatch`）：有 Conda 时会复用/创建 `tgwatch`，无 Conda 时回退 `.venv`。随后安装依赖、如缺失则复制 `config.toml`，并打开 GUI。macOS 启动器兼容 bash；受限网络下若 `pip/setuptools/wheel` 升级失败，会提示警告并继续尝试安装项目。

请确保文件顶部包含 `config_version = 1.0`，旧版本将被拒绝运行。

如果你是从旧配置升级（缺少 `config_version`），tgwatch 会停止并提示迁移。迁移会将 `config.toml` 备份为 `config-old-0.1.toml`，并创建新的 `config.toml`（尽量迁移旧值）。请在运行前检查新文件。备份文件已被 git 忽略。

在首次登录前必须编辑所有字段。

推荐：启动本地 GUI（默认 `http://127.0.0.1:8765`）进行配置：

```bash
tgwatch gui
```

GUI 提供 **Run once** / **Run daemon** / **Stop daemon** 按钮与运行日志。若 session 文件尚未生成，请先在终端运行一次 `python -m tgwatch run --config config.toml` 完成登录。
你也可以在 GUI 中选择单个目标群，或在 CLI 上使用 `--target`（名称或 `target_chat_id`）来限制 **Run once** 的执行范围。GUI 里还有 **Push to control chat** 开关（默认关闭），日志面板最多显示 200 行并可滚动，空日志保持紧凑高度。
当 `retention_days > 180` 时，点击 **Run daemon** 会弹出界面内确认区；勾选风险确认后，点击 **Confirm & Start Run** 才会启动。

## 2. Telegram 凭据（`[telegram]`）

字段 | 获取方式 | 说明
----- | -------- | ----
`api_id` | 用监控所用手机号登录 [my.telegram.org](https://my.telegram.org) → **API development tools** → 创建应用 → 复制数字 `App api_id`。 | 必须是用户账号，不要使用 Bot Token。
`api_hash` | 与 `api_id` 同页，复制 `App api_hash`。 | 视为密码，勿记录或分享。
`session_file` | Telethon 会话文件路径，默认 `data/tgwatch.session`。 | 路径建议保留在仓库内但需 git 忽略；如移到其他位置，确保目录可读写。

首次运行（`python -m tgwatch run ...`）会在终端提示输入验证码，并自动生成 session 文件。

## 3. 发送端账号（可选）（`[sender]`）

用于“双账号桥接”：账号 A 负责抓取，账号 B 负责发送控制群消息，从而让账号 A 能收到通知。

字段 | 含义 | 说明
----- | ---- | ----
`session_file` | 发送端账号（账号 B）的 session 文件路径。 | 只要设置了 `[sender]` 就必须填写。与 `[telegram]` 共用同一 `api_id` / `api_hash`，但路径必须与 `telegram.session_file` 不同。

首次运行会分别提示登录账号 B。请确保账号 B 已加入控制群并拥有发言权限。不需要桥接时可省略 `[sender]`。

## 4. 目标群（`[[targets]]`）

每个 `[[targets]]` 条目代表一个要监控的群/频道。若只有一个目标群，旧版 `[target]` 仍可用，但推荐使用多目标格式。限制：最多 5 个目标群、每群最多 5 个用户、最多 5 个控制群。仍支持手动编辑，但更容易出错。

字段 | 含义 | 获取方式
----- | ---- | ----
`name` | 目标群的可选标签 | 用于日志/GUI；不填写时会自动标为 `group-1`、`group-2` 等
`target_chat_id` | 目标群/频道的数字 ID，超级群/频道以 `-100` 开头。 | 在 Telegram Desktop/手机中打开群 → 点击标题 → 复制邀请链接 → 发送给 `@userinfobot`/`@getidsbot`/`@RawDataBot`，机器人会返回 `chat_id = -100...`。若无法分享链接，见下方“私有群无邀请链接”。
`tracked_user_ids` | 需要监控的用户 ID 列表。 | 让目标用户给 `@userinfobot` 发送消息并把 ID 转发给你，或把 `@userinfobot` 拉进群后 `/whois @username`。用真实 ID 替换示例列表（`[11111111, 22222222]`）。
`summary_interval_minutes` | 可选：该目标群的报告频率 | 未填写则使用 `reporting.summary_interval_minutes`
`control_group` | 该目标群对应的控制群 | 当存在多个控制群时必填；只有一个控制群时可省略

提示：

- ID 必须是数字，用户名不生效。
- 只填写需要追踪的人，其它成员会被忽略。
- 超级群务必保留 `-100` 前缀，才能让报告里的 `MSG` 链接正确跳回 Telegram。
- 不填写 `name` 时，tgwatch 会按顺序显示为 `group-1`、`group-2` 等。

### 可选别名

为了更易读，可给每个用户 ID 添加别名（按目标群配置）：

```toml
[[targets]]
name = "group-1"
target_chat_id = -1001234567890
tracked_user_ids = [11111111, 22222222]

[targets.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

每个 key 必须在该目标群的 `tracked_user_ids` 列表中。报告与控制群推送会显示 `Alice (11111111)`。

### 私有群无邀请链接

如果群没有邀请链接，可以用以下方式拿到 `target_chat_id`：

1. **转发消息给 ID 机器人**  
   将群内任意消息转发给 `@userinfobot` 或 `@RawDataBot`，机器人会返回 `Chat ID: -100...`。转发时需关闭“隐藏发送者”。
2. **临时拉入 ID 机器人**  
   若无法转发，请让管理员临时邀请 `@userinfobot` 进群，执行 `/mychatid` 或 `/whois`，记录数字 ID 后移除机器人。
3. **使用 Telegram Desktop 开发者信息**  
   在 macOS 上使用 Telegram Desktop（Qt 版）：
   1. 菜单 `Telegram Desktop` → **Preferences…**（`⌘,`）。
   2. **Advanced** → **Experimental settings** → 开启 **Enable experimental features** 与 **Show message IDs**。
   3. 回到群聊右键消息 → **Copy message link**。链接形如 `https://t.me/c/1234567890/55`，转换为 `-1001234567890` 后填入 `target_chat_id`。

若仅有原生 macOS “Telegram” 应用（圆形图标）且无 Advanced 菜单，请安装 Desktop 版或使用网页版（`https://web.telegram.org/k/`），地址栏会显示 `#-1001234567890`。

## 5. 控制群（`[control_groups]`）

控制群用于接收报告并下发命令（`/last`、`/since` 等）。可配置多个控制群，并通过 `targets[].control_group` 进行映射。

字段 | 描述 | 建议
----- | ---- | ----
`control_chat_id` | 控制群位置，用于接收摘要和执行命令。 | 建议使用“Saved Messages”或仅你可控的小群，并确保你的账号在群内。
`is_forum` | 控制群是否开启 Topics（论坛模式）。 | 普通群或“Saved Messages”保持 `false`。
`topic_routing_enabled` | 启用按用户路由到 Topics。 | 不需要时保持 `false`。
`topic_target_map` | 追踪用户 ID → Topic ID 映射（按目标群 chat_id 区分）。 | 仅在 `topic_routing_enabled = true` 时填写。

若只有一个控制群，`targets[].control_group` 可省略；若存在多个控制群，则每个目标群都必须指定 `control_group`。

### Topic 路由（论坛群）

当 `is_forum = true` 且 `topic_routing_enabled = true` 时，tgwatch 会将每个追踪用户在对应目标群中的消息推送到 Topic。未在该目标群的 `topic_target_map` 中映射的用户会回退到 General 主题。
启用 Topic 路由时，HTML 报告也会按用户拆分，并在消息流之前发送到对应 Topic。

示例：

```toml
[control_groups.main]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control_groups.main.topic_target_map."-1001234567890"]
11111111 = 9001  # Alice -> Topic A
22222222 = 9002  # Bob -> Topic B
```

#### 如何获取 Topic ID

Topic ID 即创建该 Topic 的系统消息 ID。获取方式：

1. 打开控制群并进入目标 Topic。
2. 找到该 Topic 的创建系统消息（或该 Topic 的第一条消息）。
3. 右键消息选择 **Copy message link**。
4. 链接形如 `https://t.me/c/1234567890/9001`，最后的数字（`9001`）就是 Topic ID。

General 主题固定 ID 为 `1`。关闭 Topic 路由时默认发送到 General。

## 6. 本地存储（`[storage]`）

字段 | 描述 | 默认值
----- | ---- | ------
`db_path` | SQLite 数据库路径。 | `data/tgwatch.sqlite3`
`media_dir` | 媒体文件保存目录。 | `data/media`

可保留默认值或设置为可写路径。`doctor` 会检查目录可创建且数据库可写。

## 7. 报告（`[reporting]`）

字段 | 描述 | 默认值
----- | ---- | ------
`reports_dir` | HTML 报告根目录，子目录按 `reports/YYYY-MM-DD/HHMM/index.html` 组织。 | `reports`
`summary_interval_minutes` | `run` 的默认报告间隔（目标群可通过 `targets[].summary_interval_minutes` 覆盖）。 | `120`
`timezone` | IANA 时区（如 `Asia/Shanghai`、`America/Los_Angeles`）。 | `UTC`
`retention_days` | 报告/媒体保留天数，超过即自动清理；设置 >180 时会触发确认（CLI 终端提示或 GUI 界面确认）。 | `30`

每个时间窗内，tgwatch 会生成 HTML 报告并推送到控制群，然后逐条发送该窗口的消息（含引用与媒体）。

## 8. 显示（`[display]`）

字段 | 描述 | 默认值
----- | ---- | ------
`show_ids` | 控制群推送中是否显示用户 ID。 | `true`
`time_format` | 时间戳格式（strftime 语法）。为空则使用默认值。 | `%Y.%m.%d %H:%M:%S (%Z)`

## 9. 通知（`[notifications]`）

字段 | 描述 | 默认值
----- | ---- | ------
`bark_key` | Bark 推送密钥。设置后，报告/心跳/错误会推送到手机。 | （空）

## 10. 验证配置

编辑 `config.toml` 后执行：

```bash
python -m tgwatch doctor --config config.toml
```

`doctor` 会检查：

- 必填字段是否齐全
- session/db/media/report 目录是否可创建
- SQLite 架构是否可写入

通过后即可运行：

```bash
python -m tgwatch once --config config.toml --since 2h
python -m tgwatch run --config config.toml
```

> 请勿提交 `config.toml`、`*.session`、`data/`、`reports/` 等敏感文件。
