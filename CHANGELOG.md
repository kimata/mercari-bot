# Changelog

このプロジェクトにおけるすべての重要な変更はこのファイルに記録されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づいています。
このプロジェクトは [Semantic Versioning](https://semver.org/spec/v2.0.0.html) に準拠しています。

## [Unreleased]

### ✨ Added

- 値下げ履歴の記録機能を追加（アイテム毎の処理結果を SQLite の `data.history` に記録）
- 売却検知とサマリー通知を追加（前回実行時の出品一覧との差分から売却・取り下げを検知し、値下げ履歴付きで Slack に通知）
- `parse_modified_hour()` に「◯週間前」表記のサポートを追加（サイト側の表記追加への先回り対応）
- 設定バリデーションを強化（schema に step/threshold/interval の minimum と mail セクション定義を追加、threshold < 300 とデフォルト discount 条件の欠如を警告ログで検出）

### 🔄 Changed

- 値下げ後の価格が下限（threshold）を下回る場合は値下げしないよう変更（従来は下限を一度だけ下回ることがあった）
- アイテム単位の処理が失敗しても次のアイテムに進むよう変更（2 アイテム連続で失敗した場合のみ中断）
- 終了コードを「-1 の合算」から失敗プロファイル有無による 0/1 に変更（`mercari_price_down.execute()` の戻り値も bool 化、ログに N/M プロファイル成功を出力）
- ダイアログ閉じ処理を my_lib の公開 API `close_popup()` に集約（ARIA 属性ベース + Escape フォールバックの実装に一本化、my-py-lib 1a56915）
- `mercari_price_down.execute()` の引数から `data_path` / `dump_path` を削除（config から取得するよう統一）
- ProgressObserver の TypeAlias を廃止し、my_lib の Protocol を拡張した `StatusProgressObserver` に変更（`# type: ignore` を解消）
- discount リストのソートをアイテム処理毎から設定読み込み時の 1 回に変更
- 到達不能な is_stop チェック（死コード）を削除

### 🐛 Fixed

- 週1回程度の頻度で LINE 再認証が必要になる問題を修正（Chrome の Preferences 肥大化バグにより起動がタイムアウトし、プロファイル退避でセッションが消失していた。my-py-lib d9df888 で肥大化した Preferences のみを起動前に削除するよう変更）
- config.example.yaml にメルカリ認証情報（user/pass）と data セクションが欠けており、そのままでは起動できなかった問題を修正
- Slack 設定を省略すると KeyError でクラッシュする問題を修正
- ブラウザ起動失敗時に Slack 通知されず、後続プロファイルも実行されない問題を修正
- 価格検証エラーがリトライにより正常終了扱いになり、通知されない問題を修正（Slack 通知の上でエラー終了するよう変更）
- 価格変更の送信後に検証がタイムアウトすると、リトライで正常終了に化ける問題を修正（送信以降のタイムアウトを `PriceVerificationTimeoutError` に変換してリトライさせず、通知の上で失敗扱いに）
- スキーマパスが CWD 相対で、リポジトリ外から実行すると FileNotFoundError になる問題を修正（`__file__` 基準で解決）
- エラーがあっても「🎉 全プロファイル完了」と表示される問題を修正（失敗時は失敗数付きのエラー表示に変更）
- 進捗表示の商品名トリミングが全角幅を考慮しておらず、ステータスバーからはみ出す問題を修正（rich.cells による表示幅ベースの切り詰めに変更）
- ブラウザクラッシュ時にエラー通知自体が失敗することがある問題を修正（current_url 取得とページダンプの失敗を握りつぶすよう変更）

### 📝 Documentation

- README のセットアップ用設定例にメルカリ認証情報と data セクションを追記
- schema/config.schema に data セクションの定義を追加
- README / CLAUDE.md を実装に同期（存在しない `src/app.py` への言及を `mercari-bot` コマンドに修正、アーキテクチャ節を実構成に更新、CronJob 時刻を 7:00/18:00 に修正、black/flake8 を ruff に修正）
- config.example.yaml の mail 設定例を現行の MailConfig 形式（smtp: host/port）に修正

## [0.1.1] - 2026-01-24

### ✨ Added

- オークション形式の出品をスキップする機能を追加
- エラー時にページソースを Slack に投稿する機能を追加
- セッションエラー時の自動リトライ機能を追加
- demo.py のユニットテストを追加
- ty 型チェッカーを CI に追加

### 🔄 Changed

- 型安全性向上と Null Object Pattern 導入
- BrowserManager 移行と例外階層の標準化
- with_session_retry() を使用してセッションリトライを共通化
- progress.py を my_lib.cui_progress に移行
- エントリポイントを [project.scripts] パターンに統一
- 内部でのみ使用される定数に \_ 接頭辞を付与
- 未使用の logging.handlers インポートを削除
- CI キャッシュキーの設計を改善
- Python パッケージをキャッシュプロキシから取得するよう設定

### 🐛 Fixed

- エラーログと Slack 通知を改善
- tmux 環境での幅調整を TMUX 環境変数で判定
- BrowserManager 導入に伴うテストのモック修正
- ty 依存関係を追加（CI エラー修正）

### 📝 Documentation

- CLAUDE.md に開発ワークフロー規約を追加

## [0.1.0] - 2025-12-31

初回リリース。メルカリ出品アイテムの自動値下げ機能を提供。

### ✨ Added

- メルカリへの自動ログイン機能（LINE 認証対応）
- 出品中アイテムの自動値下げ機能
    - お気に入り数に応じた値下げ戦略
    - 最低価格（閾値）の設定
    - 更新間隔の設定
- 複数プロファイル（アカウント）対応
- CAPTCHA 対応（音声認識）
- Slack/メール通知機能
- Rich を使用した進捗表示
- NullObject パターンで通知コードを簡潔化
- Slack 設定なしでも動作可能
- dataclass を使った型安全な設定クラス
- mypy/pyright による静的型チェック環境
- デモ用スクリプトを追加
- ユニットテストを大幅に拡充（カバレッジ 86%）
- GitHub Release ワークフロー（Nuitka を使用）
- Docker/Kubernetes 対応
- GitLab CI/CD パイプライン

### 🏗️ Infrastructure

- Ubuntu 24.04 ベースの Docker イメージ
- Google Chrome 同梱
- uv によるパッケージ管理
- Kubernetes CronJob 設定（1 日 2 回実行：9:00, 21:00）

[Unreleased]: https://github.com/kimata/mercari-bot/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/kimata/mercari-bot/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kimata/mercari-bot/releases/tag/v0.1.0
