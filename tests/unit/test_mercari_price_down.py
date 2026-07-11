#!/usr/bin/env python3
# ruff: noqa: S101
"""
mercari_price_down モジュールのテスト

Selenium 操作をモックして処理フローをテストします。
"""

import pathlib
import unittest.mock

import my_lib.store.mercari.exceptions
import pytest
import selenium.common.exceptions
from my_lib.notify.slack import SlackConfig, SlackEmptyConfig
from my_lib.store.mercari.config import MercariItem

import mercari_bot.exceptions
import mercari_bot.history
import mercari_bot.mercari_price_down
import mercari_bot.progress
from mercari_bot.config import AppConfig, DataConfig, ProfileConfig

_DUMMY_DUMP_PATH = pathlib.Path("/tmp")  # noqa: S108


def _create_mock_item(
    name: str = "テスト商品",
    price: int = 3000,
    favorite: int = 5,
    is_stop: int = 0,
    item_id: str = "m12345",
    url: str = "https://jp.mercari.com/item/m12345",
    view: int = 100,
) -> MercariItem:
    """テスト用の MercariItem を作成"""
    return MercariItem(
        id=item_id,
        url=url,
        name=name,
        price=price,
        view=view,
        favorite=favorite,
        is_stop=is_stop,
    )


class TestExecute:
    """execute 関数のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            assert ret is True

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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.store.mercari.exceptions.LoginError("ログイン失敗"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            assert ret is False
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("予期しないエラー"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            assert ret is False
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
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
                debug_mode=True,
                progress=mock_progress,
            )

            # エラーステータスが設定される
            error_calls = [
                call
                for call in mock_progress.set_status.call_args_list
                if len(call[0]) > 0 and "エラー" in call[0][0]
            ]
            assert len(error_calls) > 0
            # is_error=True で呼ばれる
            assert any(call[1].get("is_error", False) for call in error_calls)

    def test_execute_driver_always_quit(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """正常・異常に関わらずドライバーが終了される"""
        mock_browser_manager = unittest.mock.MagicMock()
        mock_browser_manager.get_driver.return_value = (mock_driver, unittest.mock.MagicMock())

        with (
            unittest.mock.patch("my_lib.browser_manager.BrowserManager", return_value=mock_browser_manager),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("エラー"),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            mock_browser_manager.quit.assert_called_once()

    def test_execute_calls_iter_items(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """iter_items_on_display が呼ばれる"""
        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                progress=mock_progress,
            )

            # progress_observer には全アイテム記録用のラッパーが渡され、
            # 内側の observer として progress が使われる
            call_kwargs = mock_iter.call_args[1]
            assert "progress_observer" in call_kwargs
            observer = call_kwargs["progress_observer"]
            assert isinstance(observer, mercari_bot.progress.ItemRecordingObserver)
            assert observer.inner == mock_progress

    def test_execute_session_error_retry_success(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """セッションエラー発生後、リトライで成功するケース"""
        call_count = 0

        def login_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 1回目はセッションエラー
                raise selenium.common.exceptions.InvalidSessionIdException("session deleted")
            # 2回目は成功

        # BrowserManager のモック（2つ作成：初回用とリトライ用）
        mock_browser_manager1 = unittest.mock.MagicMock()
        mock_browser_manager1.get_driver.return_value = (mock_driver, unittest.mock.MagicMock())
        mock_browser_manager2 = unittest.mock.MagicMock()
        mock_browser_manager2.get_driver.return_value = (mock_driver, unittest.mock.MagicMock())

        browser_manager_call_count = 0

        def browser_manager_side_effect(*_args, **_kwargs):
            nonlocal browser_manager_call_count
            browser_manager_call_count += 1
            if browser_manager_call_count == 1:
                return mock_browser_manager1
            return mock_browser_manager2

        with (
            unittest.mock.patch(
                "my_lib.browser_manager.BrowserManager",
                side_effect=browser_manager_side_effect,
            ),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=login_side_effect,
            ),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                clear_profile_on_browser_error=True,
            )

            assert ret is True  # リトライで成功
            # BrowserManager が2回作成される（初回 + リトライ）
            assert browser_manager_call_count == 2

    def test_execute_session_error_no_retry_when_disabled(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """clear_profile_on_browser_error=False の場合はリトライしない"""
        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=selenium.common.exceptions.InvalidSessionIdException("session deleted"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("my_lib.chrome_util.delete_profile") as mock_delete_profile,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                clear_profile_on_browser_error=False,  # リトライ無効
            )

            assert ret is False  # リトライせずに失敗
            mock_delete_profile.assert_not_called()  # プロファイル削除は呼ばれない

    def test_execute_session_error_retry_exhausted(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
        mock_driver,
    ):
        """リトライ回数を超えた場合は失敗"""
        mock_browser_manager = unittest.mock.MagicMock()
        mock_browser_manager.get_driver.return_value = (mock_driver, unittest.mock.MagicMock())
        browser_manager_call_count = 0

        def browser_manager_side_effect(*_args, **_kwargs):
            nonlocal browser_manager_call_count
            browser_manager_call_count += 1
            return mock_browser_manager

        with (
            unittest.mock.patch(
                "my_lib.browser_manager.BrowserManager",
                side_effect=browser_manager_side_effect,
            ),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=selenium.common.exceptions.InvalidSessionIdException("session deleted"),
            ),
            unittest.mock.patch("my_lib.notify.slack.error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                clear_profile_on_browser_error=True,
            )

            assert ret is False  # 最終的に失敗
            # BrowserManager が2回作成される（初回 + リトライ）
            assert browser_manager_call_count == 2


class TestGetModifiedHour:
    """_get_modified_hour のテスト"""

    @pytest.fixture
    def mock_wait(self):
        """モック WebDriverWait"""
        wait = unittest.mock.MagicMock()
        return wait

    def test_get_modified_hour(self, mock_wait):
        """更新時間の取得"""
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "3時間前"
        mock_wait.until.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(mock_wait)

        assert result == 3

    def test_get_modified_hour_days(self, mock_wait):
        """日単位の更新時間"""
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "2日前"
        mock_wait.until.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(mock_wait)

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

    def test_execute_item_skip_recent(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """最近更新されたアイテムはスキップ"""
        item = _create_mock_item()

        # _get_modified_hour が小さい値を返すようモック
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "1時間前"
        mock_wait.until.return_value = mock_element

        with unittest.mock.patch("my_lib.selenium_util.click_xpath"):
            result = mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

        # interval.hour (20) より小さいのでスキップ
        assert result.action == mercari_bot.history.ItemAction.SKIP_RECENT


class TestExecuteItemWithSlackConfig:
    """Slack 設定ありでのテスト"""

    @pytest.fixture
    def slack_config(self):
        """モック SlackConfig"""
        return unittest.mock.MagicMock(spec=SlackConfig)

    @pytest.fixture
    def mock_config_with_slack(self, profile_config: ProfileConfig, slack_config, tmp_path: pathlib.Path):
        """Slack 設定付き AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=slack_config,
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
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
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("テストエラー"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config_with_slack,
                profile_config,
                debug_mode=True,
            )

            mock_notify.assert_called_once()
            # Slack 設定が渡される
            assert mock_notify.call_args[0][0] == mock_config_with_slack.slack


