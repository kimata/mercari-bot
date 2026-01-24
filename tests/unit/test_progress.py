#!/usr/bin/env python3
# ruff: noqa: S101
"""
progress モジュールのテスト

Rich による進捗表示のテストです。
"""

import unittest.mock

import rich.style
import rich.text

import mercari_bot.progress
from mercari_bot.progress import (
    _PROGRESS_ITEM,
    _STATUS_STYLE_ERROR,
    _STATUS_STYLE_NORMAL,
    ProgressDisplay,
    _DisplayRenderable,
    _NullLive,
    _NullProgress,
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

    def test_start_stop_tty(self):
        """TTY 環境での start/stop"""
        with unittest.mock.patch.object(
            mercari_bot.progress.rich.console.Console,
            "is_terminal",
            new_callable=lambda: property(lambda self: True),
        ):
            progress = ProgressDisplay()
            progress.start()
            # TTY 環境では実際の Live/Progress が使われる
            assert not isinstance(progress._live, _NullLive)
            assert not isinstance(progress._progress, _NullProgress)
            progress.stop()
            # stop 後は NullLive に戻る
            assert isinstance(progress._live, _NullLive)


class TestProgressDisplaySetStatus:
    """ProgressDisplay.set_status のテスト"""

    def test_set_status_updates_text(self):
        """ステータステキストを更新"""
        progress = ProgressDisplay()
        progress.set_status("処理中...")

        assert progress._status_text == "処理中..."
        assert progress._status_is_error is False

    def test_set_status_error(self):
        """エラー状態で更新"""
        progress = ProgressDisplay()
        progress.set_status("エラー発生", is_error=True)

        assert progress._status_text == "エラー発生"
        assert progress._status_is_error is True

    def test_set_status_normal_after_error(self):
        """エラー後に通常状態に戻す"""
        progress = ProgressDisplay()
        progress.set_status("エラー", is_error=True)
        progress.set_status("復帰")

        assert progress._status_text == "復帰"
        assert progress._status_is_error is False

    def test_set_status_logs_in_non_tty(self):
        """非 TTY 環境では logging で出力"""
        progress = ProgressDisplay()

        with unittest.mock.patch("logging.info") as mock_info:
            progress.set_status("テストメッセージ")
            mock_info.assert_called_once_with("テストメッセージ")

    def test_set_status_logs_error_in_non_tty(self):
        """非 TTY 環境でエラー時は logging.error"""
        progress = ProgressDisplay()

        with unittest.mock.patch("logging.error") as mock_error:
            progress.set_status("エラーメッセージ", is_error=True)
            mock_error.assert_called_once_with("エラーメッセージ")

    def test_set_status_in_tty_calls_refresh(self):
        """TTY 環境では _refresh_display が呼ばれる"""
        progress = ProgressDisplay()
        # TTY 状態をシミュレート
        mock_console = unittest.mock.MagicMock()
        mock_console.is_terminal = True
        progress._console = mock_console
        progress._live = unittest.mock.MagicMock()

        with unittest.mock.patch.object(progress, "_refresh_display") as mock_refresh:
            progress.set_status("テスト")

            mock_refresh.assert_called_once()


class TestProgressDisplayObserver:
    """ProgressObserver Protocol 実装のテスト"""

    def test_on_total_count_without_progress(self):
        """NullProgress の場合は何もしない（Null Object パターン）"""
        progress = ProgressDisplay()
        # 非TTY環境ではデフォルトで NullProgress が使われる
        assert isinstance(progress._progress, _NullProgress)

        # エラーなく完了
        progress.on_total_count(10)

    def test_on_total_count_with_progress(self):
        """_progress がある場合はタスクを追加"""
        progress = ProgressDisplay()
        mock_progress = unittest.mock.MagicMock()
        mock_progress.add_task.return_value = 1
        progress._progress = mock_progress

        progress.on_total_count(10)

        mock_progress.add_task.assert_called_once_with(_PROGRESS_ITEM, total=10)
        assert progress._item_task_id == 1

    def test_on_item_start(self):
        """on_item_start でステータス更新"""
        progress = ProgressDisplay()
        item = {"name": "テスト商品"}

        with unittest.mock.patch.object(progress, "set_status") as mock_set:
            progress.on_item_start(0, 10, item)

            mock_set.assert_called_once()
            assert "テスト商品" in mock_set.call_args[0][0]
            assert "🏷️" in mock_set.call_args[0][0]

    def test_on_item_start_unknown_name(self):
        """name がない場合は「不明」"""
        progress = ProgressDisplay()
        item = {}

        with unittest.mock.patch.object(progress, "set_status") as mock_set:
            progress.on_item_start(0, 10, item)

            assert "不明" in mock_set.call_args[0][0]

    def test_on_item_complete_without_progress(self):
        """NullProgress の場合は何もしない（Null Object パターン）"""
        progress = ProgressDisplay()
        # 非TTY環境ではデフォルトで NullProgress が使われる
        assert isinstance(progress._progress, _NullProgress)

        # エラーなく完了
        progress.on_item_complete(0, 10, {"name": "test"})

    def test_on_item_complete_with_progress(self):
        """_progress がある場合はタスクを更新"""
        import rich.progress

        progress = ProgressDisplay()
        mock_progress = unittest.mock.MagicMock()
        progress._progress = mock_progress
        progress._item_task_id = rich.progress.TaskID(1)

        progress.on_item_complete(0, 10, {"name": "test"})

        mock_progress.update.assert_called_once_with(rich.progress.TaskID(1), advance=1)


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


class TestProgressDisplayStatusBar:
    """ステータスバー作成のテスト"""

    def test_create_status_bar_normal(self):
        """通常時のステータスバー"""
        progress = ProgressDisplay()
        progress._status_text = "処理中"
        progress._status_is_error = False

        table = progress._create_status_bar()

        assert table is not None
        # Table が返されることを確認

    def test_create_status_bar_error(self):
        """エラー時のステータスバー"""
        progress = ProgressDisplay()
        progress._status_text = "エラー"
        progress._status_is_error = True

        table = progress._create_status_bar()

        assert table is not None

    def test_create_display_without_tasks(self):
        """タスクなしの表示"""
        progress = ProgressDisplay()
        progress._status_text = "テスト"

        display = progress._create_display()

        # ステータスバーのみ
        assert display is not None

    def test_create_display_with_tasks(self):
        """タスクありの表示"""
        progress = ProgressDisplay()
        progress._status_text = "テスト"
        mock_progress = unittest.mock.MagicMock()
        mock_progress.tasks = [unittest.mock.MagicMock()]
        progress._progress = mock_progress

        display = progress._create_display()

        # Group が返される
        assert display is not None


class TestDisplayRenderable:
    """_DisplayRenderable のテスト"""

    def test_rich_method(self):
        """__rich__ メソッドが _create_display を呼ぶ"""
        progress = ProgressDisplay()
        renderable = _DisplayRenderable(progress)

        with unittest.mock.patch.object(progress, "_create_display", return_value="test") as mock:
            result = renderable.__rich__()

            mock.assert_called_once()
            assert result == "test"


class TestRichStyleValidation:
    """rich のスタイル文字列が有効かを検証"""

    def test_status_bar_styles_are_valid(self):
        """ステータスバーのスタイルが有効"""
        for style_str in [_STATUS_STYLE_NORMAL, _STATUS_STYLE_ERROR]:
            style = rich.style.Style.parse(style_str)
            assert style is not None, f"Invalid style: {style_str}"

    def test_normal_style_has_mercari_red(self):
        """通常スタイルがメルカリレッドを含む"""
        assert "#E72121" in _STATUS_STYLE_NORMAL

    def test_error_style_has_red_background(self):
        """エラースタイルが赤背景"""
        assert "red" in _STATUS_STYLE_ERROR.lower()


class TestProgressConstants:
    """定数のテスト"""

    def test_progress_item_label(self):
        """プログレスバーのラベル"""
        assert _PROGRESS_ITEM == "アイテム処理"


class TestProgressDisplayRefresh:
    """表示更新のテスト"""

    def test_refresh_display_with_live(self):
        """_live がある場合は refresh を呼ぶ"""
        progress = ProgressDisplay()
        mock_live = unittest.mock.MagicMock()
        progress._live = mock_live

        progress._refresh_display()

        mock_live.refresh.assert_called_once()

    def test_refresh_display_without_live(self):
        """NullLive の場合は何もしない（Null Object パターン）"""
        progress = ProgressDisplay()
        # 非TTY環境ではデフォルトで NullLive が使われる
        assert isinstance(progress._live, _NullLive)

        # エラーなく完了
        progress._refresh_display()


class TestNullProgress:
    """_NullProgress のテスト"""

    def test_null_progress_rich_method(self):
        """__rich__ メソッドが空のテキストを返す"""
        null_progress = _NullProgress()
        result = null_progress.__rich__()

        assert isinstance(result, rich.text.Text)
        assert str(result) == ""


class TestNullLive:
    """_NullLive のテスト"""

    def test_null_live_start(self):
        """start メソッドが何もしない"""
        null_live = _NullLive()
        # 例外なく完了
        null_live.start()


class TestTmuxEnvironment:
    """TMUX 環境のテスト"""

    def test_status_bar_width_in_tmux(self):
        """TMUX 環境でステータスバーの幅が -2 される"""
        import os

        progress = ProgressDisplay()
        progress._status_text = "テスト"

        original_width = progress._console.width

        with unittest.mock.patch.dict(os.environ, {"TMUX": "tmux-socket,12345,0"}):
            table = progress._create_status_bar()
            # テーブルが作成される
            assert table is not None
            # TMUX 環境では幅が -2 される
            assert table.width == original_width - 2

    def test_status_bar_width_without_tmux(self):
        """非 TMUX 環境でステータスバーの幅がそのまま"""
        import os

        progress = ProgressDisplay()
        progress._status_text = "テスト"

        original_width = progress._console.width

        # TMUX 環境変数がない場合
        env_copy = os.environ.copy()
        env_copy.pop("TMUX", None)
        with unittest.mock.patch.dict(os.environ, env_copy, clear=True):
            table = progress._create_status_bar()
            # テーブルが作成される
            assert table is not None
            # 幅がそのまま
            assert table.width == original_width
