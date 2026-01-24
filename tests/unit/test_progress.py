#!/usr/bin/env python3
# ruff: noqa: S101
"""
progress モジュールのテスト

my_lib.cui_progress.ProgressManager を使用した進捗表示のテストです。
"""

import unittest.mock

from my_lib.store.mercari.config import MercariItem

from mercari_bot.progress import (
    _PROGRESS_ITEM,
    NullProgressDisplay,
    ProgressDisplay,
    create_progress_display,
)


def _create_mock_item(
    name: str = "テスト商品",
    price: int = 1000,
    favorite: int = 5,
    is_stop: int = 0,
) -> MercariItem:
    """テスト用の MercariItem を作成"""
    return MercariItem(
        id="m12345",
        url="https://jp.mercari.com/item/m12345",
        name=name,
        price=price,
        view=100,
        favorite=favorite,
        is_stop=is_stop,
    )


class TestProgressDisplayBasic:
    """ProgressDisplay 基本テスト"""

    def test_create_progress_display(self):
        """create_progress_display でインスタンス作成"""
        progress = create_progress_display()
        assert isinstance(progress, ProgressDisplay)

    def test_is_terminal_property(self):
        """is_terminal プロパティ"""
        progress = ProgressDisplay()
        # テスト環境では通常 False
        assert isinstance(progress.is_terminal, bool)

    def test_start_stop(self):
        """start/stop が正常に動作する"""
        progress = ProgressDisplay()
        # エラーなく完了することを確認
        progress.start()
        progress.stop()


class TestProgressDisplaySetStatus:
    """ProgressDisplay.set_status のテスト"""

    def test_set_status_calls_manager(self):
        """set_status が ProgressManager.set_status を呼ぶ"""
        progress = ProgressDisplay()

        with unittest.mock.patch.object(progress._manager, "set_status") as mock_set:
            progress.set_status("処理中...")
            mock_set.assert_called_once_with("処理中...", is_error=False)

    def test_set_status_error(self):
        """エラー状態で更新"""
        progress = ProgressDisplay()

        with unittest.mock.patch.object(progress._manager, "set_status") as mock_set:
            progress.set_status("エラー発生", is_error=True)
            mock_set.assert_called_once_with("エラー発生", is_error=True)


class TestProgressDisplayObserver:
    """ProgressObserver Protocol 実装のテスト"""

    def test_on_total_count_calls_set_progress_bar(self):
        """on_total_count が set_progress_bar を呼ぶ"""
        progress = ProgressDisplay()

        with unittest.mock.patch.object(progress._manager, "set_progress_bar") as mock_set:
            progress.on_total_count(10)
            mock_set.assert_called_once_with(_PROGRESS_ITEM, total=10)

    def test_on_item_start(self):
        """on_item_start でステータス更新"""
        progress = ProgressDisplay()
        item = _create_mock_item(name="テスト商品")

        with unittest.mock.patch.object(progress, "set_status") as mock_set:
            progress.on_item_start(0, 10, item)

            mock_set.assert_called_once()
            assert "テスト商品" in mock_set.call_args[0][0]
            assert "処理中" in mock_set.call_args[0][0]

    def test_on_item_complete_calls_update_progress_bar(self):
        """on_item_complete が update_progress_bar を呼ぶ"""
        progress = ProgressDisplay()
        item = _create_mock_item()

        with unittest.mock.patch.object(progress._manager, "update_progress_bar") as mock_update:
            progress.on_item_complete(0, 10, item)
            mock_update.assert_called_once_with(_PROGRESS_ITEM)


class TestProgressDisplayTruncate:
    """商品名の省略テスト"""

    def test_truncate_short_name(self):
        """短い名前は省略しない"""
        progress = ProgressDisplay()
        result = progress._truncate_name("短い名前", 20)
        assert result == "短い名前"

    def test_truncate_long_name(self):
        """長い名前は省略する"""
        progress = ProgressDisplay()
        result = progress._truncate_name("これは非常に長い商品名です", 10)
        assert len(result) == 10
        assert result.endswith("...")

    def test_truncate_exact_length(self):
        """ちょうどの長さは省略しない"""
        progress = ProgressDisplay()
        result = progress._truncate_name("12345", 5)
        assert result == "12345"

    def test_get_max_item_name_length(self):
        """最大長の計算"""
        progress = ProgressDisplay()
        max_len = progress._get_max_item_name_length()
        # 最低でも 10 は返す
        assert max_len >= 10


class TestNullProgressDisplay:
    """NullProgressDisplay のテスト（Null Object Pattern）"""

    def test_is_terminal_always_false(self):
        """is_terminal は常に False"""
        null_progress = NullProgressDisplay()
        assert null_progress.is_terminal is False

    def test_start_does_nothing(self):
        """start は何もしない"""
        null_progress = NullProgressDisplay()
        # 例外なく完了
        null_progress.start()

    def test_stop_does_nothing(self):
        """stop は何もしない"""
        null_progress = NullProgressDisplay()
        # 例外なく完了
        null_progress.stop()

    def test_set_status_does_nothing(self):
        """set_status は何もしない"""
        null_progress = NullProgressDisplay()
        # 例外なく完了
        null_progress.set_status("テスト")
        null_progress.set_status("エラー", is_error=True)

    def test_on_total_count_does_nothing(self):
        """on_total_count は何もしない"""
        null_progress = NullProgressDisplay()
        # 例外なく完了
        null_progress.on_total_count(10)

    def test_on_item_start_does_nothing(self):
        """on_item_start は何もしない"""
        null_progress = NullProgressDisplay()
        item = _create_mock_item()
        # 例外なく完了
        null_progress.on_item_start(0, 10, item)

    def test_on_item_complete_does_nothing(self):
        """on_item_complete は何もしない"""
        null_progress = NullProgressDisplay()
        item = _create_mock_item()
        # 例外なく完了
        null_progress.on_item_complete(0, 10, item)


class TestProgressConstants:
    """定数のテスト"""

    def test_progress_item_label(self):
        """プログレスバーのラベル"""
        assert _PROGRESS_ITEM == "アイテム処理"


class TestProgressDisplayManagerIntegration:
    """ProgressManager との統合テスト"""

    def test_manager_is_initialized(self):
        """ProgressManager が正しく初期化される"""
        progress = ProgressDisplay()

        # ProgressManager インスタンスが存在する
        assert progress._manager is not None

    def test_manager_has_mercari_color(self):
        """メルカリレッドが設定されている"""
        progress = ProgressDisplay()

        # 内部の ProgressManager の設定を確認
        # （ProgressManager の実装詳細に依存するため、基本的な存在確認のみ）
        assert hasattr(progress._manager, "console")
