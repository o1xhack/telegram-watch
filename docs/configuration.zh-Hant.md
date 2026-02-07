# 設定指南

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

**文件版本：** `v1.0.0`

`tgwatch` 會從 `config.toml` 讀取所有執行參數。此檔案只應保存在本機，禁止提交或分享。請依下列步驟填寫所有欄位後再執行 `python -m tgwatch ...`。

## 1. 複製範例設定

```bash
cp config.example.toml config.toml
```

一鍵方式：雙擊 `launch_tgwatch.command`（macOS）或 `launch_tgwatch.bat`（Windows）。啟動器優先使用 Conda（環境名 `tgwatch`）：有 Conda 時會重用/建立 `tgwatch`，沒有 Conda 時回退 `.venv`。隨後安裝依賴、若缺少則複製 `config.toml`，並開啟 GUI。macOS 啟動器相容 bash；受限網路下若 `pip/setuptools/wheel` 升級失敗，會提示警告並繼續嘗試安裝專案。

請確認檔案頂部包含 `config_version = 1.0`，舊版本會被拒絕執行。

若你是從舊設定升級（缺少 `config_version`），tgwatch 會停止並提示遷移。遷移會將 `config.toml` 備份為 `config-old-0.1.toml`，並建立新的 `config.toml`（盡量搬移舊值）。請在執行前檢查新檔案。備份檔已被 git 忽略。

首次登入前必須編輯所有欄位。

推薦：啟動本機 GUI（預設 `http://127.0.0.1:8765`）進行設定：

```bash
tgwatch gui
```

GUI 提供 **Run once** / **Run daemon** / **Stop daemon** 按鈕與執行日誌。若尚未建立 session 檔，請先在終端執行一次 `python -m tgwatch run --config config.toml` 完成登入。
你也可以在 GUI 中選擇單一目標群，或在 CLI 上使用 `--target`（名稱或 `target_chat_id`）來限制 **Run once** 的執行範圍。GUI 另提供 **Push to control chat** 開關（預設關閉），日誌面板最多顯示 200 行並可滾動，空日誌保持緊湊高度。
當 `retention_days > 180` 時，點擊 **Run daemon** 會跳出介面內確認區；勾選風險確認後，點擊 **Confirm & Start Run** 才會啟動。

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

## 4. 目標群（`[[targets]]`）

每個 `[[targets]]` 條目代表一個要監控的群/頻道。若只有一個目標群，舊版 `[target]` 仍可用，但建議使用多目標格式。限制：最多 5 個目標群、每群最多 5 位使用者、最多 5 個控制群。仍支援手動編輯，但較容易出錯。

欄位 | 含義 | 取得方式
----- | ---- | ----
`name` | 目標群可選標籤 | 用於日誌/GUI；未填寫時會自動標為 `group-1`、`group-2` 等
`target_chat_id` | 目標群/頻道的數字 ID，超級群/頻道以 `-100` 開頭。 | 在 Telegram Desktop/手機打開群 → 點標題 → 複製邀請連結 → 傳給 `@userinfobot`/`@getidsbot`/`@RawDataBot`，機器人會回覆 `chat_id = -100...`。若無法分享連結，請見「私有群無邀請連結」。
`tracked_user_ids` | 要監控的使用者 ID 清單。 | 請目標使用者傳訊給 `@userinfobot` 並回傳 ID，或將 `@userinfobot` 加入群內 `/whois @username`。用實際 ID 取代範例（`[11111111, 22222222]`）。
`summary_interval_minutes` | 可選：此目標群的報告頻率 | 未填寫則使用 `reporting.summary_interval_minutes`
`control_group` | 對應的控制群 | 當存在多個控制群時必填；只有一個控制群時可省略

提示：

- ID 必須是數字，使用者名稱無效。
- 只填想追蹤的人，其他成員會被忽略。
- 超級群務必保留 `-100` 前綴，才能讓報告中的 `MSG` 連結正確跳回 Telegram。
- 未填寫 `name` 時，tgwatch 會依順序顯示為 `group-1`、`group-2` 等。

### 可選別名

為了更易讀，可為每個使用者 ID 設定別名（按目標群設定）：

```toml
[[targets]]
name = "group-1"
target_chat_id = -1001234567890
tracked_user_ids = [11111111, 22222222]

[targets.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

每個 key 必須存在於該目標群的 `tracked_user_ids`。報告與控制群推送會顯示 `Alice (11111111)`。

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

## 5. 控制群（`[control_groups]`）

控制群用於接收報告並下達命令（`/last`、`/since` 等）。可配置多個控制群，並透過 `targets[].control_group` 進行映射。

欄位 | 說明 | 建議
----- | ---- | ----
`control_chat_id` | 控制群位置，用於接收摘要與指令。 | 建議使用 “Saved Messages” 或只有你可控的小群，並確保你的帳號在群內。
`is_forum` | 控制群是否啟用 Topics（論壇模式）。 | 一般群或 “Saved Messages” 保持 `false`。
`topic_routing_enabled` | 啟用依使用者路由到 Topics。 | 不需要時保持 `false`。
`topic_target_map` | 使用者 ID → Topic ID 對照表（按目標群 chat_id 區分）。 | 僅在 `topic_routing_enabled = true` 時填寫。

若只有一個控制群，`targets[].control_group` 可省略；若存在多個控制群，則每個目標群都必須指定 `control_group`。

### Topic 路由（論壇群）

當 `is_forum = true` 且 `topic_routing_enabled = true` 時，tgwatch 會把追蹤使用者在對應目標群中的訊息送到 Topic。未在該目標群的 `topic_target_map` 中映射的使用者會回退到 General 主題。
啟用 Topic 路由時，HTML 報告也會按使用者拆分，並在訊息流之前送到對應 Topic。

範例：

```toml
[control_groups.main]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control_groups.main.topic_target_map."-1001234567890"]
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
`summary_interval_minutes` | `run` 的預設報告間隔（目標群可用 `targets[].summary_interval_minutes` 覆蓋）。 | `120`
`timezone` | IANA 時區（如 `Asia/Taipei`、`America/Los_Angeles`）。 | `UTC`
`retention_days` | 報告/媒體保留天數，超過即自動清理；設定 >180 時會觸發確認（CLI 終端提示或 GUI 介面確認）。 | `30`

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
