#!/usr/bin/env python3
# ruff: noqa: S101
"""
設定パースのテスト
"""
import unittest.mock

import pytest

from mercari_bot.config import (
    AppConfig,
    DataConfig,
    DiscountConfig,
    IntervalConfig,
    ProfileConfig,
    _parse_data,
    _parse_discount,
    _parse_interval,
    _parse_profile,
    load,
)
from my_lib.notify.slack import SlackEmptyConfig


class TestDiscountConfig:
    """DiscountConfig のテスト"""

    def test_parse(self):
        """辞書からパース"""
        data = {"favorite_count": 10, "step": 200, "threshold": 3000}
        config = _parse_discount(data)
        assert config.favorite_count == 10
        assert config.step == 200
        assert config.threshold == 3000

    def test_frozen(self):
        """frozen dataclass（変更不可）"""
        config = DiscountConfig(favorite_count=5, step=100, threshold=1000)
        with pytest.raises(AttributeError):
            config.favorite_count = 10  # type: ignore[misc]

    def test_missing_key_raises_error(self):
        """必須キーが欠けているとエラー"""
        data = {"favorite_count": 10, "step": 200}  # threshold が欠けている
        with pytest.raises(KeyError):
            _parse_discount(data)

    def test_various_values(self):
        """様々な値の組み合わせ"""
        test_cases = [
            {"favorite_count": 0, "step": 50, "threshold": 500},
            {"favorite_count": 100, "step": 1000, "threshold": 10000},
            {"favorite_count": 1, "step": 10, "threshold": 100},
        ]
        for data in test_cases:
            config = _parse_discount(data)
            assert config.favorite_count == data["favorite_count"]
            assert config.step == data["step"]
            assert config.threshold == data["threshold"]


class TestIntervalConfig:
    """IntervalConfig のテスト"""

    def test_parse(self):
        """辞書からパース"""
        data = {"hour": 24}
        config = _parse_interval(data)
        assert config.hour == 24

    def test_frozen(self):
        """frozen dataclass（変更不可）"""
        config = IntervalConfig(hour=12)
        with pytest.raises(AttributeError):
            config.hour = 24  # type: ignore[misc]

    def test_missing_key_raises_error(self):
        """必須キーが欠けているとエラー"""
        data = {}  # hour が欠けている
        with pytest.raises(KeyError):
            _parse_interval(data)


class TestDataConfig:
    """DataConfig のテスト"""

    def test_parse(self):
        """辞書からパース"""
        data = {"selenium": "data/selenium", "dump": "data/dump"}
        config = _parse_data(data)
        assert config.selenium == "data/selenium"
        assert config.dump == "data/dump"

    def test_frozen(self):
        """frozen dataclass（変更不可）"""
        config = DataConfig(selenium="/path/selenium", dump="/path/dump")
        with pytest.raises(AttributeError):
            config.selenium = "/new/path"  # type: ignore[misc]


class TestProfileConfig:
    """ProfileConfig のテスト"""

    def test_parse(self):
        """辞書からパース"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()

        with (
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ) as mock_mercari_parse,
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ) as mock_line_parse,
        ):
            data = {
                "name": "Test Profile",
                "mercari": {"email": "test@example.com"},
                "line": {"user": "test_user", "pass": "test_pass"},
                "discount": [
                    {"favorite_count": 10, "step": 200, "threshold": 3000},
                    {"favorite_count": 0, "step": 100, "threshold": 1000},
                ],
                "interval": {"hour": 20},
            }
            config = _parse_profile(data)

            assert config.name == "Test Profile"
            assert config.mercari == mock_mercari
            assert config.line == mock_line
            assert len(config.discount) == 2
            assert config.discount[0].favorite_count == 10
            assert config.discount[0].step == 200
            assert config.discount[1].favorite_count == 0
            assert config.interval.hour == 20

            mock_mercari_parse.assert_called_once_with(data)
            mock_line_parse.assert_called_once_with({"user": "test_user", "pass": "test_pass"})

    def test_frozen(self):
        """frozen dataclass（変更不可）"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()
        config = ProfileConfig(
            name="Test",
            mercari=mock_mercari,
            discount=[],
            interval=IntervalConfig(hour=24),
            line=mock_line,
        )
        with pytest.raises(AttributeError):
            config.name = "New Name"  # type: ignore[misc]


