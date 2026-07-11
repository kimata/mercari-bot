#!/usr/bin/env python3
from __future__ import annotations

import logging
import pathlib
import random
import re
import traceback
from typing import TYPE_CHECKING, Any

import my_lib.browser_manager
import my_lib.memory_util
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
import mercari_bot.history
import mercari_bot.logic
import mercari_bot.notify_slack
import mercari_bot.progress
from mercari_bot.config import AppConfig, ProfileConfig
from mercari_bot.history import ItemAction, ItemResult

_MAX_RETRY_COUNT = 1

if TYPE_CHECKING:
    from my_lib.store.mercari.config import MercariItem
    from selenium.webdriver.remote.webdriver import WebDriver

    from mercari_bot.history import HistoryStore
    from mercari_bot.progress import StatusProgressObserver

_WAIT_TIMEOUT_SEC = 15

# NOTE: アイテム単位の処理がこの回数連続で失敗したら中断する。
# 連続失敗はサイト構造の変化（スクレイピング不能）を示唆するため。
_MAX_CONSECUTIVE_ITEM_FAILURES = 2


def _get_current_url_safely(driver: WebDriver) -> str:
    """current_url を取得する。ブラウザが死んでいる場合でも例外を出さない。"""
    try:
        return driver.current_url
    except selenium.common.exceptions.WebDriverException:
        return "(取得失敗)"


def _notify_sold_items(
    config: AppConfig,
    profile: ProfileConfig,
    history_db: HistoryStore,
    seen: dict[str, MercariItem],
) -> None:
    """前回実行時の一覧から消えたアイテムを売却（取り下げ）として通知する"""
    removed = mercari_bot.history.detect_removed_items(
        history_db.get_snapshot(profile.name), set(seen.keys())
    )
    if not removed:
        return

    history_map = {
        item.item_id: history_db.get_price_down_history(profile.name, item.item_id) for item in removed
    }
    message = mercari_bot.history.build_sold_message(removed, history_map)
    logging.info("%s", message)
    my_lib.notify.slack.info(
        config.slack,
        f"メルカリ商品売却検知 ({profile.name})",
        message,
    )


def _get_modified_hour(wait: WebDriverWait[Any]) -> int:
    elem = wait.until(
        EC.presence_of_element_located((By.XPATH, '//div[@id="item-info"]//p[@color="secondary"]'))
    )
    return mercari_bot.logic.parse_modified_hour(elem.text)


