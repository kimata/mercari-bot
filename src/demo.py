#!/usr/bin/env python3
"""
デモ用スクリプト

実際のメルカリにはアクセスせず、擬似的な処理ログを表示します。
tests/fixtures/mercari_item_titles.json からランダムにアイテムを選択し、
値下げ処理のシミュレーションを行います。

Usage:
  demo.py [-n COUNT]

Options:
  -n COUNT  : 処理するアイテム数 [default: 20]
"""

from __future__ import annotations

import json
import logging
import pathlib
import random
import sys
import time
import unittest.mock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURE_PATH = pathlib.Path(__file__).parent.parent / "tests" / "fixtures" / "mercari_item_titles.json"

# 確率設定
SKIP_MODIFIED_HOUR_RATIO = 0.2  # 更新時間が短いのでスキップ
SKIP_BELOW_THRESHOLD_RATIO = 0.2  # 価格が閾値以下でスキップ

# 実際の time.sleep を保存（モック前に）
_real_time_sleep = time.sleep


def _load_fixture() -> list[str]:
    """フィクスチャファイルからアイテムタイトルを読み込む"""
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["titles"]


def _generate_mock_items(
    titles: list[str],
    count: int,
    threshold: int,
    discount_step: int,
) -> list[dict[str, Any]]:
    """モックアイテムを生成する

    確率分布に基づいてアイテムを生成:
    - 20%: 更新時間スキップ用（modified_hour は後でモックで制御）
    - 20%: 価格が閾値以下（price - step < threshold となる価格）
    - 60%: 価格変更対象（price - step >= threshold となる価格）
    """
    items: list[dict[str, Any]] = []
    selected_titles = random.sample(titles, min(count, len(titles)))

    for _, title in enumerate(selected_titles):
        rand = random.random()
        favorite = random.randint(0, 15)
        view = random.randint(0, 500)

        if rand < SKIP_MODIFIED_HOUR_RATIO + SKIP_BELOW_THRESHOLD_RATIO:
            if rand >= SKIP_MODIFIED_HOUR_RATIO:
                # 20%: 価格が閾値以下になるように設定
                # price - step < threshold となる価格
                price = threshold + discount_step - random.randint(10, 500)
                price = max(300, (price // 10) * 10)  # 最低300円、10円単位
            else:
                # 20%: 更新時間スキップ（価格は普通）
                price = random.randint(threshold + discount_step, 50000)
                price = (price // 10) * 10
        else:
            # 60%: 価格変更対象
            price = random.randint(threshold + discount_step + 100, 50000)
            price = (price // 10) * 10

        items.append(
            {
                "id": f"m{random.randint(10000000000, 99999999999)}",
                "url": f"https://jp.mercari.com/item/m{random.randint(10000000000, 99999999999)}",
                "name": title,
                "price": price,
                "view": view,
                "favorite": favorite,
                "is_stop": 0,
            }
        )

    return items


def _simulate_delay(base_sec: float, variance: float = 0.3) -> None:
    """ランダムな遅延をシミュレートする（実際より短め）"""
    delay = base_sec * (1 + random.uniform(-variance, variance)) * 0.5  # 実際の50%の時間
    _real_time_sleep(delay)


def _create_modified_hour_mock(interval_hour: int) -> Callable[..., int]:
    """_get_modified_hour のモックを作成"""

    def mock_get_modified_hour(driver: Any) -> int:
        if random.random() < SKIP_MODIFIED_HOUR_RATIO:
            # 20%: 更新時間が短い（スキップ対象）
            return random.randint(1, interval_hour - 1)
        else:
            # 80%: 更新時間が十分（処理対象）
            return random.randint(interval_hour, 72)

    return mock_get_modified_hour


def _create_mock_driver() -> unittest.mock.MagicMock:
    """モックドライバを作成"""
    driver = unittest.mock.MagicMock()

    # find_elements が空リストを返す（送料なし）
    driver.find_elements.return_value = []

    # find_element の設定
    mock_element = unittest.mock.MagicMock()
    driver.find_element.return_value = mock_element

    return driver


def execute(item_count: int = 20) -> int:
    """デモを実行する"""
    from my_lib.notify.slack import SlackEmptyConfig
    from my_lib.store.mercari.config import LineLoginConfig, MercariLoginConfig

    import app
    from mercari_bot.config import (
        AppConfig,
        DataConfig,
        DiscountConfig,
        IntervalConfig,
        ProfileConfig,
    )

    # 設定値
    interval_hour = 20
    threshold = 3000
    discount_step = 100

    # フィクスチャからアイテムを生成
    titles = _load_fixture()
    items = _generate_mock_items(titles, item_count, threshold, discount_step)

    # モック設定を作成
    mock_config = AppConfig(
        profile=[
            ProfileConfig(
                name="Demo Profile",
                mercari=MercariLoginConfig(user="demo@example.com", password="dummy"),
                line=LineLoginConfig(user="demo", password="dummy"),
                discount=[
                    DiscountConfig(favorite_count=10, step=200, threshold=threshold),
                    DiscountConfig(favorite_count=0, step=discount_step, threshold=threshold),
                ],
                interval=IntervalConfig(hour=interval_hour),
            )
        ],
        slack=SlackEmptyConfig(),
        data=DataConfig(selenium="/tmp/demo-selenium", dump="/tmp/demo-dump"),
        mail=unittest.mock.MagicMock(),
    )

    # モックドライバ
    mock_driver = _create_mock_driver()

    # 価格追跡用の状態
    price_state: dict[str, int] = {"current": 10000, "new": 10000, "updated": False}

    # 価格入力フィールドの値を動的に設定
    def get_price_attribute(name: str) -> str | None:
        if name == "value":
            return str(price_state["current"])
        return None

    # send_keys で価格更新を検知
    def mock_send_keys(keys: Any) -> None:
        # 数字が入力されたら価格更新とみなす
        if isinstance(keys, str) and keys.isdigit():
            price_state["new"] = int(keys)
            price_state["updated"] = True
            # 価格入力時のウェイト
            _simulate_delay(0.8)
            # 更新ボタンクリック後のページ反映を待機
            _simulate_delay(1.5)

    # find_element が返す要素のモック
    def mock_find_element(by: Any, value: str) -> unittest.mock.MagicMock:
        element = unittest.mock.MagicMock()
        if "price" in value:
            element.get_attribute = get_price_attribute
            element.send_keys = mock_send_keys
            # 価格表示用 - 更新後は新価格を返す
            if price_state["updated"]:
                element.text = str(price_state["new"])
            else:
                element.text = str(price_state["current"])
        else:
            element.text = "0"
        return element

    mock_driver.find_element = mock_find_element

    # iter_items のモックで現在のアイテム価格を追跡
    # scrape.py の iter_items_on_display と同じログを出力する
    def tracking_mock_iter(
        driver: Any,
        wait: Any,
        debug_mode: bool,
        handlers: list[Callable[..., None]],
        progress_observer: Any = None,
    ) -> None:
        item_count = len(items)

        # scrape.py:74 と同じログ
        logging.info("%d 個の出品があります。", item_count)

        if progress_observer is not None:
            progress_observer.on_total_count(item_count)

        for i, item in enumerate(items):
            index = i + 1  # scrape.py は 1-indexed

            # scrape.py:158-167 (_execute_item) と同じログ
            logging.info(
                "[%d/%d] %s [%s] [%s円] [%s view] [%s favorite] を処理します。",
                index,
                item_count,
                item["name"],
                item["id"],
                f"{item['price']:,}",
                f"{item['view']:,}",
                f"{item['favorite']:,}",
            )

            if progress_observer is not None:
                progress_observer.on_item_start(index, item_count, item)

            # アイテムページへの遷移をシミュレート
            _simulate_delay(1.5)

            # 現在の価格を記録し、状態をリセット
            price_state["current"] = item["price"]
            price_state["new"] = item["price"]
            price_state["updated"] = False

            for handler in handlers:
                handler(driver, wait, item, debug_mode)

            if progress_observer is not None:
                progress_observer.on_item_complete(index, item_count, item)

            # 出品リストに戻る遷移をシミュレート
            _simulate_delay(1.0)

    # WebDriverWait のモック
    mock_wait_class = unittest.mock.MagicMock()
    mock_wait_instance = unittest.mock.MagicMock()
    mock_wait_instance.until = unittest.mock.MagicMock(return_value=True)
    mock_wait_class.return_value = mock_wait_instance

    # Selenium 関連をすべてモック
    with (
        unittest.mock.patch("my_lib.selenium_util.create_driver", return_value=mock_driver),
        unittest.mock.patch("my_lib.selenium_util.clear_cache"),
        unittest.mock.patch("my_lib.store.mercari.login.execute") as mock_login,
        unittest.mock.patch(
            "my_lib.store.mercari.scrape.iter_items_on_display",
            side_effect=tracking_mock_iter,
        ),
        unittest.mock.patch("my_lib.selenium_util.log_memory_usage"),
        unittest.mock.patch("my_lib.selenium_util.quit_driver_gracefully"),
        # WebDriverWait をモック
        unittest.mock.patch(
            "mercari_bot.mercari_price_down.WebDriverWait",
            mock_wait_class,
        ),
        # _execute_item 内で使用される関数のモック
        unittest.mock.patch(
            "mercari_bot.mercari_price_down._get_modified_hour",
            side_effect=_create_modified_hour_mock(interval_hour),
        ),
        unittest.mock.patch(
            "my_lib.selenium_util.click_xpath",
            side_effect=lambda *args, **kwargs: _simulate_delay(0.5),
        ),
        unittest.mock.patch("my_lib.selenium_util.xpath_exists", return_value=False),
        unittest.mock.patch(
            "my_lib.selenium_util.random_sleep",
            side_effect=lambda sec: _simulate_delay(sec * 0.3),
        ),
        unittest.mock.patch("my_lib.selenium_util.wait_patiently"),
        unittest.mock.patch("my_lib.selenium_util.dump_page"),
        # 通知関連のモック（エラー時のスクリーンショット対策）
        unittest.mock.patch("mercari_bot.notify_slack.error_with_screenshot"),
        unittest.mock.patch("mercari_bot.notify_slack.error_with_traceback"),
        unittest.mock.patch("mercari_bot.notify_slack.dump_and_notify_error"),
        unittest.mock.patch(
            "time.sleep",
            side_effect=lambda sec: _simulate_delay(sec * 0.3),
        ),
    ):
        # ログインのモック（遅延をシミュレート）
        def mock_login_func(*args: Any, **kwargs: Any) -> None:
            _simulate_delay(2.0)

        mock_login.side_effect = mock_login_func

        # 実行
        ret_code = app.execute(mock_config, notify_log=False, debug_mode=False, log_str_io=None)

    return ret_code


if __name__ == "__main__":
    import docopt
    import my_lib.logger

    assert __doc__ is not None
    args = docopt.docopt(__doc__)

    item_count = int(args["-n"]) if args["-n"] else 20

    # app.py と同じロギング設定を使用
    # TTY 環境では SIMPLE_FORMAT を使用して Rich Live と干渉しないようにする
    log_format = my_lib.logger.SIMPLE_FORMAT if sys.stdout.isatty() else None

    my_lib.logger.init("demo.mercari", level=logging.INFO, log_format=log_format)

    ret_code = execute(item_count)
    sys.exit(ret_code)