class TestAppConfig:
    """AppConfig のテスト"""

    def test_frozen(self):
        """frozen dataclass（変更不可）"""
        config = AppConfig(
            profile=[],
            slack=SlackEmptyConfig(),
            data=DataConfig(selenium="/path", dump="/dump"),
            mail=unittest.mock.MagicMock(),
        )
        with pytest.raises(AttributeError):
            config.profile = []  # type: ignore[misc]


class TestLoad:
    """load 関数のテスト"""

    @pytest.fixture
    def sample_raw_config(self):
        """サンプル生設定データ"""
        return {
            "profile": [
                {
                    "name": "Profile 1",
                    "mercari": {"email": "test@example.com"},
                    "line": {"user": "user", "pass": "pass"},
                    "discount": [
                        {"favorite_count": 0, "step": 100, "threshold": 1000},
                    ],
                    "interval": {"hour": 24},
                }
            ],
            "slack": {},
            "data": {"selenium": "data/selenium", "dump": "data/dump"},
        }

    def test_load_without_slack(self, sample_raw_config):
        """Slack設定なしでロード"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config),
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=SlackEmptyConfig(),
            ),
        ):
            config = load("config.yaml")

            assert isinstance(config, AppConfig)
            assert len(config.profile) == 1
            assert config.profile[0].name == "Profile 1"
            assert isinstance(config.slack, SlackEmptyConfig)
            assert config.data.selenium == "data/selenium"
            assert config.data.dump == "data/dump"

    def test_load_with_slack(self, sample_raw_config):
        """Slack設定ありでロード"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()
        mock_slack = unittest.mock.MagicMock()
        # SlackConfig としてマークするため spec を設定
        from my_lib.notify.slack import SlackConfig

        mock_slack = unittest.mock.MagicMock(spec=SlackConfig)

        sample_raw_config["slack"] = {
            "bot_token": "xoxb-test",
            "info": {"channel": {"name": "#test"}},
            "captcha": {"channel": {"id": "C123", "name": "#captcha"}},
            "error": {"channel": {"id": "C456", "name": "#error"}},
        }

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config),
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=mock_slack,
            ),
        ):
            config = load("config.yaml")

            assert config.slack == mock_slack

    def test_load_with_mail(self, sample_raw_config):
        """メール設定ありでロード"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()
        mock_mail = unittest.mock.MagicMock()

        sample_raw_config["mail"] = {
            "smtp_server": "smtp.example.com",
            "from": "test@example.com",
            "to": ["user@example.com"],
        }

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config),
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=SlackEmptyConfig(),
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_mail_config",
                return_value=mock_mail,
            ),
        ):
            config = load("config.yaml")

            assert config.mail == mock_mail

    def test_load_invalid_slack_config_raises_error(self, sample_raw_config):
        """不正な Slack 設定でエラー"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()
        # SlackConfig でも SlackEmptyConfig でもないオブジェクト
        invalid_slack = "invalid"

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config),
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=invalid_slack,
            ),
            pytest.raises(ValueError, match="Slack 設定には info, captcha, error の全てが必要です"),
        ):
            load("config.yaml")

    def test_load_multiple_profiles(self, sample_raw_config):
        """複数プロファイルのロード"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()

        sample_raw_config["profile"].append({
            "name": "Profile 2",
            "mercari": {"email": "test2@example.com"},
            "line": {"user": "user2", "pass": "pass2"},
            "discount": [
                {"favorite_count": 5, "step": 150, "threshold": 2000},
            ],
            "interval": {"hour": 12},
        })

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config),
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=SlackEmptyConfig(),
            ),
        ):
            config = load("config.yaml")

            assert len(config.profile) == 2
            assert config.profile[0].name == "Profile 1"
            assert config.profile[1].name == "Profile 2"
            assert config.profile[1].interval.hour == 12

    def test_load_with_schema(self, sample_raw_config):
        """スキーマ指定でロード"""
        mock_mercari = unittest.mock.MagicMock()
        mock_line = unittest.mock.MagicMock()

        with (
            unittest.mock.patch("my_lib.config.load", return_value=sample_raw_config) as mock_load,
            unittest.mock.patch(
                "mercari_bot.config.parse_mercari_login", return_value=mock_mercari
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_line_login", return_value=mock_line
            ),
            unittest.mock.patch(
                "mercari_bot.config.parse_slack_config",
                return_value=SlackEmptyConfig(),
            ),
        ):
            load("config.yaml", "config.schema")

            mock_load.assert_called_once_with("config.yaml", "config.schema")