def _execute_item(
    driver: WebDriver,
    wait: WebDriverWait[Any],
    profile: ProfileConfig,
    item: MercariItem,
    debug_mode: bool,
    dump_path: pathlib.Path,
) -> ItemResult:
    # NOTE: 公開停止中 (is_stop != 0) のアイテムは my_lib 側で詳細ページへの遷移前に
    # スキップされるため、ここには公開中のアイテムのみが渡ってくる。

    # NOTE: 「オークションで注目を集めませんか」ポップアップが表示される場合は閉じる
    my_lib.store.mercari.scrape.close_popup(driver)

    modified_hour = _get_modified_hour(wait)

    if modified_hour < profile.interval.hour:
        logging.info("更新してから %d 時間しか経過していないため、スキップします。", modified_hour)
        return ItemResult(ItemAction.SKIP_RECENT, item.price)

    my_lib.selenium_util.click_xpath(driver, '//a[@data-testid="checkout-link"]')

    wait.until(EC.title_contains("商品の情報を編集"))

    if my_lib.selenium_util.xpath_exists(driver, '//button[contains(text(), "タイムセールを終了する")]'):
        logging.info("タイムセール中のため、スキップします。")
        return ItemResult(ItemAction.SKIP_TIME_SALE, item.price)

    # NOTE: ページタイトル変更後、販売形式のラジオボタンがレンダリングされるまで待機
    wait.until(EC.presence_of_element_located((By.XPATH, '//input[@data-testid="auction-price-option"]')))

    if my_lib.selenium_util.xpath_exists(driver, '//input[@data-testid="auction-price-option"][@checked]'):
        logging.info("オークション形式のため、スキップします。")
        return ItemResult(ItemAction.SKIP_AUCTION, item.price)

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
        return ItemResult(ItemAction.SKIP_NO_DISCOUNT, item.price)

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

    # NOTE: edit-button のクリックで送信は確定している。以降のタイムアウトを
    # そのまま伝播させると my_lib のリトライで再実行され、更新直後のため
    # interval 判定でスキップ → 検証されないまま正常終了に化けてしまう。
    # そのため、リトライ対象外の専用例外に変換する。
    try:
        my_lib.selenium_util.random_sleep(1)
        # NOTE: 「出品情報の確認」ポップアップが表示される場合がある
        my_lib.selenium_util.click_xpath(
            driver, '//button[contains(text(), "このまま変更を確定する")]', is_warn=False
        )
        my_lib.selenium_util.click_xpath(
            driver, '//button[contains(text(), "このまま出品する")]', is_warn=False
        )

        # NOTE: オークション促進などのダイアログが表示される場合は閉じる
        my_lib.store.mercari.scrape.close_popup(driver)

        # NOTE: 変更後にページ遷移しない場合、アイテム詳細ページに直接遷移する
        my_lib.selenium_util.random_sleep(3)
        if "/sell/edit/" in driver.current_url:
            logging.warning("変更後のページ遷移が発生しませんでした: %s", driver.current_url)
            # NOTE: 編集ページの状態を保存して原因調査を可能にする (一時的なデバッグコード)
            my_lib.selenium_util.dump_page(driver, random.randint(0, 99), dump_path)  # noqa: S311
            item_url = edit_url.replace("/sell/edit/", "/item/")
            driver.get(item_url)

        wait.until(EC.text_to_be_present_in_element((By.XPATH, "//h1"), re.sub(" +", " ", item.name)))
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
    except selenium.common.exceptions.TimeoutException as e:
        raise mercari_bot.exceptions.PriceVerificationTimeoutError(item.name) from e

    if new_total_price != (new_price + shipping_fee):
        raise mercari_bot.exceptions.PriceVerificationError(
            expected=new_price + shipping_fee, actual=new_total_price
        )

    logging.info("価格を変更しました。(%s円 -> %s円)", f"{item.price:,}", f"{new_total_price:,}")

    return ItemResult(ItemAction.PRICE_DOWN, item.price, new_total_price)


def execute(
    config: AppConfig,
    profile: ProfileConfig,
    debug_mode: bool,
    progress: StatusProgressObserver | None = None,
    clear_profile_on_browser_error: bool = False,
) -> bool:
    """メルカリ値下げ処理を実行する。成功したら True を返す。

    セッションエラー（ブラウザクラッシュ等）が発生した場合、
    clear_profile_on_browser_error=True であればプロファイルを削除してリトライする。
    """
    if progress is None:
        progress = mercari_bot.progress.NullProgressDisplay()

    # NOTE: デバッグモードでは 1 アイテムしか走査されず、記録するとスナップショットが
    # 不完全になり売却の誤検知につながるため、何もしない実装を使う
    history_db: HistoryStore = (
        mercari_bot.history.NullHistoryDb()
        if debug_mode
        else mercari_bot.history.HistoryDb(config.data.history)
    )

    browser_manager = my_lib.browser_manager.BrowserManager(
        profile_name=profile.name,
        data_dir=config.data.selenium,
        wait_timeout=_WAIT_TIMEOUT_SEC,
        clear_profile_on_error=clear_profile_on_browser_error,
    )

    for attempt in range(_MAX_RETRY_COUNT + 1):
        try:
            return _execute_once(
                config, profile, config.data.dump, debug_mode, progress, browser_manager, history_db
            )
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
                    data_dir=config.data.selenium,
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
            return False

    return False  # ここには到達しないはずだが、型チェックのため


