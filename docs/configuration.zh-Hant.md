# 設定指南

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

`tgwatch` 會從 `config.toml` 讀取所有執行參數。此檔案只應保存在本機，禁止提交或分享。請依下列步驟填寫所有欄位後再執行 `python -m tgwatch ...`。

## 1. 複製範例設定

```bash
cp config.example.toml config.toml
```

首次登入前必須編輯所有欄位。

## 2. Telegram 憑證（`[telegram]`）

欄位 | 取得方式 | 說明
----- | -------- | ----
`api_id` | 使用監控所用的手機號碼登入 [my.telegram.org](https://my.telegram.org) → **API development tools** → 建立應用 → 複製數字 `App api_id`。 | 必須是使用者帳號，不要用 Bot Token。
`api_hash` | 與 `api_id` 同頁，複製 `App api_hash`。 | 視同密碼，勿記錄或分享。
`session_file` | Telethon session 檔案路徑，預設 `data/tgwatch.session`。 | 建議留在倉庫內但需 git 忽略；若移到其他位置，確保目錄可讀寫。

第一次執行（`python -m tgwatch run ...`）會在終端提示輸入驗證碼並建立 session 檔案。

## 3. 發送端帳號（可選）（`[sender]`）

用於「雙帳號橋接」：帳號 A 負責抓取，帳號 B 負責發送控制群訊息，讓帳號 A 能收到通知。

欄位 | 含義 | 說明
----- | ---- | ----
`session_file` | 發送端帳號（帳號 B）的 session 檔案路徑。 | 設定了 `[sender]` 就必填。與 `[telegram]` 共用 `api_id` / `api_hash`，但路徑必須與 `telegram.session_file` 不同。

首次執行會分別提示登入帳號 B。請確認帳號 B 已加入控制群並具備發言權限。不需要橋接時可省略 `[sender]`。

## 4. 目標群資訊（`[target]`）

欄位 | 含義 | 取得方式
----- | ---- | ----
`target_chat_id` | 目標群/頻道的數字 ID，超級群/頻道以 `-100` 開頭。 | 在 Telegram Desktop/手機打開群 → 點標題 → 複製邀請連結 → 傳給 `@userinfobot`/`@getidsbot`/`@RawDataBot`，機器人會回覆 `chat_id = -100...`。若無法分享連結，請見「私有群無邀請連結」。
`tracked_user_ids` | 要監控的使用者 ID 清單。 | 請目標使用者傳訊給 `@userinfobot` 並回傳 ID，或將 `@userinfobot` 加入群內 `/whois @username`。用實際 ID 取代範例（`[11111111, 22222222]`）。

提示：

- ID 必須是數字，使用者名稱無效。
- 只填想追蹤的人，其他成員會被忽略。
- 超級群務必保留 `-100` 前綴，才能讓報告中的 `MSG` 連結正確跳回 Telegram。

### 可選別名

為了更易讀，可為每個使用者 ID 設定別名：

```toml
[target.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

每個 key 必須存在於 `tracked_user_ids`。報告與控制群推送會顯示 `Alice (11111111)`。

### 私有群無邀請連結

若群沒有邀請連結，可使用以下方式取得 `target_chat_id`：

1. **轉發訊息給 ID 機器人**  
   將群內任意訊息轉發給 `@userinfobot` 或 `@RawDataBot`，機器人會回覆 `Chat ID: -100...`。轉發時需關閉「隱藏傳送者」。
2. **暫時邀請 ID 機器人**  
   若無法轉發，請管理員暫時邀請 `@userinfobot` 進群，輸入 `/mychatid` 或 `/whois`，記下數字 ID 後移除。
3. **使用 Telegram Desktop 的開發者資訊**  
   macOS 使用 Telegram Desktop（Qt 版）：
   1. `Telegram Desktop` 選單 → **Preferences…**（`⌘,`）。
   2. **Advanced** → **Experimental settings** → 開啟 **Enable experimental features** 與 **Show message IDs**。
   3. 回到群聊右鍵訊息 → **Copy message link**。連結形如 `https://t.me/c/1234567890/55`，轉成 `-1001234567890` 後填入 `target_chat_id`。

   若只有原生 macOS “Telegram” 應用（圓形圖示）且沒有 Advanced 選單，請改用 Desktop 版或網頁版（`https://web.telegram.org/k/`），地址列會顯示 `#-1001234567890`。

## 5. 控制群（`[control]`）

欄位 | 說明 | 建議
----- | ---- | ----
`control_chat_id` | 控制群位置，用於接收摘要與指令（`/last`、`/since` 等）。 | 建議使用 “Saved Messages” 或只有你可控的小群，並確保你的帳號在群內。
`is_forum` | 控制群是否啟用 Topics（論壇模式）。 | 一般群或 “Saved Messages” 保持 `false`。
`topic_routing_enabled` | 啟用依使用者路由到 Topics。 | 不需要時保持 `false`。
`topic_user_map` | 使用者 ID → Topic ID 對照表。 | 僅在 `topic_routing_enabled = true` 時填寫。

### Topic 路由（論壇群）

當 `is_forum = true` 且 `topic_routing_enabled = true` 時，tgwatch 會把追蹤使用者的訊息送到對應 Topic。未映射使用者回退到 General 主題。
啟用 Topic 路由時，HTML 報告也會按使用者拆分，並在訊息流之前送到對應 Topic。

範例：

```toml
[control]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control.topic_user_map]
11111111 = 9001  # Alice -> Topic A
22222222 = 9002  # Bob -> Topic B
```

#### 如何取得 Topic ID

Topic ID 即建立該 Topic 的系統訊息 ID。取得方式：

1. 打開控制群並進入目標 Topic。
2. 找到 Topic 建立的系統訊息（或該 Topic 的第一則訊息）。
3. 右鍵訊息選 **Copy message link**。
4. 連結形如 `https://t.me/c/1234567890/9001`，最後的數字（`9001`）即 Topic ID。

General 主題固定 ID 為 `1`。關閉 Topic 路由時預設送到 General。

## 6. 本機儲存（`[storage]`）

欄位 | 說明 | 預設值
----- | ---- | ------
`db_path` | SQLite 資料庫路徑。 | `data/tgwatch.sqlite3`
`media_dir` | 媒體檔案保存目錄。 | `data/media`

可保留預設值或改為可寫路徑。`doctor` 會檢查目錄可建立且 DB 可寫。

## 7. 報告（`[reporting]`）

欄位 | 說明 | 預設值
----- | ---- | ------
`reports_dir` | HTML 報告根目錄，子目錄依 `reports/YYYY-MM-DD/HHMM/index.html` 組織。 | `reports`
`summary_interval_minutes` | `run` 生成報告的間隔分鐘（建議 ≥10 以避免 FloodWait）。 | `120`
`timezone` | IANA 時區（如 `Asia/Taipei`、`America/Los_Angeles`）。 | `UTC`
`retention_days` | 報告/媒體保留天數，超過即自動清理；設定 >180 時會提示確認。 | `30`

每個時間窗內，tgwatch 會生成 HTML 報告並推送至控制群，之後逐條送出該窗口訊息（含引用與媒體）。

## 8. 顯示（`[display]`）

欄位 | 說明 | 預設值
----- | ---- | ------
`show_ids` | 控制群推送是否顯示使用者 ID。 | `true`
`time_format` | 時間戳格式（strftime）。空白則使用預設值。 | `%Y.%m.%d %H:%M:%S (%Z)`

## 9. 通知（`[notifications]`）

欄位 | 說明 | 預設值
----- | ---- | ------
`bark_key` | Bark 推播金鑰。設定後報告/心跳/錯誤會推送到手機。 | （空）

## 10. 驗證設定

編輯 `config.toml` 後請執行：

```bash
python -m tgwatch doctor --config config.toml
```

`doctor` 會檢查：

- 必填欄位是否齊全
- session/db/media/report 目錄是否可建立
- SQLite 架構是否可寫入

通過後即可執行：

```bash
python -m tgwatch once --config config.toml --since 2h
python -m tgwatch run --config config.toml
```

> 請勿提交 `config.toml`、`*.session`、`data/`、`reports/` 等敏感檔案。
