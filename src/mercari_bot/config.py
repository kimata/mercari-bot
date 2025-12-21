#!/usr/bin/env python3
"""設定ファイルの型定義"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import my_lib.config


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
class LineConfig:
    """LINE ログイン情報"""

    user: str
    password: str


@dataclass(frozen=True)
class ProfileConfig:
    """プロファイル設定"""

    name: str
    user: str
    password: str
    discount: list[DiscountConfig]
    interval: IntervalConfig
    line: LineConfig


@dataclass(frozen=True)
class SlackChannelConfig:
    """Slack チャンネル設定"""

    name: str
    id: str | None = None  # info チャンネルでは id は不要


@dataclass(frozen=True)
class SlackInfoConfig:
    """Slack 情報通知設定"""

    channel: SlackChannelConfig


@dataclass(frozen=True)
class SlackCaptchaConfig:
    """Slack CAPTCHA 通知設定"""

    channel: SlackChannelConfig


@dataclass(frozen=True)
class SlackErrorConfig:
    """Slack エラー通知設定"""

    channel: SlackChannelConfig
    interval_min: int


@dataclass(frozen=True)
class SlackConfig:
    """Slack 設定"""

    bot_token: str
    from_name: str
    info: SlackInfoConfig
    captcha: SlackCaptchaConfig
    error: SlackErrorConfig


@dataclass(frozen=True)
class DataConfig:
    """データパス設定"""

    selenium: str
    dump: str


@dataclass(frozen=True)
class MailSmtpConfig:
    """SMTP 設定"""

    host: str
    port: int


@dataclass(frozen=True)
class MailConfig:
    """メール設定"""

    smtp: MailSmtpConfig
    user: str
    password: str
    from_address: str
    to: str


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


def _parse_line(data: dict[str, Any]) -> LineConfig:
    return LineConfig(
        user=data["user"],
        password=data["pass"],
    )


def _parse_profile(data: dict[str, Any]) -> ProfileConfig:
    return ProfileConfig(
        name=data["name"],
        user=data["user"],
        password=data["pass"],
        discount=[_parse_discount(d) for d in data["discount"]],
        interval=_parse_interval(data["interval"]),
        line=_parse_line(data["line"]),
    )


def _parse_slack_channel(data: dict[str, Any]) -> SlackChannelConfig:
    return SlackChannelConfig(
        name=data["name"],
        id=data.get("id"),
    )


def _parse_slack_info(data: dict[str, Any]) -> SlackInfoConfig:
    return SlackInfoConfig(channel=_parse_slack_channel(data["channel"]))


def _parse_slack_captcha(data: dict[str, Any]) -> SlackCaptchaConfig:
    return SlackCaptchaConfig(channel=_parse_slack_channel(data["channel"]))


def _parse_slack_error(data: dict[str, Any]) -> SlackErrorConfig:
    return SlackErrorConfig(
        channel=_parse_slack_channel(data["channel"]),
        interval_min=data["interval_min"],
    )


def _parse_slack(data: dict[str, Any]) -> SlackConfig:
    return SlackConfig(
        bot_token=data["bot_token"],
        from_name=data["from"],
        info=_parse_slack_info(data["info"]),
        captcha=_parse_slack_captcha(data["captcha"]),
        error=_parse_slack_error(data["error"]),
    )


def _parse_data(data: dict[str, Any]) -> DataConfig:
    return DataConfig(
        selenium=data["selenium"],
        dump=data["dump"],
    )


def _parse_mail(data: dict[str, Any]) -> MailConfig:
    return MailConfig(
        smtp=MailSmtpConfig(host=data["smtp"]["host"], port=data["smtp"]["port"]),
        user=data["user"],
        password=data["pass"],
        from_address=data["from"],
        to=data["to"],
    )


def load(config_path: str, schema_path: str | None = None) -> AppConfig:
    """設定ファイルを読み込んで AppConfig を返す"""
    raw_config = my_lib.config.load(config_path, schema_path)

    return AppConfig(
        profile=[_parse_profile(p) for p in raw_config["profile"]],
        slack=_parse_slack(raw_config["slack"]),
        data=_parse_data(raw_config["data"]),
        mail=_parse_mail(raw_config["mail"]) if "mail" in raw_config else None,
    )
