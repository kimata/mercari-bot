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

`from xxx import yyy` は基本的に使用せず、`import xxx` としてモジュールをインポートし、参照時は `xxx.yyy` と完全修飾名で記述する：

```python
# 推奨
import my_lib.selenium_util
import my_lib.store.mercari.login

driver = my_lib.selenium_util.create_driver(...)

# 非推奨
from my_lib.selenium_util import create_driver

driver = create_driver(...)
```

これにより、関数やクラスがどのモジュールに属しているかが明確になり、コードの可読性と保守性が向上する。

例外: dataclass や型定義は直接インポート可

```python
from mercari_bot.config import AppConfig, ProfileConfig
```

### 型アノテーションと型情報のないライブラリ

型情報を持たないライブラリを使用する場合、大量の `# type: ignore[union-attr]` を記載する代わりに、変数に `Any` 型を明示的に指定する：

```python
from typing import Any

# 推奨: Any 型を明示して type: ignore を不要にする
result: Any = some_untyped_lib.call()
result.method1()
result.method2()

# 非推奨: 大量の type: ignore コメント
result = some_untyped_lib.call()  # type: ignore[union-attr]
result.method1()  # type: ignore[union-attr]
result.method2()  # type: ignore[union-attr]
```

これにより、コードの可読性を維持しつつ型チェッカーのエラーを抑制できる。

### pyright エラーへの対処方針

pyright のエラー対策として、各行に `# type: ignore` コメントを記載して回避するのは**最後の手段**とする。

**優先順位：**

1. **型推論できるようにコードを修正する** - 変数の初期化時に型が明確になるようにする
2. **型アノテーションを追加する** - 関数の引数や戻り値、変数に適切な型を指定する
3. **Any 型を使用する** - 型情報のないライブラリの場合（上記セクション参照）
4. **`# type: ignore` コメント** - 上記で解決できない場合の最終手段

```python
# 推奨: 型推論可能なコード
items: list[str] = []
items.append("value")

# 非推奨: type: ignore の多用
items = []  # type: ignore[var-annotated]
items.append("value")  # type: ignore[union-attr]
```

**例外：** テストコードでは、モックやフィクスチャの都合上 `# type: ignore` の使用を許容する。

### CLI

- docopt を使用
- エントリポイントは `src/app.py`
- `if __name__ == "__main__":` で引数解析

### 設定

- YAML 形式（`config.yaml`）
- JSON Schema で検証（`schema/config.schema`）
- `mercari_bot/config.py` で `dataclass` として型定義

### パス設定の扱い

設定ファイルで相対パスを指定する場合、`my_lib.config.resolve_path()` を使用して設定ファイルの場所を基準とした絶対パスに解決する：

```python
import my_lib.config

# config.yaml の場所を基準にパスを解決
selenium_path = my_lib.config.resolve_path(raw_config, data["selenium"])
```

DataConfig には str ではなく pathlib.Path を格納し、使用側での変換を不要にする。

### my_lib との型整合性

my_lib が特定の型（dataclass 等）を使用する場合、mercari-bot 側でもその型を使用する。これにより IDE の補完が効き、型安全性が向上する。

```python
# 推奨: my_lib の型を使用
from my_lib.store.mercari.config import MercariItem

def on_item_start(self, index: int, total: int, item: MercariItem) -> None:
    name = item.name  # 属性アクセス

# 非推奨: dict[str, Any] で受け取る
def on_item_start(self, index: int, total: int, item: dict[str, Any]) -> None:
    name = item.get("name", "不明")  # キーアクセス
```

TYPE_CHECKING ブロックで条件付きインポートすることで、実行時のインポートを避けつつ型チェックを有効にできる：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_lib.store.mercari.config import MercariItem

def process_item(item: MercariItem) -> None:
    ...
```

## 設定ファイル

`config.example.yaml` を参考に `config.yaml` を作成：

```yaml
profile:
    - name: Profile 1
      line:
          user: LINE ユーザ ID
          pass: LINE パスワード
      discount:
          - favorite_count: 10 # お気に入り数が10以上
            step: 200 # 200円値下げ
            threshold: 3000 # 3000円が下限
          - favorite_count: 0 # デフォルト
            step: 100
            threshold: 3000
      interval:
          hour: 20 # 20時間以内に更新済みならスキップ

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

