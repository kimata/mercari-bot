#!/usr/bin/env python3
"""設定ファイルの型定義"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import my_lib.config
from my_lib.notify.mail import MailConfig, MailEmptyConfig
from my_lib.notify.slack import (
    SlackConfig,
    SlackEmptyConfig,
)
from my_lib.store.mercari.config import (
    LineLoginConfig,
    MercariLoginConfig,
)

# メルカリの最低出品価格
_MIN_LISTING_PRICE = 300


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
    discount: list[DiscountConfig]  # favorite_count 降順にソート済み
    interval: IntervalConfig
    line: LineLoginConfig


@dataclass(frozen=True)
class DataConfig:
    """データパス設定"""

    selenium: pathlib.Path
    dump: pathlib.Path
    history: pathlib.Path  # 値下げ履歴 DB (SQLite)


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


def _warn_profile_misconfiguration(profile: ProfileConfig) -> None:
    """運用ミスになりやすい設定を早期に警告する"""
    for discount in profile.discount:
        if discount.threshold < _MIN_LISTING_PRICE:
            logging.warning(
                "プロファイル「%s」: threshold (%d円) がメルカリの最低出品価格 (%d円) 未満です。"
                "値下げ後の価格が %d円 を下回ると価格変更の送信が失敗し続けます。",
                profile.name,
                discount.threshold,
                _MIN_LISTING_PRICE,
                _MIN_LISTING_PRICE,
            )

    if all(discount.favorite_count > 0 for discount in profile.discount):
        logging.warning(
            "プロファイル「%s」: favorite_count: 0 のデフォルト条件がありません。"
            "お気に入り数が条件未満のアイテムはすべてスキップされます。",
            profile.name,
        )


def _parse_profile(data: dict[str, Any]) -> ProfileConfig:
    # NOTE: favorite_count 降順に評価する仕様を設定型のレベルで保証するため、
    # ここでソートして格納する
    discount = sorted(
        (_parse_discount(d) for d in data["discount"]),
        key=lambda d: d.favorite_count,
        reverse=True,
    )
    profile = ProfileConfig(
        name=data["name"],
        mercari=MercariLoginConfig.parse(data),
        discount=discount,
        interval=_parse_interval(data["interval"]),
        line=LineLoginConfig.parse(data["line"]),
    )
    _warn_profile_misconfiguration(profile)
    return profile


def _parse_data(data: dict[str, Any], raw_config: dict[str, Any]) -> DataConfig:
    selenium = my_lib.config.resolve_path(raw_config, data["selenium"])
    return DataConfig(
        selenium=selenium,
        dump=my_lib.config.resolve_path(raw_config, data["dump"]),
        # NOTE: 省略時は selenium データディレクトリ配下（k8s では PVC マウント済み）に置く
        history=(
            my_lib.config.resolve_path(raw_config, data["history"])
            if "history" in data
            else selenium / "history.db"
        ),
    )


def load(config_path: str, schema_path: str | pathlib.Path | None = None) -> AppConfig:
    """設定ファイルを読み込んで AppConfig を返す"""
    raw_config = my_lib.config.load(config_path, schema_path)

    slack_config = SlackConfig.parse(raw_config.get("slack", {}))
    if not isinstance(slack_config, SlackConfig | SlackEmptyConfig):
        msg = "Slack 設定には info, captcha, error の全てが必要です（または全て省略）"
        raise ValueError(msg)

    return AppConfig(
        profile=[_parse_profile(p) for p in raw_config["profile"]],
        slack=slack_config,
        data=_parse_data(raw_config["data"], raw_config),
        mail=MailConfig.parse(raw_config.get("mail", {})),
    )


def log_config_summary(config: AppConfig) -> None:
    """設定内容を人が読みやすい形でログ出力する"""
    for profile in config.profile:
        logging.info("=" * 50)
        logging.info("プロファイル「%s」の値下げ設定:", profile.name)
        logging.info("-" * 50)

        # 更新間隔
        logging.info(
            "  更新間隔: %d時間以上経過したアイテムのみ処理",
            profile.interval.hour,
        )

        # 値下げルール
        logging.info("  値下げルール:")
        for discount in profile.discount:
            if discount.favorite_count > 0:
                condition = f"お気に入り {discount.favorite_count} 以上"
            else:
                condition = "それ以外"

            logging.info(
                "    - %s: %d円値下げ (下限: %s円)",
                condition,
                discount.step,
                f"{discount.threshold:,}",
            )

        logging.info("=" * 50)
