#!/usr/bin/env python3
"""メルカリの出品アイテムを巡回して値下げする。

ブラウザ操作は `my_lib.browser.Page` 抽象（Patchright バックエンド、headful）のみに依存する。
Page はプロファイル 1 件の実行ごとに `page()` スコープで開き、with を抜けるとタブごと閉じる。
"""

from __future__ import annotations

import logging
import pathlib
import random
import re
import traceback
from typing import TYPE_CHECKING

import my_lib.browser
import my_lib.browser.helpers
import my_lib.notify.slack
import my_lib.store.mercari.exceptions
import my_lib.store.mercari.login
import my_lib.store.mercari.scrape
from my_lib.browser import Xpath

import mercari_bot.exceptions
import mercari_bot.history
import mercari_bot.logic
import mercari_bot.notify_slack
import mercari_bot.progress
from mercari_bot.config import AppConfig, ProfileConfig
from mercari_bot.history import ItemAction, ItemResult

_MAX_RETRY_COUNT = 1

if TYPE_CHECKING:
    from my_lib.browser import Element, Page
    from my_lib.store.mercari.config import MercariItem

    from mercari_bot.history import HistoryStore
    from mercari_bot.progress import StatusProgressObserver

_WAIT_TIMEOUT_SEC = 15
# NOTE: 待機がタイムアウトしたときにリロードして待ち直す回数
_WAIT_RETRY_COUNT = 1

# NOTE: 商品ページの「商品の編集」リンク。data-testid ではなく編集ページへの href で特定する。
_EDIT_LINK_XPATH = '//a[starts-with(@href, "/sell/edit/")]'
# NOTE: 編集ページの「法令に基づく表示事項を登録しました」同意チェックボックス
_LISTING_ALERT_CONSENT_XPATH = '//input[@data-testid="listing-alert-consent"]'
_MODIFIED_HOUR_XPATH = '//div[@id="item-info"]//p[@color="secondary"]'
_PRICE_INPUT_XPATH = '//input[@name="price"]'
_PRICE_VIEW_XPATH = '//div[@data-testid="price"]'

# NOTE: アイテム単位の処理がこの回数連続で失敗したら中断する。
# 連続失敗はサイト構造の変化（スクレイピング不能）を示唆するため。
_MAX_CONSECUTIVE_ITEM_FAILURES = 2


def _get_current_url_safely(page: Page) -> str:
    """現在の URL を取得する。ブラウザが死んでいる場合でも例外を出さない。"""
    try:
        return page.url
    except Exception:  # NOTE: ブラウザ死亡時はバックエンド固有の例外になるため広く捕捉する
        return "(取得失敗)"


def _find(page: Page, xpath: str) -> Element:
    """要素を 1 つ取得する（無ければ ElementNotFoundError）。"""
    element = page.find(Xpath(xpath))
    if element is None:
        raise my_lib.browser.ElementNotFoundError(f"Element is not found: {xpath}")
    return element


def _click_xpath(page: Page, xpath: str, *, is_warn: bool = True) -> bool:
    """要素が存在すればクリックする。存在しなければ警告（is_warn=True 時）を出して False を返す。"""
    element = page.find(Xpath(xpath))
    if element is None:
        if is_warn:
            logging.warning("Element is not found: %s", xpath)
        return False

    element.click()
    return True


def _wait_present_patiently(page: Page, xpath: str) -> None:
    """要素が現れるまで待つ。タイムアウトしたらリロードして待ち直す。"""
    for i in range(_WAIT_RETRY_COUNT + 1):
        try:
            page.wait_present(Xpath(xpath), timeout=_WAIT_TIMEOUT_SEC)
            return
        except my_lib.browser.WaitTimeoutError:
            if i == _WAIT_RETRY_COUNT:
                raise
            logging.warning("タイムアウトが発生したのでリロードします: %s", xpath)
            page.refresh()


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


def _is_checked(checkbox: Element) -> bool:
    return bool(checkbox.evaluate("(el) => el.checked"))


