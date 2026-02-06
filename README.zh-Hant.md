# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

追蹤： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文頻道](https://t.me/lalabeng) · [Telegram 中文頻道](https://t.me/o1xinsight)

## 主要特色

把嘈雜的 Telegram 群/頻道變成可查詢的個人信號來源 —— **完全本機、無需 Bot**。

- **只看重要的人**：在大群中僅追蹤少數高信號帳號（以使用者 ID 訂閱）。
- **控制群儀表板**：在控制聊天（收藏訊息或你控制的私密群）接收訊息與摘要，並用簡單指令按需查詢（`/last`、`/since`、`/export`，僅限你本人帳號）。
- **定時 HTML 摘要 + 訊息流**：HTML 報告包含上下文與媒體快照，並逐條推送每則訊息到控制群；每則訊息都附可點擊的 `MSG` 連結回到原訊息。
- **證據留存**：訊息與引用文字存入 SQLite，媒體快照保存在磁碟，便於回溯與匯出。
- **自動分流**：可選將不同使用者分流到各自的 Topic（論壇模式），未設定回到 General。
- **長期穩定**：保留清理、心跳/錯誤提示、FloodWait 退避，適合實際群組長跑。
- **預設隱私優先**：完全在本機執行，不上傳、不依賴第三方收集。
- **可選推送鏡像**：如需手機提醒，可用 Bark 同步摘要/心跳/錯誤。

適用情境：社群營運、研究人員、交易者，或任何需要 **信號萃取 + 本機歸檔** 的人。

以下章節說明安裝、設定與使用。

## 先決條件

- macOS，Python 3.11+
- 於 [my.telegram.org](https://my.telegram.org/) 取得的 Telegram API ID / hash（必須是使用者帳號）
- 僅使用本機儲存空間，不依賴雲端
- 若要長時間以守護模式運作，建議使用可長期上線的 Mac，例如 Mac mini

## 安裝

目前尚未發布到 PyPI，需透過 Git 安裝（標記版）或本機可編輯安裝。

### 第一步：安裝套件（建議使用標記版）

**推薦（穩定且可重現）：安裝標記版**

> 只想執行 `tgwatch` 並固定版本時使用。

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.3.1"
python -m tgwatch --help
```

**開發用：可編輯安裝**

> 本機改程式碼時使用。

```bash
pip install -e .
python -m tgwatch --help
```

### 第二步：建立 Python 環境（二選一）

可用系統自帶 `venv` 或 Conda，只要 Python ≥ 3.11 即可。

#### 方式 A：`python -m venv`（推薦）

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

> 提示：同一時間只需啟用一種環境。命令列前綴應顯示 `(.venv)` 或 `(tgwatch)`。

### 第三步：照流程完成設定

安裝並啟用環境後：

1) 複製 `config.example.toml` → `config.toml`
2) 執行 `tgwatch doctor`
3) 執行 `tgwatch once --since 2h --push` 測試
4) 執行 `tgwatch run` 進入守護模式

## 設定

1. 複製範例設定：

   ```bash
   cp config.example.toml config.toml
   ```

   一鍵方式：雙擊 `launch_tgwatch.command`（macOS）或 `launch_tgwatch.bat`（Windows）。啟動器現在優先使用 Conda（環境名 `tgwatch`）：若偵測到 Conda 則重用/建立 `tgwatch`，若沒有 Conda 則回退 `.venv`。接著安裝依賴、若缺少則複製 `config.toml`，並開啟 GUI。macOS 啟動器已相容 bash；若在受限網路下 `pip/setuptools/wheel` 升級失敗，會給出警告並繼續嘗試安裝專案。

   提示：可使用本機 GUI 設定（預設 `http://127.0.0.1:8765`）：

   ```bash
   tgwatch gui
   ```

2. 啟動本機 GUI（推薦）進行設定：

   ```bash
   tgwatch gui
   ```

   仍可直接編輯 `config.toml`，但不建議，較容易出錯。

3. 若選擇手動編輯檔案，請填入：

   - `config_version`（必須為 `1.0`）
   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（預設 `data/tgwatch.session`）
   - `[sender] session_file`（可選：用第二帳號發送以讓主帳號收到通知）
   - `targets[].name`（可選標籤；未填寫時會顯示為 `group-1`、`group-2` 等）
   - `targets[].target_chat_id`（目標群/頻道 ID）
   - `targets[].tracked_user_ids`（要監控的使用者 ID 列表）
   - `targets[].summary_interval_minutes`（可選：每個目標群的報告頻率）
   - `targets[].control_group`（可選；當存在多個控制群時必填）
   - `[targets.tracked_user_aliases]`（可選 ID→別名對應）
   - `control_groups.<name>.control_chat_id`（接收報告與指令的控制群）
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_target_map.<target_chat_id>]`（可選：依使用者分流到 TG Topic）
   - `storage.db_path` 與 `storage.media_dir`
   - `reporting.reports_dir` 與 `reporting.summary_interval_minutes`（預設報告頻率）
   - `reporting.timezone`（如 `Asia/Taipei`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（報告/媒體保留天數，預設 30；超過 180 時，CLI 會提示確認，GUI 會走介面內確認流程）
   - `[notifications] bark_key`（可選 Bark Key，可同步手機推播）
   - `[display] show_ids`（是否顯示 ID，預設 true）與 `time_format`（strftime 格式字串）可調整控制群推送的名字/時間格式

單一目標群仍可沿用舊版 `[target]` + `[control]` 設定。

### 單一目標 Run once

`tgwatch once` 預設會跑所有目標群。若只想跑單一群，可傳目標名稱或 `target_chat_id`：

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

GUI 的 Run once 區域新增 **Push to control chat** 選項（預設關閉）。

### 遷移

如果從舊配置升級（缺少 `config_version`），tgwatch 會停止並提示遷移。

1. GUI 會鎖定並顯示 **Migrate Config** 按鈕。
2. CLI 的 `run`/`once` 會顯示紅字提示並詢問是否遷移。
3. 遷移會將 `config.toml` 重新命名為 `config-old-0.1.toml`，並寫入新的 `config.toml`（盡量搬移舊值）。

請在再次執行前檢查新的 `config.toml`。`config-old-0.1.toml` 等備份檔已被 git 忽略。

### Bark Key 取得方式

1. 在手機安裝 Bark App，開啟後點齒輪圖示 → 「複製設備碼」，即可取得 `xxxxxxxxxxxxxxxxxxxxxxxx` 形式的 Key。
2. 在 `config.toml` 中寫入：

   ```toml
   [notifications]
   bark_key = "你的BarkKey"
   ```

3. 執行 `tgwatch run ...` 後，報告/心跳/錯誤會以 “Telegram Watch” 群組推播到 Bark。

更詳細的欄位說明、如何取得群/人 ID、目錄建議，可參考 [docs/configuration.md](docs/configuration.md)。

> ⚠️ 請勿將 `config.toml`、session 檔、`data/`、`reports/` 等敏感資料送進 Git。

## 使用方式

所有指令可透過 `python -m tgwatch ...` 或 `tgwatch ...` 執行，務必帶上 `--config`。

### Doctor

檢查設定與目錄權限，並確保 SQLite 架構可建立：

```bash
python -m tgwatch doctor --config config.toml
```

### GUI（本機設定介面）

啟動本機 UI 來管理目標群與控制群（會自動開啟瀏覽器）：

```bash
tgwatch gui
```

GUI 也提供 **Run once**、**Run daemon**、**Stop daemon** 按鈕並顯示執行日誌。`Run daemon` 會啟動背景行程，關閉瀏覽器不會停止執行；重新開啟 GUI 會繼續顯示日誌。若尚未建立 session 檔，請先在終端執行一次 `python -m tgwatch run --config config.toml` 完成登入，再使用 GUI 啟動。
當 `retention_days > 180` 時，點擊 **Run daemon** 會先顯示介面內確認區。勾選風險確認後，**Confirm & Start Run** 才可點擊。若操作失敗，Runner 訊息區會顯示錯誤。

### Once（單次報告）

抓取最近時間窗（例如 2 小時），寫入資料庫並為每個目標群輸出 `reports/YYYY-MM-DD/HHMM/index.html`：

```bash
python -m tgwatch once --config config.toml --since 2h
# 加上 --push 可立即把報告與訊息推到控制群，方便檢查
python -m tgwatch once --config config.toml --since 2h --push
```

### Run（常駐模式）

首次執行會在終端要求輸入 Telegram 驗證碼：

```bash
python -m tgwatch run --config config.toml
```

執行時：

- 持續監看每個目標群，追蹤使用者訊息會被寫入（文字、引用、媒體快照）。
- 依各目標群的 `summary_interval_minutes`（或全域預設）產生 HTML 報告並推送到對應控制群，再依序推送該時間窗內的所有訊息。
- 報告內的圖片預設以 Base64 內嵌；若檔案讀取失敗，則會退回相對路徑。
- 控制群可接受指令（僅限你本人帳號）：
  - `/help`
  - `/last <user_id|@username> [N]`
  - `/since <10m|2h|ISO>`
  - `/export <10m|2h|ISO>`

## 測試

```bash
pytest
```

## 隱私與安全

- 僅在本機運作，不依賴遠端服務。
- 不會在紀錄中輸出 API hash、電話或聊天內容。
- `config.toml`、session 檔、資料輸出等皆已列入 `.gitignore`。
- Flood-wait 退避適用於 Telegram API 呼叫（發送、下載、實體解析）。

## Changelog

版本更新記錄見 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 授權

MIT，詳見 `LICENSE`。
