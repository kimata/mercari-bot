#!/usr/bin/env python3
"""
純粋ロジック関数群

Selenium や DOM アクセスに依存しない、テスト容易な関数を定義します。
"""
from __future__ import annotations

import logging
import re

from mercari_bot.config import ProfileConfig


class ModifiedTimeParseError(Exception):
    """更新時間テキストのパースに失敗した場合の例外"""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__(f"更新時間のパースに失敗しました: {text!r}")


def parse_modified_hour(text: str) -> int:
    """更新時間テキストを時間単位にパース

    Args:
        text: 更新時間テキスト（例: "3時間前", "2日前", "1か月前"）

    Returns:
        経過時間（時間単位）

    Raises:
        ModifiedTimeParseError: パースできない形式の場合
    """
    if re.search(r"秒前", text) or re.search(r"分前", text):
        return 0
    elif re.search(r"時間前", text):
        return int("".join(filter(str.isdigit, text)))
    elif re.search(r"日前", text):
        return int("".join(filter(str.isdigit, text))) * 24
    elif re.search(r"か月前", text):
        return int("".join(filter(str.isdigit, text))) * 24 * 30
    elif re.search(r"半年以上前", text):
        return 24 * 30 * 6
    else:
        raise ModifiedTimeParseError(text)


def get_discount_step(
    profile: ProfileConfig, price: int, shipping_fee: int, favorite_count: int
) -> int | None:
    """お気に入り数と価格から値下げ幅を決定

    Args:
        profile: プロファイル設定
        price: 現在価格（送料抜き）
        shipping_fee: 送料
        favorite_count: お気に入り数

    Returns:
        値下げ幅。値下げしない場合は None
    """
    for discount_info in sorted(profile.discount, key=lambda x: x.favorite_count, reverse=True):
        if favorite_count >= discount_info.favorite_count:
            if price >= discount_info.threshold:
                return discount_info.step
            else:
                logging.info(
                    "現在価格が%s円 (送料: %s円) のため、スキップします。", f"{price:,}", f"{shipping_fee:,}"
                )
                return None

    logging.info("イイねの数(%d)が条件を満たさなかったので、スキップします。", favorite_count)
    return None


def round_price(price: int) -> int:
    """価格を10円単位に丸める

    Args:
        price: 価格

    Returns:
        10円単位に丸めた価格
    """
    return (price // 10) * 10
