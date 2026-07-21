# telegram-watch

[English](../README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

[![Release](https://img.shields.io/github/v/release/o1xhack/telegram-watch?style=for-the-badge&label=release&color=7c3aed)](https://github.com/o1xhack/telegram-watch/releases/latest)
[![Stars](https://img.shields.io/github/stars/o1xhack/telegram-watch?style=for-the-badge&label=stars&color=7c3aed)](https://github.com/o1xhack/telegram-watch/stargazers)
[![License](https://img.shields.io/github/license/o1xhack/telegram-watch?style=for-the-badge&label=license&color=7c3aed)](../LICENSE)

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-o1xhack-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/o1xhack)

**文件版本：** `v1.0.7`（release `v1.7.0`）

追蹤： [X/Twitter](https://x.com/o1xhack) · [Telegram 英文頻道](https://t.me/lalabeng) · [Telegram 中文頻道](https://t.me/o1xinsight)

## 主要特色

把嘈雜的 Telegram 群/頻道變成私有且結構化的信號系統 —— **完全本機、無需 Bot**。

![telegram-watch GUI](assets/tgwatch-gui-v1.png)

- **多目標監控**：可同時追蹤多個群/頻道，每個目標可獨立設定名單、別名與彙整間隔。
- **控制群路由**：每個目標可綁定到指定控制群，便於按場景拆分工作流程。
- **按目標 Topic 映射**：在論壇模式下以 `target_chat_id + user_id` 映射 Topic，同一使用者在不同來源群可走不同 Topic。
- **GUI 優先設定**：憑證、目標、控制群、映射與儲存都可在本機 GUI 完成——依據瀏覽器語言自動切換中文或英文介面。
- **一鍵本機啟動器**：啟動流程採 Conda（`tgwatch`）優先，並自動回退到 `venv`。
- **GUI 執行控制**：支援 Run once（可選單目標與 push）、Run daemon、Stop daemon，並可查看即時日誌。
- **安全執行護欄**：啟動前 session 檢查、長保留視窗確認，以及介面內可見錯誤提示。
- **自動重連**：daemon 模式在臨時網路故障時自動重連（指數退避），恢復後向控制群發送通知。
- **預設本機持久化**：訊息歸檔至 SQLite、媒體快照落盤、自動產生 HTML 報告。
- **即時推送模式** *（實驗性）*：被追蹤使用者的訊息到達後立即轉發至控制群組，內建 7 層速率防護體系，防止帳號受限。
- **隱私優先設計**：不依賴雲端、不記錄敏感金鑰，執行期敏感檔預設不進 git。

適用情境：社群營運、研究人員、交易者，或任何需要 **信號萃取 + 本機歸檔** 的人。

## 快速開始

5 步上手。你需要：**macOS + Python 3.11+** 以及一個 Telegram 使用者帳號。

### 1. 取得 Telegram API 憑證

前往 [my.telegram.org](https://my.telegram.org/)，用手機號碼登入，建立應用以取得 **API ID** 和 **API Hash**。

### 2. 複製倉庫

複製穩定 release 版本（推薦）：

```bash
git clone --branch v1.7.0 https://github.com/o1xhack/telegram-watch.git
cd telegram-watch
```

> 也可以複製 `main` 取得最新程式碼：`git clone https://github.com/o1xhack/telegram-watch.git`

### 3. 雙擊啟動器

在 Finder 中雙擊 **`launch_tgwatch.command`**，它會自動：
- 建立 Python 環境（有 Conda 用 Conda `tgwatch`，否則用 `.venv`）
- 安裝所有依賴
- 若缺少則複製 `config.example.toml` → `config.toml`
- 在瀏覽器中開啟 GUI

### 4. 在 GUI 中設定

GUI 開啟後（`http://127.0.0.1:8765`）：
1. 在 Telegram 區域填入 **API ID** 和 **API Hash**
2. 新增一個或多個 **Target**（要監控的群/頻道及追蹤使用者 ID）
3. 新增一個 **Control Group**（報告與訊息推送的目標群）
4. 點擊 **Save**

### 5. 首次登入（終端）

首次執行需在終端輸入 Telegram 驗證碼：

```bash
# 如果用了啟動器，先啟用同一環境：
# Conda: conda activate tgwatch
# venv:  source .venv/bin/activate

python -m tgwatch run --config config.toml
```

按提示輸入手機號碼與驗證碼。連線成功後守護程序即開始執行。按 `Ctrl+C` 停止，或之後直接在 GUI 中使用 **Run daemon** / **Stop daemon**。

> **提示**：首次登入後，後續啟動/停止都可在 GUI 中完成，不需再用終端。

## 手動安裝

<details>
<summary>面向開發者，或不想使用啟動器時</summary>

### 建立 Python 環境（二選一）

#### 方式 A：venv（推薦）

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

### 安裝套件

**可編輯安裝（開發用）：**

```bash
pip install -e .
```

**標記版安裝（穩定、版本固定）：**

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.8.0"
```

### 設定與執行

```bash
cp config.example.toml config.toml
tgwatch gui          # 在 GUI 中編輯設定，或手動編輯 config.toml
tgwatch doctor       # 驗證設定
tgwatch once --since 2h --push   # 測試執行
tgwatch run          # 啟動常駐模式
```

</details>

## 設定

**推薦使用 GUI**（`tgwatch gui` 或啟動器）—— 涵蓋所有設定項且不易出錯。

如需手動編輯 `config.toml`，完整欄位說明見 [configuration.md](configuration.md)。關鍵欄位：

| 區塊 | 欄位 | 說明 |
|------|------|------|
| `telegram` | `api_id`、`api_hash` | Telegram API 憑證 |
| `telegram` | `session_file` | Session 路徑（預設 `data/tgwatch.session`） |
| `sender` | `session_file` | 可選的第二帳號 session |
| `targets[]` | `target_chat_id`、`tracked_user_ids` | 監控目標 |
| `targets[]` | `name`、`tracked_user_aliases` | 可選標籤與別名 |
| `targets[]` | `summary_interval_minutes`、`control_group` | 每目標覆寫項 |
| `control_groups.<name>` | `control_chat_id` | 報告推送目標 |
| `control_groups.<name>` | `is_forum`、`topic_routing_enabled`、`topic_target_map` | Topic 路由 |
| `control_groups.<name>` | `skip_html_report` | 跳過 HTML 檔案，僅發逐條訊息 |
| `reporting` | `reports_dir`、`summary_interval_minutes`、`timezone`、`retention_days` | 報告設定 |
| `storage` | `db_path`、`media_dir` | 本機儲存路徑 |
| `notifications` | `bark_key` | 可選 Bark 手機推播 |
| `display` | `show_ids`、`time_format` | 顯示格式 |
| `realtime` | `push_mode` | `"interval"`（預設）或 `"realtime"`（實驗性） |
| `realtime` | `rate_limit_per_minute`、`rate_limit_per_hour`、`rate_limit_per_day` | 速率防護限制 |

單一目標群仍可沿用舊版 `[target]` + `[control]` 設定。

### 單一目標 Run once

`tgwatch once` 預設跑所有目標群。若只跑單一群，傳目標名稱或 `target_chat_id`：

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

### 舊設定遷移

從舊配置升級（缺少 `config_version`）時，tgwatch 會停止並提示遷移。

1. GUI 會鎖定並顯示 **Migrate Config** 按鈕。
2. CLI 的 `run`/`once` 會顯示紅字提示並詢問是否遷移。
3. 遷移會將 `config.toml` 重新命名為 `config-old-0.1.toml`，並寫入新 `config.toml`（盡量搬移舊值）。

### Bark 推播

1. 手機安裝 Bark App，點齒輪 → 複製裝置碼。
2. 在設定中填入 `[notifications]` → `bark_key = "你的Key"`（或在 GUI 中設定）。
3. 報告、心跳、錯誤會以「Telegram Watch」群組推播到 Bark。

### 即時推送模式 *（實驗性）*

預設情況下，tgwatch 會收集訊息並定期彙整發送（「interval」模式）。**即時模式**會在訊息到達的一剎那將其轉發至控制群組。

1. 在 GUI 中找到 **Realtime Push Mode** 區塊，切換為 **Realtime (Experimental)**。
2. 確認風險提示對話框（超出速率限制可能導致帳號受限）。
3. 如有需要可調整速率防護參數 — 預設值已偏保守。

即時模式內建 **7 層速率防護**：滑動視窗限流（20 條/分鐘）、隨機抖動間隔（3 秒 ± 1 秒）、媒體額外延遲（+2 秒）、每小時/每日上限（200/時、1000/天）、FloodWait 指數退避、熔斷器（自動暫停 30 分鐘 + Bark 告警）、啟動冷卻期（5 分鐘 @ 5 條/分鐘）。詳見[設定指南](configuration.zh-Hant.md)。

> ⚠️ 請勿將 `config.toml`、session 檔、`data/`、`reports/` 等敏感資料送進 Git。

## 使用方式

所有指令：`python -m tgwatch <cmd>` 或 `tgwatch <cmd>`，務必帶上 `--config config.toml`。

### Doctor

檢查設定與目錄權限，並確保 SQLite 架構可建立：

```bash
tgwatch doctor --config config.toml
```

### GUI（本機設定介面）

啟動本機 UI（預設 `http://127.0.0.1:8765`）：

```bash
tgwatch gui
```

GUI 提供 **Run once**、**Run daemon**、**Stop daemon** 按鈕並顯示執行日誌。`Run daemon` 會啟動背景行程，關閉瀏覽器不會停止執行；重新開啟 GUI 會繼續顯示日誌。

### Once（單次報告）

抓取最近時間窗的訊息、寫入資料庫並產生 HTML 報告：

```bash
tgwatch once --config config.toml --since 2h
# 加上 --push 可立即推送到控制群
tgwatch once --config config.toml --since 2h --push
```

### Run（常駐模式）

首次執行會在終端要求輸入 Telegram 驗證碼：

```bash
tgwatch run --config config.toml
```

執行時：
- 持續監看每個目標群，追蹤使用者訊息會被寫入（文字、引用、媒體快照）。
- 依各目標群的彙整間隔產生 HTML 報告並推送到對應控制群，再依序推送訊息。
- 控制群可接受指令（僅限你本人帳號）：`/help`、`/last`、`/since`、`/export`。

## GitHub Actions（自動每日擷取）

可透過 GitHub Actions 定時執行 `tgwatch once` —— 無需本機守護程序。Fork 本倉庫，設定兩個 GitHub Secret 即可。

### 所需 GitHub Secrets

| Secret | 內容 | 如何產生 |
|--------|------|----------|
| `TGWATCH_CONFIG_TOML` | `config.toml` 的完整內容 | 直接複製貼上檔案內容 |
| `TELEGRAM_SESSION_BASE64` | Base64 編碼的 session 檔 | 見下方步驟 |

### 設定步驟

1. **本機登入一次**以產生 session 檔：

   ```bash
   pip install -e .
   cp config.example.toml config.toml
   # 填入 api_id、api_hash、target_chat_id、tracked_user_ids 等
   tgwatch once --config config.toml --since 1m
   # 按提示輸入手機號碼與驗證碼
   ```

2. **編碼 session 檔**：

   ```bash
   # macOS
   base64 -i data/tgwatch.session
   # Linux
   base64 data/tgwatch.session
   ```

3. **新增 Secrets**：在 fork 倉庫的 Settings → Secrets and variables → Actions → New repository secret。
   - `TGWATCH_CONFIG_TOML`：貼上 `config.toml` 內容
   - `TELEGRAM_SESSION_BASE64`：貼上 base64 輸出

4. **完成。** 工作流每天 UTC 02:00 自動執行。也可在 Actions 頁面手動觸發，自訂時間窗（如 `48h`）。

### 運作方式

- 工作流從 Secrets 中還原 `config.toml` 與 session 檔
- 執行 `tgwatch once --since 24h` 擷取最近 24 小時的訊息
- 將 HTML 報告與 SQLite 資料庫上傳為 GitHub Actions Artifact（保留 30 天）
- 每次執行後清理敏感檔案

### 注意事項

- **Session 失效**：若在 Telegram「使用中的裝置」中撤銷該 session，工作流會報錯。重新在本機執行步驟 1–3 即可。
- **隱私**：設定與 session 檔透過 Secret 注入，不會提交至倉庫。Artifact 僅對倉庫協作者可見。
- **無 AI 摘要**：目前工作流僅蒐集原始訊息並產生 HTML 報告。基於 LLM 的智慧摘要為後續規劃功能。

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

版本更新記錄見 [CHANGELOG.md](CHANGELOG.md)。

## 授權

MIT，詳見 `LICENSE`。