class TestBrowserStartupError:
    """ブラウザ起動エラー時のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_browser_startup_error_with_profile_delete(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """ブラウザ起動エラー時は Slack 通知してエラー終了する（例外は伝播しない）"""
        mock_browser_manager = unittest.mock.MagicMock()
        mock_browser_manager.get_driver.side_effect = Exception("ブラウザ起動失敗")

        with (
            unittest.mock.patch(
                "my_lib.browser_manager.BrowserManager",
                return_value=mock_browser_manager,
            ),
            unittest.mock.patch("my_lib.notify.slack.error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                clear_profile_on_browser_error=True,
            )

            assert ret is False
            mock_notify.assert_called_once()
            assert "ブラウザ起動" in mock_notify.call_args[0][1]

    def test_browser_startup_error_without_profile_delete(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """ブラウザ起動エラー時にプロファイル削除しない（clear_profile_on_browser_error=False）"""
        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver",
                side_effect=Exception("ブラウザ起動失敗"),
            ),
            unittest.mock.patch("my_lib.chrome_util.delete_profile") as mock_delete,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                clear_profile_on_browser_error=False,
            )

            assert ret is False
            # プロファイル削除は呼ばれない
            mock_delete.assert_not_called()

    def test_browser_startup_error_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """ブラウザ起動エラー時に progress にエラーステータスを設定"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            unittest.mock.patch(
                "my_lib.selenium_util.create_driver",
                side_effect=Exception("ブラウザ起動失敗"),
            ),
            unittest.mock.patch("my_lib.chrome_util.delete_profile"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                progress=mock_progress,
                clear_profile_on_browser_error=True,
            )

            assert ret is False
            # エラーステータスが設定される
            error_calls = [call for call in mock_progress.set_status.call_args_list if "エラー" in call[0][0]]
            assert len(error_calls) > 0
            assert any(call[1].get("is_error", False) for call in error_calls)


