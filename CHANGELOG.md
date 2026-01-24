# Changelog

このプロジェクトにおけるすべての重要な変更はこのファイルに記録されます。

フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に基づいています。
このプロジェクトは [Semantic Versioning](https://semver.org/spec/v2.0.0.html) に準拠しています。

## [Unreleased]

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
