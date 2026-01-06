#!/usr/bin/env python3
"""Rich を使用した進捗表示モジュール

TTY 環境では Rich による視覚的な進捗表示を行い、
非 TTY 環境（CI/CD パイプラインなど）では logging にフォールバックします。
my_lib.cui_progress を使用して実装しています。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import my_lib.cui_progress

# プログレスバーのラベル
_PROGRESS_ITEM = "アイテム処理"


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
        """ステータスバーに表示可能な商品名の最大長を計算する"""
        # ターミナル幅を取得
        terminal_width = self._manager.console.width

        # ステータスバーは ratio 1:3:1 で分割
        # 中央（ステータス）は全体の 3/5
        status_width = (terminal_width * 3) // 5

        # プレフィックス「🏷️ 処理中: 」の分を引く（絵文字は2文字分として計算）
        prefix_length = len("🏷️ 処理中: ") + 1  # 絵文字の表示幅補正

        return max(status_width - prefix_length, 10)

    def _truncate_name(self, name: str, max_length: int) -> str:
        """商品名を指定した長さに省略する"""
        if len(name) <= max_length:
            return name
        return name[: max_length - 3] + "..."

    # --- ProgressObserver Protocol の実装 ---
    def on_total_count(self, count: int) -> None:
        """アイテム総数が判明したときに呼ばれる"""
        self._manager.set_progress_bar(_PROGRESS_ITEM, total=count)

    def on_item_start(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理開始時に呼ばれる"""
        name = item.get("name", "不明")
        max_length = self._get_max_item_name_length()
        name = self._truncate_name(name, max_length)
        self.set_status(f"🏷️ 処理中: {name}")

    def on_item_complete(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理完了時に呼ばれる"""
        self._manager.update_progress_bar(_PROGRESS_ITEM)


def create_progress_display() -> ProgressDisplay:
    """ProgressDisplay インスタンスを作成する

    Returns:
        ProgressDisplay インスタンス

    """
    return ProgressDisplay()
