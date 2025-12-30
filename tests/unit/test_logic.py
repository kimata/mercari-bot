#!/usr/bin/env python3
# ruff: noqa: S101
"""
logic モジュールのテスト

Selenium に依存しない純粋ロジック関数のテストです。
"""
import pytest

import mercari_bot.logic
from mercari_bot.config import DiscountConfig, IntervalConfig, ProfileConfig
from my_lib.store.mercari.config import LineLoginConfig, MercariLoginConfig


class TestParseModifiedHour:
    """parse_modified_hour のテスト"""

    def test_seconds_ago(self):
        """秒前"""
        assert mercari_bot.logic.parse_modified_hour("30秒前") == 0

    def test_minutes_ago(self):
        """分前"""
        assert mercari_bot.logic.parse_modified_hour("15分前") == 0

    def test_hours_ago_single(self):
        """1時間前"""
        assert mercari_bot.logic.parse_modified_hour("1時間前") == 1

    def test_hours_ago_multiple(self):
        """複数時間前"""
        assert mercari_bot.logic.parse_modified_hour("5時間前") == 5

    def test_hours_ago_large(self):
        """大きい時間"""
        assert mercari_bot.logic.parse_modified_hour("23時間前") == 23

    def test_days_ago_single(self):
        """1日前"""
        assert mercari_bot.logic.parse_modified_hour("1日前") == 24

    def test_days_ago_multiple(self):
        """複数日前"""
        assert mercari_bot.logic.parse_modified_hour("3日前") == 72

    def test_days_ago_week(self):
        """1週間相当"""
        assert mercari_bot.logic.parse_modified_hour("7日前") == 168

    def test_months_ago_single(self):
        """1か月前"""
        assert mercari_bot.logic.parse_modified_hour("1か月前") == 24 * 30

    def test_months_ago_multiple(self):
        """複数月前"""
        assert mercari_bot.logic.parse_modified_hour("3か月前") == 24 * 30 * 3

    def test_over_half_year(self):
        """半年以上前"""
        assert mercari_bot.logic.parse_modified_hour("半年以上前") == 24 * 30 * 6

    def test_invalid_format_raises_error(self):
        """無効な形式でエラー"""
        with pytest.raises(mercari_bot.logic.ModifiedTimeParseError) as exc_info:
            mercari_bot.logic.parse_modified_hour("不明な形式")
        assert "不明な形式" in str(exc_info.value)

    def test_empty_raises_error(self):
        """空文字でエラー"""
        with pytest.raises(mercari_bot.logic.ModifiedTimeParseError):
            mercari_bot.logic.parse_modified_hour("")

    def test_english_format_raises_error(self):
        """英語形式でエラー"""
        with pytest.raises(mercari_bot.logic.ModifiedTimeParseError):
            mercari_bot.logic.parse_modified_hour("3 hours ago")


class TestGetDiscountStep:
    """get_discount_step のテスト"""

    def test_high_favorite_high_price(self, profile_config: ProfileConfig):
        """お気に入り多数、価格が閾値以上"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=5000,
            shipping_fee=0,
            favorite_count=15,
        )
        assert result == 200  # favorite_count >= 10 なので step=200

    def test_medium_favorite_high_price(self, profile_config: ProfileConfig):
        """お気に入り中程度、価格が閾値以上"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=3000,
            shipping_fee=0,
            favorite_count=7,
        )
        assert result == 150  # favorite_count >= 5 なので step=150

    def test_low_favorite_high_price(self, profile_config: ProfileConfig):
        """お気に入り少数、価格が閾値以上"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=2000,
            shipping_fee=0,
            favorite_count=2,
        )
        assert result == 100  # favorite_count >= 0 なので step=100

    def test_zero_favorite(self, profile_config: ProfileConfig):
        """お気に入りゼロ"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=2000,
            shipping_fee=0,
            favorite_count=0,
        )
        assert result == 100  # favorite_count >= 0 なので step=100

    def test_price_below_threshold_returns_none(self, profile_config: ProfileConfig):
        """価格が閾値未満の場合は None"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=2500,  # threshold=3000 未満
            shipping_fee=0,
            favorite_count=15,
        )
        assert result is None

    def test_price_at_threshold(self, profile_config: ProfileConfig):
        """価格が閾値ちょうど"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=3000,  # threshold=3000
            shipping_fee=0,
            favorite_count=10,
        )
        assert result == 200

    def test_single_discount_above_threshold(self, profile_single_discount: ProfileConfig):
        """単一設定で閾値以上"""
        result = mercari_bot.logic.get_discount_step(
            profile_single_discount,
            price=1000,
            shipping_fee=0,
            favorite_count=0,
        )
        assert result == 100

    def test_single_discount_below_threshold(self, profile_single_discount: ProfileConfig):
        """単一設定で閾値未満"""
        result = mercari_bot.logic.get_discount_step(
            profile_single_discount,
            price=400,  # threshold=500 未満
            shipping_fee=0,
            favorite_count=0,
        )
        assert result is None

    def test_with_shipping_fee(self, profile_config: ProfileConfig):
        """送料がある場合（price は送料抜き）"""
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=3000,
            shipping_fee=500,
            favorite_count=10,
        )
        assert result == 200

    def test_exact_favorite_boundary(self, profile_config: ProfileConfig):
        """お気に入り数が境界値ちょうど"""
        # favorite_count=10 で step=200
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=5000,
            shipping_fee=0,
            favorite_count=10,
        )
        assert result == 200

        # favorite_count=9 で step=150
        result = mercari_bot.logic.get_discount_step(
            profile_config,
            price=5000,
            shipping_fee=0,
            favorite_count=9,
        )
        assert result == 150


