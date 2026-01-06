#!/usr/bin/env python3
from __future__ import annotations

import logging
import logging.handlers
import pathlib
import re
import time
import traceback
from typing import TYPE_CHECKING, Any

import my_lib.chrome_util
import my_lib.notify.slack
import my_lib.selenium_util
import my_lib.store.mercari.exceptions
import my_lib.store.mercari.login
import my_lib.store.mercari.scrape
import selenium.common.exceptions
import selenium.webdriver.support.expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait

import mercari_bot.logic
import mercari_bot.notify_slack
import mercari_bot.progress
from mercari_bot.config import AppConfig, ProfileConfig

_MAX_RETRY_COUNT = 1

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

_WAIT_TIMEOUT_SEC = 15


def _get_modified_hour(driver: WebDriver) -> int:
    modified_text = driver.find_element(
        By.XPATH,
        '//div[@id="item-info"]//div[contains(@class,"merShowMore")]'
        '/following-sibling::p[contains(@class, "merText")]',
    ).text

    return mercari_bot.logic.parse_modified_hour(modified_text)


def _execute_item(
    driver: WebDriver,
    wait: WebDriverWait,  # type: ignore[type-arg]
    profile: ProfileConfig,
    item: dict[str, Any],
    debug_mode: bool,
) -> None:
    if item["is_stop"] != 0:
        logging.info("公開停止中のため、スキップします。")
        return

    modified_hour = _get_modified_hour(driver)

    if modified_hour < profile.interval.hour:
        logging.info("更新してから %d 時間しか経過していないため、スキップします。", modified_hour)
        return

    my_lib.selenium_util.click_xpath(
        driver, '//span[contains(text(), "閉じる")]/following-sibling::button', is_warn=False
    )

    my_lib.selenium_util.click_xpath(driver, '//a[@data-testid="checkout-link"]')

    if my_lib.selenium_util.xpath_exists(driver, '//button[contains(text(), "タイムセールを終了する")]'):
        logging.info("タイムセール中のため、スキップします。")
        return

    wait.until(EC.title_contains("商品の情報を編集"))

    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "OK")]', is_warn=False)

    wait.until(EC.presence_of_element_located((By.XPATH, '//input[@name="price"]')))

    # NOTE: 梱包・発送たのメル便の場合は送料を取得
    if len(driver.find_elements(By.XPATH, '//span[@data-testid="shipping-fee"]')) != 0:
        shipping_fee = int(
            driver.find_element(
                By.XPATH,
                '//span[@data-testid="shipping-fee"]/span[contains(@class, "number")]',
            ).text.replace(",", "")
        )
    else:
        shipping_fee = 0

    price = item["price"] - shipping_fee

    value_attr = driver.find_element(By.XPATH, '//input[@name="price"]').get_attribute("value")
    if value_attr is None:
        raise RuntimeError("価格の取得に失敗しました。")
    cur_price = int(value_attr)
    if cur_price != price:
        raise RuntimeError("ページ遷移中に価格が変更されました。")

    discount_step = mercari_bot.logic.get_discount_step(profile, price, shipping_fee, item["favorite"])
    if discount_step is None:
        return

    new_price = price if debug_mode else mercari_bot.logic.round_price(price - discount_step)

    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(Keys.CONTROL + "a")
    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(Keys.BACK_SPACE)
    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(str(new_price))
    my_lib.selenium_util.random_sleep(2)
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "変更する")]')

    time.sleep(1)
    # NOTE: 「出品情報の確認」ポップアップが表示される場合がある
    my_lib.selenium_util.click_xpath(
        driver, '//button[contains(text(), "このまま変更を確定する")]', is_warn=False
    )
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "このまま出品する")]', is_warn=False)

    my_lib.selenium_util.wait_patiently(
        driver,
        wait,
        EC.title_contains(re.sub(" +", " ", item["name"])),
    )
    my_lib.selenium_util.wait_patiently(
        driver,
        wait,
        EC.presence_of_element_located((By.XPATH, '//div[@data-testid="price"]')),
    )

    # NOTE: 価格更新が反映されていない場合があるので、再度ページを取得する
    time.sleep(3)
    driver.get(driver.current_url)
    wait.until(EC.presence_of_element_located((By.XPATH, '//div[@data-testid="price"]')))

    new_total_price = int(
        re.sub(
            ",",
            "",
            driver.find_element(By.XPATH, '//div[@data-testid="price"]/span[2]').text,
        )
    )

    if new_total_price != (new_price + shipping_fee):
        error_message = (
            f"編集後の価格が意図したものと異なっています。"
            f"(期待値: {new_price + shipping_fee:,}円, 実際: {new_total_price:,}円)"
        )
        raise RuntimeError(error_message)

    logging.info("価格を変更しました。(%s円 -> %s円)", f"{item['price']:,}", f"{new_total_price:,}")


