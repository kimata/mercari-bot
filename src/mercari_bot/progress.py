#!/usr/bin/env python3
"""Rich を使用した進捗表示モジュール

TTY 環境では Rich による視覚的な進捗表示を行い、
非 TTY 環境（CI/CD パイプラインなど）では logging にフォールバックします。
my_lib.cui_progress を使用して実装しています。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import my_lib.cui_progress
import my_lib.store.mercari.progress
import rich.cells

if TYPE_CHECKING:
    from my_lib.store.mercari.config import MercariItem

# プログレスバーのラベル
_PROGRESS_ITEM = "アイテム処理"


@runtime_checkable
class StatusProgressObserver(my_lib.store.mercari.progress.ProgressObserver, Protocol):
    """my_lib の ProgressObserver に加えて、ステータス表示を受け取れる observer"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def set_status(self, status: str, is_error: bool = False) -> None: ...


@dataclass
class ProgressDisplay:
    """Rich による進捗表示を管理するクラス

    ProgressObserver Protocol を実装し、iter_items_on_display に渡して使用します。
    my_lib.cui_progress.ProgressManager を使用して実装しています。

    Examples:
        progress = ProgressDisplay()
        progress.start()
        try:
            progress.set_status("ログイン中...")
            my_lib.store.mercari.login.execute(...)

            progress.set_status("アイテム処理中...")
            my_lib.store.mercari.scrape.iter_items_on_display(
                driver, wait, debug_mode, [handler], progress_observer=progress
            )

            progress.set_status("完了")
        finally:
            progress.stop()

    """

    _manager: my_lib.cui_progress.ProgressManager = field(
        default_factory=lambda: my_lib.cui_progress.ProgressManager(
            color="#E72121",  # メルカリレッド
            title=" メルカリ ",
            description_width=20,
            show_remaining_time=False,
            auto_start=False,
        ),
    )

    @property
    def is_terminal(self) -> bool:
        """TTY 環境かどうかを返す"""
        return self._manager.is_terminal

    def start(self) -> None:
        """進捗表示を開始する"""
        self._manager.start()

    def stop(self) -> None:
        """進捗表示を停止する"""
        self._manager.stop()

    def set_status(self, status: str, is_error: bool = False) -> None:
        """ステータスを更新する

        Args:
            status: 表示するステータステキスト
            is_error: エラー状態かどうか（True の場合は赤色で表示）

        """
        self._manager.set_status(status, is_error=is_error)

    def _get_max_item_name_length(self) -> int:
        """ステータスバーに表示可能な商品名の最大表示幅（セル数）を計算する"""
        # ターミナル幅を取得
        terminal_width = self._manager.console.width

        # ステータスバーは ratio 1:3:1 で分割
        # 中央（ステータス）は全体の 3/5
        status_width = (terminal_width * 3) // 5

        # プレフィックス「🏷️ 処理中: 」の分を引く
        prefix_length = rich.cells.cell_len("🏷️ 処理中: ")

        return max(status_width - prefix_length, 10)

    def _truncate_name(self, name: str, max_width: int) -> str:
        """商品名を指定した表示幅（セル数）に省略する

        全角文字は 2 セルとして数えるため、日本語の商品名でも
        ステータスバーからはみ出さない。
        """
        if rich.cells.cell_len(name) <= max_width:
            return name
        return rich.cells.set_cell_size(name, max_width - 3).rstrip() + "..."

    # --- ProgressObserver Protocol の実装 ---
    def on_total_count(self, count: int) -> None:
        """アイテム総数が判明したときに呼ばれる"""
        self._manager.set_progress_bar(_PROGRESS_ITEM, total=count)

    def on_item_start(self, index: int, total: int, item: MercariItem) -> None:
        """各アイテムの処理開始時に呼ばれる"""
        max_length = self._get_max_item_name_length()
        name = self._truncate_name(item.name, max_length)
        self.set_status(f"🏷️ 処理中: {name}")

    def on_item_complete(self, index: int, total: int, item: MercariItem) -> None:
        """各アイテムの処理完了時に呼ばれる"""
        self._manager.update_progress_bar(_PROGRESS_ITEM)


@dataclass
class NullProgressDisplay:
    """何もしない進捗表示（Null Object Pattern）

    progress_observer が不要な場合に使用し、None チェックを不要にする。
    ProgressDisplay と同じインターフェースを持つが、すべてのメソッドが何もしない。
    """

    @property
    def is_terminal(self) -> bool:
        """常に False を返す"""
        return False

    def start(self) -> None:
        """何もしない"""

    def stop(self) -> None:
        """何もしない"""

    def set_status(self, status: str, is_error: bool = False) -> None:
        """何もしない"""

    def on_total_count(self, count: int) -> None:
        """何もしない"""

    def on_item_start(self, index: int, total: int, item: MercariItem) -> None:
        """何もしない"""

    def on_item_complete(self, index: int, total: int, item: MercariItem) -> None:
        """何もしない"""


@dataclass
class ItemRecordingObserver:
    """内側の observer に委譲しつつ、出現した全アイテムを記録する observer

    my_lib 側は公開停止中のアイテムを item_func に渡さないため、
    出品一覧の全アイテム（売却検知のスナップショット対象）は
    on_item_start で捕捉する。
    """

    inner: my_lib.store.mercari.progress.ProgressObserver
    seen: dict[str, MercariItem] = field(default_factory=dict)

    def on_total_count(self, count: int) -> None:
        self.inner.on_total_count(count)

    def on_item_start(self, index: int, total: int, item: MercariItem) -> None:
        # NOTE: リトライ時に同一アイテムで複数回呼ばれるため、dict で重複排除する
        self.seen[item.id] = item
        self.inner.on_item_start(index, total, item)

    def on_item_complete(self, index: int, total: int, item: MercariItem) -> None:
        self.inner.on_item_complete(index, total, item)


def create_progress_display() -> ProgressDisplay:
    """ProgressDisplay インスタンスを作成する

    Returns:
        ProgressDisplay インスタンス

    """
    return ProgressDisplay()