def _execute_once(
    config: AppConfig,
    profile: ProfileConfig,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: StatusProgressObserver,
    browser_manager: my_lib.browser_manager.BrowserManager,
    history_db: HistoryStore,
) -> bool:
    """メルカリ値下げ処理の1回分の実行。成功したら True を返す。"""
    progress.set_status(f"🤖 ブラウザを起動中... ({profile.name})")

    try:
        driver, wait = browser_manager.get_driver()
    except Exception:
        # NOTE: 例外を伝播させると Slack 通知も後続プロファイルの処理も行われないため、
        # ここで通知してエラー終了扱いにする。
        logging.exception("ブラウザの起動に失敗しました")
        progress.set_status("❌ ブラウザ起動エラー", is_error=True)
        my_lib.notify.slack.error(
            config.slack,
            "メルカリブラウザ起動エラー",
            traceback.format_exc(),
        )
        return False

    price_verification_failed = False

    # NOTE: execute_item に profile を渡すためのラッパー
    def item_handler(
        driver: WebDriver,
        wait: WebDriverWait[Any],
        item: MercariItem,
        debug_mode: bool,
    ) -> None:
        nonlocal price_verification_failed
        try:
            result = _execute_item(driver, wait, profile, item, debug_mode, dump_path)
        except mercari_bot.exceptions.PostSubmitError as e:
            # NOTE: 送信後のエラー（検証失敗・検証タイムアウト）を再試行させると、
            # 直前の送信で商品の更新時間がリセットされているため interval 判定で
            # スキップされ、正常終了に化けてしまう。
            # ここで通知してアイテムを終了扱いにし、プロファイルの結果を失敗にする。
            price_verification_failed = True
            logging.exception("価格検証に失敗しました: %s", item.name)
            mercari_bot.notify_slack.dump_and_notify_error(
                config.slack, "メルカリ価格検証エラー", driver, dump_path, e
            )
            result = ItemResult(ItemAction.FAILED, item.price)

        history_db.add_record(profile.name, item, result)

    # NOTE: 売却検知用に、出品一覧に出現した全アイテム（公開停止中を含む）を記録する
    recorder = mercari_bot.progress.ItemRecordingObserver(inner=progress)

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
            progress_observer=recorder,
            max_consecutive_failures=_MAX_CONSECUTIVE_ITEM_FAILURES,
        )

        # NOTE: 途中で中断されるとスナップショットが不完全になり売却を誤検知するため、
        # 一覧を最後まで走査できた場合のみ売却検知とスナップショット更新を行う
        if not debug_mode:
            _notify_sold_items(config, profile, history_db, recorder.seen)
            history_db.replace_snapshot(profile.name, recorder.seen.values())

        memory_bytes = my_lib.memory_util.read_selenium_memory_bytes()
        if memory_bytes is not None:
            logging.info("Chrome memory (PSS): %s MB", f"{memory_bytes // (1024 * 1024):,}")

        if price_verification_failed:
            progress.set_status(f"⚠️ 完了（価格検証エラーあり） ({profile.name})", is_error=True)
            return False

        progress.set_status(f"✅ 完了 ({profile.name})")

        return True
    except selenium.common.exceptions.InvalidSessionIdException:
        # セッションエラーはリトライのために re-raise する
        logging.warning("セッションエラーが発生しました（ブラウザがクラッシュした可能性があります）")
        raise
    except my_lib.store.mercari.exceptions.LoginError as e:
        logging.exception("ログインに失敗しました: URL: %s", _get_current_url_safely(driver))
        progress.set_status("❌ ログインエラー", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリログインエラー", driver, dump_path, e
        )
        return False
    except Exception as e:
        logging.exception("エラーが発生しました: URL: %s", _get_current_url_safely(driver))
        progress.set_status("❌ エラー発生", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリ値下げエラー", driver, dump_path, e
        )
        return False
    finally:
        browser_manager.quit()
