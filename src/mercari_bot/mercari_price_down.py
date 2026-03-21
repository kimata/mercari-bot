#!/usr/bin/env python3
from __future__ import annotations

import logging
import pathlib
import re
import traceback
from typing import TYPE_CHECKING, Any, TypeAlias

import my_lib.browser_manager
import my_lib.notify.slack
import my_lib.selenium_util
import my_lib.store.mercari.exceptions
import my_lib.store.mercari.login
import my_lib.store.mercari.scrape
import selenium.common.exceptions
import selenium.webdriver.support.expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

import mercari_bot.exceptions
import mercari_bot.logic
import mercari_bot.notify_slack
import mercari_bot.progress
from mercari_bot.config import AppConfig, ProfileConfig

_MAX_RETRY_COUNT = 1

if TYPE_CHECKING:
    from my_lib.store.mercari.config import MercariItem
    from selenium.webdriver.remote.webdriver import WebDriver

# 進捗表示オブジェクトの型エイリアス
ProgressObserver: TypeAlias = mercari_bot.progress.ProgressDisplay | mercari_bot.progress.NullProgressDisplay

_WAIT_TIMEOUT_SEC = 15


def _dismiss_dialog(driver: WebDriver) -> None:
    """ページ上に表示されているダイアログ（オークション促進等）を閉じる。

    ダイアログが存在しない場合は何もせずに返る。
    別の要素に覆われてクリックできない場合は JavaScript 経由でクリックする。
    """
    xpath = '//div[@role="dialog"]//span[contains(text(), "閉じる")]/following-sibling::button'
    if not my_lib.selenium_util.xpath_exists(driver, xpath):
        return

    elem = driver.find_element(By.XPATH, xpath)
    try:
        elem.click()
    except selenium.common.exceptions.ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", elem)


def _get_modified_hour(driver: WebDriver) -> int:
    modified_text = driver.find_element(
        By.XPATH,
        '//div[@id="item-info"]//p[@color="secondary"]',
    ).text

    return mercari_bot.logic.parse_modified_hour(modified_text)


