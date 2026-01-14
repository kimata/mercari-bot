#!/usr/bin/env python3
"""Slack でエラー通知を行います。"""

from __future__ import annotations

import io
import pathlib
import random
import traceback
from typing import TYPE_CHECKING

import my_lib.notify.slack
import my_lib.selenium_util
import PIL.Image

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from mercari_bot.config import SlackConfig, SlackEmptyConfig


def error_with_screenshot(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    message: str,
    driver: WebDriver,
) -> None:
    """スクリーンショット付きでエラーを通知する。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        message: エラーメッセージ
        driver: スクリーンショット取得用の WebDriver

    """
    my_lib.notify.slack.error_with_image(
        slack_config,
        title,
        message,
        {
            "data": PIL.Image.open(io.BytesIO(driver.get_screenshot_as_png())),
            "text": "エラー時のスクリーンショット",
        },
    )


def error_with_traceback(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    driver: WebDriver,
) -> None:
    """エラーをトレースバック付きで通知する。

    例外ハンドラ内で使用し、現在の例外情報を自動取得します。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        driver: スクリーンショット取得用の WebDriver

    Examples:
        except Exception:
            logging.exception("Failed to do something")
            mercari_bot.notify_slack.error_with_traceback(config.slack, "処理に失敗", driver)

    """
    error_with_screenshot(slack_config, title, traceback.format_exc(), driver)


def dump_and_notify_error(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    driver: WebDriver,
    dump_path: pathlib.Path,
    exception: Exception,
) -> None:
    """ページダンプを保存し、エラーを通知する。

    例外ハンドラ内で使用します。ページダンプの保存とSlack通知を一括で行います。
    スクリーンショットとページソース（gzip圧縮）をスレッドに添付します。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        driver: WebDriver
        dump_path: ダンプ保存先パス
        exception: 発生した例外

    Examples:
        except Exception as e:
            logging.exception("URL: %s", driver.current_url)
            mercari_bot.notify_slack.dump_and_notify_error(
                config.slack, "メルカリエラー", driver, dump_path, e
            )

    """
    my_lib.selenium_util.dump_page(driver, int(random.random() * 100), dump_path)  # noqa: S311
    my_lib.selenium_util.clean_dump(dump_path)

    # スクリーンショットを取得
    try:
        screenshot = PIL.Image.open(io.BytesIO(driver.get_screenshot_as_png()))
    except Exception:
        screenshot = None

    # ページソースを取得
    try:
        page_source: str | None = driver.page_source
    except Exception:
        page_source = None

    my_lib.notify.slack.notify_error_with_page(slack_config, title, exception, screenshot, page_source)
