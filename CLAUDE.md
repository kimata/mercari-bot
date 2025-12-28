# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業する際のガイダンスを提供します。

## プロジェクト概要

mercari-bot は、メルカリに出品中のアイテムの価格を自動的に値下げするボットです。Selenium WebDriver を使用してメルカリにログインし、お気に入り数やアイテムの価格に応じて戦略的な価格調整を行います。

### 主な機能

- お気に入り数に応じた値下げ戦略
- 複数プロファイル（アカウント）対応
- LINE 経由のログイン認証
- CAPTCHA 対応（音声認識）
- Slack/メール通知

## 開発コマンド

```bash
# 依存関係のインストール
uv sync

# ヘルプ表示
uv run python src/app.py -h

# デバッグモード（価格変更は行わない）
uv run python src/app.py -D

# 通常実行（ログ通知付き）
uv run python src/app.py -l

# 設定ファイル指定
uv run python src/app.py -c custom-config.yaml

# Docker で実行（推奨）
docker compose run --build --rm mercari-bot

# テスト実行
uv run pytest

# 型チェック
uv run mypy src/
uv run pyright src/
```

## アーキテクチャ

```
src/
├── app.py                          # エントリポイント（docopt CLI）
└── mercari_bot/
    ├── config.py                   # 設定読み込み・型定義（dataclass）
    └── mercari_price_down.py       # 値下げ処理ロジック
```

### 処理フロー

1. `app.py`: 設定読み込み → 各プロファイルに対して `mercari_price_down.execute()` を実行
2. `mercari_price_down.py`:
   - `my_lib.store.mercari.login.execute()` でログイン
   - `my_lib.store.mercari.scrape.iter_items_on_display()` で出品中アイテムを取得
   - `_execute_item()` で各アイテムの値下げ処理

### 値下げロジック

- 更新から一定時間経過したアイテムのみ対象（`interval.hour` で設定）
- お気に入り数に応じて値下げ幅を決定（`discount` で設定）
- 最低価格（`threshold`）を下回る場合はスキップ
- 価格は 10 円単位に丸める

## コーディング規約

### インポートスタイル

```python
# NG: from xxx import yyy
# OK: import xxx として xxx.yyy でアクセス
import my_lib.selenium_util
import my_lib.store.mercari.login
```

例外: dataclass や型定義は直接インポート可

```python
from mercari_bot.config import AppConfig, ProfileConfig
```

### CLI

- docopt を使用
- エントリポイントは `src/app.py`
- `if __name__ == "__main__":` で引数解析

### 設定

- YAML 形式（`config.yaml`）
- JSON Schema で検証（`config.schema`）
- `mercari_bot/config.py` で `dataclass` として型定義

## 設定ファイル

`config.example.yaml` を参考に `config.yaml` を作成：

```yaml
profile:
  - name: Profile 1
    line:
      user: LINE ユーザ ID
      pass: LINE パスワード
    discount:
      - favorite_count: 10  # お気に入り数が10以上
        step: 200           # 200円値下げ
        threshold: 3000     # 3000円が下限
      - favorite_count: 0   # デフォルト
        step: 100
        threshold: 3000
    interval:
      hour: 20              # 20時間以内に更新済みならスキップ

# オプション: Slack 通知
slack:
  bot_token: xoxp-...
  from: Mercari Bot
  info:
    channel:
      name: "#mercari"
  captcha:
    channel:
      name: "#captcha"
      id: XXXXXXXXXXX
  error:
    channel:
      name: "#error"
      id: XXXXXXXXXXX
    interval_min: 180
```

## 依存関係

### 主要ライブラリ

- `my-lib`: 共通ライブラリ（Selenium 操作、メルカリログイン、通知）
- `selenium`: ブラウザ自動化
- `undetected-chromedriver`: 検出回避付き Chrome ドライバ
- `pydub` / `speechrecognition`: CAPTCHA 音声認識
- `docopt-ng`: CLI パーサー

### my-py-lib

`my_lib` のコードは `../my-py-lib` に存在します。リファクタリングで `my_lib` も修正した方がよい場合：

1. `../my-py-lib` を修正
2. commit & push
3. このリポジトリの `pyproject.toml` を更新（コミットハッシュ）
4. `uv sync`

**重要**: `my_lib` を修正する際は、何を変更したいのかを説明し、確認を取ること。

## プロジェクト管理ファイル

`pyproject.toml` をはじめとする一般的なプロジェクト管理ファイルは、`../py-project` で管理しています。

**重要**: 以下のファイルを直接編集しないこと：

- `pyproject.toml`
- `.pre-commit-config.yaml`
- `renovate.json`
- その他 `py-project` が管理する設定ファイル

修正が必要な場合：

1. `../py-project` のテンプレートを更新
2. `uv run src/app.py -p mercari-bot --apply` で適用
3. `uv sync` で依存関係を更新

**重要**: 修正する際は、何を変更したいのかを説明し、確認を取ること。

## インフラ

### Docker

- ベースイメージ: Ubuntu 24.04
- Google Chrome 同梱
- `uv` でパッケージ管理
- エントリポイント: `./src/app.py -l`

### Kubernetes

`kubernetes/` に CronJob 設定（1日2回実行：9:00, 21:00）

### CI/CD

GitHub Actions（`.github/workflows/docker.yaml`）:

- Docker イメージのビルド・プッシュ（ghcr.io）
- ブランチ/タグに応じたイメージタグ付け

## テスト

```bash
# ユニットテスト
uv run pytest

# カバレッジ付き
uv run pytest --cov=src --cov-report=html

# 特定テスト
uv run pytest tests/test_typecheck.py
```

E2E テストはデフォルトで除外（`--ignore=tests/e2e`）。

## ドキュメント更新

**重要**: コードを更新した際は、以下のドキュメントの更新が必要か検討すること：

- `README.md`: ユーザ向けの機能説明・セットアップ手順
- `CLAUDE.md`: 開発者（Claude Code）向けのガイダンス

特に以下の変更時は更新を検討：

- 新機能の追加
- 設定項目の変更
- 依存関係の追加・変更
- アーキテクチャの変更
