#!/usr/bin/env python3
# ruff: noqa: S101
"""
mercari_price_down モジュールのテスト

ブラウザ操作（my_lib.browser の Page）をモックして処理フローをテストします。
"""

import pathlib
import unittest.mock

import my_lib.browser
import my_lib.store.mercari.exceptions
import pytest
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


def _create_mock_page(url: str = "https://jp.mercari.com/test") -> unittest.mock.MagicMock:
    """モック Page を作成"""
    page = unittest.mock.MagicMock()
    page.url = url
    page.find_all.return_value = []
    page.exists.return_value = False
    return page


def _create_mock_browser_manager(
    page: unittest.mock.MagicMock | None = None,
    launch_error: Exception | None = None,
) -> unittest.mock.MagicMock:
    """page() スコープが page を返す BrowserManager モックを作成

    launch_error を指定すると page() スコープの開始（ブラウザ起動）で例外を送出する。
    """
    manager = unittest.mock.MagicMock()
    scope = manager.page.return_value
    if launch_error is not None:
        scope.__enter__.side_effect = launch_error
    else:
        scope.__enter__.return_value = page if page is not None else _create_mock_page()
    scope.__exit__.return_value = False
    return manager


def _make_config(profile_config: ProfileConfig, tmp_path: pathlib.Path, slack=None) -> AppConfig:
    return AppConfig(
        profile=[profile_config],
        slack=SlackEmptyConfig() if slack is None else slack,
        data=DataConfig(
            selenium=tmp_path / "selenium",
            dump=tmp_path / "dump",
            history=tmp_path / "history.db",
        ),
        mail=unittest.mock.MagicMock(),
    )


def _patch_browser(manager: unittest.mock.MagicMock):
    return unittest.mock.patch("my_lib.browser.BrowserManager", return_value=manager)