def _execute_item(
    driver: WebDriver,
    wait: WebDriverWait[Any],
    profile: ProfileConfig,
    item: MercariItem,
    debug_mode: bool,
) -> None:
    if item.is_stop != 0:
        logging.info("公開停止中のため、スキップします。")
        return

    # NOTE: 「オークションで注目を集めませんか」ポップアップが表示される場合は閉じる
    _dismiss_dialog(driver)

    modified_hour = _get_modified_hour(driver)

    if modified_hour < profile.interval.hour:
        logging.info("更新してから %d 時間しか経過していないため、スキップします。", modified_hour)
        return

    my_lib.selenium_util.click_xpath(
        driver, '//span[contains(text(), "閉じる")]/following-sibling::button', is_warn=False
    )

    my_lib.selenium_util.click_xpath(driver, '//a[@data-testid="checkout-link"]')

    wait.until(EC.title_contains("商品の情報を編集"))

    if my_lib.selenium_util.xpath_exists(driver, '//button[contains(text(), "タイムセールを終了する")]'):
        logging.info("タイムセール中のため、スキップします。")
        return

    # NOTE: ページタイトル変更後、販売形式のラジオボタンがレンダリングされるまで待機
    wait.until(EC.presence_of_element_located((By.XPATH, '//input[@data-testid="auction-price-option"]')))

    if my_lib.selenium_util.xpath_exists(driver, '//input[@data-testid="auction-price-option"][@checked]'):
        logging.info("オークション形式のため、スキップします。")
        return

    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "OK")]', is_warn=False)

    wait.until(EC.presence_of_element_located((By.XPATH, '//input[@name="price"]')))

    # NOTE: 梱包・発送たのメル便の場合は送料を取得
    if driver.find_elements(By.XPATH, '//span[@data-testid="shipping-fee"]'):
        shipping_fee = int(
            driver.find_element(
                By.XPATH,
                '//span[@data-testid="shipping-fee"]/span[contains(@class, "number")]',
            ).text.replace(",", "")
        )
    else:
        shipping_fee = 0

    price = item.price - shipping_fee

    value_attr = driver.find_element(By.XPATH, '//input[@name="price"]').get_attribute("value")
    if value_attr is None:
        raise mercari_bot.exceptions.PriceRetrievalError("価格の取得に失敗しました")
    cur_price = int(value_attr)
    if cur_price != price:
        raise mercari_bot.exceptions.PriceChangedError(expected=price, actual=cur_price)

    discount_step = mercari_bot.logic.get_discount_step(profile, price, shipping_fee, item.favorite)
    if discount_step is None:
        return

    new_price = price if debug_mode else mercari_bot.logic.round_price(price - discount_step)

    price_input = driver.find_element(By.XPATH, '//input[@name="price"]')
    # NOTE: React の controlled input に対して値を確実に反映させるため、
    # nativeInputValueSetter で値を設定してから input イベントを発火する
    driver.execute_script(
        """
        var input = arguments[0];
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        ).set;
        nativeInputValueSetter.call(input, arguments[1]);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        price_input,
        str(new_price),
    )
    my_lib.selenium_util.random_sleep(2)
    edit_url = driver.current_url
    my_lib.selenium_util.click_xpath(driver, '//button[@data-testid="edit-button"]')

    my_lib.selenium_util.random_sleep(1)
    # NOTE: 「出品情報の確認」ポップアップが表示される場合がある
    my_lib.selenium_util.click_xpath(
        driver, '//button[contains(text(), "このまま変更を確定する")]', is_warn=False
    )
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "このまま出品する")]', is_warn=False)

    # NOTE: オークション促進などのダイアログが表示される場合は閉じる
    _dismiss_dialog(driver)

    # NOTE: 変更後にページ遷移しない場合、アイテム詳細ページに直接遷移する
    my_lib.selenium_util.random_sleep(3)
    if "/sell/edit/" in driver.current_url:
        logging.warning("変更後のページ遷移が発生しませんでした: %s", driver.current_url)
        item_url = edit_url.replace("/sell/edit/", "/item/")
        driver.get(item_url)

    wait.until(EC.title_contains(re.sub(" +", " ", item.name)))
    my_lib.selenium_util.wait_patiently(
        driver,
        wait,
        EC.presence_of_element_located((By.XPATH, '//div[@data-testid="price"]')),
    )

    # NOTE: 価格更新が反映されていない場合があるので、再度ページを取得する
    my_lib.selenium_util.random_sleep(3)
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
        raise mercari_bot.exceptions.PriceVerificationError(
            expected=new_price + shipping_fee, actual=new_total_price
        )

    logging.info("価格を変更しました。(%s円 -> %s円)", f"{item.price:,}", f"{new_total_price:,}")


def execute(
    config: AppConfig,
    profile: ProfileConfig,
    data_path: pathlib.Path,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: ProgressObserver | None = None,
    clear_profile_on_browser_error: bool = False,
) -> int:
    """メルカリ値下げ処理を実行する。

    セッションエラー（ブラウザクラッシュ等）が発生した場合、
    clear_profile_on_browser_error=True であればプロファイルを削除してリトライする。
    """
    if progress is None:
        progress = mercari_bot.progress.NullProgressDisplay()

    browser_manager = my_lib.browser_manager.BrowserManager(
        profile_name=profile.name,
        data_dir=data_path,
        wait_timeout=_WAIT_TIMEOUT_SEC,
        clear_profile_on_error=clear_profile_on_browser_error,
    )

    for attempt in range(_MAX_RETRY_COUNT + 1):
        try:
            return _execute_once(config, profile, dump_path, debug_mode, progress, browser_manager)
        except selenium.common.exceptions.InvalidSessionIdException:
            if attempt < _MAX_RETRY_COUNT:
                logging.warning(
                    "セッションエラーが発生しました。リトライします (試行 %d/%d)",
                    attempt + 1,
                    _MAX_RETRY_COUNT + 1,
                )
                progress.set_status(f"🔄 セッションエラー、リトライ中... ({profile.name})")
                # BrowserManager を再作成（プロファイルクリアオプション付き）
                browser_manager = my_lib.browser_manager.BrowserManager(
                    profile_name=profile.name,
                    data_dir=data_path,
                    wait_timeout=_WAIT_TIMEOUT_SEC,
                    clear_profile_on_error=True,  # リトライ時は常にプロファイルをクリア
                )
                continue
            # リトライ回数を超えた場合
            logging.exception("セッションエラーが発生しました（リトライ不可）")
            progress.set_status("❌ セッションエラー", is_error=True)
            my_lib.notify.slack.error(
                config.slack,
                "メルカリセッションエラー",
                traceback.format_exc(),
            )
            return -1

    return -1  # ここには到達しないはずだが、型チェックのため


def _execute_once(
    config: AppConfig,
    profile: ProfileConfig,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: ProgressObserver,
    browser_manager: my_lib.browser_manager.BrowserManager,
) -> int:
    """メルカリ値下げ処理の1回分の実行。"""
    progress.set_status(f"🤖 ブラウザを起動中... ({profile.name})")

    try:
        driver, wait = browser_manager.get_driver()
    except Exception:
        logging.exception("ブラウザの起動に失敗しました")
        progress.set_status("❌ ブラウザ起動エラー", is_error=True)
        raise

    # NOTE: execute_item に profile を渡すためのラッパー
    def item_handler(
        driver: WebDriver,
        wait: WebDriverWait[Any],
        item: MercariItem,
        debug_mode: bool,
    ) -> None:
        _execute_item(driver, wait, profile, item, debug_mode)

    try:
        progress.set_status(f"🔑 ログイン中... ({profile.name})")

        my_lib.store.mercari.login.execute(
            driver,
            wait,
            profile.mercari,
            profile.line,
            config.slack,
            dump_path,
        )

        progress.set_status(f"📦 出品リスト取得中... ({profile.name})")

        my_lib.store.mercari.scrape.iter_items_on_display(
            driver,
            wait,
            debug_mode,
            [item_handler],
            progress_observer=progress,  # type: ignore[arg-type]
        )

        my_lib.selenium_util.log_memory_usage(driver)

        progress.set_status(f"✅ 完了 ({profile.name})")

        return 0
    except selenium.common.exceptions.InvalidSessionIdException:
        # セッションエラーはリトライのために re-raise する
        logging.warning("セッションエラーが発生しました（ブラウザがクラッシュした可能性があります）")
        raise
    except my_lib.store.mercari.exceptions.LoginError as e:
        logging.exception("ログインに失敗しました: URL: %s", driver.current_url)
        progress.set_status("❌ ログインエラー", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリログインエラー", driver, dump_path, e
        )
        return -1
    except Exception as e:
        logging.exception("エラーが発生しました: URL: %s", driver.current_url)
        progress.set_status("❌ エラー発生", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリ値下げエラー", driver, dump_path, e
        )
        return -1
    finally:
        browser_manager.quit()
