#!/usr/bin/env python3
# ruff: noqa: S101
"""
progress モジュールのテスト

Rich による進捗表示のテストです。
my_lib.cui_progress を使用した実装のテストを行います。
"""

from conftest import create_mock_item

from mercari_bot.progress import (
    _PROGRESS_ITEM,
    NullProgressDisplay,
    ProgressDisplay,
    create_progress_display,
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

    def test_start_stop_non_tty(self):
        """非 TTY 環境での start/stop"""
        progress = ProgressDisplay()
        # 非 TTY では何も起こらない
        progress.start()
        progress.stop()
        # エラーなく完了することを確認


class TestProgressDisplaySetStatus:
    """ProgressDisplay.set_status のテスト"""

    def test_set_status_updates_text(self):
        """ステータステキストを更新"""
        progress = ProgressDisplay()
        progress.set_status("処理中...")
        # ManagerのステータステキストがセットされていればOK
        assert progress._manager._status_text == "処理中..."

    def test_set_status_error(self):
        """エラー状態で更新"""
        progress = ProgressDisplay()
        progress.set_status("エラー発生", is_error=True)

        assert progress._manager._status_text == "エラー発生"
        assert progress._manager._status_is_error is True

    def test_set_status_normal_after_error(self):
        """エラー後に通常状態に戻す"""
        progress = ProgressDisplay()
        progress.set_status("エラー", is_error=True)
        progress.set_status("復帰")

        assert progress._manager._status_text == "復帰"
        assert progress._manager._status_is_error is False


class TestProgressDisplayObserver:
    """ProgressObserver Protocol 実装のテスト"""

    def test_on_total_count(self):
        """on_total_count でプログレスバーを作成"""
        progress = ProgressDisplay()
        progress.on_total_count(10)

        assert progress._manager.has_progress_bar(_PROGRESS_ITEM)

    def test_on_item_start(self):
        """on_item_start でステータス更新"""
        progress = ProgressDisplay()
        item = create_mock_item(name="テスト商品")

        progress.on_item_start(0, 10, item)

        assert "テスト商品" in progress._manager._status_text
        assert "🏷️" in progress._manager._status_text

    def test_on_item_complete(self):
        """on_item_complete でプログレスバーを更新"""
        progress = ProgressDisplay()
        progress.on_total_count(10)
        progress.on_item_complete(0, 10, create_mock_item())

        task = progress._manager.get_progress_bar(_PROGRESS_ITEM)
        assert task.count == 1


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


class TestProgressConstants:
    """定数のテスト"""

    def test_progress_item_label(self):
        """プログレスバーのラベル"""
        assert _PROGRESS_ITEM == "アイテム処理"


class TestProgressDisplayManager:
    """ProgressManager との統合テスト"""

    def test_manager_is_initialized(self):
        """ProgressManager が正しく初期化される"""
        progress = ProgressDisplay()

        # メルカリ固有の設定が適用されている
        assert progress._manager._color == "#E72121"
        assert progress._manager._title == " メルカリ "
        assert progress._manager._description_width == 20
        assert progress._manager._show_remaining_time is False


class TestNullProgressDisplay:
    """NullProgressDisplay のテスト（Null Object Pattern）"""

    def test_is_terminal_always_false(self):
        """is_terminal は常に False"""
        progress = NullProgressDisplay()
        assert progress.is_terminal is False

    def test_start_does_nothing(self):
        """start は何もしない"""
        progress = NullProgressDisplay()
        progress.start()  # エラーなく完了

    def test_stop_does_nothing(self):
        """stop は何もしない"""
        progress = NullProgressDisplay()
        progress.stop()  # エラーなく完了

    def test_set_status_does_nothing(self):
        """set_status は何もしない"""
        progress = NullProgressDisplay()
        progress.set_status("テスト")
        progress.set_status("エラー", is_error=True)
        # エラーなく完了

    def test_on_total_count_does_nothing(self):
        """on_total_count は何もしない"""
        progress = NullProgressDisplay()
        progress.on_total_count(10)
        # エラーなく完了

    def test_on_item_start_does_nothing(self):
        """on_item_start は何もしない"""
        progress = NullProgressDisplay()
        item = create_mock_item()
        progress.on_item_start(0, 10, item)
        # エラーなく完了

    def test_on_item_complete_does_nothing(self):
        """on_item_complete は何もしない"""
        progress = NullProgressDisplay()
        item = create_mock_item()
        progress.on_item_complete(0, 10, item)
        # エラーなく完了
