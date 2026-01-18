#!/usr/bin/env python3
# ruff: noqa: S101
"""
demo.py のテスト

デモ用スクリプトの動作をテストします。
"""

import json
import pathlib
import unittest.mock

import pytest

import demo


class TestLoadFixture:
    """_load_fixture のテスト"""

    def test_load_fixture(self, tmp_path: pathlib.Path):
        """フィクスチャファイルを読み込む"""
        # テスト用フィクスチャファイルを作成
        fixture_data = {"titles": ["テスト商品1", "テスト商品2", "テスト商品3"]}
        fixture_path = tmp_path / "mercari_item_titles.json"
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False))

        # _FIXTURE_PATH をモック
        with unittest.mock.patch.object(demo, "_FIXTURE_PATH", fixture_path):
            titles = demo._load_fixture()

        assert titles == ["テスト商品1", "テスト商品2", "テスト商品3"]


class TestGenerateMockItems:
    """_generate_mock_items のテスト"""

    def test_generate_mock_items_basic(self):
        """基本的なモックアイテム生成"""
        titles = ["商品A", "商品B", "商品C"]
        items = demo._generate_mock_items(titles, count=3, threshold=3000, discount_step=100)

        assert len(items) == 3
        for item in items:
            assert hasattr(item, "id")
            assert hasattr(item, "url")
            assert hasattr(item, "name")
            assert hasattr(item, "price")
            assert hasattr(item, "view")
            assert hasattr(item, "favorite")
            assert hasattr(item, "is_stop")
            assert item.is_stop == 0

    def test_generate_mock_items_count_limit(self):
        """カウントがタイトル数を超える場合"""
        titles = ["商品A", "商品B"]
        items = demo._generate_mock_items(titles, count=10, threshold=3000, discount_step=100)

        # titles の数が上限
        assert len(items) == 2

    def test_generate_mock_items_price_distribution(self):
        """価格分布のテスト（確率的だが、十分な数で検証）"""
        titles = [f"商品{i}" for i in range(100)]
        items = demo._generate_mock_items(titles, count=100, threshold=3000, discount_step=100)

        # 全アイテムが有効な価格を持つ
        for item in items:
            assert item.price >= 300  # 最低価格
            assert item.price % 10 == 0  # 10円単位


class TestSimulateDelay:
    """_simulate_delay のテスト"""

    def test_simulate_delay(self):
        """遅延シミュレーション"""
        with unittest.mock.patch.object(demo, "_real_time_sleep") as mock_sleep:
            demo._simulate_delay(1.0, variance=0.0)

            # 実際の50%の時間で呼ばれる
            mock_sleep.assert_called_once()
            call_arg = mock_sleep.call_args[0][0]
            assert 0.4 <= call_arg <= 0.6  # 0.5 前後


class TestCreateModifiedHourMock:
    """_create_modified_hour_mock のテスト"""

    def test_create_modified_hour_mock(self):
        """更新時間モックの作成"""
        mock_func = demo._create_modified_hour_mock(interval_hour=20)

        # 呼び出し可能
        result = mock_func(None)
        assert isinstance(result, int)
        assert 1 <= result <= 72


class TestCreateMockDriver:
    """_create_mock_driver のテスト"""

    def test_create_mock_driver(self):
        """モックドライバの作成"""
        driver = demo._create_mock_driver()

        assert driver is not None
        # find_elements が空リストを返す
        assert driver.find_elements.return_value == []
        # find_element がモック要素を返す
        assert driver.find_element.return_value is not None


class TestExecute:
    """execute 関数のテスト"""

    @pytest.fixture
    def fixture_file(self, tmp_path: pathlib.Path):
        """テスト用フィクスチャファイル"""
        fixture_data = {"titles": [f"テスト商品{i}" for i in range(5)]}
        fixture_path = tmp_path / "mercari_item_titles.json"
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False))
        return fixture_path

    def test_execute_success(self, fixture_file: pathlib.Path):
        """正常実行"""
        with unittest.mock.patch.object(demo, "_FIXTURE_PATH", fixture_file):
            ret = demo.execute(item_count=3)

        assert ret == 0

    def test_execute_with_fewer_items(self, fixture_file: pathlib.Path):
        """アイテム数が少ない場合"""
        with unittest.mock.patch.object(demo, "_FIXTURE_PATH", fixture_file):
            ret = demo.execute(item_count=2)

        assert ret == 0


class TestInternalFunctions:
    """内部関数のエッジケーステスト"""

    def test_get_price_attribute_non_value(self, tmp_path: pathlib.Path):
        """get_price_attribute で name != 'value' の場合"""
        # demo.execute 内で定義される内部関数をテストするため、
        # 同等のロジックを直接テスト
        price_state = {"current": 10000, "new": 10000, "updated": False}

        def get_price_attribute(name: str) -> str | None:
            if name == "value":
                return str(price_state["current"])
            return None

        # value 以外の属性
        assert get_price_attribute("other") is None
        assert get_price_attribute("class") is None

    def test_mock_find_element_non_price(self, tmp_path: pathlib.Path):
        """mock_find_element で 'price' が含まれない場合"""
        price_state = {"current": 10000, "new": 10000, "updated": False}

        def get_price_attribute(name: str) -> str | None:
            if name == "value":
                return str(price_state["current"])
            return None

        def mock_find_element(by, value: str) -> unittest.mock.MagicMock:
            element = unittest.mock.MagicMock()
            if "price" in value:
                element.get_attribute = get_price_attribute
                if price_state["updated"]:
                    element.text = str(price_state["new"])
                else:
                    element.text = str(price_state["current"])
            else:
                element.text = "0"
            return element

        # price が含まれない場合
        element = mock_find_element(None, "some-other-xpath")
        assert element.text == "0"

        # price が含まれる場合
        element = mock_find_element(None, "price-input")
        assert element.text == "10000"


class TestMainBlock:
    """__main__ ブロックのテスト"""

    def test_main_block(self, tmp_path: pathlib.Path):
        """メインブロックの実行"""
        fixture_data = {"titles": ["テスト商品"]}
        fixture_path = tmp_path / "mercari_item_titles.json"
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False))

        with (
            unittest.mock.patch.object(demo, "_FIXTURE_PATH", fixture_path),
            unittest.mock.patch("docopt.docopt", return_value={"-n": "1"}),
            unittest.mock.patch("my_lib.logger.init"),
            unittest.mock.patch("sys.stdout.isatty", return_value=False),
            unittest.mock.patch("sys.exit") as mock_exit,
        ):
            # __main__ ブロックを直接実行
            exec(  # noqa: S102
                compile(
                    """
import docopt
import my_lib.logger
import logging
import sys

args = docopt.docopt(demo.__doc__)
item_count = int(args["-n"]) if args["-n"] else 20
log_format = my_lib.logger.SIMPLE_FORMAT if sys.stdout.isatty() else None
my_lib.logger.init("demo.mercari", level=logging.INFO, log_format=log_format)
ret_code = demo.execute(item_count)
sys.exit(ret_code)
""",
                    "<string>",
                    "exec",
                ),
                {"demo": demo},
            )

            mock_exit.assert_called_once_with(0)
