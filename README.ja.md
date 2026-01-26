# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

フォロー: [X/Twitter](https://x.com/o1xhack) · [Telegram 英語チャンネル](https://t.me/lalabeng) · [Telegram 中文チャンネル](https://t.me/o1xinsight)

## ハイライト

Mac 上で完結する Telegram ウォッチャー（Telethon 製）。主なポイントは次のとおりです。

- **ユーザーアカウントのみ**：Bot ではなく Telegram のユーザーアカウント（MTProto）で監視します。
- **ユーザー別ルーティング**：特定ユーザーだけ追跡し、必要ならコントロールチャットの Topic に分流（未設定は General）。
- **実用的なレポート**：任意のウィンドウで HTML レポートを作成し、コントロールチャットへ送信、`MSG` リンクで元メッセージへ戻れます。
- **コンテキスト保持**：引用テキストとメディアのスナップショットを SQLite とローカルに保存。
- **運用の安心**：ハートビート/エラー通知、保持クリーンアップ、FloodWait 退避、Bark 連携（任意）。

## 機能一覧

- Telegram のユーザーアカウントでログイン（MTProto、Bot 不要）。
- 複数のユーザー ID を同時に追跡し、エイリアスも設定可能。
- コントロールチャットへレポートとメッセージを送信し、`/last`・`/since`・`/export` で素早く確認。
- Telegram の Topic（テーマ）ごとにユーザーを振り分け可能。未設定は General に送信。
- 引用コンテキスト（引用テキスト + メディア）をまとめて保持。
- HTML レポートは画像を埋め込み、`MSG` リンクで元の Telegram へ戻れる。
- 古いレポート/メディアを自動で整理し、ディスク使用量を抑制。

以下ではインストール、設定、コマンドの使い方を説明します。

## 必要環境

- macOS、Python 3.11 以上
- [my.telegram.org](https://my.telegram.org/) で取得した Telegram API ID / hash（ユーザーアカウント用）
- ローカルストレージのみ（クラウドサービス不要）
- 常時監視する場合は、常にオンライン状態を保てる Mac（例: Mac mini）を用意すると安定します

## インストール

`python -m venv` か Conda のどちらかを使用してください（Python 3.11 以上）。

### 方法 0：タグ付きリリースをインストール（推奨）

固定された Git タグから安定版をインストールします：

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.1.0"

python -m tgwatch --help
```

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
> 上記のタグは常に「最新リリース済みのバージョン」（現在は `v0.1.0`）を指します。新しいタグを公開した後にのみ、このサンプルを更新してください。

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
   - `[display] show_ids`（ID を表示するか、デフォルト true）と `time_format`（strftime 形式）でコントロールチャットの名前/時刻表示を調整

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
