#!/usr/bin/env python3
from __future__ import annotations

import io
import logging
import logging.handlers
import pathlib
import random
import re
import time
import traceback
from typing import TYPE_CHECKING, Any

import my_lib.notify.slack
import my_lib.selenium_util
import my_lib.store.mercari.login
import my_lib.store.mercari.scrape
import PIL.Image
import selenium.webdriver.support.expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait

from mercari_bot.config import AppConfig, ProfileConfig

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

WAIT_TIMEOUT_SEC = 15


def get_modified_hour(driver: WebDriver) -> int:
    modified_text = driver.find_element(
        By.XPATH,
        '//div[@id="item-info"]//div[contains(@class,"merShowMore")]'
        '/following-sibling::p[contains(@class, "merText")]',
    ).text

    if re.compile(r"秒前").search(modified_text) or re.compile(r"分前").search(modified_text):
        return 0
    elif re.compile(r"時間前").search(modified_text):
        return int("".join(filter(str.isdigit, modified_text)))
    elif re.compile(r"日前").search(modified_text):
        return int("".join(filter(str.isdigit, modified_text))) * 24
    elif re.compile(r"か月前").search(modified_text):
        return int("".join(filter(str.isdigit, modified_text))) * 24 * 30
    elif re.compile(r"半年以上前").search(modified_text):
        return 24 * 30 * 6
    else:
        return -1


def get_discount_step(profile: ProfileConfig, price: int, shipping_fee: int, favorite_count: int) -> int | None:
    for discount_info in sorted(profile.discount, key=lambda x: x.favorite_count, reverse=True):
        if favorite_count >= discount_info.favorite_count:
            if price >= discount_info.threshold:
                return discount_info.step
            else:
                logging.info(
                    "現在価格が%s円 (送料: %s円) のため、スキップします。", f"{price:,}", f"{shipping_fee:,}"
                )

                return None

    logging.info("イイねの数(%d)が条件を満たさなかったので、スキップします。", favorite_count)
    return None


def execute_item(
    driver: WebDriver,
    wait: WebDriverWait,  # type: ignore[type-arg]
    profile: ProfileConfig,
    item: dict[str, Any],
    debug_mode: bool,
) -> None:
    if item["is_stop"] != 0:
        logging.info("公開停止中のため、スキップします。")
        return

    modified_hour = get_modified_hour(driver)

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
        raise RuntimeError("価格の取得に失敗しました。")  # noqa: EM101
    cur_price = int(value_attr)
    if cur_price != price:
        raise RuntimeError("ページ遷移中に価格が変更されました。")  # noqa: EM101

    discount_step = get_discount_step(profile, price, shipping_fee, item["favorite"])
    if discount_step is None:
        return

    new_price = price if debug_mode else int((price - discount_step) / 10) * 10  # 10円単位に丸める

    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(Keys.CONTROL + "a")
    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(Keys.BACK_SPACE)
    driver.find_element(By.XPATH, '//input[@name="price"]').send_keys(str(new_price))
    my_lib.selenium_util.random_sleep(2)
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "変更する")]')

    time.sleep(1)
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


def _build_slack_config_dict(config: AppConfig) -> dict[str, Any]:
    """my_lib.store.mercari.login 用に Slack 設定を辞書形式に変換"""
    return {
        "bot_token": config.slack.bot_token,
        "from": config.slack.from_name,
        "captcha": {
            "channel": {
                "name": config.slack.captcha.channel.name,
                "id": config.slack.captcha.channel.id,
            }
        },
    }


def _build_profile_dict(profile: ProfileConfig) -> dict[str, Any]:
    """my_lib.store.mercari.scrape 用に profile を辞書形式に変換"""
    return {
        "name": profile.name,
        "user": profile.mercari.user,
        "pass": profile.mercari.password,
        "discount": [
            {
                "favorite_count": d.favorite_count,
                "step": d.step,
                "threshold": d.threshold,
            }
            for d in profile.discount
        ],
        "interval": {"hour": profile.interval.hour},
        "line": {"user": profile.line.user, "pass": profile.line.password},
    }


def execute(
    config: AppConfig,
    profile: ProfileConfig,
    data_path: pathlib.Path,
    dump_path: pathlib.Path,
    debug_mode: bool,
) -> int:
    driver = my_lib.selenium_util.create_driver(profile.name, data_path)

    my_lib.selenium_util.clear_cache(driver)

    wait = WebDriverWait(driver, WAIT_TIMEOUT_SEC)

    # NOTE: my_lib の関数は辞書形式を期待するため変換
    slack_config_dict = _build_slack_config_dict(config)
    profile_dict = _build_profile_dict(profile)

    # NOTE: execute_item に profile を渡すためのラッパー
    def item_handler(
        driver: WebDriver,
        wait: WebDriverWait,  # type: ignore[type-arg]
        scrape_config: dict[str, Any],  # noqa: ARG001
        item: dict[str, Any],
        debug_mode: bool,
    ) -> None:
        execute_item(driver, wait, profile, item, debug_mode)

    try:
        my_lib.store.mercari.login.execute(
            driver,
            wait,
            profile.line.user,
            profile.line.password,
            slack_config_dict,
            dump_path,
        )

        my_lib.store.mercari.scrape.iter_items_on_display(
            driver, wait, profile_dict, debug_mode, [item_handler]
        )

        my_lib.selenium_util.log_memory_usage(driver)

        return 0
    except Exception:
        logging.exception("URL: %s", driver.current_url)

        my_lib.selenium_util.dump_page(driver, int(random.random() * 100), dump_path)  # noqa: S311
        my_lib.selenium_util.clean_dump(dump_path)

        my_lib.notify.slack.error_with_image(
            config.slack,
            "メルカリ値下げエラー",
            traceback.format_exc(),
            {
                "data": PIL.Image.open(io.BytesIO(driver.get_screenshot_as_png())),
                "text": "エラー時のスクリーンショット",
            },
        )
        return -1
    finally:
        my_lib.selenium_util.quit_driver_gracefully(driver)
