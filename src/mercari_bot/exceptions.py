#!/usr/bin/env python3
"""カスタム例外クラス定義"""

from __future__ import annotations


class MercariBotError(Exception):
    """MercariBot 基底例外"""


class DiscountError(MercariBotError):
    """値下げ処理関連エラー"""


class ModifiedTimeParseError(DiscountError):
    """更新時間テキストのパースに失敗した場合の例外"""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__(f"更新時間のパースに失敗しました: {text!r}")


class PriceError(DiscountError):
    """価格関連エラー"""


class PriceRetrievalError(PriceError):
    """価格の取得に失敗"""


class PriceChangedError(PriceError):
    """ページ遷移中に価格が変更された"""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"ページ遷移中に価格が変更されました (期待値: {expected}, 実際: {actual})")


class PriceVerificationError(PriceError):
    """編集後の価格が意図と異なる"""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"編集後の価格が意図したものと異なっています (期待値: {expected:,}円, 実際: {actual:,}円)"
        )