class TestSessionErrorWithProgress:
    """セッションエラー + progress のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_session_error_retry_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """セッションエラー時にリトライメッセージを progress に表示"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)
        mock_driver = unittest.mock.MagicMock()

        call_count = 0

        def login_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise selenium.common.exceptions.InvalidSessionIdException("session deleted")
            # 2回目は成功

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=login_side_effect),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("my_lib.chrome_util.delete_profile"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                progress=mock_progress,
                clear_profile_on_browser_error=True,
            )

            assert ret is True  # 成功
            # リトライメッセージが表示される
            retry_calls = [
                call for call in mock_progress.set_status.call_args_list if "リトライ" in call[0][0]
            ]
            assert len(retry_calls) >= 1

    def test_session_error_exhausted_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """セッションエラーでリトライ上限超過時に progress にエラー表示"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)
        mock_driver = unittest.mock.MagicMock()

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=selenium.common.exceptions.InvalidSessionIdException("session deleted"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("my_lib.chrome_util.delete_profile"),
            unittest.mock.patch("my_lib.notify.slack.error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                progress=mock_progress,
                clear_profile_on_browser_error=True,
            )

            assert ret is False  # 失敗
            # セッションエラーのステータス
            error_calls = [
                call for call in mock_progress.set_status.call_args_list if "セッションエラー" in call[0][0]
            ]
            assert len(error_calls) >= 1


class TestLoginErrorWithProgress:
    """ログインエラー + progress のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_login_error_with_progress(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """ログインエラー時に progress にエラーステータスを設定"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)
        mock_driver = unittest.mock.MagicMock()
        mock_driver.current_url = "https://jp.mercari.com/test"

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.store.mercari.exceptions.LoginError("ログイン失敗"),
            ),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
                progress=mock_progress,
            )

            assert ret is False
            # ログインエラーステータス
            error_calls = [
                call for call in mock_progress.set_status.call_args_list if "ログイン" in call[0][0]
            ]
            assert len(error_calls) >= 1
            # is_error=True で呼ばれる
            error_with_flag = [call for call in error_calls if call[1].get("is_error", False)]
            assert len(error_with_flag) >= 1


class TestItemHandler:
    """item_handler ラッパー関数のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
            ),
            mail=unittest.mock.MagicMock(),
        )

    def test_item_handler_is_called(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """iter_items_on_display から item_handler が呼び出される"""
        mock_driver = unittest.mock.MagicMock()
        item = _create_mock_item()

        def iter_items_side_effect(
            driver, wait, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            # item_handler を呼び出す
            for handler in handlers:
                handler(driver, wait, item, debug_mode)

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch("mercari_bot.mercari_price_down._execute_item") as mock_execute_item,
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            # 正常終了し、item_handler 経由で _execute_item が呼ばれる
            assert ret is True
            mock_execute_item.assert_called_once()

    def test_price_verification_error_notifies_and_fails(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """価格検証エラーは Slack 通知され、プロファイルの結果が失敗になる（BUG-8 回帰テスト）"""
        mock_driver = unittest.mock.MagicMock()
        item = _create_mock_item()

        def iter_items_side_effect(
            driver, wait, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            for handler in handlers:
                handler(driver, wait, item, debug_mode)

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch(
                "mercari_bot.mercari_price_down._execute_item",
                side_effect=mercari_bot.exceptions.PriceVerificationError(expected=2900, actual=3000),
            ),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            assert ret is False
            mock_notify.assert_called_once()
            assert "価格検証" in mock_notify.call_args[0][1]

    def test_post_submit_timeout_notifies_and_fails(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """送信後の検証タイムアウトも Slack 通知され、プロファイルの結果が失敗になる（§3.1）"""
        mock_driver = unittest.mock.MagicMock()
        item = _create_mock_item()

        def iter_items_side_effect(
            driver, wait, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            for handler in handlers:
                handler(driver, wait, item, debug_mode)

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch(
                "mercari_bot.mercari_price_down._execute_item",
                side_effect=mercari_bot.exceptions.PriceVerificationTimeoutError("テスト商品"),
            ),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            assert ret is False
            mock_notify.assert_called_once()
            assert "価格検証" in mock_notify.call_args[0][1]

    def test_item_result_is_recorded(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """item_handler が処理結果を履歴 DB に記録する（F1）"""
        mock_driver = unittest.mock.MagicMock()
        item = _create_mock_item()
        result = mercari_bot.history.ItemResult(mercari_bot.history.ItemAction.PRICE_DOWN, 3000, 2900)

        def iter_items_side_effect(
            driver, wait, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            for handler in handlers:
                handler(driver, wait, item, debug_mode)

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch(
                "mercari_bot.mercari_price_down._execute_item",
                return_value=result,
            ),
            unittest.mock.patch("mercari_bot.history.HistoryDb") as mock_history_cls,
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=False,
            )

            assert ret is True
            mock_history = mock_history_cls.return_value
            mock_history_cls.assert_called_once_with(mock_config.data.history)
            mock_history.add_record.assert_called_once_with(profile_config.name, item, result)
            # 走査完了後にスナップショットが更新される
            mock_history.replace_snapshot.assert_called_once()

    def test_max_consecutive_failures_is_passed(
        self,
        mock_config: AppConfig,
        profile_config: ProfileConfig,
        tmp_path: pathlib.Path,
    ):
        """iter_items_on_display に max_consecutive_failures が渡される（BUG-6 回帰テスト）"""
        mock_driver = unittest.mock.MagicMock()

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=True,
            )

            call_kwargs = mock_iter.call_args[1]
            assert call_kwargs["max_consecutive_failures"] == 2


class TestExecuteItemPriceChange:
    """_execute_item の価格変更パスのテスト"""

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

    def test_execute_item_time_sale(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """タイムセール中のアイテムはスキップ"""
        item = _create_mock_item()

        # _get_modified_hour が大きい値を返す（更新から時間が経過）
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "25時間前"
        mock_wait.until.return_value = mock_element

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch(
                "my_lib.selenium_util.xpath_exists",
                return_value=True,  # タイムセールボタンが存在
            ),
        ):
            # タイムセール中なのでスキップ
            result = mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

            assert result.action == mercari_bot.history.ItemAction.SKIP_TIME_SALE

    def test_execute_item_with_shipping_fee(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """送料ありの場合のテスト"""
        item = _create_mock_item(price=5000)

        # _get_modified_hour が大きい値を返す
        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        # 送料要素
        mock_shipping_element = unittest.mock.MagicMock()
        mock_shipping_element.text = "1,000"

        # 価格入力欄
        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "4000"  # 5000 - 1000 = 4000

        # 更新後価格（new_price + shipping_fee = 4000 + 1000 = 5000）
        mock_new_price_element = unittest.mock.MagicMock()
        mock_new_price_element.text = "5,000"

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if "shipping-fee" in xpath and "number" in xpath:
                return mock_shipping_element
            if 'name="price"' in xpath:
                return mock_price_input
            if 'data-testid="price"' in xpath:
                return mock_new_price_element
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = [unittest.mock.MagicMock()]  # shipping-fee 要素あり

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            unittest.mock.patch("my_lib.selenium_util.random_sleep"),
            unittest.mock.patch("my_lib.selenium_util.wait_patiently"),
            unittest.mock.patch("time.sleep"),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_price_mismatch(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """ページ遷移中に価格が変更された場合"""
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "2500"  # 価格が変更されている

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if 'name="price"' in xpath:
                return mock_price_input
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []  # shipping-fee なし

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            pytest.raises(mercari_bot.exceptions.PriceChangedError),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_price_attribute_none(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """価格入力欄の value が None の場合"""
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = None  # value が None

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if 'name="price"' in xpath:
                return mock_price_input
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []  # shipping-fee なし

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            pytest.raises(mercari_bot.exceptions.PriceRetrievalError),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_no_discount(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """割引ステップが None の場合（閾値以下）"""
        item = _create_mock_item(price=500, favorite=0)  # 閾値以下

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "500"

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if 'name="price"' in xpath:
                return mock_price_input
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
        ):
            # 割引対象外なのでスキップ
            result = mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

            assert result.action == mercari_bot.history.ItemAction.SKIP_NO_DISCOUNT

    def test_execute_item_price_change_success(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """価格変更成功（debug_mode=True）"""
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "3000"

        # 更新後の価格（debug_mode=True なので変更なし、3000 のまま）
        mock_new_price_element = unittest.mock.MagicMock()
        mock_new_price_element.text = "3,000"

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if 'name="price"' in xpath:
                return mock_price_input
            if 'data-testid="price"' in xpath:
                return mock_new_price_element
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            unittest.mock.patch("my_lib.selenium_util.random_sleep"),
            unittest.mock.patch("my_lib.selenium_util.wait_patiently"),
            unittest.mock.patch("time.sleep"),
        ):
            # 正常終了し、値下げ結果が返る
            result = mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

            assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
            assert result.old_price == 3000
            assert result.new_price == 3000  # debug_mode=True なので同額

    def test_execute_item_post_submit_timeout(self, mock_driver, mock_wait, profile_config: ProfileConfig):
        """送信後のタイムアウトは PriceVerificationTimeoutError に変換される（§3.1）

        TimeoutException のまま伝播させると my_lib のリトライで再実行され、
        interval 判定でスキップ → 検証されないまま正常終了に化けるため。
        """
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"

        # wait.until の呼び出し順: 更新時間 → タイトル → オークション → 価格入力欄
        # →（送信）→ h1 待機。送信後の h1 待機でタイムアウトさせる。
        mock_wait.until.side_effect = [
            mock_modified_element,
            unittest.mock.MagicMock(),
            unittest.mock.MagicMock(),
            unittest.mock.MagicMock(),
            selenium.common.exceptions.TimeoutException(),
        ]

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "3000"

        def find_element_side_effect(by, xpath):
            if 'name="price"' in xpath:
                return mock_price_input
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            unittest.mock.patch("my_lib.selenium_util.random_sleep"),
            unittest.mock.patch("time.sleep"),
            pytest.raises(mercari_bot.exceptions.PriceVerificationTimeoutError),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_pre_submit_timeout_propagates(
        self, mock_driver, mock_wait, profile_config: ProfileConfig
    ):
        """送信前のタイムアウトは TimeoutException のまま伝播する（リトライ可能・回帰テスト）"""
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"

        # 送信前のタイトル待機（2 回目の wait.until）でタイムアウトさせる
        mock_wait.until.side_effect = [
            mock_modified_element,
            selenium.common.exceptions.TimeoutException(),
        ]

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            unittest.mock.patch("my_lib.selenium_util.random_sleep"),
            unittest.mock.patch("time.sleep"),
            pytest.raises(selenium.common.exceptions.TimeoutException),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_post_submit_error_hierarchy(self):
        """送信後エラーの例外階層（item_handler は PostSubmitError で捕捉する）"""
        assert issubclass(
            mercari_bot.exceptions.PriceVerificationError, mercari_bot.exceptions.PostSubmitError
        )
        assert issubclass(
            mercari_bot.exceptions.PriceVerificationTimeoutError, mercari_bot.exceptions.PostSubmitError
        )
        assert issubclass(mercari_bot.exceptions.PostSubmitError, mercari_bot.exceptions.PriceError)

    def test_execute_item_price_verification_failed(
        self, mock_driver, mock_wait, profile_config: ProfileConfig
    ):
        """価格変更後の検証で価格が一致しない"""
        item = _create_mock_item()

        mock_modified_element = unittest.mock.MagicMock()
        mock_modified_element.text = "25時間前"
        mock_wait.until.return_value = mock_modified_element

        mock_price_input = unittest.mock.MagicMock()
        mock_price_input.get_attribute.return_value = "3000"

        # 更新後の価格が異なる
        mock_new_price_element = unittest.mock.MagicMock()
        mock_new_price_element.text = "2,500"

        def find_element_side_effect(by, xpath):
            if 'color="secondary"' in xpath:
                return mock_modified_element
            if 'name="price"' in xpath:
                return mock_price_input
            if 'data-testid="price"' in xpath:
                return mock_new_price_element
            return unittest.mock.MagicMock()

        mock_driver.find_element.side_effect = find_element_side_effect
        mock_driver.find_elements.return_value = []

        with (
            unittest.mock.patch("my_lib.selenium_util.click_xpath"),
            unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
            unittest.mock.patch("my_lib.selenium_util.random_sleep"),
            unittest.mock.patch("my_lib.selenium_util.wait_patiently"),
            unittest.mock.patch("time.sleep"),
            pytest.raises(mercari_bot.exceptions.PriceVerificationError),
        ):
            mercari_bot.mercari_price_down._execute_item(
                mock_driver, mock_wait, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )


class TestSoldDetection:
    """売却検知のテスト（F5）"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return AppConfig(
            profile=[profile_config],
            slack=SlackEmptyConfig(),
            data=DataConfig(
                selenium=tmp_path / "selenium",
                dump=tmp_path / "dump",
                history=tmp_path / "history.db",
            ),
            mail=unittest.mock.MagicMock(),
        )

    def _execute_with_items(self, mock_config: AppConfig, profile_config: ProfileConfig, items, debug_mode):
        """iter_items_on_display が items を on_item_start に流す状態で execute を実行"""
        mock_driver = unittest.mock.MagicMock()

        def iter_items_side_effect(
            driver, wait, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            assert progress_observer is not None
            for index, item in enumerate(items, start=1):
                progress_observer.on_item_start(index, len(items), item)

        with (
            unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
            unittest.mock.patch("my_lib.selenium_util.clear_cache"),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch("my_lib.memory_util.read_selenium_memory_bytes", return_value=None),
            unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
            unittest.mock.patch("my_lib.notify.slack.info") as mock_info,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config,
                profile_config,
                debug_mode=debug_mode,
            )

        return ret, mock_info

    def test_removed_item_is_notified(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """前回の一覧から消えたアイテムが売却として通知される"""
        sold_item = _create_mock_item(name="売れた商品", item_id="sold-id")
        remaining_item = _create_mock_item(name="残っている商品", item_id="remaining-id")

        # 前回実行: 2 アイテムが存在
        history_db = mercari_bot.history.HistoryDb(mock_config.data.history)
        history_db.replace_snapshot(profile_config.name, [sold_item, remaining_item])
        history_db.add_record(
            profile_config.name,
            sold_item,
            mercari_bot.history.ItemResult(mercari_bot.history.ItemAction.PRICE_DOWN, 3100, 3000),
        )

        # 今回実行: sold_item が消えている
        ret, mock_info = self._execute_with_items(
            mock_config, profile_config, [remaining_item], debug_mode=False
        )

        assert ret is True
        mock_info.assert_called_once()
        assert "売却" in mock_info.call_args[0][1]
        message = mock_info.call_args[0][2]
        assert "売れた商品" in message
        assert "値下げ 1回" in message

        # スナップショットは今回の内容に更新される
        snapshot = history_db.get_snapshot(profile_config.name)
        assert [s.item_id for s in snapshot] == ["remaining-id"]

    def test_no_removed_items_no_notification(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """アイテムが消えていなければ通知しない"""
        item = _create_mock_item()

        history_db = mercari_bot.history.HistoryDb(mock_config.data.history)
        history_db.replace_snapshot(profile_config.name, [item])

        ret, mock_info = self._execute_with_items(mock_config, profile_config, [item], debug_mode=False)

        assert ret is True
        mock_info.assert_not_called()

    def test_first_run_no_notification(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """初回実行（スナップショットなし）では通知しない"""
        ret, mock_info = self._execute_with_items(
            mock_config, profile_config, [_create_mock_item()], debug_mode=False
        )

        assert ret is True
        mock_info.assert_not_called()

    def test_debug_mode_skips_detection_and_db(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """デバッグモードでは売却検知も DB 作成も行わない"""
        ret, mock_info = self._execute_with_items(
            mock_config, profile_config, [_create_mock_item()], debug_mode=True
        )

        assert ret is True
        mock_info.assert_not_called()
        assert not mock_config.data.history.exists()
