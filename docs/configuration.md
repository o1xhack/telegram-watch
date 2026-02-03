# Configuration Guide

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

`tgwatch` reads all runtime parameters from `config.toml`. This file stays on your Mac and should never be committed or shared. Follow the steps below to fill every field with valid values before running `python -m tgwatch ...`.

## 1. Copy the example

```bash
cp config.example.toml config.toml
```

All fields must be edited before the watcher can log in.

Recommended: launch the local GUI (default `http://127.0.0.1:8765`) to edit config without touching the file:

```bash
tgwatch gui
```

## 2. Telegram credentials (`[telegram]`)

Field | How to obtain | Notes
----- | ------------- | -----
`api_id` | Log in to [my.telegram.org](https://my.telegram.org) with the same phone number the watcher will use → **API development tools** → create an application → copy the numeric `App api_id`. | User-account credentials only; do **not** use Bot tokens.
`api_hash` | Same page as `api_id`; copy the `App api_hash`. | Treat like a password. Never log or share it.
`session_file` | Path to the Telethon session file the watcher will store. Default `data/tgwatch.session` works for most setups. | Keep the path inside the repo but git-ignored (already covered). If you move it elsewhere, ensure the directory exists and is readable/writable.

First run (`python -m tgwatch run ...`) will prompt for the Telegram login code in the terminal and populate the session file automatically.

## 3. Sender account (optional) (`[sender]`)

Use this when you want a second Telegram account to *send* control-group messages, so your primary account (the one that reads/collects messages) can still receive notifications. This is the “A collects, B sends” bridge.

Field | What it represents | Notes
----- | ------------------ | -----
`session_file` | Session file for the sender account (account B). | Required when `[sender]` is set. Uses the same `api_id` / `api_hash` as `[telegram]`. Must be a different path from `telegram.session_file`.

First run will prompt for the sender account login code separately. Make sure account B is a member of the control chat and has permission to post. Omit `[sender]` to keep the current single-account behavior.

## 4. Target groups (`[[targets]]`)

Each `[[targets]]` entry describes one Telegram group/channel you want to monitor. If you only have a single group, the legacy `[target]` format still works, but the multi-target format is recommended. Limits: up to 5 target groups, 5 users per group, and 5 control groups. Manual edits are supported but more error-prone than the GUI.

Field | What it represents | How to find it
----- | ------------------ | -------------
`name` | A unique label for this target group. | Any short string (used in logs/commands).
`target_chat_id` | Numeric ID of the group/channel you want to monitor. Supergroups/channels start with `-100`. | In Telegram Desktop/Mobile open the chat → tap the title → copy the invite link → send it to `@userinfobot`, `@getidsbot`, or `@RawDataBot` and it will reply with `chat_id = -100...`. For private chats with no shareable link, see “Private group without invite link” below.
`tracked_user_ids` | List of integer user IDs to watch inside the target chat. | Ask each target user to send a message to `@userinfobot` and forward you the ID, or invite `@userinfobot` to the chat and reply `/whois @username`. Replace the sample list (`[11111111, 22222222]`) with the actual integers.
`summary_interval_minutes` | Optional per-target report interval. | If omitted, falls back to `reporting.summary_interval_minutes`.
`control_group` | Which control group should receive reports for this target. | Required when multiple control groups exist; optional if only one control group is configured.

Tips:

- Always keep the IDs numeric; quoted usernames will not work.
- Include only the users you care about; everything else is ignored.
- For supergroups, keep the `-100` prefix so `MSG` links jump back to Telegram.

### Optional aliases

To make reports easier to read, you can assign human-friendly labels to each tracked user ID (per target group).

```toml
[[targets]]
name = "group-1"
target_chat_id = -1001234567890
tracked_user_ids = [11111111, 22222222]

[targets.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

Each key must match an ID listed in that target’s `tracked_user_ids`. Reports and control-chat summaries will display `Alice (11111111)` instead of a bare number.

### Private group without invite link

If you joined a private group and cannot create invite links, you still have a few options to reveal the numeric `target_chat_id`:

1. **Forward a message to an ID bot**  
   From Telegram (desktop or mobile) forward any recent message from the private group to `@userinfobot` or `@RawDataBot`. Forwarded messages keep the original chat metadata and the bot will respond with `Chat ID: -100...` even if it cannot join the group. Make sure “Hide sender name” is disabled when forwarding so the metadata stays intact.
2. **Temporarily add an ID bot**  
   If forwarding is disabled, ask an admin to temporarily invite `@userinfobot` (or similar) into the group. Run `/mychatid` or `/whois` inside the group, note the numeric ID, then remove the bot.
3. **Use Telegram Desktop’s developer info**  
   The Telegram Desktop (Qt) app for macOS and Windows exposes “Experimental settings”. On macOS, open **Telegram Desktop** (the square blue icon from [desktop.telegram.org](https://desktop.telegram.org/), not the App Store “Telegram” app), then:
   1. `Telegram Desktop` menu → **Preferences…** (`⌘,`).
   2. Go to **Advanced** → scroll to **Experimental settings** → toggle **Enable experimental features** → turn on **Show message IDs**.
   3. Go back to the chat, right-click any message → **Copy message link**.  
      The link looks like `https://t.me/c/1234567890/55`; convert it to `-1001234567890` and write it into `target_chat_id`.

   If you only have the native macOS “Telegram” app (round icon) and no Advanced menu, either install Telegram Desktop from the link above or use the web client (`https://web.telegram.org/k/`) where the address bar shows `#-1001234567890` when the group is open.

Pick whichever option your group permissions allow. Once you have the numeric ID, fill `targets[].target_chat_id` in `config.toml`.

## 5. Control groups (`[control_groups]`)

Control groups receive reports and accept commands (`/last`, `/since`, `/export`). You can define one or more control groups, then map each target group to a control group via `targets[].control_group`.

Field | Description | Recommendation
----- | ----------- | --------------
`control_chat_id` | Where tgwatch posts summaries and where you send commands. | Use your personal “Saved Messages” dialog or a private group that only you control. Retrieve the numeric ID the same way as the target chat (bots like `@userinfobot` show `chat_id` in replies). Make sure your own Telegram account is a member so commands are accepted.
`is_forum` | Set `true` if the control chat has Topics (forum mode) enabled. | Keep `false` for normal groups or “Saved Messages”.
`topic_routing_enabled` | Enable per-user routing into forum topics. | Leave `false` unless you want per-user topics.
`topic_user_map` | Map tracked user IDs to forum topic IDs. | Provide only when `topic_routing_enabled = true`.

If only one control group is configured, `targets[].control_group` can be omitted (all targets route to the single control group). If multiple control groups exist, every target must declare `control_group`.

### Topic routing (forum groups)

When `is_forum = true` and `topic_routing_enabled = true`, tgwatch sends each tracked user’s messages into the configured forum topic for that user. If a user is not listed in `topic_user_map`, their messages fall back to the General topic.
When topic routing is enabled, HTML reports are also split per user and sent to the matching topic before the message stream.

Example:

```toml
[control_groups.main]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control_groups.main.topic_user_map]
11111111 = 9001  # Alice -> Topic A
22222222 = 9002  # Bob -> Topic B
```

#### How to find a topic ID

Topic IDs are the message IDs of the service message that created the topic. The easiest way to obtain one:

1. Open the control group, then open the target topic.
2. Find the system message that says the topic was created (or the first message in that topic).
3. Right-click the message and choose **Copy message link**.
4. The link looks like `https://t.me/c/1234567890/9001` (or similar). The last number (`9001`) is the topic ID.

The General topic always uses ID `1`. When topic routing is disabled, tgwatch posts to General by default.

If you only want the General topic, you can omit `topic_user_map` and keep `topic_routing_enabled = false`.

## 6. Local storage (`[storage]`)

Field | Description | Default
----- | ----------- | -------
`db_path` | SQLite database storing messages and metadata. | `data/tgwatch.sqlite3`
`media_dir` | Directory where downloaded media is stored. | `data/media`

You may leave the defaults or point them to any writable path. The `doctor` command verifies that the directories exist (or can be created) and that the DB file is writable.

## 7. Reporting (`[reporting]`)

Field | Description | Default
----- | ----------- | -------
`reports_dir` | Root folder for generated HTML reports. Subdirectories follow `reports/YYYY-MM-DD/HHMM/index.html`. | `reports`
`summary_interval_minutes` | Default report interval for `run`. Targets can override this with `targets[].summary_interval_minutes`. Set `30` for every half hour, or any other positive integer (recommended ≥ 10 to avoid FloodWait). | `120` (2 hours)
`timezone` | IANA timezone string (examples: `Asia/Shanghai`, `America/Los_Angeles`, `America/New_York`, `Asia/Tokyo`). Determines how timestamps appear in reports and control-chat pushes. Falls back to `UTC` if omitted. | `UTC`
`retention_days` | How many days of reports/media to keep when `run` is active. Older directories are deleted automatically at startup and after each summary. Setting values > 180 triggers a confirmation prompt to warn about disk usage. | `30`

During each window, tgwatch writes the HTML report to `reports_dir`, uploads that file to the control chat, and then streams the window内的每条消息（文本 + 引用 + 媒体）到控制聊天，方便在手机端查看。Reply sections in each report include any quoted images/documents so you can see the full context without opening Telegram.

## 8. Display (`[display]`)

Field | Description | Default
----- | ----------- | -------
`show_ids` | Whether control-chat pushes append `(ID)` to aliases/usernames. | `true`
`time_format` | Timestamp format for control-chat pushes (`strftime` syntax, e.g., `%Y.%m.%d %H:%M:%S (%Z)`). Leave blank to use the default. | `%Y.%m.%d %H:%M:%S (%Z)`

## 9. Notifications (`[notifications]`)

Field | Description | Default
----- | ----------- | -------
`bark_key` | Optional Bark key for push notifications. When set, reports, heartbeats, and error alerts are mirrored to your phone under the `Telegram Watch` group. | _(empty)_

## 10. Validate the configuration

After editing `config.toml`, run:

```bash
python -m tgwatch doctor --config config.toml
```

The doctor command checks:

- All required fields (IDs, hashes, paths) are present and correctly typed.
- The session/DB/media/report directories exist or can be created.
- The SQLite schema can be created at `storage.db_path`.

If validation passes, you can run one-shot or daemon modes:

```bash
python -m tgwatch once --config config.toml --since 2h
python -m tgwatch run --config config.toml
```

> Keep `config.toml`, `*.session`, `data/`, and `reports/` out of git. They already appear in `.gitignore`; avoid copying them elsewhere.
