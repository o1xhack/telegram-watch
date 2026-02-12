# telegram-watch

[English](../README.md) | [简体中文](README.zh-Hans.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md)

**ドキュメント版:** `v1.0.4`

フォロー: [X/Twitter](https://x.com/o1xhack) · [Telegram 英語チャンネル](https://t.me/lalabeng) · [Telegram 中文チャンネル](https://t.me/o1xinsight)

## 主要機能

雑多な Telegram グループ/チャンネルを、私用かつ構造化されたシグナルシステムに変換 — **完全ローカル、Bot 不要**。

![telegram-watch GUI](assets/tgwatch-gui-v1.png)

- **マルチターゲット監視**：複数グループ/チャンネルを同時監視し、ターゲットごとに監視対象・別名・集計間隔を個別設定。
- **コントロールグループ振り分け**：各ターゲットを指定コントロールグループへルーティングし、運用導線を分離。
- **ターゲット単位 Topic マッピング**：フォーラムモードで `target_chat_id + user_id` を Topic ID に対応付け、同一ユーザー ID でも元グループごとに別 Topic へ送信。
- **GUI 優先の設定体験**：認証情報、ターゲット、コントロールグループ、マッピング、保存先をローカル GUI から管理。
- **ワンクリック起動**：Conda（`tgwatch`）優先で起動し、利用不可時は自動で `venv` にフォールバック。
- **GUI ランナー制御**：Run once（単一ターゲット選択・push 任意）、Run daemon、Stop daemon、ライブログ確認を一画面で実行。
- **安全な実行ガード**：session 事前チェック、長期保持時の確認フロー、GUI 上の明示的なエラーメッセージ。
- **ローカル永続化**：メッセージを SQLite に保存し、メディアをスナップショット化して HTML レポートを生成。
- **プライバシー重視設計**：クラウド依存なし、機密値のログ出力なし、実行時の機密ファイルは git 対象外。

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
pip install "git+https://github.com/o1xhack/telegram-watch.git@v1.0.4"
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

   ワンクリックで始める場合は `launch_tgwatch.command`（macOS）または `launch_tgwatch.bat`（Windows）をダブルクリックしてください。ランチャーは Conda（`tgwatch` 環境）を優先し、Conda があれば `tgwatch` を再利用/作成、無ければ `.venv` にフォールバックします。その後、依存をインストールし、`config.toml` が無ければコピーして GUI を開きます。macOS ランチャーは bash 互換で、制限ネットワーク下で `pip/setuptools/wheel` の更新に失敗しても警告を出してプロジェクトのインストールを継続します。

   ヒント：ローカル GUI を起動して編集できます（既定 `http://127.0.0.1:8765`）。

   ```bash
   tgwatch gui
   ```

2. ローカル GUI（推奨）で設定します：

   ```bash
   tgwatch gui
   ```

   `config.toml` を直接編集する方法も残していますが、ミスが起きやすいため非推奨です。

3. 手動で編集する場合は次の値を入力します：

   - `config_version`（必ず `1.0`）
   - `telegram.api_id` / `telegram.api_hash`
   - `telegram.session_file`（デフォルト `data/tgwatch.session`）
   - `[sender] session_file`（任意：通知復元のために送信専用の第二アカウントを使う場合）
   - `targets[].name`（任意ラベル。省略時は `group-1`、`group-2` などで表示）
   - `targets[].target_chat_id`（監視対象グループ/チャンネルの ID）
   - `targets[].tracked_user_ids`（追跡するユーザー ID の配列）
   - `targets[].summary_interval_minutes`（任意：ターゲットごとのレポート間隔）
   - `targets[].control_group`（任意：複数の control group がある場合は必須）
   - `[targets.tracked_user_aliases]`（オプション：ID と表示名の対応表）
   - `control_groups.<name>.control_chat_id`（レポート・コマンドの送受信先）
   - `control_groups.<name>.is_forum` / `control_groups.<name>.topic_routing_enabled` / `[control_groups.<name>.topic_target_map.<target_chat_id>]`（任意：ユーザー別に TG Topic へ振り分け）
   - `storage.db_path` と `storage.media_dir`
   - `reporting.reports_dir`, `reporting.summary_interval_minutes`（デフォルトのレポート間隔）
   - `reporting.timezone`（例：`Asia/Tokyo`、`America/Los_Angeles` 等）
   - `reporting.retention_days`（レポート/メディアの保持日数。デフォルト 30。180 超は CLI では確認プロンプト、GUI では画面内確認フロー）
   - `[notifications] bark_key`（任意の Bark Key。設定するとスマホ通知を受け取れます）
   - `[display] show_ids`（ID を表示するか、デフォルト true）と `time_format`（strftime 形式）でコントロールチャットの名前/時刻表示を調整

単一ターゲット構成は従来どおり `[target]` + `[control]` でも動作します。

### 単一ターゲット Run once

`tgwatch once` は既定で全ターゲットを実行します。単一ターゲットだけ実行したい場合は、ターゲット名または `target_chat_id` を指定します。

```bash
tgwatch once --config config.toml --since 2h --target group-1
tgwatch once --config config.toml --since 2h --target -1001234567890
```

GUI の Run once に **Push to control chat** トグルを追加しました（既定はオフ）。

### 移行

古い設定（`config_version` がない）から更新すると、tgwatch は停止して移行を促します。

1. GUI はロックされ、**Migrate Config** ボタンが表示されます。
2. CLI の `run`/`once` は赤字エラーと移行確認を表示します。
3. 移行で `config.toml` を `config-old-0.1.toml` に改名し、値を引き継いだ新しい `config.toml` を作成します。

再実行前に新しい `config.toml` を確認してください。`config-old-0.1.toml` などのバックアップは git で無視されます。

### Bark Key の取得方法

1. Bark アプリをインストールして開き、右上の歯車 → 「コピー」からデバイスキーを取得します（例 `xxxxxxxxxxxxxxxxxxxxxxxx`）。
2. `config.toml` に以下のように入力：

   ```toml
   [notifications]
   bark_key = "あなたのBarkKey"
   ```

3. `tgwatch run ...` を実行すると、レポート/ハートビート/エラーが “Telegram Watch” グループで Bark に届きます。

詳しい取得方法や入力例は [configuration.md](configuration.md) を参照してください。

> ⚠️ `config.toml`、セッションファイル、`data/`、`reports/` など機密情報は Git へコミットしないでください。

## 使い方

すべてのコマンドは `python -m tgwatch ...` または `tgwatch ...` で実行できます。必ず `--config` を指定してください。

### Doctor

設定とディレクトリ、SQLite スキーマを検証：

```bash
python -m tgwatch doctor --config config.toml
```

### GUI（ローカル設定画面）

ローカル UI でターゲット/コントロールグループを編集（自動でブラウザが開きます）：

```bash
tgwatch gui
```

GUI には **Run once**、**Run daemon**、**Stop daemon** ボタンとライブログがあります。`Run daemon` はバックグラウンドで動作するため、ブラウザを閉じても停止しません。再度 GUI を開くとログを再表示します。まだ session ファイルが無い場合は、先に `python -m tgwatch run --config config.toml` をターミナルで一度実行してログインを完了してください。
`retention_days > 180` の場合、**Run daemon** をクリックすると画面内の確認ブロックが表示されます。リスク確認にチェックを入れると **Confirm & Start Run** が有効になります。失敗時は Runner メッセージ欄にエラーが表示されます。

### Once（単発レポート）

直近のウィンドウ（例：2 時間）のメッセージを取得・保存し、ターゲットごとに `reports/YYYY-MM-DD/HHMM/index.html` を生成：

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

- 各ターゲットチャットを常時リッスンし、追跡ユーザーのメッセージを保存（テキスト、引用、メディア快照）。
- 各ターゲットの `summary_interval_minutes`（または全体のデフォルト）ごとに HTML レポートを生成して対応するコントロールチャットへ送信し、その時間枠のメッセージを順次通知。
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

更新履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。

## ライセンス

MIT（詳細は `LICENSE` を参照）。
