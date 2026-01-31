# telegram-watch

[English](README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

フォロー: [X/Twitter](https://x.com/o1xhack) · [Telegram 英語チャンネル](https://t.me/lalabeng) · [Telegram 中文チャンネル](https://t.me/o1xinsight)

## 主要機能

雑多な Telegram グループ/チャンネルを、個人向けの“問い合わせ可能なシグナル”に変換 — **完全ローカル、Bot 不要**。

- **重要な人だけ監視**：大規模グループ内の高シグナルなアカウントのみ追跡（ユーザー ID で指定）。
- **コントロールチャットのダッシュボード**：Saved Messages か自分が管理する私的グループで通知とダイジェストを受け取り、`/last`・`/since`・`/export` で即時確認（自分のアカウントのみ）。
- **定期 HTML ダイジェスト + メッセージ送信**：HTML レポートにコンテキストとメディアスナップショットを含め、各メッセージをコントロールチャットに送信。各メッセージには原文へ戻る `MSG` リンク付き。
- **証跡の保持**：メッセージと引用テキストは SQLite に保存、メディアはディスクに保存。
- **自動整理**：ユーザーごとに Topic（フォーラム）へ分流可能。未設定は General。
- **長期運用に強い**：保持期限の清掃、心拍/エラー通知、FloodWait 退避で安定運用。
- **プライバシー優先**：すべてローカルで完結。アップロードや第三者収集なし。
- **通知ミラー（任意）**：Bark でサマリー/心拍/エラー通知を外部に転送可能。

コミュニティ運営、調査、トレードなど **シグナル抽出 + ローカルアーカイブ** が必要な人に最適。

以下はインストール、設定、使い方の説明です。

## 必要環境

- macOS、Python 3.11 以上
- [my.telegram.org](https://my.telegram.org/) で取得した Telegram API ID / hash（ユーザーアカウント用）
- ローカルストレージのみ（クラウドサービス不要）
- 常時監視する場合は、常にオンライン状態を保てる Mac（例: Mac mini）推奨

## インストール

PyPI 未公開のため、Git からのインストール（タグ）またはローカルの editable インストールで行います。

### ステップ 1 — パッケージのインストール（推奨：タグ版）

**推奨（安定・再現性）：タグ版をインストール**

> `tgwatch` を動かすだけならこちら。

```bash
pip install "git+https://github.com/o1xhack/telegram-watch.git@v0.3.1"
python -m tgwatch --help
```

**開発用：editable インストール**

> ローカルで改修する場合。

```bash
pip install -e .
python -m tgwatch --help
```

### ステップ 2 — Python 環境を作成（どちらか）

`venv` か Conda を使用（Python ≥ 3.11）。

#### オプション A：`python -m venv`（推奨）

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

#### オプション B：Conda

```bash
conda create -n tgwatch python=3.11
conda activate tgwatch
python -m pip install -U pip
```

> ヒント：実行前にどちらか一方の環境のみ有効にしてください。プロンプトに `(.venv)` または `(tgwatch)` が表示されていることを確認。

### ステップ 3 — 同じ手順を実行

インストール後：

1) `config.example.toml` → `config.toml`
2) `tgwatch doctor` を実行
3) `tgwatch once --since 2h --push` でテスト
4) `tgwatch run` を起動（常駐）

## 設定

1. サンプル設定をコピー：

   ```bash
   cp config.example.toml config.toml
   ```

2. `config.toml` を編集して次の値を入力します：

   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（デフォルト `data/tgwatch.session`）
   - `[sender] session_file`（任意：通知復元のために送信専用の第二アカウントを使う場合）
   - `target.target_chat_id`（監視対象グループ/チャンネルの ID）
   - `target.tracked_user_ids`（追跡するユーザー ID の配列）
   - `[target.tracked_user_aliases]`（オプション：ID と表示名の対応表）
   - `control.control_chat_id`（レポート・コマンドの送受信先）
   - `control.is_forum` / `control.topic_routing_enabled` / `[control.topic_user_map]`（任意：ユーザー別に TG Topic へ振り分け）
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

詳しい取得方法や入力例は [docs/configuration.md](docs/configuration.md) を参照してください。

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

- 監視対象のチャットを常時リッスンし、追跡ユーザーのメッセージを保存（テキスト、引用、メディア快照）。
- `summary_interval_minutes` ごとに HTML レポートを生成してコントロールチャットへ送信し、その時間枠のメッセージを順次通知。
- 画像は通常 Base64 で HTML に埋め込み、読み取れない場合は相対パスにフォールバック。
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
- Flood-wait 退避は Telegram API 呼び出し（送信、ダウンロード、エンティティ解決）に適用されます。

## Changelog

更新履歴は [docs/CHANGELOG.md](docs/CHANGELOG.md) を参照してください。

## ライセンス

MIT（詳細は `LICENSE` を参照）。
