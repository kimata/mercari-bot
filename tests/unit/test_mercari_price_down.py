#!/usr/bin/env python3
# ruff: noqa: S101
"""
mercari_price_down モジュールのテスト

Selenium 操作をモックして処理フローをテストします。
"""
import pathlib
import unittest.mock

import pytest

import mercari_bot.mercari_price_down
import mercari_bot.notify_slack
import mercari_bot.progress
import my_lib.store.mercari.exceptions
from mercari_bot.config import AppConfig, DataConfig, ProfileConfig
from my_lib.notify.slack import SlackConfig, SlackEmptyConfig


class TestExecute:
    """execute 関数のテスト"""

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

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        driver.current_url = "https://jp.mercari.com/test"
        return driver

    @pytest.fixture
    def mock_wait(self):
        """モック WebDriverWait"""
        return unittest.mock.MagicMock()

    def test_execute_success(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """正常実行"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.selenium_util.log_memory_usage"),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            assert ret == 0

    def test_execute_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """progress が渡された場合のステータス更新"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.selenium_util.log_memory_usage"),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
                progress=mock_progress,
            )

            # ステータス更新が呼ばれる
            assert mock_progress.set_status.call_count >= 3
            status_calls = [call[0][0] for call in mock_progress.set_status.call_args_list]

            # ブラウザ起動、ログイン、出品リスト取得、完了のステータス
            assert any("ブラウザ" in s for s in status_calls)
            assert any("ログイン" in s for s in status_calls)
            assert any("完了" in s for s in status_calls)

    def test_execute_login_error(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """ログインエラー時の処理"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.store.mercari.exceptions.LoginError("ログイン失敗"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch(
                "mercari_bot.notify_slack.dump_and_notify_error"
            ) as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            assert ret == -1
            mock_notify.assert_called_once()
            # タイトルに「ログイン」が含まれる
            assert "ログイン" in mock_notify.call_args[0][1]

    def test_execute_general_error(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """一般的なエラー時の処理"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("予期しないエラー"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch(
                "mercari_bot.notify_slack.dump_and_notify_error"
            ) as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            assert ret == -1
            mock_notify.assert_called_once()
            # タイトルに「値下げ」が含まれる
            assert "値下げ" in mock_notify.call_args[0][1]

    def test_execute_error_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """エラー時に progress のエラーステータスが設定される"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("エラー"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
                progress=mock_progress,
            )

            # エラーステータスが設定される
            error_calls = [
                call for call in mock_progress.set_status.call_args_list
                if len(call[0]) > 0 and "エラー" in call[0][0]
            ]
            assert len(error_calls) > 0
            # is_error=True で呼ばれる
            assert any(
                call[1].get("is_error", False) for call in error_calls
            )

    def test_execute_driver_always_quit(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """正常・異常に関わらずドライバーが終了される"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("エラー"),
            ),
            unittest.mock.patch(
                "my_lib.selenium_util.quit_driver_gracefully"
            ) as mock_quit,
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            mock_quit.assert_called_once_with(mock_driver)

    def test_execute_calls_iter_items(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """iter_items_on_display が呼ばれる"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display"
            ) as mock_iter,
            unittest.mock.patch("my_lib.selenium_util.log_memory_usage"),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            mock_iter.assert_called_once()

    def test_execute_passes_progress_observer(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """progress_observer が iter_items_on_display に渡される"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display"
            ) as mock_iter,
            unittest.mock.patch("my_lib.selenium_util.log_memory_usage"),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
                progress=mock_progress,
            )

            # progress_observer キーワード引数が渡される
            call_kwargs = mock_iter.call_args[1]
            assert "progress_observer" in call_kwargs
            assert call_kwargs["progress_observer"] == mock_progress


class TestGetModifiedHour:
    """_get_modified_hour のテスト"""

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        return driver

    def test_get_modified_hour(self, mock_driver):
        """更新時間の取得"""
        # find_element の戻り値を設定
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "3時間前"
        mock_driver.find_element.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(mock_driver)

        assert result == 3

    def test_get_modified_hour_days(self, mock_driver):
        """日単位の更新時間"""
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "2日前"
        mock_driver.find_element.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(mock_driver)

        assert result == 48  # 2 * 24


class TestExecuteItem:
    """_execute_item のテスト（Selenium 操作をモック）"""

    @pytest.fixture
    def mock_driver(self):
        """モック WebDriver"""
        driver = unittest.mock.MagicMock()
        return driver

    @pytest.fixture
    def mock_wait(self):
        """モック WebDriverWait"""
        wait = unittest.mock.MagicMock()
        return wait

    def test_execute_item_skip_stopped(
        self, mock_driver, mock_wait, profile_config: ProfileConfig
    ):
        """公開停止中のアイテムはスキップ"""
        item = {"is_stop": 1, "name": "テスト商品", "price": 3000, "favorite": 5}

        # 例外が発生しないことを確認（スキップ）
        mercari_bot.mercari_price_down._execute_item(
            mock_driver, mock_wait, profile_config, item, debug_mode=True
        )

        # 価格変更の操作は行われない
        mock_driver.find_element.assert_not_called()

    def test_execute_item_skip_recent(
        self, mock_driver, mock_wait, profile_config: ProfileConfig
    ):
        """最近更新されたアイテムはスキップ"""
        item = {"is_stop": 0, "name": "テスト商品", "price": 3000, "favorite": 5}

        # _get_modified_hour が小さい値を返すようモック
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "1時間前"
        mock_driver.find_element.return_value = mock_element

        with unittest.mock.patch(
            "my_lib.selenium_util.click_xpath"
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True
            )

        # interval.hour (20) より小さいのでスキップ
        # 価格入力欄へのアクセスは行われない


class TestExecuteItemWithSlackConfig:
    """Slack 設定ありでのテスト"""

    @pytest.fixture
    def slack_config(self):
        """モック SlackConfig"""
        return unittest.mock.MagicMock(spec=SlackConfig)

    @pytest.fixture
    def mock_config_with_slack(
        self, profile_config: ProfileConfig, slack_config, tmp_path: pathlib.Path
    ):
        """Slack 設定付き AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=slack_config,
            data=DataConfig(
                selenium=str(tmp_path / "selenium"),
                dump=str(tmp_path / "dump"),
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_execute_error_notifies_slack(
        self,
        mock_config_with_slack: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """エラー時に Slack 通知が送られる"""
        mock_driver = unittest.mock.MagicMock()
        mock_driver.current_url = "https://jp.mercari.com/test"

        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver", return_value=mock_driver
            ),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("テストエラー"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch(
                "mercari_bot.notify_slack.dump_and_notify_error"
            ) as mock_notify,
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config_with_slack,
                profile_config,
                tmp_path / "selenium",
                tmp_path / "dump",
                debug_mode=True,
            )

            mock_notify.assert_called_once()
            # Slack 設定が渡される
            assert mock_notify.call_args[0][0] == mock_config_with_slack.slack
