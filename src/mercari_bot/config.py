#!/usr/bin/env python3
"""設定ファイルの型定義"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import my_lib.config
from my_lib.notify.mail import MailConfig, MailSmtpConfig
from my_lib.notify.slack import SlackConfig, parse_slack_config


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
class MercariLoginConfig:
    """メルカリ ログイン情報"""

    user: str
    password: str


@dataclass(frozen=True)
class LineLoginConfig:
    """LINE ログイン情報"""

    user: str
    password: str


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
    slack: SlackConfig
    data: DataConfig
    mail: MailConfig | None = None


def _parse_discount(data: dict[str, Any]) -> DiscountConfig:
    return DiscountConfig(
        favorite_count=data["favorite_count"],
        step=data["step"],
        threshold=data["threshold"],
    )


def _parse_interval(data: dict[str, Any]) -> IntervalConfig:
    return IntervalConfig(hour=data["hour"])


def _parse_mercari_login(data: dict[str, Any]) -> MercariLoginConfig:
    return MercariLoginConfig(
        user=data["user"],
        password=data["pass"],
    )


def _parse_line_login(data: dict[str, Any]) -> LineLoginConfig:
    return LineLoginConfig(
        user=data["user"],
        password=data["pass"],
    )


def _parse_profile(data: dict[str, Any]) -> ProfileConfig:
    return ProfileConfig(
        name=data["name"],
        mercari=_parse_mercari_login(data),
        discount=[_parse_discount(d) for d in data["discount"]],
        interval=_parse_interval(data["interval"]),
        line=_parse_line_login(data["line"]),
    )


def _parse_data(data: dict[str, Any]) -> DataConfig:
    return DataConfig(
        selenium=data["selenium"],
        dump=data["dump"],
    )


def _parse_mail(data: dict[str, Any]) -> MailConfig:
    return MailConfig(
        smtp=MailSmtpConfig(
            host=data["smtp"]["host"],
            port=data["smtp"]["port"],
            user=data["user"],
            password=data["pass"],
        ),
        from_address=data["from"],
        to=data["to"],
    )


def load(config_path: str, schema_path: str | None = None) -> AppConfig:
    """設定ファイルを読み込んで AppConfig を返す"""
    raw_config = my_lib.config.load(config_path, schema_path)

    return AppConfig(
        profile=[_parse_profile(p) for p in raw_config["profile"]],
        slack=parse_slack_config(raw_config["slack"]),
        data=_parse_data(raw_config["data"]),
        mail=_parse_mail(raw_config["mail"]) if "mail" in raw_config else None,
    )
