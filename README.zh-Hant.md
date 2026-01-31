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

2. 編輯 `config.toml`，填入：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（預設 `data/tgwatch.session`）
   - `[sender] session_file`（可選：用第二帳號發送以讓主帳號收到通知）
   - `target.target_chat_id`（目標群/頻道 ID）
   - `target.tracked_user_ids`（要監控的使用者 ID 列表）
   - `[target.tracked_user_aliases]`（可選 ID→別名對應）
   - `control.control_chat_id`（接收報告與指令的控制群）
   - `control.is_forum` / `control.topic_routing_enabled` / `[control.topic_user_map]`（可選：依使用者分流到 TG Topic）
   - `storage.db_path` 與 `storage.media_dir`
   - `reporting.reports_dir` 與 `reporting.summary_interval_minutes`（報告頻率）
   - `reporting.timezone`（如 `Asia/Taipei`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（報告/媒體保留天數，預設 30，超過 180 會先提醒）
   - `[notifications] bark_key`（可選 Bark Key，可同步手機推播）
   - `[display] show_ids`（是否顯示 ID，預設 true）與 `time_format`（strftime 格式字串）可調整控制群推送的名字/時間格式

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

### Once（單次報告）

抓取最近時間窗（例如 2 小時），寫入資料庫並輸出 `reports/YYYY-MM-DD/HHMM/index.html`：

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

- 持續監看目標群，追蹤使用者訊息會被寫入（文字、引用、媒體快照）。
- 每個 `summary_interval_minutes` 窗口結束後，產生 HTML 報告並推送到控制群，再依序推送該時間窗內的所有訊息。
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
