#!/usr/bin/env python3
"""設定ファイルの型定義"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import my_lib.config
from my_lib.notify.mail import MailConfig, MailEmptyConfig, parse_config as parse_mail_config
from my_lib.notify.slack import (
    SlackConfig,
    SlackEmptyConfig,
    parse_config as parse_slack_config,
)
from my_lib.store.mercari.config import (
    LineLoginConfig,
    MercariLoginConfig,
    parse_line_login,
    parse_mercari_login,
)


@dataclass(frozen=True)
class DiscountConfig:
    """値下げ条件の設定"""

    favorite_count: int
    step: int
    threshold: int


@dataclass(frozen=True)
class IntervalConfig:
    """更新間隔の設定"""

    hour: int


@dataclass(frozen=True)
class ProfileConfig:
    """プロファイル設定"""

    name: str
    mercari: MercariLoginConfig
    discount: list[DiscountConfig]
    interval: IntervalConfig
    line: LineLoginConfig


@dataclass(frozen=True)
class DataConfig:
    """データパス設定"""

    selenium: str
    dump: str


@dataclass(frozen=True)
class AppConfig:
    """アプリケーション設定"""

    profile: list[ProfileConfig]
    slack: SlackConfig | SlackEmptyConfig
    data: DataConfig
    mail: MailConfig | MailEmptyConfig


def _parse_discount(data: dict[str, Any]) -> DiscountConfig:
    return DiscountConfig(
        favorite_count=data["favorite_count"],
        step=data["step"],
        threshold=data["threshold"],
    )


def _parse_interval(data: dict[str, Any]) -> IntervalConfig:
    return IntervalConfig(hour=data["hour"])


def _parse_profile(data: dict[str, Any]) -> ProfileConfig:
    return ProfileConfig(
        name=data["name"],
        mercari=parse_mercari_login(data),
        discount=[_parse_discount(d) for d in data["discount"]],
        interval=_parse_interval(data["interval"]),
        line=parse_line_login(data["line"]),
    )


def _parse_data(data: dict[str, Any]) -> DataConfig:
    return DataConfig(
        selenium=data["selenium"],
        dump=data["dump"],
    )


def load(config_path: str, schema_path: str | None = None) -> AppConfig:
    """設定ファイルを読み込んで AppConfig を返す"""
    raw_config = my_lib.config.load(config_path, schema_path)

    slack_config = parse_slack_config(raw_config["slack"])
    if not isinstance(slack_config, (SlackConfig, SlackEmptyConfig)):
        msg = "Slack 設定には info, captcha, error の全てが必要です（または全て省略）"
        raise ValueError(msg)

    return AppConfig(
        profile=[_parse_profile(p) for p in raw_config["profile"]],
        slack=slack_config,
        data=_parse_data(raw_config["data"]),
        mail=parse_mail_config(raw_config.get("mail", {})),
    )
