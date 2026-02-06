# 変更履歴

[English](CHANGELOG.md) | [简体中文](CHANGELOG.zh-Hans.md) | [繁體中文](CHANGELOG.zh-Hant.md) | [日本語](CHANGELOG.ja.md)

> 記事は新しい順に並んでいます。各項目は対応する要件番号を示します。

## 1.0.0 — 2026-02-04
- マルチターゲット監視とコントロールグループのルーティングを提供し、ローカル GUI とマッピング UX を改善（REQ-20260202-001-multi-admin-monitoring、REQ-20260203-001-config-gui-design、REQ-20260204-003-gui-control-mapping-ux）。
- ワンクリック起動スクリプトと GUI ランナー操作（run/once、バックグラウンドログ、Stop GUI）を追加し、GUI 起動クラッシュを修正（REQ-20260203-002-gui-launcher-and-runner、REQ-20260204-001-gui-launcher-loglevel-fix、REQ-20260204-002-gui-stop-button）。
- config_version = 1.0 を強制し、target_chat_id + user_id によるターゲット別 Topic マッピングとアプリ内移行フローを追加（REQ-20260204-004-topic-mapping-per-target、REQ-20260204-006-config-migration-flow）。
- 移行とデフォルト命名に関するテストを補強し、ドキュメントを更新（REQ-20260205-001-audit-tests-docs）。
- 移行を簡素化し、`config-old-0.1.toml` バックアップのみ作成（REQ-20260205-002-drop-config-sample）。
- run once を単一ターゲットに絞り込めるようにし、CLI/GUI に追加（REQ-20260205-003-once-target-filter）。
- `config-old-*.toml` の移行バックアップを git で無視（REQ-20260205-004-ignore-old-configs）。
- GUI の run once に push トグルとログ表示上限を追加（REQ-20260205-005-gui-once-push-toggle）。
- GUI の起動前ガードを追加：session 不在時は警告表示して Run/Once を無効化し、`retention_days > 180` は画面内確認で処理して端末の y/n 待ちを回避（REQ-20260205-006-gui-run-guards）。
- GUI の retention 操作を改善：Run daemon はクリック可能のままにし、クリック後に確認フロー（チェック後に確認ボタン有効）で長期保持実行を開始（REQ-20260205-007-gui-retention-click-confirm-flow）。
- GUI に `Stop daemon` 操作を追加し、run 起動後に retention 確認パネルが残る不具合を修正。Runner パネル上で daemon の起動/停止を完結可能に（REQ-20260205-008-gui-run-stop-and-confirm-dismiss）。
- push 前の校正として GUI Runner のエラーハンドリング経路を補強し、run/stop/retention 確認フローのドキュメント整合性を更新（REQ-20260205-009-pre-push-calibration-audit）。
- ランチャースクリプトを Conda（`tgwatch`）優先・venv 自動フォールバックに更新し、セットアップ文書（多言語）を整合（REQ-20260205-010-launcher-conda-prefer-fallback-venv）。
- ランチャーの堅牢性を改善：macOS ランチャーを bash 互換にし、pip ツール更新失敗時も警告を出してインストール継続を試行（REQ-20260205-011-launcher-shell-and-bootstrap-robustness）。

## 0.3.0 — 2026-01-29
- 送信専用の第2アカウントによるブリッジを追加し、プライマリアカウントの通知を復元（REQ-20260129-002-bridge-implementation）。
- デュアルアカウント設定時にプライマリ/送信アカウントのログイン表示を明確化（REQ-20260129-003-sender-login-prompt）。
- デュアルアカウントのログイン案内をユーザー向けに整理し、ターミナルで明確に区別（REQ-20260129-004-friendly-login-prompts）。

## 0.2.0 — 2026-01-25
- フォーラム Topic（トピック）への任意ルーティングを追加し、指定ユーザーを制御チャットの Topic にマッピング可能に（未設定は General トピックへ）（REQ-20260125-002-topic-routing）。
- コントロールチャットの blockquote で余計な空行が出る問題を修正（REQ-20260125-003-reply-blockquote-regression）。
- README のハイライト/機能一覧を更新し、Topic ルーティング等の説明を反映（REQ-20260125-004-readme-refresh）。
- 完了済み要件を `docs/requests/Done/` にアーカイブしてアクティブ一覧を簡潔化（REQ-20260125-005-archive-done-requests）。
- run モードの “Watcher is still running” がアイドル間隔ごとに再送されるよう修正（REQ-20260125-006-heartbeat-repeat）。
- Topic ルーティング有効時にユーザーごとに HTML レポートを分割して送信（REQ-20260125-007-topic-report-split）。
- v0.2.0 に合わせて README のインストール tag と設定案内を更新（REQ-20260125-008-readme-release-tag）。

## 0.1.2 — 2026-01-24
- run モードのサマリーで activity tracker と Bark ラベルが渡らない問題を修正し、Bark/コントロールチャット通知と “Watcher is still running” の心拍を復元（REQ-20260124-024-run-notify-regression）。
- run サマリーで tracker/bark コンテキストが渡ることを保証する回帰テストを追加（REQ-20260124-024-run-notify-regression）。

## 0.1.1 — 2026-01-24
- リリース管理フローを導入：各要件で SemVer を選び、changelog を更新し、README からリンク（REQ-20260124-023-versioning-log）。

## 0.1.0 — 2026-01-23
- telegram-watch MVP を提供：Telethon ベースの監視、ログイン、ユーザー絞り込み、SQLite 永続化、メディア保存、HTML レポートの制御チャット配信（REQ-20260117-001-mvp-bootstrap）。
- `doctor`/`once`/`run` の CLI を追加し、FloodWait 対応、Bark 通知、保持期間の清掃、引用コンテキスト取得を提供（REQ-20260117-001-mvp-bootstrap）。
- 詳細な設定ガイド（README + `docs/configuration.md`）を公開し、API 資格情報、Chat ID、ローカルパス、プライバシー注意点を説明（REQ-20260117-002-config-docs）。
