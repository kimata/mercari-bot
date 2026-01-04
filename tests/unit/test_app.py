#!/usr/bin/env python3
# ruff: noqa: S101
"""
app.py のテスト

mercari_price_down をモックして UI フローをテストします。
"""

import io
import pathlib
import unittest.mock

import pytest
from my_lib.notify.slack import SlackEmptyConfig

import app
import mercari_bot.progress
from mercari_bot.config import AppConfig, DataConfig, ProfileConfig


class TestExecute:
    """execute のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=str(tmp_path / "selenium"),
                dump=str(tmp_path / "dump"),
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_execute_success(self, mock_config: AppConfig):
        """正常実行"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0) as mock_execute,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start") as mock_start,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop") as mock_stop,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status") as mock_status,
        ):
            ret = app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

            assert ret == 0
            mock_execute.assert_called_once()
            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            # 最後に完了ステータスが設定される
            mock_status.assert_called()
            assert "完了" in mock_status.call_args_list[-1][0][0]

    def test_execute_with_error(self, mock_config: AppConfig):
        """エラー時の戻り値"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=-1),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
        ):
            ret = app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

            assert ret == -1

    def test_execute_multiple_profiles(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """複数プロファイルの実行"""
        config = AppConfig(
            profile=[profile_config, profile_config],  # 2つのプロファイル
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=str(tmp_path / "selenium"),
                dump=str(tmp_path / "dump"),
            ),
            mail=unittest.mock.MagicMock(),
        )

        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0) as mock_execute,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
        ):
            ret = app.execute(config, notify_log=False, debug_mode=True, log_str_io=None)

            assert ret == 0
            assert mock_execute.call_count == 2

    def test_execute_cumulative_errors(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """複数プロファイルでエラーが累積される"""
        config = AppConfig(
            profile=[profile_config, profile_config, profile_config],  # 3つのプロファイル
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=str(tmp_path / "selenium"),
                dump=str(tmp_path / "dump"),
            ),
            mail=unittest.mock.MagicMock(),
        )

        with (
            # 1つ目と3つ目でエラー
            unittest.mock.patch(
                "mercari_bot.mercari_price_down.execute",
                side_effect=[-1, 0, -1],
            ),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
        ):
            ret = app.execute(config, notify_log=False, debug_mode=True, log_str_io=None)

            # -1 + 0 + -1 = -2
            assert ret == -2

    def test_execute_progress_always_stopped(self, mock_config: AppConfig):
        """例外発生時でも progress.stop() が呼ばれる"""
        with (
            unittest.mock.patch(
                "mercari_bot.mercari_price_down.execute",
                side_effect=Exception("Test error"),
            ),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop") as mock_stop,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
            pytest.raises(Exception, match="Test error"),
        ):
            app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

        # finally で stop が呼ばれる
        mock_stop.assert_called_once()

    def test_execute_with_notify_log_and_log_str_io(self, mock_config: AppConfig):
        """ログ通知が有効な場合"""
        log_str_io = io.StringIO()
        log_str_io.write("Test log content")

        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
            unittest.mock.patch("my_lib.notify.mail.send") as mock_mail,
            unittest.mock.patch("my_lib.notify.slack.info") as mock_slack,
        ):
            app.execute(mock_config, notify_log=True, debug_mode=True, log_str_io=log_str_io)

            mock_mail.assert_called_once()
            mock_slack.assert_called_once()

    def test_execute_notify_not_called_when_disabled(self, mock_config: AppConfig):
        """notify_log=False の場合は通知しない"""
        log_str_io = io.StringIO()
        log_str_io.write("Test log content")

        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
            unittest.mock.patch("my_lib.notify.mail.send") as mock_mail,
            unittest.mock.patch("my_lib.notify.slack.info") as mock_slack,
        ):
            app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=log_str_io)

            mock_mail.assert_not_called()
            mock_slack.assert_not_called()

    def test_execute_notify_not_called_when_no_log_str_io(self, mock_config: AppConfig):
        """log_str_io=None の場合は通知しない"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
            unittest.mock.patch("my_lib.notify.mail.send") as mock_mail,
            unittest.mock.patch("my_lib.notify.slack.info") as mock_slack,
        ):
            app.execute(mock_config, notify_log=True, debug_mode=True, log_str_io=None)

            mock_mail.assert_not_called()
            mock_slack.assert_not_called()

    def test_execute_passes_progress_to_mercari_price_down(self, mock_config: AppConfig):
        """progress が mercari_price_down に渡される"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0) as mock_execute,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
        ):
            app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

            # progress キーワード引数が渡される
            call_kwargs = mock_execute.call_args[1]
            assert "progress" in call_kwargs
            assert isinstance(call_kwargs["progress"], mercari_bot.progress.ProgressDisplay)

    def test_execute_passes_correct_paths(self, mock_config: AppConfig, tmp_path: pathlib.Path):
        """正しいパスが mercari_price_down に渡される"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0) as mock_execute,
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "start"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop"),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "set_status"),
        ):
            app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

            call_args = mock_execute.call_args[0]
            assert call_args[2] == pathlib.Path(mock_config.data.selenium)
            assert call_args[3] == pathlib.Path(mock_config.data.dump)


class TestProgressIntegration:
    """Progress との統合テスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=str(tmp_path / "selenium"),
                dump=str(tmp_path / "dump"),
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_progress_lifecycle(self, mock_config: AppConfig):
        """Progress のライフサイクル（start → set_status → stop）"""
        call_order: list[str] = []

        def track_start() -> None:
            call_order.append("start")

        def track_stop() -> None:
            call_order.append("stop")

        def track_status(status: str) -> None:
            call_order.append(f"status:{status[:10]}")

        with (
            unittest.mock.patch("mercari_bot.mercari_price_down.execute", return_value=0),
            unittest.mock.patch.object(
                mercari_bot.progress.ProgressDisplay, "start", side_effect=track_start
            ),
            unittest.mock.patch.object(mercari_bot.progress.ProgressDisplay, "stop", side_effect=track_stop),
            unittest.mock.patch.object(
                mercari_bot.progress.ProgressDisplay, "set_status", side_effect=track_status
            ),
        ):
            app.execute(mock_config, notify_log=False, debug_mode=True, log_str_io=None)

        # start が最初、stop が最後
        assert call_order[0] == "start"
        assert call_order[-1] == "stop"
