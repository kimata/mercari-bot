#!/usr/bin/env python3
# ruff: noqa: S101
"""
notify_slack モジュールのテスト
"""
import io
import pathlib
import unittest.mock

import PIL.Image
import pytest

import mercari_bot.notify_slack
from my_lib.notify.slack import SlackConfig, SlackEmptyConfig


class TestErrorWithScreenshot:
    """error_with_screenshot のテスト"""

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        # 1x1 の PNG 画像を返す
        img = PIL.Image.new("RGB", (1, 1), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        driver.get_screenshot_as_png.return_value = buf.getvalue()
        return driver

    @pytest.fixture
    def slack_config(self):
        """Slack 設定"""
        return unittest.mock.MagicMock(spec=SlackConfig)

    def test_calls_error_with_image(self, mock_driver, slack_config):
        """error_with_image が呼ばれる"""
        with unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error:
            mercari_bot.notify_slack.error_with_screenshot(
                slack_config, "テストエラー", "エラー詳細", mock_driver
            )

            mock_error.assert_called_once()
            call_args = mock_error.call_args
            assert call_args[0][0] == slack_config
            assert call_args[0][1] == "テストエラー"
            assert call_args[0][2] == "エラー詳細"
            # 画像データが渡されている
            assert "data" in call_args[0][3]
            assert "text" in call_args[0][3]
            assert call_args[0][3]["text"] == "エラー時のスクリーンショット"

    def test_with_empty_slack_config(self, mock_driver):
        """SlackEmptyConfig でも動作する"""
        empty_config = SlackEmptyConfig()
        with unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error:
            mercari_bot.notify_slack.error_with_screenshot(
                empty_config, "タイトル", "メッセージ", mock_driver
            )

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0] == empty_config

    def test_screenshot_is_pil_image(self, mock_driver, slack_config):
        """スクリーンショットが PIL.Image として渡される"""
        with unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error:
            mercari_bot.notify_slack.error_with_screenshot(
                slack_config, "タイトル", "メッセージ", mock_driver
            )

            image_data = mock_error.call_args[0][3]["data"]
            assert isinstance(image_data, PIL.Image.Image)


class TestErrorWithTraceback:
    """error_with_traceback のテスト"""

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        img = PIL.Image.new("RGB", (1, 1), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        driver.get_screenshot_as_png.return_value = buf.getvalue()
        return driver

    @pytest.fixture
    def slack_config(self):
        """Slack 設定"""
        return unittest.mock.MagicMock(spec=SlackConfig)

    def test_includes_traceback(self, mock_driver, slack_config):
        """traceback が含まれる"""
        with unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error:
            try:
                raise ValueError("テスト例外")  # noqa: EM101, TRY301
            except ValueError:
                mercari_bot.notify_slack.error_with_traceback(
                    slack_config, "エラー発生", mock_driver
                )

            mock_error.assert_called_once()
            message = mock_error.call_args[0][2]
            assert "ValueError" in message
            assert "テスト例外" in message
            assert "Traceback" in message

    def test_title_is_passed(self, mock_driver, slack_config):
        """タイトルが渡される"""
        with unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error:
            try:
                raise RuntimeError("dummy")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.error_with_traceback(
                    slack_config, "カスタムタイトル", mock_driver
                )

            assert mock_error.call_args[0][1] == "カスタムタイトル"


class TestDumpAndNotifyError:
    """dump_and_notify_error のテスト"""

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        img = PIL.Image.new("RGB", (1, 1), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        driver.get_screenshot_as_png.return_value = buf.getvalue()
        return driver

    @pytest.fixture
    def slack_config(self):
        """Slack 設定"""
        return unittest.mock.MagicMock(spec=SlackConfig)

    def test_calls_dump_page(self, mock_driver, slack_config, tmp_path):
        """dump_page が呼ばれる"""
        with (
            unittest.mock.patch("my_lib.selenium_util.dump_page") as mock_dump,
            unittest.mock.patch("my_lib.selenium_util.clean_dump"),
            unittest.mock.patch("my_lib.notify.slack.error_with_image"),
        ):
            try:
                raise RuntimeError("test")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.dump_and_notify_error(
                    slack_config, "エラー", mock_driver, tmp_path
                )

            mock_dump.assert_called_once()
            call_args = mock_dump.call_args[0]
            assert call_args[0] == mock_driver
            # 2番目はランダムな整数
            assert isinstance(call_args[1], int)
            assert call_args[2] == tmp_path

    def test_calls_clean_dump(self, mock_driver, slack_config, tmp_path):
        """clean_dump が呼ばれる"""
        with (
            unittest.mock.patch("my_lib.selenium_util.dump_page"),
            unittest.mock.patch("my_lib.selenium_util.clean_dump") as mock_clean,
            unittest.mock.patch("my_lib.notify.slack.error_with_image"),
        ):
            try:
                raise RuntimeError("test")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.dump_and_notify_error(
                    slack_config, "エラー", mock_driver, tmp_path
                )

            mock_clean.assert_called_once_with(tmp_path)

    def test_calls_error_with_traceback(self, mock_driver, slack_config, tmp_path):
        """error_with_traceback が呼ばれる"""
        with (
            unittest.mock.patch("my_lib.selenium_util.dump_page"),
            unittest.mock.patch("my_lib.selenium_util.clean_dump"),
            unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error,
        ):
            try:
                raise RuntimeError("テストエラー")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.dump_and_notify_error(
                    slack_config, "カスタムタイトル", mock_driver, tmp_path
                )

            mock_error.assert_called_once()
            assert mock_error.call_args[0][1] == "カスタムタイトル"
            assert "RuntimeError" in mock_error.call_args[0][2]

    def test_dump_path_is_pathlib(self, mock_driver, slack_config, tmp_path):
        """dump_path として pathlib.Path を受け付ける"""
        dump_path = pathlib.Path(tmp_path) / "dump"

        with (
            unittest.mock.patch("my_lib.selenium_util.dump_page") as mock_dump,
            unittest.mock.patch("my_lib.selenium_util.clean_dump"),
            unittest.mock.patch("my_lib.notify.slack.error_with_image"),
        ):
            try:
                raise RuntimeError("test")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.dump_and_notify_error(
                    slack_config, "エラー", mock_driver, dump_path
                )

            assert mock_dump.call_args[0][2] == dump_path

    def test_with_empty_slack_config(self, mock_driver, tmp_path):
        """SlackEmptyConfig でも動作する（通知は送られない）"""
        empty_config = SlackEmptyConfig()

        with (
            unittest.mock.patch("my_lib.selenium_util.dump_page") as mock_dump,
            unittest.mock.patch("my_lib.selenium_util.clean_dump") as mock_clean,
            unittest.mock.patch("my_lib.notify.slack.error_with_image") as mock_error,
        ):
            try:
                raise RuntimeError("test")  # noqa: EM101, TRY301
            except RuntimeError:
                mercari_bot.notify_slack.dump_and_notify_error(
                    empty_config, "エラー", mock_driver, tmp_path
                )

            # ダンプは行われる
            mock_dump.assert_called_once()
            mock_clean.assert_called_once()
            # 通知も呼ばれる（SlackEmptyConfig で何もしない）
            mock_error.assert_called_once()
