# telegram-watch

[English](../README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

[![Release](https://img.shields.io/github/v/release/o1xhack/telegram-watch?style=for-the-badge&label=release&color=7c3aed)](https://github.com/o1xhack/telegram-watch/releases/latest)
[![Stars](https://img.shields.io/github/stars/o1xhack/telegram-watch?style=for-the-badge&label=stars&color=7c3aed)](https://github.com/o1xhack/telegram-watch/stargazers)
[![License](https://img.shields.io/github/license/o1xhack/telegram-watch?style=for-the-badge&label=license&color=7c3aed)](../LICENSE)

[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-o1xhack-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/o1xhack)

**ドキュメント版:** `v1.0.7`（release `v1.7.0`）

フォロー: [X/Twitter](https://x.com/o1xhack) · [Telegram 英語チャンネル](https://t.me/lalabeng) · [Telegram 中文チャンネル](https://t.me/o1xinsight)

## 主要機能

雑多な Telegram グループ/チャンネルを、私用かつ構造化されたシグナルシステムに変換 — **完全ローカル、Bot 不要**。

![telegram-watch GUI](assets/tgwatch-gui-v1.png)

- **マルチターゲット監視**：複数グループ/チャンネルを同時監視し、ターゲットごとに監視対象・別名・集計間隔を個別設定。
- **コントロールグループ振り分け**：各ターゲットを指定コントロールグループへルーティングし、運用導線を分離。
- **ターゲット単位 Topic マッピング**：フォーラムモードで `target_chat_id + user_id` を Topic ID に対応付け、同一ユーザー ID でも元グループごとに別 Topic へ送信。
- **GUI 優先の設定体験**：認証情報、ターゲット、コントロールグループ、マッピング、保存先をローカル GUI から管理。ブラウザ言語に基づき中国語・英語を自動切替。
- **ワンクリック起動**：Conda（`tgwatch`）優先で起動し、利用不可時は自動で `venv` にフォールバック。
- **GUI ランナー制御**：Run once（単一ターゲット選択・push 任意）、Run daemon、Stop daemon、ライブログ確認を一画面で実行。
- **安全な実行ガード**：session 事前チェック、長期保持時の確認フロー、GUI 上の明示的なエラーメッセージ。
- **自動再接続**：daemon モードで一時的なネットワーク障害発生時に指数バックオフで自動再接続し、復旧後コントロールチャットに通知を送信。
- **ローカル永続化**：メッセージを SQLite に保存し、メディアをスナップショット化して HTML レポートを生成。
- **リアルタイムプッシュモード** *（実験的）*：追跡対象ユーザーのメッセージを受信即座にコントロールチャットへ転送。7 層レート保護システムでアカウント制限を防止。
- **プライバシー重視設計**：クラウド依存なし、機密値のログ出力なし、実行時の機密ファイルは git 対象外。

コミュニティ運営、調査、トレードなど **シグナル抽出 + ローカルアーカイブ** が必要な人に最適。

## クイックスタート

5 ステップで開始。必要なもの：**macOS + Python 3.11 以上**、Telegram ユーザーアカウント。

### 1. Telegram API 認証情報を取得

[my.telegram.org](https://my.telegram.org/) にアクセスし、電話番号でサインイン。アプリを作成して **API ID** と **API Hash** を取得します。

### 2. リポジトリをクローン

安定版リリースをクローン（推奨）：

```bash
git clone --branch v1.7.0 https://github.com/o1xhack/telegram-watch.git
cd telegram-watch
```

> 最新コードが必要な場合は `main` をクローン：`git clone https://github.com/o1xhack/telegram-watch.git`

### 3. ランチャーをダブルクリック

Finder で **`launch_tgwatch.command`** をダブルクリックします。自動的に以下を実行します：
- Python 環境を作成（Conda `tgwatch` があればそれを使用、なければ `.venv`）
- 全依存パッケージをインストール
- `config.example.toml` → `config.toml` がなければコピー
- ブラウザで GUI を起動

### 4. GUI で設定

GUI が開いたら（`http://127.0.0.1:8765`）：
1. Telegram セクションに **API ID** と **API Hash** を入力
2. **Target** を追加（監視するグループ/チャンネルと追跡ユーザー ID）
3. **Control Group** を追加（レポートとメッセージの送信先）
4. **Save** をクリック

### 5. 初回ログイン（ターミナル）

初回は Telegram 認証コードをターミナルで入力する必要があります：

```bash
# ランチャーを使用した場合、同じ環境を有効にしてください：
# Conda: conda activate tgwatch
# venv:  source .venv/bin/activate

python -m tgwatch run --config config.toml
```

電話番号と認証コードを入力してください。接続後、デーモンが動作を開始します。`Ctrl+C` で停止するか、今後は GUI の **Run daemon** / **Stop daemon** を使用できます。

> **ヒント**：初回ログイン後は、起動/停止すべて GUI から操作できます。ターミナルは不要です。

## 手動インストール

<details>
<summary>開発者向け、またはランチャーを使用しない場合</summary>

### Python 環境を作成（どちらか）

#### オプション A：venv（推奨）

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

#### オプション B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

### パッケージをインストール

**Editable インストール（開発用）：**

```bash
pip install -e .
```

**タグ版インストール（安定・バージョン固定）：**

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.8.0"
```

### 設定と実行

```bash
cp config.example.toml config.toml
tgwatch gui          # GUI で設定を編集、または config.toml を手動編集
tgwatch doctor       # 設定を検証
tgwatch once --since 2h --push   # テスト実行
tgwatch run          # デーモンを起動
```

</details>

## 設定

**GUI の使用を推奨**（`tgwatch gui` またはランチャー）— すべての設定を網羅し、構文エラーを防止します。

`config.toml` を手動で編集する場合は [configuration.md](configuration.md) を参照してください。主要なフィールド：

| セクション | フィールド | 説明 |
|-----------|-----------|------|
| `telegram` | `api_id`、`api_hash` | Telegram API 認証情報 |
| `telegram` | `session_file` | Session パス（デフォルト `data/tgwatch.session`） |
| `sender` | `session_file` | 任意の第二アカウント session |
| `targets[]` | `target_chat_id`、`tracked_user_ids` | 監視対象 |
| `targets[]` | `name`、`tracked_user_aliases` | 任意のラベルと別名 |
| `targets[]` | `summary_interval_minutes`、`control_group` | ターゲット別オーバーライド |
| `control_groups.<name>` | `control_chat_id` | レポート送信先 |
| `control_groups.<name>` | `is_forum`、`topic_routing_enabled`、`topic_target_map` | Topic ルーティング |
| `control_groups.<name>` | `skip_html_report` | HTML ファイルをスキップし個別メッセージのみ送信 |
| `reporting` | `reports_dir`、`summary_interval_minutes`、`timezone`、`retention_days` | レポート設定 |
| `storage` | `db_path`、`media_dir` | ローカルストレージパス |
| `notifications` | `bark_key` | 任意の Bark プッシュ通知 |
| `display` | `show_ids`、`time_format` | 表示フォーマット |
| `realtime` | `push_mode` | `"interval"`（デフォルト）または `"realtime"`（実験的） |
| `realtime` | `rate_limit_per_minute`、`rate_limit_per_hour`、`rate_limit_per_day` | レート保護制限 |

単一ターゲット構成は従来どおり `[target]` + `[control]` でも動作します。

### 単一ターゲット Run once

`tgwatch once` は既定で全ターゲットを実行します。単一ターゲットだけ実行するには、ターゲット名または `target_chat_id` を指定：

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

### 旧設定からの移行

古い設定（`config_version` がない）から更新すると、tgwatch は停止して移行を促します。

1. GUI はロックされ、**Migrate Config** ボタンが表示されます。
2. CLI の `run`/`once` は赤字エラーと移行確認を表示します。
3. 移行で `config.toml` を `config-old-0.1.toml` に改名し、値を引き継いだ新しい `config.toml` を作成します。

### Bark プッシュ通知

1. Bark アプリをインストールし、歯車 → デバイスキーをコピー。
2. 設定に追加：`[notifications]` → `bark_key = "あなたのKey"`（または GUI で設定）。
3. レポート、ハートビート、エラーが「Telegram Watch」グループで Bark に届きます。

### リアルタイムプッシュモード *（実験的）*

デフォルトでは、tgwatch はメッセージを収集して定期的にまとめて送信します（「interval」モード）。**リアルタイムモード**はメッセージ到着と同時にコントロールチャットへ転送します。

1. GUI の **Realtime Push Mode** セクションで **Realtime (Experimental)** に切り替え。
2. リスク確認ダイアログを承認（レート制限を超えるとアカウント制限の可能性があります）。
3. 必要に応じてレート保護設定を調整 — デフォルト値は控えめに設定されています。

リアルタイムモードには **7 層レート保護**が組み込まれています：スライディングウィンドウ（20 件/分）、ジッター付き遅延（3 秒 ± 1 秒）、メディア追加遅延（+2 秒）、時間/日次上限（200/時、1000/日）、FloodWait 指数バックオフ、サーキットブレーカー（30 分自動停止 + Bark 通知）、起動ウォームアップ（5 分 @ 5 件/分）。詳細は[設定ガイド](configuration.ja.md)を参照してください。

> ⚠️ `config.toml`、セッションファイル、`data/`、`reports/` など機密情報は Git へコミットしないでください。

## 使い方

すべてのコマンド：`python -m tgwatch <cmd>` または `tgwatch <cmd>`。必ず `--config config.toml` を指定。

### Doctor

設定とディレクトリ、SQLite スキーマを検証：

```bash
tgwatch doctor --config config.toml
```

### GUI（ローカル設定画面）

ローカル UI を起動（既定 `http://127.0.0.1:8765`）：

```bash
tgwatch gui
```

GUI には **Run once**、**Run daemon**、**Stop daemon** ボタンとライブログがあります。`Run daemon` はバックグラウンドで動作するため、ブラウザを閉じても停止しません。再度 GUI を開くとログを再表示します。

### Once（単発レポート）

直近のウィンドウのメッセージを取得・保存し、HTML レポートを生成：

```bash
tgwatch once --config config.toml --since 2h
# --push を付けるとコントロールチャットへ即座に送信
tgwatch once --config config.toml --since 2h --push
```

### Run（常駐モード）

初回実行時はターミナルで Telegram のログインコード入力が必要です：

```bash
tgwatch run --config config.toml
```

常駐モードでは：
- 各ターゲットチャットを常時リッスンし、追跡ユーザーのメッセージを保存（テキスト、引用、メディア快照）。
- 各ターゲットの集計間隔ごとに HTML レポートを生成して対応するコントロールチャットへ送信し、メッセージを順次通知。
- コントロールチャットでコマンドが利用可能（自分のアカウント限定）：`/help`、`/last`、`/since`、`/export`。

## GitHub Actions（自動日次取得）

GitHub Actions を使って `tgwatch once` をスケジュール実行できます。ローカルのデーモンは不要。本リポジトリを Fork し、2 つの GitHub Secret を設定するだけです。

### 必要な GitHub Secrets

| Secret | 内容 | 生成方法 |
|--------|------|----------|
| `TGWATCH_CONFIG_TOML` | `config.toml` の全内容 | ファイルの内容をコピー＆ペースト |
| `TELEGRAM_SESSION_BASE64` | Base64 エンコードされた session ファイル | 以下の手順を参照 |

### セットアップ手順

1. **ローカルで一度ログイン**して session ファイルを生成：

   ```bash
   pip install -e .
   cp config.example.toml config.toml
   # api_id、api_hash、target_chat_id、tracked_user_ids などを入力
   tgwatch once --config config.toml --since 1m
   # 電話番号と認証コードの入力を求められます
   ```

2. **session ファイルをエンコード**：

   ```bash
   # macOS
   base64 -i data/tgwatch.session
   # Linux
   base64 data/tgwatch.session
   ```

3. **Secrets を追加**：Fork 先の Settings → Secrets and variables → Actions → New repository secret。
   - `TGWATCH_CONFIG_TOML`：`config.toml` の内容を貼り付け
   - `TELEGRAM_SESSION_BASE64`：base64 の出力を貼り付け

4. **完了。** ワークフローは毎日 UTC 02:00 に自動実行されます。Actions タブから手動で時間ウィンドウ（例：`48h`）を指定して実行することもできます。

### 仕組み

- ワークフローが Secrets から `config.toml` と session ファイルを復元
- `tgwatch once --since 24h` で直近 24 時間のメッセージを取得
- HTML レポートと SQLite データベースを GitHub Actions Artifact としてアップロード（30 日保持）
- 実行後に機密ファイルをクリーンアップ

### 注意事項

- **Session の失効**：Telegram の「アクティブなセッション」から該当 session を無効にすると、ワークフローはエラーで終了します。ローカルで手順 1–3 を再実行してください。
- **プライバシー**：設定と session ファイルは Secret から注入され、リポジトリにはコミットされません。Artifact はリポジトリのコラボレーターのみ閲覧可能です。
- **AI 要約なし**：現在のワークフローは生メッセージの収集と HTML レポート生成のみです。LLM ベースの要約は今後の機能として計画中です。

## テスト

```bash
pytest
```

## プライバシーと安全性

- すべてローカルで動作し、外部サービスへアップロードしません。
- API hash、電話番号、チャット内容はログしません。
- セッションファイルや生成物は `.gitignore` 済みで、機密情報を守ります。
- Flood-wait 退避は Telegram API 呼び出し（送信、ダウンロード、エンティティ解決）に適用されます。

## Changelog

更新履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。

## ライセンス

MIT（詳細は `LICENSE` を参照）。
