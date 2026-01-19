# Configuration Guide

`tgwatch` reads all runtime parameters from `config.toml`. This file stays on your Mac and should never be committed or shared. Follow the steps below to fill every field with valid values before running `python -m tgwatch ...`.

## 1. Copy the example

```bash
cp config.example.toml config.toml
```

All fields must be edited before the watcher can log in.

## 2. Telegram credentials (`[telegram]`)

Field | How to obtain | Notes
----- | ------------- | -----
`api_id` | Log in to [my.telegram.org](https://my.telegram.org) with the same phone number the watcher will use → **API development tools** → create an application → copy the numeric `App api_id`. | User-account credentials only; do **not** use Bot tokens.
`api_hash` | Same page as `api_id`; copy the `App api_hash`. | Treat like a password. Never log or share it.
`session_file` | Path to the Telethon session file the watcher will store. Default `data/tgwatch.session` works for most setups. | Keep the path inside the repo but git-ignored (already covered). If you move it elsewhere, ensure the directory exists and is readable/writable.

First run (`python -m tgwatch run ...`) will prompt for the Telegram login code in the terminal and populate the session file automatically.

## 3. Target chat details (`[target]`)

Field | What it represents | How to find it
----- | ------------------ | -------------
`target_chat_id` | Numeric ID of the group/channel you want to monitor. Supergroups/channels start with `-100`. | In Telegram Desktop/Mobile open the chat → tap the title → copy the invite link → send it to `@userinfobot`, `@getidsbot`, or `@RawDataBot` and it will reply with `chat_id = -100...`. You can also forward any message from the chat to `@userinfobot`.
`tracked_user_ids` | List of integer user IDs to watch inside the target chat. | Ask each target user to send a message to `@userinfobot` and forward you the ID, or invite `@userinfobot` to the chat and reply `/whois @username`. Replace the sample list (`[11111111, 22222222]`) with the actual integers.

Tips:

- Always keep the IDs numeric; quoted usernames will not work.
- Include only the users you care about; everything else is ignored.

## 4. Control chat (`[control]`)

Field | Description | Recommendation
----- | ----------- | --------------
`control_chat_id` | Where tgwatch posts summaries and where you send commands (`/last`, `/since`, etc.). | Use your personal “Saved Messages” dialog or a private group that only you control. Retrieve the numeric ID the same way as the target chat (bots like `@userinfobot` show `chat_id` in replies). Make sure your own Telegram account is a member so commands are accepted.

## 5. Local storage (`[storage]`)

Field | Description | Default
----- | ----------- | -------
`db_path` | SQLite database storing messages and metadata. | `data/tgwatch.sqlite3`
`media_dir` | Directory where downloaded media is stored. | `data/media`

You may leave the defaults or point them to any writable path. The `doctor` command verifies that the directories exist (or can be created) and that the DB file is writable.

## 6. Reporting (`[reporting]`)

Field | Description | Default
----- | ----------- | -------
`reports_dir` | Root folder for generated HTML reports. Subdirectories follow `reports/YYYY-MM-DD/HHMM/index.html`. | `reports`
`summary_interval_minutes` | How often the `run` command posts summary digests to the control chat. | `120` (2 hours)

Reports and media stay local; nothing leaves your machine unless you explicitly share the files.

## 7. Validate the configuration

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
