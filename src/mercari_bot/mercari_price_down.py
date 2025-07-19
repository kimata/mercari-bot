#!/usr/bin/env python3
import io
import logging
import logging.handlers
import random
import re
import time
import traceback

import my_lib.notify.slack
import my_lib.selenium_util
import my_lib.store.mercari.login
import my_lib.store.mercari.scrape
import PIL.Image
import selenium.webdriver.common.by
import selenium.webdriver.common.keys
import selenium.webdriver.support
import selenium.webdriver.support.wait

WAIT_TIMEOUT_SEC = 15


def get_modified_hour(driver):
    modified_text = driver.find_element(
        selenium.webdriver.common.by.By.XPATH,
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


def get_discount_step(scrape_config, price, shipping_fee, favorite_count):
    for discount_info in sorted(scrape_config["discount"], key=lambda x: x["favorite_count"], reverse=True):
        if favorite_count >= discount_info["favorite_count"]:
            if price >= discount_info["threshold"]:
                return discount_info["step"]
            else:
                logging.info(
                    "現在価格が%s円 (送料: %s円) のため、スキップします。", f"{price:,}", f"{shipping_fee:,}"
                )

                return None

    logging.info("イイねの数(%d)が条件を満たさなかったので、スキップします。", favorite_count)
    return None


def execute_item(driver, wait, scrape_config, item, debug_mode):
    if item["is_stop"] != 0:
        logging.info("公開停止中のため、スキップします。")
        return

    modified_hour = get_modified_hour(driver)

    if modified_hour < scrape_config["interval"]["hour"]:
        logging.info("更新してから %d 時間しか経過していないため、スキップします。", modified_hour)
        return

    my_lib.selenium_util.click_xpath(
        driver, '//span[contains(text(), "閉じる")]/following-sibling::button', is_warn=False
    )

    my_lib.selenium_util.click_xpath(driver, '//a[@data-testid="checkout-link"]')

    if my_lib.selenium_util.xpath_exists(driver, '//button[contains(text(), "タイムセールを終了する")]'):
        logging.info("タイムセール中のため、スキップします。")
        return

    wait.until(selenium.webdriver.support.expected_conditions.title_contains("商品の情報を編集"))

    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "OK")]', is_warn=False)

    wait.until(
        selenium.webdriver.support.expected_conditions.presence_of_element_located(
            (selenium.webdriver.common.by.By.XPATH, '//input[@name="price"]')
        )
    )

    # NOTE: 梱包・発送たのメル便の場合は送料を取得
    if (
        len(
            driver.find_elements(
                selenium.webdriver.common.by.By.XPATH,
                '//span[@data-testid="shipping-fee"]',
            )
        )
        != 0
    ):
        shipping_fee = int(
            driver.find_element(
                selenium.webdriver.common.by.XPATH,
                '//span[@data-testid="shipping-fee"]/span[contains(@class, "number")]',
            ).text.replace(",", "")
        )
    else:
        shipping_fee = 0

    price = item["price"] - shipping_fee

    cur_price = int(
        driver.find_element(selenium.webdriver.common.by.By.XPATH, '//input[@name="price"]').get_attribute(
            "value"
        )
    )
    if cur_price != price:
        raise RuntimeError("ページ遷移中に価格が変更されました。")  # noqa: EM101

    discount_step = get_discount_step(scrape_config, price, shipping_fee, item["favorite"])
    if discount_step is None:
        return

    new_price = price if debug_mode else int((price - discount_step) / 10) * 10  # 10円単位に丸める

    driver.find_element(selenium.webdriver.common.by.By.XPATH, '//input[@name="price"]').send_keys(
        selenium.webdriver.common.keys.Keys.CONTROL + "a"
    )
    driver.find_element(selenium.webdriver.common.by.By.XPATH, '//input[@name="price"]').send_keys(
        selenium.webdriver.common.keys.Keys.BACK_SPACE
    )
    driver.find_element(selenium.webdriver.common.by.By.XPATH, '//input[@name="price"]').send_keys(new_price)
    my_lib.selenium_util.random_sleep(2)
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "変更する")]')

    time.sleep(1)
    my_lib.selenium_util.click_xpath(driver, '//button[contains(text(), "このまま出品する")]', is_warn=False)

    my_lib.selenium_util.wait_patiently(
        driver,
        wait,
        selenium.webdriver.support.expected_conditions.title_contains(re.sub(" +", " ", item["name"])),
    )
    my_lib.selenium_util.wait_patiently(
        driver,
        wait,
        selenium.webdriver.support.expected_conditions.presence_of_element_located(
            (selenium.webdriver.common.by.By.XPATH, '//div[@data-testid="price"]')
        ),
    )

    # NOTE: 価格更新が反映されていない場合があるので、再度ページを取得する
    time.sleep(3)
    driver.get(driver.current_url)
    wait.until(
        selenium.webdriver.support.expected_conditions.presence_of_element_located(
            (selenium.webdriver.common.by.By.XPATH, '//div[@data-testid="price"]')
        )
    )

    new_total_price = int(
        re.sub(
            ",",
            "",
            driver.find_element(
                selenium.webdriver.common.by.By.XPATH,
                '//div[@data-testid="price"]/span[2]',
            ).text,
        )
    )

    if new_total_price != (new_price + shipping_fee):
        error_message = (
            f"編集後の価格が意図したものと異なっています。"
            f"(期待値: {new_price + shipping_fee:,}円, 実際: {new_total_price:,}円)"
        )
        raise RuntimeError(error_message)

    logging.info("価格を変更しました。(%s円 -> %s円)", f"{item['price']:,}", f"{new_total_price:,}")


def execute(config, profile, data_path, dump_path, debug_mode):
    driver = my_lib.selenium_util.create_driver(profile["name"], data_path)

    my_lib.selenium_util.clear_cache(driver)

    wait = selenium.webdriver.support.wait.WebDriverWait(driver, WAIT_TIMEOUT_SEC)

    try:
        my_lib.store.mercari.login.execute(
            driver,
            wait,
            profile["line"]["user"],
            profile["line"]["pass"],
            config["slack"],
            dump_path,
        )

        my_lib.store.mercari.scrape.iter_items_on_display(driver, wait, profile, debug_mode, [execute_item])

        my_lib.selenium_util.log_memory_usage(driver)

        return 0
    except Exception:
        logging.exception("URL: %s", driver.current_url)

        my_lib.selenium_util.dump_page(driver, int(random.random() * 100), dump_path)  # noqa: S311
        my_lib.selenium_util.clean_dump(dump_path)

        if "slack" in config:
            my_lib.notify.slack.error_with_image(
                config["slack"]["bot_token"],
                config["slack"]["error"]["channel"]["name"],
                config["slack"]["error"]["channel"]["id"],
                config["slack"]["from"],
                traceback.format_exc(),
                {
                    "data": PIL.Image.open(io.BytesIO(driver.get_screenshot_as_png())),
                    "text": "エラー時のスクリーンショット",
                },
                interval_min=config["slack"]["error"]["interval_min"],
            )
        return -1
    finally:
        driver.close()
        driver.quit()
