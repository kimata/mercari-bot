#!/usr/bin/env python3
"""Slack でエラー通知を行います。"""

from __future__ import annotations

import io
import logging
import pathlib
import random
import traceback
from typing import TYPE_CHECKING

import my_lib.browser.helpers
import my_lib.notify.slack
import PIL.Image
from my_lib.notify.slack import AttachImage

if TYPE_CHECKING:
    from my_lib.browser import Page
    from my_lib.notify.slack import SlackConfig, SlackEmptyConfig


def error_with_screenshot(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    message: str,
    page: Page,
) -> None:
    """スクリーンショット付きでエラーを通知する。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        message: エラーメッセージ
        page: スクリーンショット取得用の Page

    """
    my_lib.notify.slack.error_with_image(
        slack_config,
        title,
        message,
        AttachImage(
            data=PIL.Image.open(io.BytesIO(page.screenshot())),
            text="エラー時のスクリーンショット",
        ),
    )


def error_with_traceback(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    page: Page,
) -> None:
    """エラーをトレースバック付きで通知する。

    例外ハンドラ内で使用し、現在の例外情報を自動取得します。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        page: スクリーンショット取得用の Page

    Examples:
        except Exception:
            logging.exception("Failed to do something")
            mercari_bot.notify_slack.error_with_traceback(config.slack, "処理に失敗", page)

    """
    error_with_screenshot(slack_config, title, traceback.format_exc(), page)


def dump_and_notify_error(
    slack_config: SlackConfig | SlackEmptyConfig,
    title: str,
    page: Page,
    dump_path: pathlib.Path,
    exception: Exception,
) -> None:
    """ページダンプを保存し、エラーを通知する。

    例外ハンドラ内で使用します。ページダンプの保存とSlack通知を一括で行います。
    スクリーンショットとページソース（gzip圧縮）をスレッドに添付します。
    `page()` スコープの内側（タブが生きている間）で呼ぶこと。

    Args:
        slack_config: Slack 設定
        title: エラータイトル
        page: 対象の Page
        dump_path: ダンプ保存先パス
        exception: 発生した例外

    Examples:
        except Exception as e:
            logging.exception("URL: %s", page.url)
            mercari_bot.notify_slack.dump_and_notify_error(
                config.slack, "メルカリエラー", page, dump_path, e
            )

    """
    # NOTE: ブラウザが死んでいてもエラー通知自体は行えるよう、ダンプ失敗は握りつぶす
    try:
        my_lib.browser.helpers.dump_page(page, random.randint(0, 99), dump_path)  # noqa: S311
        my_lib.browser.helpers.clean_dump(dump_path)
    except Exception:
        logging.exception("ページダンプの保存に失敗しました")

    # スクリーンショットを取得
    try:
        screenshot = PIL.Image.open(io.BytesIO(page.screenshot()))
    except Exception:
        screenshot = None

    # ページソースを取得
    try:
        page_source: str | None = page.content
    except Exception:
        page_source = None

    my_lib.notify.slack.notify_error_with_page(slack_config, title, exception, screenshot, page_source)
