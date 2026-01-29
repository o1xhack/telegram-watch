# 配置指南

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

`tgwatch` 会从 `config.toml` 读取所有运行参数。该文件应仅保存在本机，禁止提交或分享。按以下步骤填写所有字段后再运行 `python -m tgwatch ...`。

## 1. 复制示例配置

```bash
cp config.example.toml config.toml
```

在首次登录前必须编辑所有字段。

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

## 4. 目标群信息（`[target]`）

字段 | 含义 | 获取方式
----- | ---- | ----
`target_chat_id` | 目标群/频道的数字 ID，超级群/频道以 `-100` 开头。 | 在 Telegram Desktop/手机中打开群 → 点击标题 → 复制邀请链接 → 发送给 `@userinfobot`/`@getidsbot`/`@RawDataBot`，机器人会返回 `chat_id = -100...`。若无法分享链接，见下方“私有群无邀请链接”。
`tracked_user_ids` | 需要监控的用户 ID 列表。 | 让目标用户给 `@userinfobot` 发送消息并把 ID 转发给你，或把 `@userinfobot` 拉进群后 `/whois @username`。用真实 ID 替换示例列表（`[11111111, 22222222]`）。

提示：

- ID 必须是数字，用户名不生效。
- 只填写需要追踪的人，其它成员会被忽略。
- 超级群务必保留 `-100` 前缀，才能让报告里的 `MSG` 链接正确跳回 Telegram。

### 可选别名

为了更易读，可给每个用户 ID 添加别名：

```toml
[target.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

每个 key 必须在 `tracked_user_ids` 列表中。报告与控制群推送会显示 `Alice (11111111)`。

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

## 5. 控制群（`[control]`）

字段 | 描述 | 建议
----- | ---- | ----
`control_chat_id` | 控制群位置，用于接收摘要和执行命令（`/last`、`/since` 等）。 | 建议使用“Saved Messages”或仅你可控的小群，并确保你的账号在群内。
`is_forum` | 控制群是否开启 Topics（论坛模式）。 | 普通群或“Saved Messages”保持 `false`。
`topic_routing_enabled` | 启用按用户路由到 Topics。 | 不需要时保持 `false`。
`topic_user_map` | 追踪用户 ID → Topic ID 映射。 | 仅在 `topic_routing_enabled = true` 时填写。

### Topic 路由（论坛群）

当 `is_forum = true` 且 `topic_routing_enabled = true` 时，tgwatch 会将每个追踪用户的消息推送到对应的 Topic。未映射用户回退到 General 主题。
启用 Topic 路由时，HTML 报告也会按用户拆分，并在消息流之前发送到对应 Topic。

示例：

```toml
[control]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control.topic_user_map]
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
`summary_interval_minutes` | `run` 生成报告的间隔分钟数（建议 ≥10 以避免 FloodWait）。 | `120`
`timezone` | IANA 时区（如 `Asia/Shanghai`、`America/Los_Angeles`）。 | `UTC`
`retention_days` | 报告/媒体保留天数，超过即自动清理；设置 >180 时会提示确认。 | `30`

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
