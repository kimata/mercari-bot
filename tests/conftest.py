#!/usr/bin/env python3
# ruff: noqa: S101, S106
"""
共通テストフィクスチャ

テスト全体で使用する共通のフィクスチャとヘルパーを定義します。
"""

import pathlib
import unittest.mock

import my_lib.browser
import pytest
from my_lib.notify.slack import SlackEmptyConfig
from my_lib.store.mercari.config import LineLoginConfig, MercariItem, MercariLoginConfig

from mercari_bot.config import AppConfig, DataConfig, DiscountConfig, IntervalConfig, ProfileConfig


# === テストユーティリティ ===
def create_mock_item(
    name: str = "テスト商品",
    price: int = 3000,
    favorite: int = 5,
    is_stop: int = 0,
) -> MercariItem:
    """テスト用の MercariItem を作成する"""
    return MercariItem(
        id="test-id",
        url="https://jp.mercari.com/item/test",
        name=name,
        price=price,
        view=100,
        favorite=favorite,
        is_stop=is_stop,
    )


# === 環境モック ===
@pytest.fixture(scope="session", autouse=True)
def env_mock():
    """テスト環境用の環境変数モック"""
    with unittest.mock.patch.dict(
        "os.environ",
        {
            "TEST": "true",
            "NO_COLORED_LOGS": "true",
        },
    ) as fixture:
        yield fixture


@pytest.fixture(scope="session", autouse=True)
def slack_mock():
    """Slack API のモック"""
    with (
        unittest.mock.patch(
            "my_lib.notify.slack.slack_sdk.web.client.WebClient.chat_postMessage",
            return_value={"ok": True, "ts": "1234567890.123456"},
        ),
        unittest.mock.patch(
            "my_lib.notify.slack.slack_sdk.web.client.WebClient.files_upload_v2",
            return_value={"ok": True, "files": [{"id": "test_file_id"}]},
        ),
        unittest.mock.patch(
            "my_lib.notify.slack.slack_sdk.web.client.WebClient.files_getUploadURLExternal",
            return_value={"ok": True, "upload_url": "https://example.com"},
        ) as fixture,
    ):
        yield fixture


@pytest.fixture(autouse=True)
def _clear():
    """各テスト前にステートをクリア"""
    import my_lib.notify.slack

    my_lib.notify.slack._interval_clear()
    my_lib.notify.slack._hist_clear()


# === プロファイルフィクスチャ ===
@pytest.fixture
def profile_config() -> ProfileConfig:
    """テスト用プロファイル設定"""
    return ProfileConfig(
        name="Test Profile",
        mercari=MercariLoginConfig(
            user="test@example.com",
            password="test_password",
        ),
        discount=[
            DiscountConfig(favorite_count=10, step=200, threshold=3000),
            DiscountConfig(favorite_count=5, step=150, threshold=2000),
            DiscountConfig(favorite_count=0, step=100, threshold=1000),
        ],
        interval=IntervalConfig(hour=20),
        line=LineLoginConfig(user="line_user", password="line_pass"),
    )


@pytest.fixture
def profile_single_discount() -> ProfileConfig:
    """単一の値下げ設定を持つプロファイル"""
    return ProfileConfig(
        name="Single Discount Profile",
        mercari=MercariLoginConfig(
            user="test@example.com",
            password="test_password",
        ),
        discount=[
            DiscountConfig(favorite_count=0, step=100, threshold=500),
        ],
        interval=IntervalConfig(hour=24),
        line=LineLoginConfig(user="line_user", password="line_pass"),
    )


# === Slack 通知検証 ===
@pytest.fixture
def slack_checker():
    """Slack 通知検証ヘルパーを返す"""
    import my_lib.notify.slack

    class SlackChecker:
        def assert_notified(self, message, index=-1):
            notify_hist = my_lib.notify.slack._hist_get(is_thread_local=False)
            assert len(notify_hist) != 0, "通知がされていません。"
            assert notify_hist[index].find(message) != -1, f"「{message}」が通知されていません。"

        def assert_not_notified(self):
            notify_hist = my_lib.notify.slack._hist_get(is_thread_local=False)
            assert notify_hist == [], "通知がされています。"

    return SlackChecker()


# === BrowserManager モック ===
@pytest.fixture
def mock_page():
    """モック Page"""
    page = unittest.mock.MagicMock()
    page.url = "https://jp.mercari.com/test"
    page.find_all.return_value = []
    page.exists.return_value = False
    return page


@pytest.fixture
def mock_browser_manager(mock_page):
    """モック BrowserManager（page() スコープが mock_page を返す）"""
    manager = unittest.mock.MagicMock(spec=my_lib.browser.BrowserManager)
    manager.page.return_value.__enter__.return_value = mock_page
    manager.page.return_value.__exit__.return_value = False
    return manager


# === AppConfig フィクスチャ ===
@pytest.fixture
def app_config(profile_config: ProfileConfig, tmp_path: pathlib.Path) -> AppConfig:
    """テスト用の基本 AppConfig

    profile_config フィクスチャを使用して単一プロファイルの設定を作成します。
    複数プロファイルや特殊な設定が必要な場合は、個別にフィクスチャを作成してください。
    """
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