class TestRoundPrice:
    """round_price のテスト"""

    def test_round_down(self):
        """切り捨て"""
        assert mercari_bot.logic.round_price(1234) == 1230

    def test_round_down_nine(self):
        """9で終わる場合"""
        assert mercari_bot.logic.round_price(1239) == 1230

    def test_already_rounded(self):
        """既に10円単位"""
        assert mercari_bot.logic.round_price(1230) == 1230

    def test_zero(self):
        """ゼロ"""
        assert mercari_bot.logic.round_price(0) == 0

    def test_small_value(self):
        """小さい値"""
        assert mercari_bot.logic.round_price(5) == 0

    def test_ten(self):
        """10円"""
        assert mercari_bot.logic.round_price(10) == 10

    def test_large_value(self):
        """大きい値"""
        assert mercari_bot.logic.round_price(123456) == 123450

    def test_typical_discount_scenario(self):
        """典型的な値下げシナリオ"""
        # 3000円から100円引いて2900円
        assert mercari_bot.logic.round_price(3000 - 100) == 2900
        # 2950円から100円引いて2850円
        assert mercari_bot.logic.round_price(2950 - 100) == 2850
        # 2945円から100円引いて2840円（切り捨て）
        assert mercari_bot.logic.round_price(2945 - 100) == 2840


class TestGetDiscountStepEdgeCases:
    """get_discount_step の境界ケーステスト"""

    def test_no_matching_favorite_count(self):
        """どの条件にもマッチしない favorite_count"""
        # favorite_count > 0 を要求する設定
        from mercari_bot.config import DiscountConfig, IntervalConfig, ProfileConfig
        from my_lib.store.mercari.config import LineLoginConfig, MercariLoginConfig

        profile = ProfileConfig(
            name="High Favorite Only",
            mercari=MercariLoginConfig(user="test@example.com", password="test"),
            discount=[
                DiscountConfig(favorite_count=100, step=500, threshold=5000),
                DiscountConfig(favorite_count=50, step=300, threshold=3000),
            ],
            interval=IntervalConfig(hour=24),
            line=LineLoginConfig(user="user", password="pass"),
        )

        # favorite_count=10 はどの条件にもマッチしない
        result = mercari_bot.logic.get_discount_step(
            profile,
            price=10000,
            shipping_fee=0,
            favorite_count=10,  # 50未満
        )

        assert result is None


class TestModifiedTimeParseError:
    """ModifiedTimeParseError のテスト"""

    def test_error_message(self):
        """エラーメッセージにテキストが含まれる"""
        error = mercari_bot.logic.ModifiedTimeParseError("テスト文字列")
        assert "テスト文字列" in str(error)
        assert error.text == "テスト文字列"

    def test_error_inheritance(self):
        """Exception を継承している"""
        error = mercari_bot.logic.ModifiedTimeParseError("test")
        assert isinstance(error, Exception)
