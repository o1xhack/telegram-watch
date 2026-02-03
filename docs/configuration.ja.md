# 設定ガイド

[English](configuration.md) | [简体中文](configuration.zh-Hans.md) | [繁體中文](configuration.zh-Hant.md) | [日本語](configuration.ja.md)

`tgwatch` は `config.toml` から実行パラメータを読み込みます。このファイルはローカルにのみ保存し、共有やコミットはしないでください。`python -m tgwatch ...` を実行する前に、すべての項目を埋めてください。

## 1. サンプルをコピー

```bash
cp config.example.toml config.toml
```

初回ログイン前に全項目を編集してください。

推奨：ローカル GUI（既定 `http://127.0.0.1:8765`）で編集します。

```bash
tgwatch gui
```

## 2. Telegram 認証情報（`[telegram]`）

項目 | 取得方法 | 注意点
----- | -------- | ------
`api_id` | 監視に使う電話番号で [my.telegram.org](https://my.telegram.org) にログイン → **API development tools** → アプリを作成 → 数字の `App api_id` をコピー。 | ユーザーアカウントのみ。Bot トークンは不可。
`api_hash` | `api_id` と同じページにある `App api_hash` をコピー。 | パスワード同様に扱い、共有しない。
`session_file` | Telethon のセッションファイルの保存先（既定 `data/tgwatch.session`）。 | リポジトリ内に置く場合は git ignore 済みであることを確認。別場所の場合は読み書き可能に。

初回実行（`python -m tgwatch run ...`）でコード入力が求められ、セッションファイルが作成されます。

## 3. 送信側アカウント（任意）（`[sender]`）

「A が取得、B が送信」のブリッジに使います。送信はアカウント B が行い、アカウント A が通知を受け取れるようにします。

項目 | 意味 | 注意点
----- | ---- | ------
`session_file` | 送信側アカウント（B）のセッションファイル。 | `[sender]` を設定する場合は必須。`[telegram]` と同じ `api_id` / `api_hash` を使いますが、`telegram.session_file` とは別パスにしてください。

初回実行時にアカウント B のログインコード入力が求められます。アカウント B がコントロールチャットに参加し、投稿権限があることを確認してください。不要な場合は `[sender]` を省略できます。

## 4. 監視対象グループ（`[[targets]]`）

各 `[[targets]]` エントリが 1 つの監視対象グループ/チャンネルを表します。単一の対象だけなら旧形式の `[target]` も使えますが、複数対応の形式を推奨します。上限：ターゲット 5 件、各ターゲット 5 ユーザー、control group 5 件。手動編集も可能ですがミスが起きやすいので非推奨です。

項目 | 意味 | 取得方法
----- | ---- | ----
`name` | ターゲット名/ラベル | 任意の短い文字列（ログ/コマンドで使用）
`target_chat_id` | 監視対象グループ/チャンネルの数値 ID。スーパーグループ/チャンネルは `-100` で始まる。 | Telegram Desktop/モバイルでチャットを開く → タイトル → 招待リンクをコピー → `@userinfobot`/`@getidsbot`/`@RawDataBot` に送ると `chat_id = -100...` が返ります。招待リンクがない場合は下記参照。
`tracked_user_ids` | 追跡するユーザー ID の配列。 | 各ユーザーに `@userinfobot` へ送信してもらうか、`@userinfobot` をグループに追加して `/whois @username`。例の `[11111111, 22222222]` を実 ID に置き換え。
`summary_interval_minutes` | 任意：ターゲットごとのレポート間隔 | 未設定なら `reporting.summary_interval_minutes`
`control_group` | このターゲットの送信先 control group | 複数の control group がある場合は必須

ヒント：

- ID は数値のみ。ユーザー名は不可。
- 追跡対象のみ入力（他ユーザーは無視）。
- スーパーグループは `-100` プレフィックスを保持（`MSG` リンクが正しく動作）。

### エイリアス（任意）

読みやすさのために別名を付けられます（ターゲットごとに設定）：

```toml
[[targets]]
name = "group-1"
target_chat_id = -1001234567890
tracked_user_ids = [11111111, 22222222]

[targets.tracked_user_aliases]
11111111 = "Alice"
22222222 = "Bob (PM)"
```

キーは対象ターゲットの `tracked_user_ids` に含まれる必要があります。制御チャットとレポートで `Alice (11111111)` のように表示されます。

### 招待リンクのないプライベートグループ

以下の方法で `target_chat_id` を取得できます：

1. **メッセージを ID Bot に転送**  
   グループ内のメッセージを `@userinfobot`/`@RawDataBot` に転送すると `Chat ID: -100...` が返ります。転送時に「送信者名を隠す」をオフにしてください。
2. **ID Bot を一時的に追加**  
   転送できない場合、管理者に依頼して `@userinfobot` を一時追加し、`/mychatid` または `/whois` を実行して ID を控えたら削除。
3. **Telegram Desktop の開発者情報**  
   macOS で Telegram Desktop（Qt 版）を使用：
   1. `Telegram Desktop` メニュー → **Preferences…**（`⌘,`）。
   2. **Advanced** → **Experimental settings** → **Enable experimental features** と **Show message IDs** をオン。
   3. グループでメッセージを右クリック → **Copy message link**。`https://t.me/c/1234567890/55` のようなリンクを `-1001234567890` に変換して `target_chat_id` に記入。

ネイティブの macOS 版（丸アイコン）しかない場合は Desktop 版か Web 版（`https://web.telegram.org/k/`）を利用してください。

## 5. コントロールグループ（`[control_groups]`）

コントロールグループはレポートとコマンド（`/last`、`/since` など）の送信先です。複数の control group を定義し、`targets[].control_group` でマッピングできます。

項目 | 説明 | 推奨
----- | ---- | ----
`control_chat_id` | レポート/コマンドの送信先。 | “Saved Messages” か自分だけのグループを推奨。
`is_forum` | コントロールチャットが Topics（フォーラム）を有効にしているか。 | 通常グループや “Saved Messages” は `false`。
`topic_routing_enabled` | ユーザーごとの Topic ルーティングを有効化。 | 不要なら `false`。
`topic_user_map` | ユーザー ID → Topic ID の対応表。 | `topic_routing_enabled = true` の場合のみ。

control group が 1 つだけなら `targets[].control_group` は省略可能です。複数ある場合は各ターゲットで必ず指定してください。

### Topic ルーティング（フォーラムグループ）

`is_forum = true` かつ `topic_routing_enabled = true` の場合、tgwatch はユーザーごとに対応する Topic へ送信します。未設定ユーザーは General に送られます。
Topic ルーティング有効時は、HTML レポートもユーザーごとに分割され、メッセージ送信前に対応 Topic へ送られます。

例：

```toml
[control_groups.main]
control_chat_id = -1009876543210
is_forum = true
topic_routing_enabled = true

[control_groups.main.topic_user_map]
11111111 = 9001  # Alice -> Topic A
22222222 = 9002  # Bob -> Topic B
```

#### Topic ID の取得方法

Topic ID は Topic 作成時のシステムメッセージ ID です。取得手順：

1. コントロールグループを開き、対象 Topic へ移動。
2. Topic 作成のシステムメッセージ（または最初のメッセージ）を見つける。
3. 右クリックで **Copy message link**。
4. `https://t.me/c/1234567890/9001` の末尾 `9001` が Topic ID。

General の Topic ID は常に `1` です。Topic ルーティングを無効にすると General に送信されます。

## 6. ローカル保存（`[storage]`）

項目 | 説明 | 既定値
----- | ---- | ------
`db_path` | SQLite DB の保存先。 | `data/tgwatch.sqlite3`
`media_dir` | メディア保存先ディレクトリ。 | `data/media`

デフォルトのままでも任意の書き込み可能なパスでも構いません。`doctor` が作成可否と書き込み権限を確認します。

## 7. レポート（`[reporting]`）

項目 | 説明 | 既定値
----- | ---- | ------
`reports_dir` | HTML レポートのルート。`reports/YYYY-MM-DD/HHMM/index.html` 形式。 | `reports`
`summary_interval_minutes` | `run` のデフォルトレポート間隔（ターゲットごとに `targets[].summary_interval_minutes` で上書き可能）。 | `120`
`timezone` | IANA タイムゾーン（例 `Asia/Tokyo`、`America/Los_Angeles`）。 | `UTC`
`retention_days` | レポート/メディアの保持日数。超過分は自動削除。180 日超は確認。 | `30`

各ウィンドウで HTML レポートを生成し、コントロールチャットへ送信後、メッセージ（引用・メディア含む）を送ります。

## 8. 表示（`[display]`）

項目 | 説明 | 既定値
----- | ---- | ------
`show_ids` | コントロールチャットに ID を表示するか。 | `true`
`time_format` | 時刻表示（strftime）。空欄ならデフォルト。 | `%Y.%m.%d %H:%M:%S (%Z)`

## 9. 通知（`[notifications]`）

項目 | 説明 | 既定値
----- | ---- | ------
`bark_key` | Bark のキー。設定するとレポート/心拍/エラーが通知されます。 | （空）

## 10. 設定の検証

編集後に次を実行：

```bash
python -m tgwatch doctor --config config.toml
```

`doctor` で確認される内容：

- 必須項目が揃っているか
- session/db/media/report のディレクトリが作成可能か
- SQLite スキーマが作成可能か

問題なければ実行可能です：

```bash
python -m tgwatch once --config config.toml --since 2h
python -m tgwatch run --config config.toml
```

> `config.toml`、`*.session`、`data/`、`reports/` をコミットしないでください。
