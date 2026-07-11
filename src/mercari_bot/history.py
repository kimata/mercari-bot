#!/usr/bin/env python3
"""値下げ履歴の記録と売却検知（SQLite）

各実行でアイテム毎の処理結果（値下げ・スキップ理由）を記録し、
前回実行時のアイテム一覧との差分から売却（または取り下げ）を検知します。
"""

from __future__ import annotations

import enum
import logging
import pathlib
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

import my_lib.sqlite_util
import my_lib.time

if TYPE_CHECKING:
    from collections.abc import Iterable

    from my_lib.store.mercari.config import MercariItem

# NOTE: CWD に依存せず、リポジトリルート基準でスキーマを解決する
_SCHEMA_HISTORY = pathlib.Path(__file__).parents[2] / "schema" / "history.schema.sql"


class ItemAction(enum.Enum):
    """アイテム 1 件の処理結果の種別"""

    PRICE_DOWN = "price_down"  # 値下げ実施
    SKIP_RECENT = "skip_recent"  # interval 未経過
    SKIP_TIME_SALE = "skip_time_sale"  # タイムセール中
    SKIP_AUCTION = "skip_auction"  # オークション形式
    SKIP_NO_DISCOUNT = "skip_no_discount"  # 下限到達 or お気に入り条件未達
    FAILED = "failed"  # 送信後エラー（検証失敗・タイムアウト）


@dataclass(frozen=True)
class ItemResult:
    """アイテム 1 件の処理結果"""

    action: ItemAction
    old_price: int  # 処理前の表示価格（送料込み）
    new_price: int | None = None  # 値下げ後の表示価格（送料込み）。値下げしなかった場合は None


@dataclass(frozen=True)
class PriceDownEntry:
    """値下げ履歴 1 件（売却通知用）"""

    at: str
    old_price: int
    new_price: int


@dataclass(frozen=True)
class SnapshotItem:
    """前回実行時に出品一覧に存在したアイテム"""

    item_id: str
    name: str
    price: int
    favorite: int
    view: int


class HistoryDb:
    """値下げ履歴・アイテムスナップショットの SQLite ストア"""

    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        my_lib.sqlite_util.init_schema_from_file(db_path, _SCHEMA_HISTORY)

    def add_record(self, profile_name: str, item: MercariItem, result: ItemResult) -> None:
        """アイテム 1 件の処理結果を記録する

        記録の失敗で値下げ処理自体を止めないよう、sqlite3 のエラーはログに留める。
        """
        try:
            with my_lib.sqlite_util.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO price_history
                        (at, profile, item_id, item_name, old_price, new_price, favorite, view, action)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        my_lib.time.now().isoformat(),
                        profile_name,
                        item.id,
                        item.name,
                        result.old_price,
                        result.new_price,
                        item.favorite,
                        item.view,
                        result.action.value,
                    ),
                )
        except sqlite3.Error:
            logging.exception("値下げ履歴の記録に失敗しました: %s", item.name)

    def get_price_down_history(self, profile_name: str, item_id: str) -> list[PriceDownEntry]:
        """アイテムの値下げ履歴を古い順に返す"""
        with my_lib.sqlite_util.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT at, old_price, new_price FROM price_history
                WHERE profile = ? AND item_id = ? AND action = ?
                ORDER BY at
                """,
                (profile_name, item_id, ItemAction.PRICE_DOWN.value),
            ).fetchall()

        return [PriceDownEntry(at=row[0], old_price=row[1], new_price=row[2]) for row in rows]

    def get_snapshot(self, profile_name: str) -> list[SnapshotItem]:
        """前回実行時のアイテム一覧を返す"""
        with my_lib.sqlite_util.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT item_id, item_name, price, favorite, view FROM item_snapshot
                WHERE profile = ?
                """,
                (profile_name,),
            ).fetchall()

        return [
            SnapshotItem(item_id=row[0], name=row[1], price=row[2], favorite=row[3], view=row[4])
            for row in rows
        ]

    def replace_snapshot(self, profile_name: str, items: Iterable[MercariItem]) -> None:
        """アイテム一覧のスナップショットを今回の内容で全置換する"""
        seen_at = my_lib.time.now().isoformat()
        with my_lib.sqlite_util.connect(self._db_path) as conn:
            conn.execute("DELETE FROM item_snapshot WHERE profile = ?", (profile_name,))
            conn.executemany(
                """
                INSERT INTO item_snapshot
                    (profile, item_id, item_name, price, favorite, view, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (profile_name, item.id, item.name, item.price, item.favorite, item.view, seen_at)
                    for item in items
                ],
            )


class NullHistoryDb:
    """記録しない履歴 DB（Null Object Pattern、デバッグモード用）"""

    def add_record(self, profile_name: str, item: MercariItem, result: ItemResult) -> None:
        """何もしない"""

    def get_price_down_history(self, profile_name: str, item_id: str) -> list[PriceDownEntry]:
        """常に空リストを返す"""
        return []

    def get_snapshot(self, profile_name: str) -> list[SnapshotItem]:
        """常に空リストを返す"""
        return []

    def replace_snapshot(self, profile_name: str, items: Iterable[MercariItem]) -> None:
        """何もしない"""


# 履歴ストアの型エイリアス
HistoryStore: TypeAlias = HistoryDb | NullHistoryDb


def detect_removed_items(previous: list[SnapshotItem], current_ids: set[str]) -> list[SnapshotItem]:
    """前回スナップショットに存在し、今回の一覧から消えたアイテムを返す"""
    return [item for item in previous if item.item_id not in current_ids]


def build_sold_message(
    removed: list[SnapshotItem],
    history_map: dict[str, list[PriceDownEntry]],
) -> str:
    """売却（取り下げ）検知のサマリー通知メッセージを組み立てる"""
    lines = ["以下の商品が出品リストから消えました（売却または取り下げ）。", ""]

    for item in removed:
        history = history_map.get(item.item_id, [])
        lines.append(
            f"● {item.name}（最終価格 {item.price:,}円 / ♥{item.favorite} / "
            f"👁{item.view} / 値下げ {len(history)}回）"
        )
        lines.extend(
            f"    - {entry.at[:10]} {entry.old_price:,}円 → {entry.new_price:,}円" for entry in history
        )

    return "\n".join(lines)