class TestExecute:
    """execute 関数のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return _make_config(profile_config, tmp_path)

    def test_execute_success(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """正常実行"""
        manager = _create_mock_browser_manager()

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            assert ret is True
            # タブは page() スコープで開閉され、ブラウザは終了される
            manager.page.assert_called_once()
            manager.page.return_value.__exit__.assert_called_once()
            manager.quit.assert_called_once()

    def test_execute_with_progress(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """progress が渡された場合のステータス更新"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, progress=mock_progress
            )

            # ステータス更新が呼ばれる
            assert mock_progress.set_status.call_count >= 3
            status_calls = [call[0][0] for call in mock_progress.set_status.call_args_list]

            # ブラウザ起動、ログイン、出品リスト取得、完了のステータス
            assert any("ブラウザ" in s for s in status_calls)
            assert any("ログイン" in s for s in status_calls)
            assert any("完了" in s for s in status_calls)

    def test_execute_login_error(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """ログインエラー時の処理"""
        page = _create_mock_page()

        with (
            _patch_browser(_create_mock_browser_manager(page)),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.store.mercari.exceptions.LoginError("ログイン失敗"),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            assert ret is False
            mock_notify.assert_called_once()
            # タイトルに「ログイン」が含まれ、ダンプ対象はスコープ内の Page
            assert "ログイン" in mock_notify.call_args[0][1]
            assert mock_notify.call_args[0][2] is page

    def test_execute_general_error(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """一般的なエラー時の処理"""
        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=Exception("予期しないエラー"),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            assert ret is False
            mock_notify.assert_called_once()
            # タイトルに「値下げ」が含まれる
            assert "値下げ" in mock_notify.call_args[0][1]

    def test_execute_error_with_progress(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """エラー時に progress のエラーステータスが設定される"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=Exception("エラー")),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, progress=mock_progress
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

    def test_execute_browser_always_quit(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """正常・異常に関わらずタブが閉じられ、ブラウザが終了される"""
        manager = _create_mock_browser_manager()

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=Exception("エラー")),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            manager.page.return_value.__exit__.assert_called_once()
            manager.quit.assert_called_once()

    def test_execute_calls_iter_items(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """iter_items_on_display がスコープ内の Page で呼ばれる"""
        page = _create_mock_page()

        with (
            _patch_browser(_create_mock_browser_manager(page)),
            unittest.mock.patch("my_lib.store.mercari.login.execute") as mock_login,
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
        ):
            mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            mock_iter.assert_called_once()
            assert mock_iter.call_args[0][0] is page
            assert mock_login.call_args[0][0] is page

    def test_execute_passes_progress_observer(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """progress_observer が iter_items_on_display に渡される"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
        ):
            mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, progress=mock_progress
            )

            # progress_observer には全アイテム記録用のラッパーが渡され、
            # 内側の observer として progress が使われる
            call_kwargs = mock_iter.call_args[1]
            assert "progress_observer" in call_kwargs
            observer = call_kwargs["progress_observer"]
            assert isinstance(observer, mercari_bot.progress.ItemRecordingObserver)
            assert observer.inner == mock_progress

    def test_execute_session_error_retry_success(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """セッションエラー発生後、リトライで成功するケース"""
        call_count = 0

        def login_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 1回目はセッションエラー
                raise my_lib.browser.SessionError("session deleted")
            # 2回目は成功

        manager = _create_mock_browser_manager()

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=login_side_effect),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, clear_profile_on_browser_error=True
            )

            assert ret is True  # リトライで成功
            # タブは 2 回開かれ（初回 + リトライ）、リトライ前にプロファイルが削除される
            assert manager.page.call_count == 2
            manager.clear_profile.assert_called_once()
            assert manager.quit.call_count == 2

    def test_execute_session_error_no_profile_clear_when_disabled(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """clear_profile_on_browser_error=False の場合はプロファイルを削除しない"""
        manager = _create_mock_browser_manager()

        with (
            _patch_browser(manager),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.browser.SessionError("session deleted"),
            ),
            unittest.mock.patch("my_lib.notify.slack.error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, clear_profile_on_browser_error=False
            )

            assert ret is False  # リトライしても失敗
            manager.clear_profile.assert_not_called()  # プロファイル削除は呼ばれない

    def test_execute_session_error_retry_exhausted(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """リトライ回数を超えた場合は失敗"""
        manager = _create_mock_browser_manager()

        with (
            _patch_browser(manager),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.browser.SessionError("session deleted"),
            ),
            unittest.mock.patch("my_lib.notify.slack.error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, clear_profile_on_browser_error=True
            )

            assert ret is False  # 最終的に失敗
            # タブは 2 回開かれる（初回 + リトライ）
            assert manager.page.call_count == 2
            mock_notify.assert_called_once()
            assert "セッション" in mock_notify.call_args[0][1]


class TestGetModifiedHour:
    """_get_modified_hour のテスト"""

    def test_get_modified_hour(self):
        """更新時間の取得"""
        page = _create_mock_page()
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "3時間前"
        page.wait_present.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(page)

        assert result == 3

    def test_get_modified_hour_days(self):
        """日単位の更新時間"""
        page = _create_mock_page()
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "2日前"
        page.wait_present.return_value = mock_element

        result = mercari_bot.mercari_price_down._get_modified_hour(page)

        assert result == 48  # 2 * 24


class TestExecuteItem:
    """_execute_item のテスト（ブラウザ操作をモック）"""

    def test_execute_item_skip_recent(self, profile_config: ProfileConfig):
        """最近更新されたアイテムはスキップ"""
        item = _create_mock_item()
        page = _create_mock_page()

        # _get_modified_hour が小さい値を返すようモック
        mock_element = unittest.mock.MagicMock()
        mock_element.text = "1時間前"
        page.wait_present.return_value = mock_element

        with unittest.mock.patch("mercari_bot.mercari_price_down._click_xpath"):
            result = mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
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
        return _make_config(profile_config, tmp_path, slack=slack_config)

    def test_execute_error_notifies_slack(
        self, mock_config_with_slack: AppConfig, profile_config: ProfileConfig
    ):
        """エラー時に Slack 通知が送られる"""
        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=Exception("テストエラー")),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            mercari_bot.mercari_price_down.execute(mock_config_with_slack, profile_config, debug_mode=True)

            mock_notify.assert_called_once()
            # Slack 設定が渡される
            assert mock_notify.call_args[0][0] == mock_config_with_slack.slack


class TestBrowserStartupError:
    """ブラウザ起動エラー時のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return _make_config(profile_config, tmp_path)

    def test_browser_startup_error_with_profile_delete(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """ブラウザ起動エラー時は Slack 通知してエラー終了し、プロファイルを削除する（例外は伝播しない）"""
        manager = _create_mock_browser_manager(launch_error=my_lib.browser.BrowserError("ブラウザ起動失敗"))

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.notify.slack.error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, clear_profile_on_browser_error=True
            )

            assert ret is False
            mock_notify.assert_called_once()
            assert "ブラウザ起動" in mock_notify.call_args[0][1]
            manager.clear_profile.assert_called_once()
            manager.quit.assert_called_once()

    def test_browser_startup_error_without_profile_delete(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """ブラウザ起動エラー時にプロファイル削除しない（clear_profile_on_browser_error=False）"""
        manager = _create_mock_browser_manager(launch_error=my_lib.browser.BrowserError("ブラウザ起動失敗"))

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.notify.slack.error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, clear_profile_on_browser_error=False
            )

            assert ret is False
            # プロファイル削除は呼ばれない
            manager.clear_profile.assert_not_called()

    def test_browser_startup_error_with_progress(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """ブラウザ起動エラー時に progress にエラーステータスを設定"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)
        manager = _create_mock_browser_manager(launch_error=my_lib.browser.BrowserError("ブラウザ起動失敗"))

        with (
            _patch_browser(manager),
            unittest.mock.patch("my_lib.notify.slack.error"),
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
        return _make_config(profile_config, tmp_path)

    def test_session_error_retry_with_progress(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """セッションエラー時にリトライメッセージを progress に表示"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        call_count = 0

        def login_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise my_lib.browser.SessionError("session deleted")
            # 2回目は成功

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute", side_effect=login_side_effect),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display"),
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
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """セッションエラーでリトライ上限超過時に progress にエラー表示"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.browser.SessionError("session deleted"),
            ),
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
        return _make_config(profile_config, tmp_path)

    def test_login_error_with_progress(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """ログインエラー時に progress にエラーステータスを設定"""
        mock_progress = unittest.mock.MagicMock(spec=mercari_bot.progress.ProgressDisplay)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch(
                "my_lib.store.mercari.login.execute",
                side_effect=my_lib.store.mercari.exceptions.LoginError("ログイン失敗"),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        ):
            ret = mercari_bot.mercari_price_down.execute(
                mock_config, profile_config, debug_mode=True, progress=mock_progress
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


def _iter_items_calling_handlers(item: MercariItem):
    """iter_items_on_display のモック（各ハンドラを (page, item, debug_mode) で呼ぶ）"""

    def iter_items_side_effect(
        page, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
    ):
        for handler in handlers:
            handler(page, item, debug_mode)

    return iter_items_side_effect


class TestItemHandler:
    """item_handler ラッパー関数のテスト"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return _make_config(profile_config, tmp_path)

    def test_item_handler_is_called(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """iter_items_on_display から item_handler が呼び出される"""
        item = _create_mock_item()
        page = _create_mock_page()

        with (
            _patch_browser(_create_mock_browser_manager(page)),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=_iter_items_calling_handlers(item),
            ),
            unittest.mock.patch("mercari_bot.mercari_price_down._execute_item") as mock_execute_item,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            # 正常終了し、item_handler 経由で _execute_item がスコープ内の Page で呼ばれる
            assert ret is True
            mock_execute_item.assert_called_once()
            assert mock_execute_item.call_args[0][0] is page

    def test_price_verification_error_notifies_and_fails(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """価格検証エラーは Slack 通知され、プロファイルの結果が失敗になる（BUG-8 回帰テスト）"""
        item = _create_mock_item()

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=_iter_items_calling_handlers(item),
            ),
            unittest.mock.patch(
                "mercari_bot.mercari_price_down._execute_item",
                side_effect=mercari_bot.exceptions.PriceVerificationError(expected=2900, actual=3000),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            assert ret is False
            mock_notify.assert_called_once()
            assert "価格検証" in mock_notify.call_args[0][1]

    def test_post_submit_timeout_notifies_and_fails(
        self, mock_config: AppConfig, profile_config: ProfileConfig
    ):
        """送信後の検証タイムアウトも Slack 通知され、プロファイルの結果が失敗になる（§3.1）"""
        item = _create_mock_item()

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=_iter_items_calling_handlers(item),
            ),
            unittest.mock.patch(
                "mercari_bot.mercari_price_down._execute_item",
                side_effect=mercari_bot.exceptions.PriceVerificationTimeoutError("テスト商品"),
            ),
            unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error") as mock_notify,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            assert ret is False
            mock_notify.assert_called_once()
            assert "価格検証" in mock_notify.call_args[0][1]

    def test_item_result_is_recorded(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """item_handler が処理結果を履歴 DB に記録する（F1）"""
        item = _create_mock_item()
        result = mercari_bot.history.ItemResult(mercari_bot.history.ItemAction.PRICE_DOWN, 3000, 2900)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=_iter_items_calling_handlers(item),
            ),
            unittest.mock.patch("mercari_bot.mercari_price_down._execute_item", return_value=result),
            unittest.mock.patch("mercari_bot.history.HistoryDb") as mock_history_cls,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=False)

            assert ret is True
            mock_history = mock_history_cls.return_value
            mock_history_cls.assert_called_once_with(mock_config.data.history)
            mock_history.add_record.assert_called_once_with(profile_config.name, item, result)
            # 走査完了後にスナップショットが更新される
            mock_history.replace_snapshot.assert_called_once()

    def test_max_consecutive_failures_is_passed(self, mock_config: AppConfig, profile_config: ProfileConfig):
        """iter_items_on_display に max_consecutive_failures が渡される（BUG-6 回帰テスト）"""
        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch("my_lib.store.mercari.scrape.iter_items_on_display") as mock_iter,
        ):
            mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=True)

            call_kwargs = mock_iter.call_args[1]
            assert call_kwargs["max_consecutive_failures"] == 2


def _build_item_page(
    *,
    modified_text: str = "25時間前",
    price_value: str | None = "3000",
    new_price_text: str = "3,000",
    shipping_fee_text: str | None = None,
    consent_checkbox: unittest.mock.MagicMock | None = None,
    url: str = "https://jp.mercari.com/item/m12345",
) -> unittest.mock.MagicMock:
    """_execute_item 用のモック Page を組み立てる

    - wait_present: 更新時間要素を返す
    - find: XPath に応じて 価格入力欄 / 送料 / 更新後価格 の要素を返す
    - find_all: 送料要素・同意チェックボックスの有無
    """
    page = _create_mock_page(url)

    modified_element = unittest.mock.MagicMock()
    modified_element.text = modified_text
    page.wait_present.return_value = modified_element

    price_input = unittest.mock.MagicMock(name="price_input")
    price_input.evaluate.side_effect = lambda script, *args: price_value if "el.value" in script else None

    shipping_element = unittest.mock.MagicMock(name="shipping")
    shipping_element.text = shipping_fee_text or "0"

    new_price_element = unittest.mock.MagicMock(name="new_price")
    new_price_element.text = new_price_text

    def find_side_effect(locator):
        xpath = locator.value
        if "shipping-fee" in xpath and "number" in xpath:
            return shipping_element
        if 'name="price"' in xpath:
            return price_input
        if 'data-testid="price"' in xpath:
            return new_price_element
        return unittest.mock.MagicMock()

    def find_all_side_effect(locator):
        xpath = locator.value
        if "listing-alert-consent" in xpath:
            return [consent_checkbox] if consent_checkbox is not None else []
        if "shipping-fee" in xpath:
            return [shipping_element] if shipping_fee_text is not None else []
        return []

    page.find.side_effect = find_side_effect
    page.find_all.side_effect = find_all_side_effect
    page._price_input = price_input
    return page


class TestExecuteItemPriceChange:
    """_execute_item の価格変更パスのテスト"""

    @pytest.fixture
    def quiet(self):
        """スリープ・クリック・待機のモック"""
        with (
            unittest.mock.patch("mercari_bot.mercari_price_down._click_xpath") as mock_click,
            unittest.mock.patch("my_lib.store.mercari.scrape.random_sleep"),
            unittest.mock.patch("mercari_bot.mercari_price_down._wait_present_patiently"),
            unittest.mock.patch("time.sleep"),
        ):
            yield mock_click

    def test_execute_item_time_sale(self, quiet, profile_config: ProfileConfig):
        """タイムセール中のアイテムはスキップ"""
        item = _create_mock_item()
        page = _build_item_page()
        page.exists.side_effect = lambda locator, **_kwargs: "タイムセール" in locator.value

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.SKIP_TIME_SALE

    def test_execute_item_auction(self, quiet, profile_config: ProfileConfig):
        """オークション形式のアイテムはスキップ"""
        item = _create_mock_item()
        page = _build_item_page()
        page.exists.side_effect = lambda locator, **_kwargs: "@checked" in locator.value

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.SKIP_AUCTION

    def test_execute_item_with_shipping_fee(self, quiet, profile_config: ProfileConfig):
        """送料ありの場合のテスト"""
        item = _create_mock_item(price=5000)
        # 5000 - 1000 = 4000、更新後価格（new_price + shipping_fee = 4000 + 1000 = 5000）
        page = _build_item_page(price_value="4000", new_price_text="5,000", shipping_fee_text="1,000")

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
        assert result.new_price == 5000

    def test_execute_item_price_mismatch(self, quiet, profile_config: ProfileConfig):
        """ページ遷移中に価格が変更された場合"""
        item = _create_mock_item()
        page = _build_item_page(price_value="2500")  # 価格が変更されている

        with pytest.raises(mercari_bot.exceptions.PriceChangedError):
            mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_price_attribute_none(self, quiet, profile_config: ProfileConfig):
        """価格入力欄の value が None の場合"""
        item = _create_mock_item()
        page = _build_item_page(price_value=None)

        with pytest.raises(mercari_bot.exceptions.PriceRetrievalError):
            mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_no_discount(self, quiet, profile_config: ProfileConfig):
        """割引ステップが None の場合（閾値以下）"""
        item = _create_mock_item(price=500, favorite=0)  # 閾値以下
        page = _build_item_page(price_value="500")

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.SKIP_NO_DISCOUNT

    def test_execute_item_price_change_success(self, quiet, profile_config: ProfileConfig):
        """価格変更成功（debug_mode=True）"""
        item = _create_mock_item()
        page = _build_item_page()

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
        assert result.old_price == 3000
        assert result.new_price == 3000  # debug_mode=True なので同額
        # 価格は nativeInputValueSetter で設定される
        set_calls = [
            c for c in page._price_input.evaluate.call_args_list if "nativeInputValueSetter" in c.args[0]
        ]
        assert len(set_calls) == 1
        assert set_calls[0].args[1] == "3000"

    def test_execute_item_price_change_not_debug(self, quiet, profile_config: ProfileConfig):
        """debug_mode=False では割引後の価格が設定される"""
        item = _create_mock_item(price=3000, favorite=0)
        page = _build_item_page(new_price_text="2,900")

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=False, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
        assert result.new_price == 2900
        set_calls = [
            c for c in page._price_input.evaluate.call_args_list if "nativeInputValueSetter" in c.args[0]
        ]
        assert set_calls[0].args[1] == "2900"

    def test_execute_item_accepts_listing_alert(self, quiet, profile_config: ProfileConfig):
        """編集ページに法令表示事項の同意チェックボックスがあれば、送信前にチェックを入れる"""
        item = _create_mock_item()

        consent_checkbox = unittest.mock.MagicMock(name="consent")
        # (el) => el.checked: 1 回目 False、2 回目 True。(el) => el.click(): None
        checked = iter([False, True])
        consent_checkbox.evaluate.side_effect = lambda script, *args: (
            next(checked) if "checked" in script else None
        )

        page = _build_item_page(consent_checkbox=consent_checkbox)

        result = mercari_bot.mercari_price_down._execute_item(
            page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
        )

        assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
        # チェックボックスの JS クリックが edit-button クリックより前に行われる
        click_calls = [c for c in consent_checkbox.evaluate.call_args_list if "click" in c.args[0]]
        assert len(click_calls) == 1
        edit_calls = [c for c in quiet.call_args_list if "edit-button" in c.args[1]]
        assert len(edit_calls) == 1

    def test_execute_item_post_submit_timeout(self, quiet, profile_config: ProfileConfig):
        """送信後のタイムアウトは PriceVerificationTimeoutError に変換される（§3.1）

        WaitTimeoutError のまま伝播させると my_lib のリトライで再実行され、
        interval 判定でスキップ → 検証されないまま正常終了に化けるため。
        """
        item = _create_mock_item()
        page = _build_item_page()
        # 送信後の h1 待機でタイムアウトさせる
        page.wait_text.side_effect = my_lib.browser.WaitTimeoutError("timeout")

        with pytest.raises(mercari_bot.exceptions.PriceVerificationTimeoutError):
            mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_pre_submit_timeout_propagates(self, quiet, profile_config: ProfileConfig):
        """送信前のタイムアウトは WaitTimeoutError のまま伝播する（リトライ可能・回帰テスト）"""
        item = _create_mock_item()
        page = _build_item_page()
        # 送信前のタイトル待機でタイムアウトさせる
        page.wait_until.side_effect = my_lib.browser.WaitTimeoutError("timeout")

        with pytest.raises(my_lib.browser.WaitTimeoutError):
            mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

    def test_execute_item_no_transition_falls_back_to_item_page(self, quiet, profile_config: ProfileConfig):
        """送信後に編集ページから遷移しない場合は商品ページへ直接遷移し、ダンプを残す"""
        item = _create_mock_item()
        page = _build_item_page(url="https://jp.mercari.com/sell/edit/m12345")

        with unittest.mock.patch("my_lib.browser.helpers.dump_page") as mock_dump:
            result = mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )

        assert result.action == mercari_bot.history.ItemAction.PRICE_DOWN
        mock_dump.assert_called_once()
        page.goto.assert_any_call("https://jp.mercari.com/item/m12345")

    def test_post_submit_error_hierarchy(self):
        """送信後エラーの例外階層（item_handler は PostSubmitError で捕捉する）"""
        assert issubclass(
            mercari_bot.exceptions.PriceVerificationError, mercari_bot.exceptions.PostSubmitError
        )
        assert issubclass(
            mercari_bot.exceptions.PriceVerificationTimeoutError, mercari_bot.exceptions.PostSubmitError
        )
        assert issubclass(mercari_bot.exceptions.PostSubmitError, mercari_bot.exceptions.PriceError)

    def test_execute_item_price_verification_failed(self, quiet, profile_config: ProfileConfig):
        """価格変更後の検証で価格が一致しない"""
        item = _create_mock_item()
        page = _build_item_page(new_price_text="2,500")  # 更新後の価格が異なる

        with pytest.raises(mercari_bot.exceptions.PriceVerificationError):
            mercari_bot.mercari_price_down._execute_item(
                page, profile_config, item, debug_mode=True, dump_path=_DUMMY_DUMP_PATH
            )


class TestAcceptListingAlert:
    """_accept_listing_alert のテスト"""

    @staticmethod
    def _checkbox(checked_values) -> unittest.mock.MagicMock:
        checkbox = unittest.mock.MagicMock()
        values = iter(checked_values)
        checkbox.evaluate.side_effect = lambda script, *args: next(values) if "checked" in script else None
        return checkbox

    def test_no_checkbox(self):
        """同意チェックボックスが無ければ何もしない"""
        page = _create_mock_page()
        page.find_all.return_value = []

        mercari_bot.mercari_price_down._accept_listing_alert(page)

    def test_already_checked(self):
        """既にチェック済みならクリックしない"""
        checkbox = self._checkbox([True])
        page = _create_mock_page()
        page.find_all.return_value = [checkbox]

        mercari_bot.mercari_price_down._accept_listing_alert(page)

        click_calls = [c for c in checkbox.evaluate.call_args_list if "click" in c.args[0]]
        assert click_calls == []

    def test_check_unchecked(self):
        """未チェックなら JavaScript でクリックする"""
        checkbox = self._checkbox([False, True])
        page = _create_mock_page()
        page.find_all.return_value = [checkbox]

        mercari_bot.mercari_price_down._accept_listing_alert(page)

        click_calls = [c for c in checkbox.evaluate.call_args_list if "click" in c.args[0]]
        assert len(click_calls) == 1

    def test_check_failed(self):
        """クリック後もチェックされない場合は例外"""
        checkbox = self._checkbox([False, False])
        page = _create_mock_page()
        page.find_all.return_value = [checkbox]

        with pytest.raises(mercari_bot.exceptions.ListingAlertConsentError):
            mercari_bot.mercari_price_down._accept_listing_alert(page)


class TestPageHelpers:
    """Page 操作ヘルパーのテスト"""

    def test_click_xpath_clicks_when_found(self):
        page = _create_mock_page()
        element = unittest.mock.MagicMock()
        page.find.return_value = element

        assert mercari_bot.mercari_price_down._click_xpath(page, "//button") is True
        element.click.assert_called_once()

    def test_click_xpath_returns_false_when_missing(self):
        page = _create_mock_page()
        page.find.return_value = None

        assert mercari_bot.mercari_price_down._click_xpath(page, "//button", is_warn=False) is False

    def test_wait_present_patiently_reloads_once(self):
        """タイムアウトしたらリロードして待ち直す"""
        page = _create_mock_page()
        page.wait_present.side_effect = [
            my_lib.browser.WaitTimeoutError("timeout"),
            unittest.mock.MagicMock(),
        ]

        mercari_bot.mercari_price_down._wait_present_patiently(page, "//div")

        page.refresh.assert_called_once()
        assert page.wait_present.call_count == 2

    def test_wait_present_patiently_gives_up(self):
        page = _create_mock_page()
        page.wait_present.side_effect = my_lib.browser.WaitTimeoutError("timeout")

        with pytest.raises(my_lib.browser.WaitTimeoutError):
            mercari_bot.mercari_price_down._wait_present_patiently(page, "//div")

    def test_get_current_url_safely_when_browser_dead(self):
        page = unittest.mock.MagicMock()
        type(page).url = unittest.mock.PropertyMock(side_effect=RuntimeError("dead"))

        assert mercari_bot.mercari_price_down._get_current_url_safely(page) == "(取得失敗)"


class TestEditLinkXpath:
    """商品ページの「商品の編集」リンク XPath が新旧 HTML 構造の両方にマッチすることを確認"""

    # NOTE: 2026-09-09 以前の構造
    OLD_HTML = (
        '<div data-testid="checkout-button">'
        '<a href="/sell/edit/m28836085390" data-testid="checkout-link">商品の編集</a></div>'
    )
    # NOTE: 2026-09-09 以降の構造（data-testid が a 要素に移り checkout-button になった）
    NEW_HTML = '<a href="/sell/edit/m12435026940" data-testid="checkout-button"><span>商品の編集</span></a>'

    @pytest.mark.parametrize("html", [OLD_HTML, NEW_HTML])
    def test_match(self, html):
        lxml_html = pytest.importorskip("lxml.html")
        tree = lxml_html.fromstring(f"<html><body>{html}</body></html>")

        matched = tree.xpath(mercari_bot.mercari_price_down._EDIT_LINK_XPATH)

        assert len(matched) == 1
        assert matched[0].text_content() == "商品の編集"


class TestSoldDetection:
    """売却検知のテスト（F5）"""

    @pytest.fixture
    def mock_config(self, profile_config: ProfileConfig, tmp_path: pathlib.Path):
        """モック AppConfig"""
        return _make_config(profile_config, tmp_path)

    def _execute_with_items(self, mock_config: AppConfig, profile_config: ProfileConfig, items, debug_mode):
        """iter_items_on_display が items を on_item_start に流す状態で execute を実行"""

        def iter_items_side_effect(
            page, debug_mode, handlers, progress_observer=None, max_consecutive_failures=None
        ):
            assert progress_observer is not None
            for index, item in enumerate(items, start=1):
                progress_observer.on_item_start(index, len(items), item)

        with (
            _patch_browser(_create_mock_browser_manager()),
            unittest.mock.patch("my_lib.store.mercari.login.execute"),
            unittest.mock.patch(
                "my_lib.store.mercari.scrape.iter_items_on_display",
                side_effect=iter_items_side_effect,
            ),
            unittest.mock.patch("my_lib.notify.slack.info") as mock_info,
        ):
            ret = mercari_bot.mercari_price_down.execute(mock_config, profile_config, debug_mode=debug_mode)

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
