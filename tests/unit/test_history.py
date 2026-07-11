#!/usr/bin/env python3
# ruff: noqa: S101
"""
history モジュールのテスト

SQLite への記録・スナップショット・売却検知ロジックをテストします。
"""

import pathlib
import sqlite3

import pytest
from my_lib.store.mercari.config import MercariItem

from mercari_bot.history import (
    HistoryDb,
    ItemAction,
    ItemResult,
    NullHistoryDb,
    PriceDownEntry,
    SnapshotItem,
    build_sold_message,
    detect_removed_items,
)

_PROFILE = "Test Profile"


def _create_item(
    item_id: str = "test-id",
    name: str = "テスト商品",
    price: int = 3000,
    favorite: int = 5,
) -> MercariItem:
    return MercariItem(
        id=item_id,
        url=f"https://jp.mercari.com/item/{item_id}",
        name=name,
        price=price,
        view=100,
        favorite=favorite,
        is_stop=0,
    )


@pytest.fixture
def history_db(tmp_path: pathlib.Path) -> HistoryDb:
    """テスト用の履歴 DB"""
    return HistoryDb(tmp_path / "history.db")


class TestHistoryDb:
    """HistoryDb のテスト"""

    def test_init_creates_tables(self, tmp_path: pathlib.Path):
        """初期化でテーブルが作成される"""
        db_path = tmp_path / "history.db"
        HistoryDb(db_path)

        with sqlite3.connect(db_path) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        assert "price_history" in tables
        assert "item_snapshot" in tables

    def test_init_creates_parent_dir(self, tmp_path: pathlib.Path):
        """親ディレクトリが無くても作成される"""
        db_path = tmp_path / "not-exist" / "history.db"
        HistoryDb(db_path)

        assert db_path.is_file()

    def test_add_record_and_get_price_down_history(self, history_db: HistoryDb):
        """記録した値下げ履歴が取得できる（スキップは除外される）"""
        item = _create_item(price=3000)

        history_db.add_record(_PROFILE, item, ItemResult(ItemAction.PRICE_DOWN, 3000, 2900))
        history_db.add_record(_PROFILE, item, ItemResult(ItemAction.SKIP_RECENT, 2900))
        history_db.add_record(_PROFILE, item, ItemResult(ItemAction.PRICE_DOWN, 2900, 2800))

        history = history_db.get_price_down_history(_PROFILE, item.id)

        assert [(entry.old_price, entry.new_price) for entry in history] == [(3000, 2900), (2900, 2800)]

    def test_get_price_down_history_filters_by_profile_and_item(self, history_db: HistoryDb):
        """profile と item_id で絞り込まれる"""
        item = _create_item()

        history_db.add_record(_PROFILE, item, ItemResult(ItemAction.PRICE_DOWN, 3000, 2900))
        history_db.add_record("Other Profile", item, ItemResult(ItemAction.PRICE_DOWN, 5000, 4900))

        assert len(history_db.get_price_down_history(_PROFILE, item.id)) == 1
        assert history_db.get_price_down_history(_PROFILE, "unknown-id") == []

    def test_replace_snapshot_roundtrip(self, history_db: HistoryDb):
        """スナップショットの保存と取得"""
        item = _create_item(name="商品A", price=3000, favorite=5)

        history_db.replace_snapshot(_PROFILE, [item])
        snapshot = history_db.get_snapshot(_PROFILE)

        assert snapshot == [SnapshotItem(item_id=item.id, name="商品A", price=3000, favorite=5, view=100)]

    def test_replace_snapshot_replaces_all(self, history_db: HistoryDb):
        """2 回目の replace で前回分が全置換される"""
        item_a = _create_item(item_id="test-id-a", name="商品A")
        item_b = _create_item(item_id="test-id-b", name="商品B")

        history_db.replace_snapshot(_PROFILE, [item_a])
        history_db.replace_snapshot(_PROFILE, [item_b])

        snapshot = history_db.get_snapshot(_PROFILE)
        assert [s.item_id for s in snapshot] == ["test-id-b"]

    def test_snapshot_is_per_profile(self, history_db: HistoryDb):
        """スナップショットはプロファイル毎に独立している"""
        history_db.replace_snapshot(_PROFILE, [_create_item()])
        history_db.replace_snapshot("Other Profile", [])

        assert len(history_db.get_snapshot(_PROFILE)) == 1
        assert history_db.get_snapshot("Other Profile") == []

    def test_add_record_error_is_suppressed(self, history_db: HistoryDb, caplog: pytest.LogCaptureFixture):
        """記録失敗は例外にならずログに留まる"""
        item = _create_item()

        # DB ファイルを壊して sqlite3.Error を誘発する
        history_db._db_path.write_text("broken")

        history_db.add_record(_PROFILE, item, ItemResult(ItemAction.PRICE_DOWN, 3000, 2900))

        assert any("記録に失敗" in record.message for record in caplog.records)


class TestNullHistoryDb:
    """NullHistoryDb のテスト（Null Object Pattern）"""

    def test_all_methods_are_noop(self):
        """すべてのメソッドが安全に呼べて、読み取りは空を返す"""
        null_db = NullHistoryDb()
        item = _create_item()

        null_db.add_record(_PROFILE, item, ItemResult(ItemAction.PRICE_DOWN, 3000, 2900))
        null_db.replace_snapshot(_PROFILE, [item])

        assert null_db.get_price_down_history(_PROFILE, item.id) == []
        assert null_db.get_snapshot(_PROFILE) == []


class TestDetectRemovedItems:
    """detect_removed_items のテスト"""

    def _snapshot(self, item_id: str) -> SnapshotItem:
        return SnapshotItem(item_id=item_id, name=f"商品{item_id}", price=3000, favorite=5, view=100)

    def test_detects_removed(self):
        """前回に存在し今回消えたアイテムを検出"""
        previous = [self._snapshot("a"), self._snapshot("b")]

        removed = detect_removed_items(previous, {"a"})

        assert [item.item_id for item in removed] == ["b"]

    def test_no_removed(self):
        """全アイテムが残っていれば空"""
        previous = [self._snapshot("a")]

        assert detect_removed_items(previous, {"a", "b"}) == []

    def test_empty_previous(self):
        """初回実行（スナップショットなし）では検出されない"""
        assert detect_removed_items([], {"a"}) == []


class TestBuildSoldMessage:
    """build_sold_message のテスト"""

    def test_message_contains_item_and_history(self):
        """商品名・価格・値下げ履歴が含まれる"""
        removed = [SnapshotItem(item_id="a", name="商品A", price=2900, favorite=5, view=120)]
        history_map = {
            "a": [
                PriceDownEntry(at="2026-07-01T09:00:00+09:00", old_price=3000, new_price=2900),
            ]
        }

        message = build_sold_message(removed, history_map)

        assert "商品A" in message
        assert "2,900円" in message
        assert "値下げ 1回" in message
        assert "2026-07-01" in message
        assert "3,000円 → 2,900円" in message

    def test_message_without_history(self):
        """値下げ履歴がないアイテムも通知できる"""
        removed = [SnapshotItem(item_id="a", name="商品A", price=2900, favorite=5, view=120)]

        message = build_sold_message(removed, {})

        assert "商品A" in message
        assert "値下げ 0回" in message