def _accept_listing_alert(page: Page) -> None:
    """編集ページの「法令に基づく表示事項を登録しました」同意チェックボックスにチェックを入れる

    化粧品カテゴリなどでは、この同意なしに送信するとエラーになり編集が確定しない。
    """
    checkboxes = page.find_all(Xpath(_LISTING_ALERT_CONSENT_XPATH))
    if not checkboxes:
        return

    checkbox = checkboxes[0]
    if _is_checked(checkbox):
        return

    logging.info("法令に基づく表示事項の同意チェックボックスにチェックを入れます。")
    # NOTE: 装飾されたチェックボックスは input 自体が不可視で通常クリックが失敗するため、
    # JavaScript でクリックイベントを発火する
    checkbox.evaluate("(el) => el.click()")

    if not _is_checked(checkbox):
        raise mercari_bot.exceptions.ListingAlertConsentError()


def _get_modified_hour(page: Page) -> int:
    elem = page.wait_present(Xpath(_MODIFIED_HOUR_XPATH), timeout=_WAIT_TIMEOUT_SEC)
    return mercari_bot.logic.parse_modified_hour(elem.text)


def _set_input_value(price_input: Element, value: str) -> None:
    # NOTE: React の controlled input に対して値を確実に反映させるため、
    # nativeInputValueSetter で値を設定してから input イベントを発火する
    price_input.evaluate(
        """
        (input, [value]) => {
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(input, value);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        value,
    )


def _execute_item(
    page: Page,
    profile: ProfileConfig,
    item: MercariItem,
    debug_mode: bool,
    dump_path: pathlib.Path,
) -> ItemResult:
    # NOTE: 公開停止中 (is_stop != 0) のアイテムは my_lib 側で詳細ページへの遷移前に
    # スキップされるため、ここには公開中のアイテムのみが渡ってくる。

    # NOTE: 「オークションで注目を集めませんか」ポップアップが表示される場合は閉じる
    my_lib.store.mercari.scrape.close_popup(page)

    modified_hour = _get_modified_hour(page)

    if modified_hour < profile.interval.hour:
        logging.info("更新してから %d 時間しか経過していないため、スキップします。", modified_hour)
        return ItemResult(ItemAction.SKIP_RECENT, item.price)

    # NOTE: 「商品の編集」ボタンは data-testid が変更されたことがある
    # （checkout-link → checkout-button、2026-09-09）ため、編集ページへの href で特定する
    _click_xpath(page, _EDIT_LINK_XPATH)

    page.wait_until(my_lib.browser.helpers.title_contains_js("商品の情報を編集"), timeout=_WAIT_TIMEOUT_SEC)

    if page.exists(Xpath('//button[contains(text(), "タイムセールを終了する")]'), visible=False):
        logging.info("タイムセール中のため、スキップします。")
        return ItemResult(ItemAction.SKIP_TIME_SALE, item.price)

    # NOTE: ページタイトル変更後、販売形式のラジオボタンがレンダリングされるまで待機
    page.wait_present(Xpath('//input[@data-testid="auction-price-option"]'), timeout=_WAIT_TIMEOUT_SEC)

    if page.exists(Xpath('//input[@data-testid="auction-price-option"][@checked]'), visible=False):
        logging.info("オークション形式のため、スキップします。")
        return ItemResult(ItemAction.SKIP_AUCTION, item.price)

    _click_xpath(page, '//button[contains(text(), "OK")]', is_warn=False)

    page.wait_present(Xpath(_PRICE_INPUT_XPATH), timeout=_WAIT_TIMEOUT_SEC)

    # NOTE: 梱包・発送たのメル便の場合は送料を取得
    if page.find_all(Xpath('//span[@data-testid="shipping-fee"]')):
        shipping_fee = int(
            _find(page, '//span[@data-testid="shipping-fee"]/span[contains(@class, "number")]').text.replace(
                ",", ""
            )
        )
    else:
        shipping_fee = 0

    price = item.price - shipping_fee

    price_input = _find(page, _PRICE_INPUT_XPATH)
    # NOTE: React の controlled input は value 属性ではなくプロパティに現在値を持つ
    value_attr = price_input.evaluate("(el) => el.value")
    if value_attr is None:
        raise mercari_bot.exceptions.PriceRetrievalError("価格の取得に失敗しました")
    cur_price = int(str(value_attr))
    if cur_price != price:
        raise mercari_bot.exceptions.PriceChangedError(expected=price, actual=cur_price)

    discount_step = mercari_bot.logic.get_discount_step(profile, price, shipping_fee, item.favorite)
    if discount_step is None:
        return ItemResult(ItemAction.SKIP_NO_DISCOUNT, item.price)

    new_price = price if debug_mode else mercari_bot.logic.round_price(price - discount_step)

    _set_input_value(price_input, str(new_price))
    my_lib.store.mercari.scrape.random_sleep(2)
    _accept_listing_alert(page)
    edit_url = page.url
    _click_xpath(page, '//button[@data-testid="edit-button"]')

    # NOTE: edit-button のクリックで送信は確定している。以降のタイムアウトを
    # そのまま伝播させると my_lib のリトライで再実行され、更新直後のため
    # interval 判定でスキップ → 検証されないまま正常終了に化けてしまう。
    # そのため、リトライ対象外の専用例外に変換する。
    try:
        my_lib.store.mercari.scrape.random_sleep(1)
        # NOTE: 「出品情報の確認」ポップアップが表示される場合がある
        _click_xpath(page, '//button[contains(text(), "このまま変更を確定する")]', is_warn=False)
        _click_xpath(page, '//button[contains(text(), "このまま出品する")]', is_warn=False)

        # NOTE: オークション促進などのダイアログが表示される場合は閉じる
        my_lib.store.mercari.scrape.close_popup(page)

        # NOTE: 変更後にページ遷移しない場合、アイテム詳細ページに直接遷移する
        my_lib.store.mercari.scrape.random_sleep(3)
        if "/sell/edit/" in page.url:
            logging.warning("変更後のページ遷移が発生しませんでした: %s", page.url)
            # NOTE: 編集ページの状態を保存して原因調査を可能にする (一時的なデバッグコード)
            my_lib.browser.helpers.dump_page(page, random.randint(0, 99), dump_path)  # noqa: S311
            item_url = edit_url.replace("/sell/edit/", "/item/")
            page.goto(item_url)

        page.wait_text(Xpath("//h1"), re.sub(" +", " ", item.name), timeout=_WAIT_TIMEOUT_SEC)
        _wait_present_patiently(page, _PRICE_VIEW_XPATH)

        # NOTE: 価格更新が反映されていない場合があるので、再度ページを取得する
        my_lib.store.mercari.scrape.random_sleep(3)
        page.goto(page.url)
        page.wait_present(Xpath(_PRICE_VIEW_XPATH), timeout=_WAIT_TIMEOUT_SEC)

        new_total_price = int(re.sub(",", "", _find(page, f"{_PRICE_VIEW_XPATH}/span[2]").text))
    except my_lib.browser.WaitTimeoutError as e:
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

    セッションエラー（ブラウザクラッシュ等）が発生した場合は 1 回リトライする。
    clear_profile_on_browser_error=True であれば、ブラウザ起動失敗時とリトライ前に
    プロファイルを削除する。
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

    browser_manager = my_lib.browser.BrowserManager(
        my_lib.browser.BrowserProfile(
            name=profile.name,
            data_dir=config.data.selenium,
            # NOTE: メルカリは bot 検出があるため headful（Xvfb 上での実行を想定）
            headless=False,
        ),
    )

    for attempt in range(_MAX_RETRY_COUNT + 1):
        try:
            return _execute_once(
                config,
                profile,
                config.data.dump,
                debug_mode,
                progress,
                browser_manager,
                history_db,
                clear_profile_on_browser_error,
            )
        except my_lib.browser.SessionError:
            if attempt < _MAX_RETRY_COUNT:
                logging.warning(
                    "セッションエラーが発生しました。リトライします (試行 %d/%d)",
                    attempt + 1,
                    _MAX_RETRY_COUNT + 1,
                )
                progress.set_status(f"🔄 セッションエラー、リトライ中... ({profile.name})")
                if clear_profile_on_browser_error:
                    browser_manager.clear_profile()
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
    browser_manager: my_lib.browser.BrowserManager,
    history_db: HistoryStore,
    clear_profile_on_browser_error: bool,
) -> bool:
    """メルカリ値下げ処理の1回分の実行。成功したら True を返す。

    タブは `page()` スコープで開き、処理が終わる（または失敗する）と閉じる。
    ブラウザ自体も 1 回分の実行が終わったら終了する。
    """
    progress.set_status(f"🤖 ブラウザを起動中... ({profile.name})")

    try:
        with browser_manager.page() as page:
            return _execute_with_page(config, profile, dump_path, debug_mode, progress, page, history_db)
    except my_lib.browser.SessionError:
        # セッションエラーはリトライのために re-raise する
        raise
    except my_lib.browser.BrowserError:
        # NOTE: ページ内の処理は _execute_with_page が捕捉するので、ここに来るのはブラウザ起動失敗。
        #       例外を伝播させると Slack 通知も後続プロファイルの処理も行われないため、
        #       ここで通知してエラー終了扱いにする。
        logging.exception("ブラウザの起動に失敗しました")
        progress.set_status("❌ ブラウザ起動エラー", is_error=True)
        my_lib.notify.slack.error(
            config.slack,
            "メルカリブラウザ起動エラー",
            traceback.format_exc(),
        )
        if clear_profile_on_browser_error:
            browser_manager.clear_profile()
        return False
    finally:
        browser_manager.quit()


def _execute_with_page(
    config: AppConfig,
    profile: ProfileConfig,
    dump_path: pathlib.Path,
    debug_mode: bool,
    progress: StatusProgressObserver,
    page: Page,
    history_db: HistoryStore,
) -> bool:
    price_verification_failed = False

    # NOTE: execute_item に profile を渡すためのラッパー
    def item_handler(page: Page, item: MercariItem, debug_mode: bool) -> None:
        nonlocal price_verification_failed
        try:
            result = _execute_item(page, profile, item, debug_mode, dump_path)
        except mercari_bot.exceptions.PostSubmitError as e:
            # NOTE: 送信後のエラー（検証失敗・検証タイムアウト）を再試行させると、
            # 直前の送信で商品の更新時間がリセットされているため interval 判定で
            # スキップされ、正常終了に化けてしまう。
            # ここで通知してアイテムを終了扱いにし、プロファイルの結果を失敗にする。
            price_verification_failed = True
            logging.exception("価格検証に失敗しました: %s", item.name)
            mercari_bot.notify_slack.dump_and_notify_error(
                config.slack, "メルカリ価格検証エラー", page, dump_path, e
            )
            result = ItemResult(ItemAction.FAILED, item.price)

        history_db.add_record(profile.name, item, result)

    # NOTE: 売却検知用に、出品一覧に出現した全アイテム（公開停止中を含む）を記録する
    recorder = mercari_bot.progress.ItemRecordingObserver(inner=progress)

    try:
        progress.set_status(f"🔑 ログイン中... ({profile.name})")

        my_lib.store.mercari.login.execute(
            page,
            profile.mercari,
            profile.line,
            config.slack,
            dump_path,
        )

        progress.set_status(f"📦 出品リスト取得中... ({profile.name})")

        my_lib.store.mercari.scrape.iter_items_on_display(
            page,
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

        if price_verification_failed:
            progress.set_status(f"⚠️ 完了（価格検証エラーあり） ({profile.name})", is_error=True)
            return False

        progress.set_status(f"✅ 完了 ({profile.name})")

        return True
    except my_lib.browser.SessionError:
        # セッションエラーはリトライのために re-raise する
        logging.warning("セッションエラーが発生しました（ブラウザがクラッシュした可能性があります）")
        raise
    except my_lib.store.mercari.exceptions.LoginError as e:
        logging.exception("ログインに失敗しました: URL: %s", _get_current_url_safely(page))
        progress.set_status("❌ ログインエラー", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリログインエラー", page, dump_path, e
        )
        return False
    except Exception as e:
        logging.exception("エラーが発生しました: URL: %s", _get_current_url_safely(page))
        progress.set_status("❌ エラー発生", is_error=True)
        mercari_bot.notify_slack.dump_and_notify_error(
            config.slack, "メルカリ値下げエラー", page, dump_path, e
        )
        return False