## リファクタリング調査の観点

コードをリファクタリングする際、以下の観点で改善可能性を調査する：

1. **Protocol / 型エイリアス**: `| None` チェックの繰り返しがある場合、Null Object Pattern または型エイリアスの導入を検討
2. **dict → dataclass/TypedDict**: 型情報が失われる `dict[str, Any]` は TypedDict で型安全にする
3. **型の統一**: 外部ライブラリが提供する型（dataclass 等）がある場合、それを使用
4. **コードの重複**: 同じ処理の繰り返しがある場合、共通化を検討
5. **冗長なアクセス**: 同じ要素への複数回アクセスは変数にキャッシュ
6. **後方互換性コード**: 不要になった互換性コード（再エクスポート等）は削除
7. **マジックナンバー**: ハードコーディングされた数値は定数化を検討
8. **my_lib 活用**: 共通ライブラリの機能を積極的に活用
9. **テストの重複排除**: テストコード内で同じモック・フィクスチャ設定が繰り返される場合、conftest.py やテストモジュール内に共通 fixture として抽出
10. **Null Object Pattern の活用**: 通知やプログレス表示などで「何もしない」バージョンが必要な場合、NullProgressDisplay のようにクラスを分離し、モック代わりに使用
11. **設定オブジェクト作成の一元化**: AppConfig や DataConfig など複数テストで繰り返し使用するオブジェクトは fixture として定義
12. **Boolean 比較のスタイル**: 空コレクションの判定には `if collection:` / `if not collection:` を使用し、`len(collection) != 0` や `len(collection) == 0` は避ける。ただし、int 型との比較（例: `is_stop != 0`）は明示的な比較が適切
13. **標準ライブラリの適切な使用**: `random.randint(a, b)` は `int(random.random() * n)` より明確。標準ライブラリが提供する適切な関数を使用する
14. **Selenium DOM アクセスの最適化**: 同一要素への複数回アクセスが必要な場合、最初の `find_elements()` 結果をキャッシュすることでパフォーマンスを向上できる。ただし、DOM の動的変更がある場合はキャッシュ無効化に注意

ただし、以下の場合は改善を見送る：

- 改善によるメリットがデメリット（複雑化、保守コスト増）を上回らない
- 過剰設計となる場合（不要な Protocol 導入等）
- 既存の実装で十分機能している場合
- YAML schema 等で既に検証済みの場合（`dict[str, Any]` → TypedDict は効果薄）

## 開発ワークフロー規約

### リポジトリ構成

- **プライマリリポジトリ**: GitLab (`gitlab.green-rabbit.net`)
- **ミラーリポジトリ**: GitHub (`github.com/kimata/mercari-bot`)

GitLab にプッシュすると、自動的に GitHub にミラーリングされます。GitHub への直接プッシュは不要です。

### コミット時の注意

- 今回のセッションで作成し、プロジェクトが機能するのに必要なファイル以外は git add しないこと
- 気になる点がある場合は追加して良いか質問すること

### リリース時の作業

タグを打つ際は、以下の手順で CHANGELOG.md を更新すること：

1. `[Unreleased]` セクションの内容を新しいバージョンセクションに移動
2. バージョン番号と日付を追加（例: `## [0.1.1] - 2026-01-24`）
3. 空の `[Unreleased]` セクションを新規作成
4. ファイル末尾のバージョン比較リンクを更新
5. 以下のカテゴリを絵文字付きで記載：
    - `### ✨ Added`: 新機能
    - `### 🔄 Changed`: 既存機能の変更
    - `### 🐛 Fixed`: バグ修正
    - `### 🗑️ Removed`: 削除された機能
    - `### 🔒 Security`: セキュリティ関連の修正
    - `### ⚡ Performance`: パフォーマンス改善
    - `### 📝 Documentation`: ドキュメント更新
    - `### 🧪 Tests`: テスト関連
    - `### 🔧 CI`: CI/CD 関連
    - `### 🏗️ Infrastructure`: インフラ関連

### バグ修正の原則

- 憶測に基づいて修正しないこと
- 必ず原因を論理的に確定させた上で修正すること
- 「念のため」の修正でコードを複雑化させないこと

### コード修正時の確認事項

- 関連するテストも修正すること
- 関連するドキュメントも更新すること
- mypy, pyright, ty がパスすることを確認すること
