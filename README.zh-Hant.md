# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

追蹤： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文頻道](https://t.me/lalabeng) · [Telegram 中文頻道](https://t.me/o1xinsight)

## 亮點

完全在本地運作的 Telegram 監看工具，基於 Telethon 實作。主要特色：

- **使用者等級監控**：直接以你的 Telegram 使用者帳號（非 Bot）登入，持續追蹤指定超級群/頻道內的特定使用者。
- **完整資料採集**：即時存下文字、引用上下文與媒體快照，寫入 SQLite 與本機媒體目錄。
- **自動報告**：依設定的時間窗（5~120 分鐘等）產生 HTML 報告，推送到控制群後再逐條推送該時間窗內的訊息，且 `MSG` 連結可直接回到 Telegram 原訊息。
- **內嵌媒體預覽**：報告中的圖片以 Base64 方式內嵌，即使在 Telegram 或手機上直接開啟 HTML 也能看到圖片。
- **心跳與告警**：若 2 小時沒有任何活動會自動送出 “Watcher is still running”；若程式異常結束，會把錯誤摘要推送到控制群並保留終端紀錄。
- **保留策略**：透過 `reporting.retention_days`（預設 30 天）定期清掉舊報告/媒體；設定超過 180 天時啟動前會先提示確認。
- **Bark 推播（選用）**：填入 Bark Key 後，報告/心跳/錯誤都會以 “Telegram Watch” 分組推送到手機。

以下章節說明安裝、設定與常用命令。

## 先決條件

- macOS，Python 3.11+
- 於 [my.telegram.org](https://my.telegram.org/) 取得的 Telegram API ID / hash（必須是使用者帳號）
- 僅使用本機儲存空間，不依賴雲端
- 若要長時間以守護模式運作，建議使用可長期上線的 Mac，例如 Mac mini

## 安裝

可選擇 `venv` 或 Conda，只要 Python ≥ 3.11 即可。

### 方式 0：安裝標記版本（推薦）

直接從 Git Tag 安裝穩定版：

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.1.1"

python -m tgwatch --help
```

### 方式 A：`python -m venv`

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
```

### 方式 B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -e .
```

> 提示：同一時間只需啟用一種環境。命令列前綴應顯示 `(.venv)` 或 `(tgwatch)`。

## 設定

1. 複製範例設定：

   ```bash
   cp config.example.toml config.toml
   ```

2. 編輯 `config.toml`，填入：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（預設 `data/tgwatch.session`）
   - `target.target_chat_id`（目標群/頻道 ID）
   - `target.tracked_user_ids`（要監控的使用者 ID 列表）
   - `[target.tracked_user_aliases]`（可選 ID→別名對應）
   - `control.control_chat_id`（接收報告與指令的控制群）
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

更詳細的欄位說明、如何取得群/人 ID、目錄建議，可參考 `docs/configuration.md`。

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

- 持續監看目標群，記錄文字、引用、媒體。
- 每個 `summary_interval_minutes` 窗口結束後，產生 HTML 報告並推送到控制群，再依序推送該時間窗內的所有訊息。
- 報告中的圖片以 Base64 方式內嵌，在 Telegram / 行動裝置開啟 HTML 也能顯示。
- 控制群可接受指令（僅限本帳號）：
  - `/help`
  - `/last <user_id|@username> [N]`
  - `/since <10m|2h|ISO>`
  - `/export <10m|2h|ISO>`

## 測試

```bash
pytest
```

## 隱私與安全

- 僅在你的 Mac 上執行，不依賴遠端服務。
- 不會在紀錄中輸出 API hash、電話或聊天內容。
- `config.toml`、session 檔、資料輸出等皆已列入 `.gitignore`。
- 內建 Flood-wait 退避，登入、下載、推送更穩定。

## 授權

MIT，詳見 `LICENSE`。
