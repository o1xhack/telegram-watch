# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

フォロー: [X/Twitter](https://x.com/o1xhack) · [Telegram 英語チャンネル](https://t.me/lalabeng) · [Telegram 中文チャンネル](https://t.me/o1xinsight)

## ハイライト

Mac 上で完結する Telegram ウォッチャー（Telethon 製）。主な特徴は以下のとおりです。

- **ユーザーアカウントで監視**：Bot ではなく自分の Telegram アカウントでログインし、指定したスーパーグループ/チャンネル内の特定ユーザーを追跡します。
- **コンテキストを丸ごと保存**：テキスト、引用スレッド、メディアのサムネイルを SQLite とローカルメディアフォルダに記録します。
- **自動レポート**：5〜120 分など任意のウィンドウで HTML レポートを生成し、コントロールチャットにアップロードしたあと、同じウィンドウのメッセージを順番にプッシュします。`MSG` リンクをクリックすると元の Telegram メッセージにジャンプできます。
- **インライン画像プレビュー**：HTML 内の画像は Base64 で埋め込み、Telegram やモバイル端末で直接レポートを開いても表示できます。
- **ハートビートとアラート**：2 時間アクティビティがない場合は「Watcher is still running」を送信し、未処理の例外で終了する際もエラー概要をコントロールチャットに通知します。
- **保持ポリシー**：`reporting.retention_days`（デフォルト 30 日）でレポート/メディアを自動削除。180 日を超える設定では起動前に確認メッセージを表示します。
- **Bark 連携（任意）**：Bark Key を設定すると、レポート・ハートビート・エラー発生時に “Telegram Watch” グループでプッシュ通知を受け取れます。

以下ではインストール、設定、コマンドの使い方を説明します。

## 必要環境

- macOS、Python 3.11 以上
- [my.telegram.org](https://my.telegram.org/) で取得した Telegram API ID / hash（ユーザーアカウント用）
- ローカルストレージのみ（クラウドサービス不要）

## インストール

`python -m venv` か Conda のどちらかを使用してください（Python 3.11 以上）。

### 方法 A：`python -m venv`

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
```

### 方法 B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -e .
```

> ヒント：コマンド実行時はどちらか一方の環境のみアクティブにしてください。プロンプトに `(.venv)` または `(tgwatch)` が表示されていることを確認しましょう。

## 設定

1. サンプル設定をコピー：

   ```bash
   cp config.example.toml config.toml
   ```

2. `config.toml` を編集して次の値を入力します：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（デフォルト `data/tgwatch.session`）
   - `target.target_chat_id`（監視対象グループ/チャンネルの ID）
   - `target.tracked_user_ids`（追跡するユーザー ID の配列）
   - `[target.tracked_user_aliases]`（オプション：ID と表示名の対応表）
   - `control.control_chat_id`（レポート・コマンドの送受信先）
   - `storage.db_path` と `storage.media_dir`
   - `reporting.reports_dir`, `reporting.summary_interval_minutes`（レポートの間隔）
   - `reporting.timezone`（例：`Asia/Tokyo`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（レポート/メディアの保持日数。デフォルト 30、180 を超えると警告）
   - `[notifications] bark_key`（任意の Bark Key。設定するとスマホ通知を受け取れます）

### Bark Key の取得方法

1. Bark アプリをインストールして開き、右上の歯車 → 「コピー」からデバイスキーを取得します（例 `xxxxxxxxxxxxxxxxxxxxxxxx`）。
2. `config.toml` に以下のように入力：

   ```toml
   [notifications]
   bark_key = "あなたのBarkKey"
   ```

3. `tgwatch run ...` を実行すると、レポート/ハートビート/エラーが “Telegram Watch” グループで Bark に届きます。

詳しい取得方法や入力例は `docs/configuration.md` を参照してください。

> ⚠️ `config.toml`、セッションファイル、`data/`、`reports/` など機密情報は Git へコミットしないでください。

## 使い方

すべてのコマンドは `python -m tgwatch ...` または `tgwatch ...` で実行できます。必ず `--config` を指定してください。

### Doctor

設定とディレクトリ、SQLite スキーマを検証：

```bash
python -m tgwatch doctor --config config.toml
```

### Once（単発レポート）

直近のウィンドウ（例：2 時間）のメッセージを取得・保存し、`reports/YYYY-MM-DD/HHMM/index.html` を生成：

```bash
python -m tgwatch once --config config.toml --since 2h
# --push を付けるとレポートとメッセージを即座にコントロールチャットへ送信（テストに便利）
python -m tgwatch once --config config.toml --since 2h --push
```

### Run（常駐モード）

初回実行時はターミナルで Telegram のログインコード入力が必要です：

```bash
python -m tgwatch run --config config.toml
```

常駐モードでは：

- 監視対象のチャットを常時リッスンし、テキスト・引用・メディアを保存。
- 各 `summary_interval_minutes` ごとに HTML レポートを生成し、コントロールチャットへ転送後、対象ユーザーのメッセージを順番に通知。
- レポート内の画像は Base64 埋め込みで、Telegram 上でもそのまま閲覧可能。
- コントロールチャットでは次のコマンドが利用できます（自分のアカウント限定）：
  - `/help`
  - `/last <user_id|@username> [N]`
  - `/since <10m|2h|ISO>`
  - `/export <10m|2h|ISO>`

## テスト

```bash
pytest
```

## プライバシーと安全性

- すべてローカルで動作し、外部サービスへアップロードしません。
- API hash、電話番号、チャット内容はログしません。
- セッションファイルや生成物は `.gitignore` 済みで、機密情報を守ります。
- Telethon の Flood-wait バックオフにより、ログイン/ダウンロード/通知が安定します。

## ライセンス

MIT（詳細は `LICENSE` を参照）。