def execute(
    config: AppConfig,
    profile: ProfileConfig,
    data_path: pathlib.Path,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: mercari_bot.progress.ProgressDisplay | None = None,
    clear_profile_on_browser_error: bool = False,
) -> int:
    """メルカリ値下げ処理を実行する。

    セッションエラー（ブラウザクラッシュ等）が発生した場合、
    clear_profile_on_browser_error=True であればプロファイルを削除してリトライする。
    """
    try:
        return my_lib.selenium_util.with_session_retry(
            lambda: _execute_once(
                config, profile, data_path, dump_path, debug_mode, progress, clear_profile_on_browser_error
            ),
            driver_name=profile.name,
            data_dir=data_path,
            max_retries=_MAX_RETRY_COUNT,
            clear_profile_on_error=clear_profile_on_browser_error,
            on_retry=lambda a, m: (
                progress.set_status(f"🔄 セッションエラー、リトライ中... ({profile.name})")
                if progress is not None
                else None
            ),
        )
    except selenium.common.exceptions.InvalidSessionIdException:
        logging.exception("セッションエラーが発生しました（リトライ不可）")
        if progress is not None:
            progress.set_status("❌ セッションエラー", is_error=True)
        my_lib.notify.slack.error(
            config.slack,
            "メルカリセッションエラー",
            traceback.format_exc(),
        )
        return -1


def _execute_once(
    config: AppConfig,
    profile: ProfileConfig,
    data_path: pathlib.Path,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: mercari_bot.progress.ProgressDisplay | None = None,
    clear_profile_on_browser_error: bool = False,
) -> int:
    """メルカリ値下げ処理の1回分の実行。"""
    if progress is not None:
        progress.set_status(f"🤖 ブラウザを起動中... ({profile.name})")

    try:
        driver = my_lib.selenium_util.create_driver(profile.name, data_path)
    except Exception:
        logging.exception("ブラウザの起動に失敗しました")
        if progress is not None:
            progress.set_status("❌ ブラウザ起動エラー", is_error=True)

        if clear_profile_on_browser_error:
            my_lib.chrome_util.delete_profile(profile.name, data_path)

        raise

    my_lib.selenium_util.clear_cache(driver)

    wait = WebDriverWait(driver, _WAIT_TIMEOUT_SEC)

    # NOTE: execute_item に profile を渡すためのラッパー
    def item_handler(
        driver: WebDriver,
        wait: WebDriverWait,  # type: ignore[type-arg]
        item: dict[str, Any],
        debug_mode: bool,
    ) -> None:
        _execute_item(driver, wait, profile, item, debug_mode)

    try:
        if progress is not None:
            progress.set_status(f"🔑 ログイン中... ({profile.name})")

        my_lib.store.mercari.login.execute(
            driver,
            wait,
            profile.mercari,
            profile.line,
            config.slack,
            dump_path,
        )

        if progress is not None:
            progress.set_status(f"📦 出品リスト取得中... ({profile.name})")

        my_lib.store.mercari.scrape.iter_items_on_display(
            driver, wait, debug_mode, [item_handler], progress_observer=progress
        )

        my_lib.selenium_util.log_memory_usage(driver)

        if progress is not None:
            progress.set_status(f"✅ 完了 ({profile.name})")

        return 0
    except selenium.common.exceptions.InvalidSessionIdException:
        # セッションエラーはリトライのために re-raise する
        logging.warning("セッションエラーが発生しました（ブラウザがクラッシュした可能性があります）")
        raise
    except my_lib.store.mercari.exceptions.LoginError:
        logging.exception("ログインに失敗しました: URL: %s", driver.current_url)
        if progress is not None:
            progress.set_status("❌ ログインエラー", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリログインエラー", driver, dump_path
        )
        return -1
    except Exception:
        logging.exception("エラーが発生しました: URL: %s", driver.current_url)
        if progress is not None:
            progress.set_status("❌ エラー発生", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリ値下げエラー", driver, dump_path
        )
        return -1
    finally:
        my_lib.selenium_util.quit_driver_gracefully(driver)
