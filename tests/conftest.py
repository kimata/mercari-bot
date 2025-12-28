#!/usr/bin/env python3
# ruff: noqa: S101
"""
共通テストフィクスチャ

テスト全体で使用する共通のフィクスチャとヘルパーを定義します。
"""
import logging
import pathlib
import unittest.mock

import pytest

from mercari_bot.config import DiscountConfig, IntervalConfig, ProfileConfig
from my_lib.store.mercari.config import LineLoginConfig, MercariLoginConfig

# === 定数 ===
# プロジェクトルートの tests/evidence/ に画像を保存
EVIDENCE_DIR = pathlib.Path(__file__).parent / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


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


# === ロギング設定 ===
logging.getLogger("selenium.webdriver.remote").setLevel(logging.WARNING)
logging.getLogger("selenium.webdriver.common").setLevel(logging.DEBUG)
